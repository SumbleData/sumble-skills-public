from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable

import httpx

from direct_mail.models import Company, HeadquartersAddress, Person


class SumbleAPIError(RuntimeError):
    pass


def _normalize_domain(value: object) -> str:
    domain = str(value or "").strip().lower()
    domain = re.sub(r"^https?://", "", domain)
    domain = re.sub(r"^www\.", "", domain)
    return domain.split("/", 1)[0]


def _normalized_brand(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _normalized_company_name(value: str) -> str:
    name = value.casefold().strip()
    name = re.sub(r"\.(?:ai|app|com|dev|io|so)\s*$", "", name)
    name = re.sub(
        r"(?:\s|,)+(?:co|corp|corporation|inc|incorporated|limited|llc|ltd|plc)\.?$",
        "",
        name,
    )
    return _normalized_brand(name)


def _is_plausible_domain_alias(
    input_domain: str,
    sumble_domain: str,
    company_name: str,
) -> bool:
    if input_domain == sumble_domain:
        return True
    input_brand = _normalized_brand(input_domain.split(".", 1)[0])
    sumble_brand = _normalized_brand(sumble_domain.split(".", 1)[0])
    company_brand = _normalized_company_name(company_name)
    return bool(
        input_brand
        and input_brand == sumble_brand
        and company_brand
        and input_brand == company_brand
    )


class SumbleClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.sumble.com/v9",
        timeout_seconds: float = 90.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("SUMBLE_API_KEY is missing.")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json",
            },
            timeout=timeout_seconds,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> SumbleClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text.strip() or f"HTTP {response.status_code}"
        detail = payload.get("detail", payload)
        return str(detail)

    def _post(self, path: str, payload: dict) -> dict:
        response = self._client.post(path, json=payload)
        if not response.is_success:
            raise SumbleAPIError(self._detail(response))
        return response.json()

    def resolve_companies(self, domains: Iterable[str]) -> tuple[list[Company], list[str]]:
        normalized_domains = list(
            dict.fromkeys(_normalize_domain(domain) for domain in domains)
        )
        address_attributes = [
            "id",
            "name",
            "slug",
            "url",
            "sumble_url",
            "headquarters_address",
        ]
        payload = {
            "organizations": [{"url": domain} for domain in normalized_domains],
            "select": {"attributes": address_attributes},
        }
        try:
            data = self._post("/organizations", payload)
        except SumbleAPIError as exc:
            if "headquarters_address" not in str(exc):
                raise
            payload["select"]["attributes"] = [
                attribute
                for attribute in address_attributes
                if attribute != "headquarters_address"
            ] + ["headquarters_country"]
            data = self._post("/organizations", payload)
        companies: list[Company] = []
        matched_inputs: set[str] = set()
        for row in data.get("organizations", []):
            attributes = row.get("attributes") or {}
            organization_id = attributes.get("id")
            if not organization_id:
                continue
            input_domain = _normalize_domain((row.get("input") or {}).get("url"))
            sumble_domain = _normalize_domain(attributes.get("url"))
            company_name = str(attributes.get("name") or input_domain)
            if not _is_plausible_domain_alias(
                input_domain,
                sumble_domain,
                company_name,
            ):
                continue
            matched_inputs.add(input_domain)
            headquarters_address = (
                HeadquartersAddress.model_validate(attributes["headquarters_address"])
                if attributes.get("headquarters_address")
                else None
            )
            companies.append(
                Company(
                    input_domain=input_domain,
                    organization_id=organization_id,
                    company_name=company_name,
                    company_domain=input_domain,
                    sumble_domain=sumble_domain,
                    company_slug=attributes.get("slug") or "",
                    headquarters_country=(
                        attributes.get("headquarters_country")
                        or (
                            headquarters_address.country_code
                            if headquarters_address
                            else ""
                        )
                    ),
                    headquarters_address=headquarters_address,
                    sumble_url=str(attributes.get("sumble_url") or ""),
                )
            )
        unmatched = [domain for domain in normalized_domains if domain not in matched_inputs]
        return companies, unmatched

    def _poll_people_request(
        self,
        request_id: str,
        *,
        poll_interval_seconds: float,
        max_wait_seconds: float,
        on_poll: Callable[[str], None] | None,
    ) -> dict:
        deadline = time.monotonic() + max_wait_seconds
        while time.monotonic() < deadline:
            data = self._post("/people", {"request_id": request_id})
            request_status = str(data.get("status") or "")
            if on_poll:
                on_poll(request_status)
            if request_status == "succeeded":
                return data
            if request_status == "failed":
                raise SumbleAPIError(str(data.get("detail") or "People search failed."))
            time.sleep(poll_interval_seconds)
        raise SumbleAPIError("People search timed out.")

    def find_people(
        self,
        companies: list[Company],
        query: str,
        *,
        max_people: int = 2_000,
        page_size: int = 200,
        poll_interval_seconds: float = 1.5,
        max_wait_seconds: float = 300.0,
        on_page: Callable[[int, int | None], None] | None = None,
        on_poll: Callable[[str], None] | None = None,
    ) -> list[Person]:
        if not companies:
            return []
        company_by_id = {company.organization_id: company for company in companies}
        people: list[Person] = []
        offset = 0
        total: int | None = None
        while offset < max_people and (total is None or offset < total):
            payload = {
                "filter": {
                    "organization_ids": list(company_by_id),
                    "query": {"query": query},
                },
                "select": {
                    "attributes": [
                        "name",
                        "linkedin_url",
                        "job_title",
                        "job_function",
                        "job_level",
                        "location",
                        "country",
                        "current_employer",
                    ]
                },
                "limit": min(page_size, max_people - offset),
                "offset": offset,
                "order_by_column": "job_level",
                "order_by_direction": "DESC",
            }
            started = self._post("/people", payload)
            request_id = started.get("request_id")
            if request_id:
                result = self._poll_people_request(
                    str(request_id),
                    poll_interval_seconds=poll_interval_seconds,
                    max_wait_seconds=max_wait_seconds,
                    on_poll=on_poll,
                )
            else:
                result = started
            total = int(result.get("total") or 0)
            for row in result.get("people") or []:
                person_id = row.get("person_id")
                attributes = row.get("attributes") or {}
                employer = attributes.get("current_employer") or {}
                organization_id = employer.get("organization_id")
                company = company_by_id.get(organization_id)
                if not person_id or not company:
                    continue
                people.append(
                    Person(
                        person_id=person_id,
                        company_domain=company.company_domain,
                        company_name=company.company_name,
                        person_name=attributes.get("name") or "",
                        current_title=attributes.get("job_title") or "",
                        job_function=attributes.get("job_function") or "",
                        job_level=attributes.get("job_level") or "",
                        person_location=attributes.get("location") or "",
                        country=attributes.get("country") or "",
                        linkedin_url=str(attributes.get("linkedin_url") or ""),
                        sumble_url=str(row.get("sumble_url") or ""),
                    )
                )
            offset += len(result.get("people") or [])
            if on_page:
                on_page(offset, total)
            if not result.get("people"):
                break
        return people
