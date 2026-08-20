import json
from types import SimpleNamespace

from direct_mail.models import Company
from direct_mail.parallel_offices import (
    discover_company_offices,
    offices_from_search_results,
)


def _company() -> Company:
    return Company(
        input_domain="example.com",
        organization_id=123,
        company_name="Example",
        company_domain="example.com",
    )


def test_parses_and_prefers_official_us_addresses() -> None:
    results = [
        SimpleNamespace(
            url="https://directory.test/example",
            excerpts=[
                "Corporate Office 1 Old Street Suite 2 Boston, MA 02110 United States."
            ],
        ),
        SimpleNamespace(
            url="https://example.com/contact",
            excerpts=[
                "Address: 350 Main, St. #400, Boston, Massachusetts 02111"
            ],
        ),
    ]

    offices = offices_from_search_results(
        _company(),
        results,
        country_code="US",
        max_offices=10,
    )

    assert len(offices) == 1
    assert offices[0].street == "350 Main St. #400"
    assert offices[0].city == "Boston"
    assert offices[0].state_region == "MA"
    assert offices[0].postal_code == "02111"
    assert offices[0].confidence == "high"
    assert offices[0].source == "parallel_search"


def test_search_uses_basic_ga_endpoint_shape() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.request = {}
            self.extract_request = {}

        def search(self, **kwargs):
            self.request = kwargs
            return SimpleNamespace(
                session_id="test-session",
                results=[
                    SimpleNamespace(
                        url="https://example.com/contact",
                        excerpts=["10 Main Road, Austin, Texas 78701"],
                    )
                ]
            )

        def extract(self, **kwargs):
            self.extract_request = kwargs
            return SimpleNamespace(results=[], errors=[])

    client = FakeClient()

    offices = discover_company_offices(
        _company(),
        "test-key",
        country_code="US",
        max_offices=3,
        client=client,
    )

    assert client.request["mode"] == "basic"
    assert client.request["timeout"] == 15
    assert client.request["advanced_settings"]["location"] == "us"
    assert client.request["advanced_settings"]["max_results"] == 20
    assert "zoominfo.com" in client.request["advanced_settings"]["source_policy"][
        "exclude_domains"
    ]
    assert client.request["search_queries"][3] == (
        "site:example.com address location"
    )
    assert client.extract_request["urls"] == ["https://example.com/contact"]
    assert client.extract_request["session_id"] == "test-session"
    assert len(offices) == 1


def test_cleans_noisy_excerpts_and_deduplicates_address_variants() -> None:
    company = Company(
        input_domain="antimetal.com",
        organization_id=456,
        company_name="Antimetal",
        company_domain="antimetal.com",
    )
    results = [
        SimpleNamespace(
            url="https://www.cbinsights.com/company/antimetal",
            excerpts=[
                "4 more. Loading... Antimetal (antimetal.com) corporate office "
                "447 Broadway 2nd Floor, New York, NY 10013"
            ],
        ),
        SimpleNamespace(
            url="https://www.datanyze.com/companies/antimetal/566148239",
            excerpts=[
                "Antimetal (antimetal.com) corporate office "
                "447 Broadway Fl 2, New York, NY 10013"
            ],
        ),
        SimpleNamespace(
            url="https://www.zoominfo.com/pic/antimetal-inc/566148239",
            excerpts=[
                "Antimetal (antimetal.com) corporate office "
                "447 Broadway Fl 2, New York City, NY 10013"
            ],
        ),
    ]

    offices = offices_from_search_results(
        company,
        results,
        country_code="US",
        max_offices=10,
    )

    assert len(offices) == 1
    assert offices[0].street == "447 Broadway Fl 2"
    assert offices[0].city == "New York"
    assert offices[0].confidence == "low"
    assert offices[0].validation_status == "review_required"
    assert offices[0].validation_reason == "No strong source confirmed the consensus"
    assert offices[0].evidence_count == 3


def test_cleans_repeated_official_address_from_page_chrome() -> None:
    company = Company(
        input_domain="cohesity.com",
        organization_id=789,
        company_name="Cohesity",
        company_domain="cohesity.com",
    )
    results = [
        SimpleNamespace(
            url="https://cohesity.com/contact",
            excerpts=[
                "Cohesity HQ 2625 Augustine Dr, Santa Clara, CA 95054. "
                "3133 Get support We're here to help. HQ 2625 Augustine Dr, "
                "Santa Clara, CA 95054. 560103 Karnataka, India. Our headquarters. "
                "HQ. 2625 Augustine Dr, Santa Clara, CA 95054."
            ],
        )
    ]

    offices = offices_from_search_results(
        company,
        results,
        country_code="US",
        max_offices=10,
    )

    assert len(offices) == 1
    assert offices[0].street == "2625 Augustine Dr"
    assert offices[0].address == "2625 Augustine Dr, Santa Clara, CA, 95054, US"


