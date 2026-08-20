from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path

import httpx
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

from direct_mail.models import Office, Person

_CENSUS_GEOCODER_URL = (
    "https://geocoding.geo.census.gov/geocoder/locations/address"
)
_US_STATE_NAMES = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "DC": "District of Columbia",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
}
_ORDINAL_WORDS = {
    "first": "1st",
    "second": "2nd",
    "third": "3rd",
    "fourth": "4th",
    "fifth": "5th",
    "sixth": "6th",
    "seventh": "7th",
    "eighth": "8th",
    "ninth": "9th",
    "tenth": "10th",
    "eleventh": "11th",
    "twelfth": "12th",
}


def normalize_office_for_geocoding(office: Office) -> Office:
    normalized = office.model_copy(deep=True)
    normalized.street = " ".join(normalized.street.split())
    normalized.city = " ".join(normalized.city.split())

    avenue_match = re.match(
        r"^of the Americas\s+(.+)$",
        normalized.city,
        flags=re.IGNORECASE,
    )
    if avenue_match and re.search(r"\bAvenue$", normalized.street, re.IGNORECASE):
        normalized.street = f"{normalized.street} of the Americas"
        normalized.city = avenue_match.group(1)

    direction_match = re.match(
        r"^(N|S|E|W|NE|NW|SE|SW)\s+(.+)$",
        normalized.city,
        flags=re.IGNORECASE,
    )
    if direction_match:
        normalized.street = f"{normalized.street} {direction_match.group(1).upper()}"
        normalized.city = direction_match.group(2)

    noisy_prefix = re.match(
        r"^(?:mailroom|store\s+front\s+level|suite\s+[A-Z0-9-]+|"
        r"(?:first|second|third|fourth|fifth|\d+(?:st|nd|rd|th))\s+floor)\s+(.+)$",
        normalized.city,
        flags=re.IGNORECASE,
    )
    if noisy_prefix:
        normalized.city = noisy_prefix.group(1)

    if re.fullmatch(
        r"(?:floor\s+\d+|\d+(?:st|nd|rd|th)\s+floor)",
        normalized.city,
        flags=re.IGNORECASE,
    ):
        office_label = re.sub(
            re.escape(normalized.company_name),
            "",
            normalized.office_name,
            flags=re.IGNORECASE,
        )
        office_label = re.sub(
            r"\b(?:headquarters|hq|office|primary)\b",
            "",
            office_label,
            flags=re.IGNORECASE,
        )
        office_label = " ".join(office_label.split()).strip(" ,-.")
        if office_label:
            normalized.city = office_label.title()

    return normalized


def office_geocode_query(office: Office) -> dict[str, str]:
    street = re.sub(
        r"\s+\d+(?:st|nd|rd|th)\s+floor\b.*$",
        "",
        office.street,
        flags=re.IGNORECASE,
    )
    street = re.sub(
        r"\s*,?\s+(?:suite|ste\.?|floor|fl\.?|unit|building|#)\s*#?[a-z0-9-]+\b.*$",
        "",
        street,
        flags=re.IGNORECASE,
    )
    return {
        key: value.strip()
        for key, value in {
            "street": street,
            "city": office.city,
            "state": office.state_region,
            "postalcode": office.postal_code,
            "country": office.country_code,
        }.items()
        if value and value.strip()
    }


def office_geocode_queries(office: Office) -> list[str | dict[str, str]]:
    structured = office_geocode_query(office)
    without_postal = {
        key: value for key, value in structured.items() if key != "postalcode"
    }
    street = structured.get("street", "")
    city = structured.get("city", "")
    state = structured.get("state", "")
    country = structured.get("country", "")
    plain_address = ", ".join(
        part for part in [street, city, state, country] if part
    )
    candidates: list[str | dict[str, str]] = [structured]
    if without_postal != structured:
        candidates.append(without_postal)
    if plain_address:
        candidates.append(plain_address)
    return candidates


