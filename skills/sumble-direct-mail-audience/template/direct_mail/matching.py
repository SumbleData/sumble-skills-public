from __future__ import annotations

import io
import math
import re
from collections.abc import Iterable
from datetime import date

import pandas as pd

from direct_mail.catalog import level_rank
from direct_mail.models import Company, Office, Person


def normalize_domain(value: object) -> str:
    domain = str(value or "").strip().lower()
    domain = re.sub(r"^https?://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    return domain.split("/", 1)[0].strip()


def parse_domains(raw_text: str, csv_contents: bytes | None = None) -> list[str]:
    candidates = re.split(r"[\s,;]+", raw_text or "")
    if csv_contents:
        dataframe = pd.read_csv(io.BytesIO(csv_contents))
        if dataframe.empty:
            csv_values: list[str] = []
        elif "domain" in dataframe.columns:
            csv_values = dataframe["domain"].dropna().astype(str).tolist()
        else:
            csv_values = dataframe.iloc[:, 0].dropna().astype(str).tolist()
        candidates.extend(csv_values)
    return list(dict.fromkeys(filter(None, (normalize_domain(value) for value in candidates))))


def parse_offices_csv(csv_contents: bytes | None) -> list[Office]:
    if not csv_contents:
        return []
    dataframe = pd.read_csv(
        io.BytesIO(csv_contents),
        dtype=str,
        keep_default_na=False,
    )
    dataframe.columns = [
        re.sub(r"[^a-z0-9]+", "_", str(column).strip().lower()).strip("_")
        for column in dataframe.columns
    ]
    aliases = {
        "domain": "company_domain",
        "company": "company_name",
        "state": "state_region",
        "state_code": "state_region",
        "country": "country_code",
    }
    dataframe = dataframe.rename(columns=aliases)
    required = {"company_domain", "city"}
    missing = required - set(dataframe.columns)
    if missing:
        raise ValueError(f"Office CSV is missing columns: {', '.join(sorted(missing))}")
    offices: list[Office] = []
    for row in dataframe.to_dict("records"):
        latitude = pd.to_numeric(row.get("latitude"), errors="coerce")
        longitude = pd.to_numeric(row.get("longitude"), errors="coerce")
        source_url = str(row.get("source_url") or "").strip()
        office_data = row | {
            "latitude": None if pd.isna(latitude) else float(latitude),
            "longitude": None if pd.isna(longitude) else float(longitude),
            "source": "uploaded",
            "evidence_urls": [source_url] if source_url else [],
            "evidence_count": 1 if source_url else 0,
            "validation_status": "verified",
            "validation_reason": "User-provided office",
        }
        offices.append(Office(**office_data))
    return offices


def _office_key(office: Office) -> tuple[str, str]:
    normalized_address = re.sub(r"[^a-z0-9]+", "", office.address.lower())
    return normalize_domain(office.company_domain), normalized_address


def merge_offices(uploaded: Iterable[Office], researched: Iterable[Office]) -> list[Office]:
    merged: dict[tuple[str, str], Office] = {}
    for office in researched:
        merged[_office_key(office)] = office
    for office in uploaded:
        merged[_office_key(office)] = office
    return sorted(
        merged.values(),
        key=lambda office: (office.company_domain, office.city, office.office_name),
    )


def sumble_headquarters_offices(
    companies: Iterable[Company],
    *,
    country_code: str,
) -> list[Office]:
    offices = []
    for company in companies:
        address = company.headquarters_address
        if address is None or not address.city or not address.street:
            continue
        address_country = address.country_code or company.headquarters_country
        if address_country.upper() != country_code.upper():
            continue
        offices.append(
            Office(
                company_domain=company.company_domain,
                company_name=company.company_name,
                office_name=f"{company.company_name} headquarters",
                street=address.street,
                city=address.city,
                state_region=address.state_code or address.state,
                postal_code=address.postal_code,
                country_code=address_country.upper(),
                source="sumble",
                source_url=company.sumble_url,
                evidence_urls=[company.sumble_url] if company.sumble_url else [],
                evidence_count=1,
                confidence="high",
                validation_status="verified",
                validation_reason="Structured Sumble headquarters address",
                checked_at=date.today().isoformat(),
            )
        )
    return offices


def companies_dataframe(companies: Iterable[Company]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "input_domain": company.input_domain,
                "company_name": company.company_name,
                "company_domain": company.company_domain,
                "sumble_domain": company.sumble_domain,
                "headquarters_country": company.headquarters_country,
                "headquarters_address": (
                    ", ".join(
                        part
                        for part in [
                            company.headquarters_address.street,
                            company.headquarters_address.city,
                            company.headquarters_address.state_code
                            or company.headquarters_address.state,
                            company.headquarters_address.postal_code,
                            company.headquarters_address.country_code,
                        ]
                        if part
                    )
                    if company.headquarters_address
                    else ""
                ),
                "sumble_url": company.sumble_url,
            }
            for company in companies
        ]
    )