def test_extracts_all_us_office_blocks_with_optional_postal_codes() -> None:
    company = Company(
        input_domain="cohesity.com",
        organization_id=789,
        company_name="Cohesity",
        company_domain="cohesity.com",
    )
    excerpt = """Office Locations
New York
250 West 34th Street, Suite #217
New York, 10119
Florida
801 International Parkway
Heathrow, Florida, United States
Minnesota
2815 Cleveland Avenue, Building 2
Roseville, Minnesota, United States
California (HQ)
2625 Augustine Drive
Santa Clara, California, United States
Virginia
1655 Fort Myer Drive, Suite 930
Arlington, Virginia, 22209
"""

    offices = offices_from_search_results(
        company,
        [SimpleNamespace(url="https://cohesity.com/contact", excerpts=[excerpt])],
        country_code="US",
        max_offices=10,
    )

    assert len(offices) == 5
    offices_by_city = {office.city: office for office in offices}
    assert set(offices_by_city) == {
        "Arlington",
        "Heathrow",
        "New York",
        "Roseville",
        "Santa Clara",
    }
    assert offices_by_city["Heathrow"].postal_code == ""
    assert offices_by_city["Roseville"].postal_code == ""
    assert offices_by_city["New York"].state_region == "NY"
    assert offices_by_city["Arlington"].postal_code == "22209"


def test_rejects_results_that_do_not_name_the_company() -> None:
    results = [
        SimpleNamespace(
            url="https://rezolve.com/about",
            excerpts=["New York office: 499 Park Ave, New York, NY 10022"],
        )
    ]

    offices = offices_from_search_results(
        _company(),
        results,
        country_code="US",
        max_offices=10,
    )

    assert offices == []


def test_prefers_current_business_source_over_data_broker() -> None:
    company = Company(
        input_domain="antimetal.com",
        organization_id=456,
        company_name="Antimetal",
        company_domain="antimetal.com",
    )
    results = [
        SimpleNamespace(
            url="https://www.zoominfo.com/pic/antimetal-inc/566148239",
            excerpts=[
                "Antimetal (antimetal.com) corporate office "
                "447 Broadway Fl 2, New York, NY 10013"
            ],
        ),
        SimpleNamespace(
            url="https://pitchbook.com/profiles/company/527330-53",
            excerpts=[
                "Antimetal (antimetal.com) Corporate Office "
                "205 West 28th Street 5th Floor, New York, NY 10001"
            ],
        ),
    ]

    offices = offices_from_search_results(
        company,
        results,
        country_code="US",
        max_offices=10,
    )

    assert len(offices) == 2
    assert offices[0].street == "205 West 28th Street 5th Floor"
    assert offices[0].postal_code == "10001"
    assert all(office.validation_status == "review_required" for office in offices)


def test_prefers_linkedin_location_over_older_business_profile() -> None:
    company = Company(
        input_domain="resolve.ai",
        organization_id=321,
        company_name="Resolve AI",
        company_domain="resolve.ai",
    )
    results = [
        SimpleNamespace(
            url="https://linkedin.com/company/resolveai",
            excerpts=[
                "Resolve AI (resolve.ai) corporate office "
                "350 Rhode Island St, San Francisco, CA 94103"
            ],
        ),
        SimpleNamespace(
            url="https://pitchbook.com/profiles/company/680347-72",
            excerpts=[
                "Resolve AI (resolve.ai) corporate office "
                "375 Alabama Street Suite 490, San Francisco, CA 94110"
            ],
        ),
    ]

    offices = offices_from_search_results(
        company,
        results,
        country_code="US",
        max_offices=10,
    )

    assert len(offices) == 2
    assert offices[0].street == "350 Rhode Island St"
    assert offices[0].source_url == "https://linkedin.com/company/resolveai"
    assert all(office.validation_status == "review_required" for office in offices)


def test_rejects_ambiguous_company_name_without_exact_domain_evidence() -> None:
    company = Company(
        input_domain="linear.app",
        organization_id=654,
        company_name="Linear",
        company_domain="linear.app",
    )
    results = [
        SimpleNamespace(
            url="https://www.packworld.com/home/company/linear-technology-corp",
            excerpts=[
                "Linear Technology Corp corporate office "
                "1630 McCarthy Blvd, Milpitas, CA 95035"
            ],
        ),
        SimpleNamespace(
            url="https://linkedin.com/company/linear-technology",
            excerpts=[
                "Linear Technology corporate office "
                "1630 McCarthy Blvd, Milpitas, CA 95035"
            ],
        ),
    ]

    offices = offices_from_search_results(
        company,
        results,
        country_code="US",
        max_offices=10,
    )

    assert offices == []