def _normalized_address_component(value: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    return "".join(_ORDINAL_WORDS.get(token, token) for token in tokens)


def _display_matches_locality(office: Office, display_name: str) -> bool:
    raw_components = [component.strip() for component in display_name.split(",")]
    raw_components = [component for component in raw_components if component]
    display_components = [
        _normalized_address_component(component) for component in raw_components
    ]
    city = _normalized_address_component(office.city)
    city_candidates = {city}
    if city.endswith("city"):
        city_candidates.add(city.removesuffix("city"))

    if office.country_code.upper() == "US" and office.state_region:
        state_code = office.state_region.upper()
        state_name = _US_STATE_NAMES.get(state_code, office.state_region)
        state_candidates = {
            _normalized_address_component(state_code),
            _normalized_address_component(state_name),
        }
        state_indexes = {
            index
            for index, component in enumerate(raw_components)
            if set(re.findall(r"[a-z0-9]+", component.casefold())).intersection(
                {state_code.casefold(), state_name.casefold()}
            )
            or display_components[index] in state_candidates
        }
        if not state_indexes:
            return False
        state_index = max(state_indexes)
        display_components = [
            component
            for index, component in enumerate(display_components)
            if index != state_index
        ]
    return not city or bool(set(display_components).intersection(city_candidates))


def geocode_result_matches_office(office: Office, display_name: str) -> bool:
    normalized_display = _normalized_address_component(display_name)
    query_street = office_geocode_query(office).get("street", "")
    street_number = re.match(r"\s*(\d+[a-z]?)\b", query_street, re.IGNORECASE)
    display_numbers = set(re.findall(r"\b\d+[a-z]?\b", display_name.casefold()))
    if street_number and street_number.group(1).casefold() not in display_numbers:
        return False

    ignored_tokens = {
        "avenue",
        "boulevard",
        "court",
        "drive",
        "east",
        "highway",
        "lane",
        "north",
        "parkway",
        "place",
        "road",
        "south",
        "street",
        "west",
    }
    street_tokens = {
        _ORDINAL_WORDS.get(token.casefold(), token.casefold())
        for token in re.findall(r"[A-Za-z]{4,}|\d+(?:st|nd|rd|th)", query_street)
        if token.casefold() not in ignored_tokens
    }
    if street_tokens and not any(token in normalized_display for token in street_tokens):
        return False
    return _display_matches_locality(office, display_name)


class CachedGeocoder:
    def __init__(
        self,
        cache_path: Path,
        *,
        user_agent: str = "direct-mail-audience-builder",
        minimum_delay_seconds: float = 1.0,
    ) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache_path = cache_path
        nominatim = Nominatim(user_agent=user_agent, timeout=20)
        self._geocode = RateLimiter(
            nominatim.geocode,
            min_delay_seconds=minimum_delay_seconds,
            swallow_exceptions=True,
        )
        self._census_get = httpx.get
        with sqlite3.connect(self._cache_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS geocodes (
                    query TEXT PRIMARY KEY,
                    latitude REAL,
                    longitude REAL,
                    display_name TEXT NOT NULL DEFAULT ''
                )
                """
            )

    def _cached_result(
        self,
        cache_key: str,
    ) -> tuple[float | None, float | None, str] | None:
        with sqlite3.connect(self._cache_path) as connection:
            cached = connection.execute(
                "SELECT latitude, longitude, display_name FROM geocodes WHERE query = ?",
                (cache_key,),
            ).fetchone()
        if cached and cached[0] is not None and cached[1] is not None:
            return float(cached[0]), float(cached[1]), str(cached[2])
        return None

    def _store_result(
        self,
        cache_key: str,
        latitude: float,
        longitude: float,
        display_name: str,
    ) -> None:
        with sqlite3.connect(self._cache_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO geocodes VALUES (?, ?, ?, ?)",
                (cache_key, latitude, longitude, display_name),
            )

    def geocode(
        self,
        query: str | dict[str, str],
    ) -> tuple[float | None, float | None, str]:
        if isinstance(query, dict):
            normalized_query: str | dict[str, str] = {
                key: " ".join(value.strip().split())
                for key, value in query.items()
                if value.strip()
            }
            cache_key = f"structured:{json.dumps(normalized_query, sort_keys=True)}"
        else:
            normalized_query = " ".join(query.strip().split())
            cache_key = normalized_query
        if not normalized_query:
            return None, None, ""
        cached = self._cached_result(cache_key)
        if cached:
            return cached

        location = self._geocode(normalized_query, exactly_one=True)
        latitude = float(location.latitude) if location else None
        longitude = float(location.longitude) if location else None
        display_name = str(location.address) if location else ""
        if location and latitude is not None and longitude is not None:
            self._store_result(cache_key, latitude, longitude, display_name)
        return latitude, longitude, display_name

    def geocode_us_address(
        self,
        office: Office,
    ) -> tuple[float | None, float | None, str]:
        if office.country_code.upper() != "US":
            return None, None, ""
        query = office_geocode_query(office)
        census_query = {
            "street": query.get("street", ""),
            "city": query.get("city", ""),
            "state": query.get("state", ""),
            "zip": query.get("postalcode", ""),
        }
        if not census_query["street"] or not census_query["state"]:
            return None, None, ""
        cache_key = f"census:{json.dumps(census_query, sort_keys=True)}"
        cached = self._cached_result(cache_key)
        if cached:
            return cached

        try:
            response = self._census_get(
                _CENSUS_GEOCODER_URL,
                params=census_query
                | {
                    "benchmark": "Public_AR_Current",
                    "format": "json",
                },
                timeout=20,
            )
            response.raise_for_status()
            matches = response.json().get("result", {}).get("addressMatches", [])
            if not matches:
                return None, None, ""
            match = matches[0]
            coordinates = match.get("coordinates") or {}
            latitude = float(coordinates["y"])
            longitude = float(coordinates["x"])
            display_name = str(match.get("matchedAddress") or "")
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None, None, ""

        self._store_result(cache_key, latitude, longitude, display_name)
        return latitude, longitude, display_name


def geocode_offices(
    offices: Iterable[Office],
    geocoder: CachedGeocoder,
    on_item: Callable[[], None] | None = None,
) -> list[Office]:
    results: list[Office] = []
    for office in offices:
        updated = normalize_office_for_geocoding(office)
        if updated.latitude is None or updated.longitude is None:
            census_geocode = getattr(geocoder, "geocode_us_address", None)
            if callable(census_geocode) and updated.country_code.upper() == "US":
                latitude, longitude, display_name = census_geocode(updated)
                if (
                    latitude is not None
                    and longitude is not None
                    and geocode_result_matches_office(updated, display_name)
                ):
                    updated.latitude = latitude
                    updated.longitude = longitude
                    updated.geocode_source = "us_census"
                    updated.geocode_match = display_name
                    updated.geocode_validation = "exact_street_and_locality"
            if updated.latitude is None or updated.longitude is None:
                for query in office_geocode_queries(updated):
                    latitude, longitude, display_name = geocoder.geocode(query)
                    if (
                        latitude is not None
                        and longitude is not None
                        and geocode_result_matches_office(updated, display_name)
                    ):
                        updated.latitude = latitude
                        updated.longitude = longitude
                        updated.geocode_source = "nominatim"
                        updated.geocode_match = display_name
                        updated.geocode_validation = "exact_street_and_locality"
                        break
        elif not updated.geocode_source:
            updated.geocode_source = "provided"
            updated.geocode_validation = "provided_coordinates"
        if updated.latitude is None or updated.longitude is None:
            prior_reason = updated.validation_reason.strip()
            geocode_reason = "No exact street-level geocode"
            updated.validation_status = "rejected"
            updated.validation_reason = (
                f"{prior_reason}; {geocode_reason}" if prior_reason else geocode_reason
            )
            updated.geocode_validation = "rejected_no_exact_match"
        results.append(updated)
        if on_item:
            on_item()
    return results


def geocode_people(
    people: Iterable[Person],
    geocoder: CachedGeocoder,
    on_item: Callable[[], None] | None = None,
) -> list[Person]:
    coordinate_by_location: dict[str, tuple[float | None, float | None]] = {}
    results: list[Person] = []
    for person in people:
        updated = person.model_copy(deep=True)
        location = " ".join(updated.person_location.strip().split())
        if location:
            if location not in coordinate_by_location:
                latitude, longitude, _ = geocoder.geocode(location)
                coordinate_by_location[location] = (latitude, longitude)
            updated.latitude, updated.longitude = coordinate_by_location[location]
        results.append(updated)
        if on_item:
            on_item()
    return results