def offices_dataframe(offices: Iterable[Office]) -> pd.DataFrame:
    return pd.DataFrame([office.model_dump() | {"address": office.address} for office in offices])


def people_dataframe(people: Iterable[Person]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "company_domain": person.company_domain,
                "company_name": person.company_name,
                "person_name": person.person_name,
                "current_title": person.current_title,
                "job_function": person.job_function,
                "job_level": person.job_level,
                "person_location": person.person_location,
                "country": person.country,
                "linkedin_url": person.linkedin_url,
                "sumble_url": person.sumble_url,
            }
            for person in people
        ]
    )


def haversine_miles(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    earth_radius_miles = 3_958.7613
    lat_a, lon_a, lat_b, lon_b = map(
        math.radians,
        [latitude_a, longitude_a, latitude_b, longitude_b],
    )
    latitude_delta = lat_b - lat_a
    longitude_delta = lon_b - lon_a
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(longitude_delta / 2) ** 2
    )
    return earth_radius_miles * 2 * math.asin(math.sqrt(haversine))


def _contains_any(value: str, terms: list[str]) -> bool:
    normalized_value = value.casefold()
    return any(term.casefold() in normalized_value for term in terms)


def build_audience(
    people: Iterable[Person],
    offices: Iterable[Office],
    *,
    radius_miles: float,
    max_people_per_company: int,
    include_title_terms: list[str] | None = None,
    exclude_title_terms: list[str] | None = None,
) -> pd.DataFrame:
    include_terms = [term.strip() for term in include_title_terms or [] if term.strip()]
    exclude_terms = [term.strip() for term in exclude_title_terms or [] if term.strip()]
    offices_by_domain: dict[str, list[Office]] = {}
    for office in offices:
        if (
            office.validation_status != "verified"
            or office.latitude is None
            or office.longitude is None
        ):
            continue
        offices_by_domain.setdefault(normalize_domain(office.company_domain), []).append(office)

    rows: list[dict] = []
    seen_people: set[tuple[str, str]] = set()
    for person in people:
        if person.latitude is None or person.longitude is None:
            continue
        if include_terms and not _contains_any(person.current_title, include_terms):
            continue
        if exclude_terms and _contains_any(person.current_title, exclude_terms):
            continue
        identity = (
            normalize_domain(person.company_domain),
            person.linkedin_url.casefold()
            or f"{person.person_name}|{person.current_title}".casefold(),
        )
        if identity in seen_people:
            continue
        seen_people.add(identity)

        candidate_offices = offices_by_domain.get(normalize_domain(person.company_domain), [])
        distances = [
            (
                haversine_miles(
                    person.latitude,
                    person.longitude,
                    office.latitude,
                    office.longitude,
                ),
                office,
            )
            for office in candidate_offices
            if office.latitude is not None and office.longitude is not None
        ]
        if not distances:
            continue
        distance_miles, nearest_office = min(distances, key=lambda item: item[0])
        if distance_miles > radius_miles:
            continue
        rows.append(
            {
                "company_domain": person.company_domain,
                "company_name": person.company_name,
                "person_name": person.person_name,
                "current_title": person.current_title,
                "job_function": person.job_function,
                "job_level": person.job_level,
                "person_location": person.person_location,
                "linkedin_url": person.linkedin_url,
                "sumble_url": person.sumble_url,
                "nearest_office": nearest_office.office_name,
                "office_address": nearest_office.address,
                "office_source": nearest_office.source,
                "office_source_url": nearest_office.source_url,
                "distance_miles": round(distance_miles, 1),
                "match_reason": (
                    f"{person.job_function}, {person.job_level}, "
                    f"{distance_miles:.1f} miles from {nearest_office.office_name}"
                ),
                "_job_level_rank": level_rank(person.job_level),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "company_domain",
                "company_name",
                "person_name",
                "current_title",
                "job_function",
                "job_level",
                "person_location",
                "linkedin_url",
                "sumble_url",
                "nearest_office",
                "office_address",
                "office_source",
                "office_source_url",
                "distance_miles",
                "match_reason",
            ]
        )
    dataframe = pd.DataFrame(rows).sort_values(
        ["company_domain", "_job_level_rank", "distance_miles", "person_name"],
        ascending=[True, False, True, True],
    )
    dataframe["company_rank"] = dataframe.groupby("company_domain").cumcount() + 1
    dataframe = dataframe[dataframe["company_rank"] <= max_people_per_company]
    return dataframe.drop(columns=["_job_level_rank"]).reset_index(drop=True)
