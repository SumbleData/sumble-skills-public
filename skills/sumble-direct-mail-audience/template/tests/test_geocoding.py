from direct_mail.geocoding import (
    geocode_offices,
    geocode_result_matches_office,
    normalize_office_for_geocoding,
    office_geocode_queries,
    office_geocode_query,
)
from direct_mail.models import Office


def test_office_geocode_query_removes_suite_and_building_details() -> None:
    new_york = Office(
        company_domain="cohesity.com",
        street="250 West 34th Street, Suite #217",
        city="New York",
        state_region="NY",
        postal_code="10119",
    )
    minnesota = Office(
        company_domain="cohesity.com",
        street="2815 Cleveland Avenue, Building 2",
        city="Roseville",
        state_region="MN",
    )

    assert office_geocode_query(new_york) == {
        "street": "250 West 34th Street",
        "city": "New York",
        "state": "NY",
        "postalcode": "10119",
        "country": "US",
    }
    assert office_geocode_query(minnesota) == {
        "street": "2815 Cleveland Avenue",
        "city": "Roseville",
        "state": "MN",
        "country": "US",
    }


def test_office_geocode_query_removes_ordinal_floor() -> None:
    office = Office(
        company_domain="antimetal.com",
        street="205 West 28th Street 5th Floor",
        city="New York",
        state_region="NY",
        postal_code="10001",
    )

    assert office_geocode_query(office)["street"] == "205 West 28th Street"


def test_office_geocoding_falls_back_when_full_address_does_not_resolve() -> None:
    office = Office(
        company_domain="cohesity.com",
        street="1655 Fort Myer Drive, Suite 930",
        city="Arlington",
        state_region="VA",
        postal_code="22209",
    )

    class FallbackGeocoder:
        def __init__(self) -> None:
            self.queries = []

        def geocode(self, query):
            self.queries.append(query)
            if len(self.queries) == 1:
                return None, None, ""
            return 38.895, -77.072, "1655 Fort Myer Drive, Arlington, VA 22209"

    geocoder = FallbackGeocoder()
    result = geocode_offices([office], geocoder)

    assert len(geocoder.queries) == 2
    assert geocoder.queries == office_geocode_queries(office)[:2]
    assert result[0].latitude == 38.895
    assert result[0].longitude == -77.072


def test_office_geocoding_rejects_city_centroid_fallback() -> None:
    office = Office(
        company_domain="servicetitan.com",
        street="555 Titan Way",
        city="Glendale",
        state_region="CA",
        postal_code="94010",
    )

    class CityOnlyGeocoder:
        def geocode(self, _query):
            return 34.1469, -118.2478, "Glendale, Los Angeles County, California"

    result = geocode_offices([office], CityOnlyGeocoder())

    assert result[0].latitude is None
    assert result[0].longitude is None
    assert result[0].validation_status == "rejected"
    assert result[0].geocode_validation == "rejected_no_exact_match"


def test_office_geocoding_requires_ordinal_street_name() -> None:
    office = Office(
        company_domain="example.com",
        street="205 West 28th Street, 5th Floor",
        city="New York",
        state_region="NY",
        postal_code="10001",
    )

    class WrongStreetGeocoder:
        def geocode(self, _query):
            return (
                40.7128,
                -74.006,
                "205 West 23rd Street, New York, NY 10011, United States",
            )

    result = geocode_offices([office], WrongStreetGeocoder())

    assert result[0].latitude is None
    assert result[0].longitude is None


def test_accepts_exact_street_and_locality_when_postal_code_differs() -> None:
    office = Office(
        company_domain="intercom.com",
        street="55 2nd Street",
        city="San Francisco",
        state_region="CA",
        postal_code="94105",
    )

    assert geocode_result_matches_office(
        office,
        "55, 2nd Street, San Francisco, California, 94104, United States",
    )


def test_rejects_same_street_in_wrong_city() -> None:
    office = Office(
        company_domain="verkada.com",
        street="79 Fifth Avenue",
        city="New York",
        state_region="NY",
        postal_code="10003",
    )

    assert not geocode_result_matches_office(
        office,
        "79, 5th Avenue, Village of Pelham, Westchester County, New York, 10803",
    )


def test_distinguishes_new_york_city_from_new_york_state() -> None:
    office = Office(
        company_domain="anaplan.com",
        street="111 West 33rd Street",
        city="New York City",
        state_region="NY",
        postal_code="10120",
    )

    assert geocode_result_matches_office(
        office,
        "111 W 33RD ST, NEW YORK, NY, 10001",
    )


def test_normalizes_page_labels_that_leak_into_city() -> None:
    office = Office(
        company_domain="infor.com",
        company_name="Infor",
        office_name="Infor office",
        street="641 Avenue",
        city="of the Americas New York",
        state_region="NY",
        postal_code="10011",
    )

    normalized = normalize_office_for_geocoding(office)

    assert normalized.street == "641 Avenue of the Americas"
    assert normalized.city == "New York"


def test_normalizes_direction_that_leaks_into_city() -> None:
    office = Office(
        company_domain="workday.com",
        street="300 New Jersey Avenue",
        city="NW Washington",
        state_region="DC",
        postal_code="20001",
    )

    normalized = normalize_office_for_geocoding(office)

    assert normalized.street == "300 New Jersey Avenue NW"
    assert normalized.city == "Washington"


def test_uses_census_before_nominatim_for_us_offices() -> None:
    office = Office(
        company_domain="amd.com",
        street="15455 N Dallas Parkway, Suite #1230",
        city="Addison",
        state_region="TX",
        postal_code="75001",
    )

    class CensusFirstGeocoder:
        def geocode_us_address(self, _office):
            return (
                32.9591,
                -96.8215,
                "15455 DALLAS PKWY, ADDISON, TX, 75001",
            )

        def geocode(self, _query):
            raise AssertionError("Nominatim should not run after an exact Census match")

    result = geocode_offices([office], CensusFirstGeocoder())

    assert result[0].latitude == 32.9591
    assert result[0].longitude == -96.8215
    assert result[0].geocode_source == "us_census"
    assert result[0].geocode_match == "15455 DALLAS PKWY, ADDISON, TX, 75001"


def test_falls_back_to_nominatim_when_census_has_no_match() -> None:
    office = Office(
        company_domain="servicetitan.com",
        street="800 N Brand Blvd #100",
        city="Glendale",
        state_region="CA",
        postal_code="91203",
    )

    class NominatimFallbackGeocoder:
        def geocode_us_address(self, _office):
            return None, None, ""

        def geocode(self, _query):
            return (
                34.158,
                -118.254,
                "800, North Brand Boulevard, Glendale, California, 91207, United States",
            )

    result = geocode_offices([office], NominatimFallbackGeocoder())

    assert result[0].latitude == 34.158
    assert result[0].longitude == -118.254
    assert result[0].geocode_source == "nominatim"