def test_accepts_official_company_location_page() -> None:
    company = Company(
        input_domain="linear.app",
        organization_id=654,
        company_name="Linear",
        company_domain="linear.app",
    )
    results = [
        SimpleNamespace(
            url="https://linear.app/contact",
            excerpts=["Linear HQ 1 Market St, San Francisco, CA 94105"],
        )
    ]

    offices = offices_from_search_results(
        company,
        results,
        country_code="US",
        max_offices=10,
    )

    assert len(offices) == 1
    assert offices[0].company_domain == "linear.app"
    assert offices[0].validation_status == "verified"
    assert offices[0].validation_reason == "Official operational office page"


def test_marks_private_mailboxes_as_rejected() -> None:
    results = [
        SimpleNamespace(
            url="https://example.com/contact",
            excerpts=["Mailing address: 548 Market St PMB 123, San Francisco, CA 94104"],
        )
    ]

    offices = offices_from_search_results(
        _company(),
        results,
        country_code="US",
        max_offices=10,
    )

    assert len(offices) == 1
    assert offices[0].validation_status == "rejected"
    assert "Non-operational" in offices[0].validation_reason


def test_official_legal_page_requires_review() -> None:
    results = [
        SimpleNamespace(
            url="https://example.com/legal/terms",
            excerpts=["Example headquarters: 1 Main St, Boston, MA 02110"],
        )
    ]

    offices = offices_from_search_results(
        _company(),
        results,
        country_code="US",
        max_offices=10,
    )

    assert len(offices) == 1
    assert offices[0].validation_status == "review_required"
    assert offices[0].validation_reason == "Official legal page only"


def test_two_independent_sources_verify_the_same_address() -> None:
    results = [
        SimpleNamespace(
            url="https://linkedin.com/company/example",
            excerpts=[
                "Example (example.com) corporate office 1 Main St, Boston, MA 02110"
            ],
        ),
        SimpleNamespace(
            url="https://pitchbook.com/profiles/example",
            excerpts=[
                "Example (example.com) headquarters 1 Main Street, Boston, MA 02110"
            ],
        ),
    ]

    offices = offices_from_search_results(
        _company(),
        results,
        country_code="US",
        max_offices=10,
    )

    assert len(offices) == 1
    assert offices[0].validation_status == "verified"
    assert offices[0].evidence_count == 2
    assert len(offices[0].evidence_urls) == 2
    assert len(json.loads(offices[0].evidence_json)) == 2


def test_two_subdomains_of_one_site_are_not_independent_sources() -> None:
    results = [
        SimpleNamespace(
            url="https://directory.example.net/example",
            excerpts=[
                "Example (example.com) corporate office 1 Main St, Boston, MA 02110"
            ],
        ),
        SimpleNamespace(
            url="https://news.example.net/example",
            excerpts=[
                "Example (example.com) headquarters 1 Main Street, Boston, MA 02110"
            ],
        ),
    ]

    offices = offices_from_search_results(
        _company(),
        results,
        country_code="US",
        max_offices=10,
    )

    assert len(offices) == 1
    assert offices[0].validation_status == "review_required"
    assert offices[0].evidence_count == 1


def test_two_stale_sources_still_require_review() -> None:
    results = [
        SimpleNamespace(
            url="https://linkedin.com/company/example",
            publish_date="2020-01-01",
            excerpts=[
                "Example (example.com) corporate office 1 Main St, Boston, MA 02110"
            ],
        ),
        SimpleNamespace(
            url="https://pitchbook.com/profiles/example",
            publish_date="2021-01-01",
            excerpts=[
                "Example (example.com) headquarters 1 Main Street, Boston, MA 02110"
            ],
        ),
    ]

    offices = offices_from_search_results(
        _company(),
        results,
        country_code="US",
        max_offices=10,
    )

    assert len(offices) == 1
    assert offices[0].validation_status == "review_required"
    assert offices[0].validation_reason == "Only stale dated evidence was found"


def test_closed_location_is_visible_but_rejected() -> None:
    results = [
        SimpleNamespace(
            url="https://example.com/contact",
            excerpts=[
                "Our former office was 1 Main St, Boston, MA 02110. We have relocated."
            ],
        )
    ]

    offices = offices_from_search_results(
        _company(),
        results,
        country_code="US",
        max_offices=10,
    )

    assert len(offices) == 1
    assert offices[0].validation_status == "rejected"
    assert "closed location" in offices[0].validation_reason
