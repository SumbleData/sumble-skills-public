import pandas as pd

from direct_mail.matching import (
    build_audience,
    haversine_miles,
    merge_offices,
    normalize_domain,
    parse_domains,
    parse_offices_csv,
    sumble_headquarters_offices,
)
from direct_mail.models import Company, HeadquartersAddress, Office, Person


def test_normalize_and_parse_domains() -> None:
    assert normalize_domain("https://www.Example.com/path") == "example.com"
    assert parse_domains("https://example.com, example.com\nacme.test") == [
        "example.com",
        "acme.test",
    ]


def test_uploaded_office_wins_over_parallel_for_same_address() -> None:
    parallel = Office(
        company_domain="example.com",
        office_name="Parallel office",
        street="1 Main St",
        city="Boston",
        state_region="MA",
        postal_code="02110",
        source="parallel",
    )
    uploaded = parallel.model_copy(update={"office_name": "Known office", "source": "uploaded"})

    merged = merge_offices([uploaded], [parallel])

    assert len(merged) == 1
    assert merged[0].office_name == "Known office"
    assert merged[0].source == "uploaded"


def test_downloaded_offices_csv_can_be_uploaded_again() -> None:
    downloaded = pd.DataFrame(
        [
            {
                "company_domain": "example.com",
                "company_name": "Example",
                "office_name": "Boston office",
                "street": "1 Main St",
                "city": "Boston",
                "state_region": "MA",
                "postal_code": "02110",
                "country_code": "US",
                "latitude": 42.3601,
                "longitude": -71.0589,
                "source": "parallel",
                "source_url": "https://example.com/contact",
                "evidence_urls": "['https://example.com/contact']",
                "evidence_count": "1",
                "validation_status": "verified",
            }
        ]
    )

    offices = parse_offices_csv(downloaded.to_csv(index=False).encode())

    assert len(offices) == 1
    assert offices[0].latitude == 42.3601
    assert offices[0].longitude == -71.0589
    assert offices[0].postal_code == "02110"
    assert offices[0].source == "uploaded"
    assert offices[0].evidence_urls == ["https://example.com/contact"]
    assert offices[0].validation_status == "verified"


def test_builds_sumble_headquarters_office_for_selected_country() -> None:
    company = Company(
        input_domain="example.com",
        organization_id=123,
        company_name="Example",
        company_domain="example.com",
        headquarters_country="US",
        headquarters_address=HeadquartersAddress(
            street="1 Main St",
            city="Boston",
            state="Massachusetts",
            state_code="MA",
            postal_code="02110",
            country_code="US",
        ),
        sumble_url="https://sumble.com/example",
    )

    offices = sumble_headquarters_offices([company], country_code="US")

    assert len(offices) == 1
    assert offices[0].source == "sumble"
    assert offices[0].address == "1 Main St, Boston, MA, 02110, US"
    assert sumble_headquarters_offices([company], country_code="GB") == []


def test_haversine_distance_is_reasonable() -> None:
    distance = haversine_miles(40.7128, -74.0060, 42.3601, -71.0589)
    assert 185 < distance < 195


def test_build_audience_filters_radius_titles_and_company_limit() -> None:
    office = Office(
        company_domain="example.com",
        company_name="Example",
        office_name="Boston office",
        city="Boston",
        state_region="MA",
        latitude=42.3601,
        longitude=-71.0589,
        validation_status="verified",
    )
    people = [
        Person(
            person_id=1,
            company_domain="example.com",
            company_name="Example",
            person_name="Ada Director",
            current_title="Director of Data",
            job_function="Data Engineer",
            job_level="Director",
            person_location="Boston, MA",
            linkedin_url="https://linkedin.com/in/ada",
            latitude=42.361,
            longitude=-71.06,
        ),
        Person(
            person_id=2,
            company_domain="example.com",
            company_name="Example",
            person_name="Eve Assistant",
            current_title="Executive Assistant",
            job_function="Operations",
            job_level="Director",
            person_location="Boston, MA",
            linkedin_url="https://linkedin.com/in/eve",
            latitude=42.361,
            longitude=-71.06,
        ),
    ]

    result = build_audience(
        people,
        [office],
        radius_miles=10,
        max_people_per_company=1,
        exclude_title_terms=["assistant"],
    )

    assert result["person_name"].tolist() == ["Ada Director"]
    assert "person_id" not in result.columns
    assert "organization_id" not in result.columns


def test_build_audience_excludes_unverified_offices() -> None:
    office = Office(
        company_domain="example.com",
        city="Boston",
        latitude=42.3601,
        longitude=-71.0589,
        validation_status="review_required",
    )
    person = Person(
        person_id=1,
        company_domain="example.com",
        company_name="Example",
        person_name="Ada Director",
        person_location="Boston, MA",
        latitude=42.361,
        longitude=-71.06,
    )

    result = build_audience(
        [person],
        [office],
        radius_miles=10,
        max_people_per_company=1,
    )

    assert result.empty
