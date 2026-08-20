from direct_mail.sumble_api import SumbleClient


def test_resolve_companies_requests_and_parses_free_attributes(monkeypatch) -> None:
    client = SumbleClient("test-key")
    captured_payload = {}

    def fake_post(_path: str, payload: dict) -> dict:
        captured_payload.update(payload)
        return {
            "organizations": [
                {
                    "input": {"url": "example.com"},
                    "attributes": {
                        "id": 123,
                        "name": "Example",
                        "slug": "example",
                        "url": "example.com",
                        "sumble_url": "https://sumble.com/example",
                        "headquarters_country": "US",
                        "headquarters_address": {
                            "street": "1 Main St",
                            "city": "Boston",
                            "state": "Massachusetts",
                            "state_code": "MA",
                            "postal_code": "02110",
                            "country_code": "US",
                        },
                    },
                }
            ]
        }

    monkeypatch.setattr(client, "_post", fake_post)

    companies, unmatched = client.resolve_companies(["example.com", "missing.test"])

    assert captured_payload["select"]["attributes"] == [
        "id",
        "name",
        "slug",
        "url",
        "sumble_url",
        "headquarters_address",
    ]
    assert companies[0].organization_id == 123
    assert companies[0].company_name == "Example"
    assert companies[0].company_domain == "example.com"
    assert companies[0].sumble_domain == "example.com"
    assert companies[0].headquarters_address is not None
    assert companies[0].headquarters_address.city == "Boston"
    assert unmatched == ["missing.test"]
    client.close()


def test_resolve_companies_falls_back_before_address_attribute_is_deployed(
    monkeypatch,
) -> None:
    client = SumbleClient("test-key")
    captured_payloads = []

    def fake_post(_path: str, payload: dict) -> dict:
        captured_payloads.append(payload["select"]["attributes"].copy())
        if "headquarters_address" in payload["select"]["attributes"]:
            from direct_mail.sumble_api import SumbleAPIError

            raise SumbleAPIError("Invalid attributes: ['headquarters_address']")
        return {"organizations": []}

    monkeypatch.setattr(client, "_post", fake_post)

    companies, unmatched = client.resolve_companies(["example.com"])

    assert companies == []
    assert unmatched == ["example.com"]
    assert "headquarters_address" in captured_payloads[0]
    assert "headquarters_address" not in captured_payloads[1]
    assert "headquarters_country" in captured_payloads[1]
    client.close()


def test_rejects_mismatched_sumble_organization(monkeypatch) -> None:
    client = SumbleClient("test-key")

    def fake_post(_path: str, _payload: dict) -> dict:
        return {
            "organizations": [
                {
                    "input": {"url": "purestorage.com"},
                    "attributes": {
                        "id": 2664,
                        "name": "Everpure",
                        "slug": "pure-storage",
                        "url": "everpuredata.com",
                    },
                }
            ]
        }

    monkeypatch.setattr(client, "_post", fake_post)

    companies, unmatched = client.resolve_companies(["purestorage.com"])

    assert companies == []
    assert unmatched == ["purestorage.com"]
    client.close()


def test_rejects_same_word_inside_a_different_domain_brand(monkeypatch) -> None:
    client = SumbleClient("test-key")

    def fake_post(_path: str, _payload: dict) -> dict:
        return {
            "organizations": [
                {
                    "input": {"url": "commerce.com"},
                    "attributes": {
                        "id": "org-commerce-bank",
                        "name": "Commerce Bank",
                        "url": "commercebank.com",
                    },
                }
            ]
        }

    monkeypatch.setattr(client, "_post", fake_post)

    companies, unmatched = client.resolve_companies(["commerce.com"])

    assert companies == []
    assert unmatched == ["commerce.com"]
    client.close()


def test_preserves_input_domain_for_plausible_alias(monkeypatch) -> None:
    client = SumbleClient("test-key")

    def fake_post(_path: str, _payload: dict) -> dict:
        return {
            "organizations": [
                {
                    "input": {"url": "notion.com"},
                    "attributes": {
                        "id": 3730,
                        "name": "Notion",
                        "slug": "notion-labs",
                        "url": "notion.so",
                    },
                }
            ]
        }

    monkeypatch.setattr(client, "_post", fake_post)

    companies, unmatched = client.resolve_companies(["notion.com"])

    assert unmatched == []
    assert companies[0].company_domain == "notion.com"
    assert companies[0].sumble_domain == "notion.so"
    client.close()
