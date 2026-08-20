from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date
from urllib.parse import urlparse

from parallel import Parallel

from direct_mail.models import Company, Office

_US_STATE_CODES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}
_US_STATE_PATTERN = "|".join(
    re.escape(state) for state in sorted(_US_STATE_CODES, key=len, reverse=True)
)
_STREET_SUFFIX_PATTERN = (
    r"Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Drive|Dr\.?|"
    r"Lane|Ln\.?|Way|Court|Ct\.?|Highway|Hwy\.?|Place|Pl\.?|Parkway|Pkwy\.?|Broadway"
)
_US_ADDRESS_PATTERN = re.compile(
    rf"""
    (?P<street>
        \d{{1,6}}[A-Za-z]?\s+
        (?:[A-Za-z0-9\#.'’-]+[\s,]+){{0,10}}?
        (?<![A-Za-z])(?:{_STREET_SUFFIX_PATTERN})(?=\s|,|$)
        (?:
            \s*,?\s*(?:Suite|Ste\.?|Floor|Fl\.?|Unit|Building|PMB|\#)\s*\#?[A-Za-z0-9-]+
            |\s+\d+(?:st|nd|rd|th)?\s+Floor
        )?
    )
    \s*,?\s+
    (?P<city>[A-Za-z][A-Za-z .'-]{{1,50}}?)
    \s*,?\s+
    (?P<state>{_US_STATE_PATTERN}|[A-Z]{{2}})
    \s*,?\s+
    (?P<postal>\d{{5}}(?:-\d{{4}})?)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_US_STREET_LINE_PATTERN = re.compile(
    rf"""
    ^(?P<street>
        \d{{1,6}}[A-Za-z]?\s+
        (?:[A-Za-z0-9\#.'’-]+[\s,]+){{0,10}}?
        (?<![A-Za-z])(?:{_STREET_SUFFIX_PATTERN})(?=\s|,|$)
        (?:
            \s*,?\s*(?:Suite|Ste\.?|Floor|Fl\.?|Unit|Building|PMB|\#)\s*\#?[A-Za-z0-9-]+
            |\s+\d+(?:st|nd|rd|th)?\s+Floor
        )?
    )$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_POSTAL_PATTERNS = {
    "CA": re.compile(r"\b[A-Z]\d[A-Z][ -]?\d[A-Z]\d\b", re.IGNORECASE),
    "GB": re.compile(
        r"\b(?:GIR\s?0AA|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})\b",
        re.IGNORECASE,
    ),
    "AU": re.compile(r"\b\d{4}\b"),
    "DE": re.compile(r"\b\d{5}\b"),
    "FR": re.compile(r"\b\d{5}\b"),
    "NL": re.compile(r"\b\d{4}\s?[A-Z]{2}\b", re.IGNORECASE),
    "SG": re.compile(r"\b\d{6}\b"),
}
_ADDRESS_MARKER = re.compile(
    r"(?:corporate office|headquarters|office address|address|located at|"
    r"locations? primary)\s*:?\s*",
    re.IGNORECASE,
)
_OFFICE_CONTEXT_PATTERN = re.compile(
    r"\b(?:headquarters|head office|corporate office|office location|office locations|"
    r"our office|our offices|physical office|located at)\b",
    re.IGNORECASE,
)
_NON_PHYSICAL_ADDRESS_PATTERN = re.compile(
    r"\b(?:P\.?\s*O\.?\s+Box|Post Office Box|PMB|private mailbox|registered agent|"
    r"registered office|virtual office|mail drop|mailing address|coworking|"
    r"co-working|shared workspace)\b",
    re.IGNORECASE,
)
_CLOSED_LOCATION_PATTERN = re.compile(
    r"\b(?:former(?:ly)?|previous(?:ly)?|old address|closed|permanently closed|"
    r"relocated from|moved from|no longer located)\b",
    re.IGNORECASE,
)
_OFFICIAL_OPERATIONAL_PATH_HINTS = (
    "about",
    "career",
    "company",
    "contact",
    "location",
    "office",
)
_OFFICIAL_LEGAL_PATH_HINTS = (
    "legal",
    "privacy",
    "terms",
)
_LOW_TRUST_SOURCE_DOMAINS = {
    "cbinsights.com",
    "datanyze.com",
    "opencorporates.com",
    "rocketreach.co",
    "signalhire.com",
    "usearch.com",
    "zoominfo.com",
}
_STRONG_SOURCE_DOMAINS = {
    "bizjournals.com",
    "costar.com",
    "pitchbook.com",
    "therealdeal.com",
    "traded.co",
}
_MULTI_LABEL_PUBLIC_SUFFIXES = {
    "co.in",
    "co.jp",
    "co.uk",
    "com.au",
    "com.br",
    "com.sg",
}


class ParallelOfficeError(RuntimeError):
    pass


def _normalize_spaces(value: str) -> str:
    return " ".join(value.strip().split())


def _evidence_fields(
    source_url: str,
    source_date: str,
    excerpt: str,
) -> dict[str, object]:
    normalized_excerpt = _normalize_spaces(excerpt)[:1_000]
    fields: dict[str, object] = {
        "source_url": source_url,
        "source_date": source_date,
        "evidence_excerpt": normalized_excerpt,
        "evidence_json": json.dumps(
            [
                {
                    "url": source_url,
                    "source_date": source_date,
                    "excerpt": normalized_excerpt,
                }
            ],
            separators=(",", ":"),
        ),
        "evidence_urls": [source_url] if source_url else [],
        "evidence_count": 1 if source_url else 0,
        "checked_at": date.today().isoformat(),
    }
    rejection_reason = _context_rejection_reason(excerpt)
    if rejection_reason:
        fields["validation_status"] = "rejected"
        fields["validation_reason"] = rejection_reason
    return fields


def _company_domains(company: Company) -> set[str]:
    return {
        domain.removeprefix("www.").lower()
        for domain in (company.company_domain, company.sumble_domain)
        if domain
    }


def _is_company_source(source_url: str, company: Company) -> bool:
    source_host = (urlparse(source_url).hostname or "").removeprefix("www.").lower()
    return any(
        source_host == company_host or source_host.endswith(f".{company_host}")
        for company_host in _company_domains(company)
    )


def _source_host(source_url: str) -> str:
    return (urlparse(source_url).hostname or "").removeprefix("www.").lower()


def _source_domain(source_url: str) -> str:
    host = _source_host(source_url)
    parts = host.split(".")
    if len(parts) < 3 or re.fullmatch(r"[\d.]+", host):
        return host
    suffix = ".".join(parts[-2:])
    if suffix in _MULTI_LABEL_PUBLIC_SUFFIXES and len(parts) >= 3:
        return ".".join(parts[-3:])
    return suffix


def _source_kind(source_url: str, company: Company) -> str:
    if not _is_company_source(source_url, company):
        return "third_party"
    source_path = urlparse(source_url).path.casefold()
    if any(hint in source_path for hint in _OFFICIAL_LEGAL_PATH_HINTS):
        return "official_legal"
    if any(hint in source_path for hint in _OFFICIAL_OPERATIONAL_PATH_HINTS):
        return "official_operational"
    return "official_other"


def _independent_source_id(source_url: str, company: Company) -> str:
    if _is_company_source(source_url, company):
        return f"official:{company.company_domain}"
    return _source_domain(source_url)


def _source_confidence(source_url: str, company: Company) -> str:
    if _is_company_source(source_url, company):
        return "high"
    source_host = (urlparse(source_url).hostname or "").removeprefix("www.").lower()
    if any(
        source_host == domain or source_host.endswith(f".{domain}")
        for domain in _LOW_TRUST_SOURCE_DOMAINS
    ):
        return "low"
    return "medium"


def _source_priority(source_url: str, company: Company) -> int:
    if _is_company_source(source_url, company):
        return 4
    source_host = (urlparse(source_url).hostname or "").removeprefix("www.").lower()
    if source_host == "linkedin.com" or source_host.endswith(".linkedin.com"):
        return 3
    if any(
        source_host == domain or source_host.endswith(f".{domain}")
        for domain in _STRONG_SOURCE_DOMAINS
    ):
        return 2
    if any(
        source_host == domain or source_host.endswith(f".{domain}")
        for domain in _LOW_TRUST_SOURCE_DOMAINS
    ):
        return 0
    return 1


def _mentions_verified_domain(company: Company, text: str) -> bool:
    haystack = text.casefold()
    return any(
        re.search(
            rf"(?<![a-z0-9.-])(?:https?://)?(?:www\.)?{re.escape(domain)}"
            rf"(?=$|[/\s,;:)\]])",
            haystack,
        )
        for domain in _company_domains(company)
    )


def _source_has_office_context(
    company: Company,
    source_url: str,
    context: str,
) -> bool:
    if _context_rejection_reason(context):
        return True
    if _source_kind(source_url, company) == "official_operational":
        return True
    return _OFFICE_CONTEXT_PATTERN.search(context) is not None


def _context_rejection_reason(context: str) -> str:
    non_physical = _NON_PHYSICAL_ADDRESS_PATTERN.search(context)
    if non_physical:
        return f"Non-operational address context: {non_physical.group(0)}"
    if _CLOSED_LOCATION_PATTERN.search(context):
        return "Former, relocated, or closed location context"
    return ""


def _clean_us_street(value: str) -> str:
    street = _normalize_spaces(value)
    suffix_matches = list(
        re.finditer(
            rf"(?<![A-Za-z])(?:{_STREET_SUFFIX_PATTERN})(?=\s|,|$)",
            street,
            flags=re.IGNORECASE,
        )
    )
    if suffix_matches:
        suffix_start = suffix_matches[-1].start()
        number_matches = list(
            re.finditer(r"\b\d{1,6}[A-Za-z]?\s+", street[:suffix_start])
        )
        if number_matches:
            street = street[number_matches[-1].start() :]
    return re.sub(
        rf",\s+(?=(?:{_STREET_SUFFIX_PATTERN})(?:\s|,|$))",
        " ",
        street,
        flags=re.IGNORECASE,
    ).strip(" ,")


def _us_office_key(office: Office) -> tuple[str, str, str]:
    street_base = re.sub(
        r"\s+\d+(?:st|nd|rd|th)\s+floor\b.*$",
        "",
        office.street,
        flags=re.IGNORECASE,
    )
    street_base = re.sub(
        r"\s+(?:suite|ste\.?|floor|fl\.?|unit|#)\s*[a-z0-9-]+\b.*$",
        "",
        street_base,
        flags=re.IGNORECASE,
    )
    suffix_replacements = {
        r"\bst\.?\b": "street",
        r"\bave\.?\b": "avenue",
        r"\brd\.?\b": "road",
        r"\bblvd\.?\b": "boulevard",
        r"\bdr\.?\b": "drive",
        r"\bln\.?\b": "lane",
        r"\bct\.?\b": "court",
        r"\bhwy\.?\b": "highway",
        r"\bpl\.?\b": "place",
        r"\bpkwy\.?\b": "parkway",
    }
    for pattern, replacement in suffix_replacements.items():
        street_base = re.sub(pattern, replacement, street_base, flags=re.IGNORECASE)
    city = re.sub(r"[^a-z0-9]+", "", office.city.casefold())
    city = city.removesuffix("city")
    return (
        office.state_region.casefold(),
        city,
        re.sub(r"[^a-z0-9]+", "", street_base.casefold()),
    )


def _office_preference(
    office: Office,
    company: Company,
) -> tuple[int, int, int, int]:
    confidence_rank = {"high": 2, "medium": 1, "low": 0}
    return (
        confidence_rank.get(office.confidence, 0),
        _source_priority(office.source_url, company),
        -len(office.street),
        -len(office.city),
    )


def _source_is_stale(source_date: str) -> bool:
    if not source_date:
        return False
    try:
        published = date.fromisoformat(source_date[:10])
    except ValueError:
        return False
    return (date.today() - published).days > 3 * 365


def _aggregate_office_candidates(
    candidates: list[Office],
    company: Company,
) -> Office:
    eligible = [
        office for office in candidates if office.validation_status != "rejected"
    ]
    ranked_candidates = eligible or candidates
    best = max(
        ranked_candidates,
        key=lambda office: _office_preference(office, company),
    )
    aggregated = best.model_copy(deep=True)
    evidence_urls = list(
        dict.fromkeys(
            office.source_url for office in candidates if office.source_url
        )
    )
    source_ids = {
        _independent_source_id(office.source_url, company)
        for office in eligible
        if office.source_url
    }
    source_kinds = {
        _source_kind(office.source_url, company)
        for office in eligible
        if office.source_url
    }
    source_dates = [office.source_date for office in eligible if office.source_date]
    has_strong_source = any(
        _source_priority(office.source_url, company) >= 2 for office in eligible
    )
    evidence_records = list(
        {
            (
                office.source_url,
                office.source_date,
                office.evidence_excerpt,
            ): {
                "url": office.source_url,
                "source_date": office.source_date,
                "excerpt": office.evidence_excerpt,
            }
            for office in candidates
            if office.source_url
        }.values()
    )

    aggregated.evidence_urls = evidence_urls
    aggregated.evidence_count = len(source_ids)
    aggregated.evidence_json = json.dumps(
        evidence_records,
        separators=(",", ":"),
    )
    if not eligible:
        aggregated.validation_status = "rejected"
        aggregated.validation_reason = best.validation_reason
        aggregated.confidence = "low"
    elif "official_operational" in source_kinds:
        aggregated.validation_status = "verified"
        aggregated.validation_reason = "Official operational office page"
        aggregated.confidence = "high"
    elif len(source_ids) >= 2 and has_strong_source and not (
        source_dates and all(_source_is_stale(value) for value in source_dates)
    ):
        aggregated.validation_status = "verified"
        aggregated.validation_reason = "Confirmed by independent sources"
        aggregated.confidence = "medium"
    elif source_dates and all(_source_is_stale(value) for value in source_dates):
        aggregated.validation_status = "review_required"
        aggregated.validation_reason = "Only stale dated evidence was found"
        aggregated.confidence = "low"
    elif "official_legal" in source_kinds:
        aggregated.validation_status = "review_required"
        aggregated.validation_reason = "Official legal page only"
        aggregated.confidence = "low"
    elif "official_other" in source_kinds:
        aggregated.validation_status = "review_required"
        aggregated.validation_reason = "Official non-location page only"
        aggregated.confidence = "low"
    elif len(source_ids) >= 2:
        aggregated.validation_status = "review_required"
        aggregated.validation_reason = "No strong source confirmed the consensus"
        aggregated.confidence = "low"
    else:
        aggregated.validation_status = "review_required"
        aggregated.validation_reason = "Only one independent third-party source"
        aggregated.confidence = "low"
    return aggregated


def _us_offices_from_text(
    company: Company,
    text: str,
    source_url: str,
    source_date: str,
) -> list[Office]:
    confidence = _source_confidence(source_url, company)
    offices: list[Office] = []
    for match in _US_ADDRESS_PATTERN.finditer(text):
        context = text[max(0, match.start() - 180) : min(len(text), match.end() + 120)]
        if not _source_has_office_context(company, source_url, context):
            continue
        state_value = _normalize_spaces(match.group("state"))
        state_region = _US_STATE_CODES.get(state_value.casefold(), state_value.upper())
        street = _clean_us_street(match.group("street"))
        offices.append(
            Office(
                company_domain=company.company_domain,
                company_name=company.company_name,
                office_name=f"{company.company_name} office",
                street=street,
                city=_normalize_spaces(match.group("city")),
                state_region=state_region,
                postal_code=match.group("postal").upper(),
                country_code="US",
                source="parallel_search",
                confidence=confidence,
                **_evidence_fields(source_url, source_date, context),
            )
        )
    return offices


def _markdown_lines(text: str) -> list[str]:
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw_line)
        line = re.sub(r"^[\s#*+-]+", "", line).strip()
        if line:
            lines.append(line)
    return lines


def _state_code(value: str) -> str:
    normalized = _normalize_spaces(value).strip(" ,.-").casefold()
    if normalized in _US_STATE_CODES:
        return _US_STATE_CODES[normalized]
    upper = normalized.upper()
    if upper in _US_STATE_CODES.values():
        return upper
    return ""


def _us_location_from_line(value: str, office_label: str) -> tuple[str, str, str] | None:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) < 2:
        return None
    city = parts[0]
    postal_match = re.search(r"\b\d{5}(?:-\d{4})?\b", value)
    postal_code = postal_match.group(0) if postal_match else ""
    state_region = ""
    for part in parts[1:]:
        state_candidate = re.sub(r"\b\d{5}(?:-\d{4})?\b", "", part)
        state_candidate = re.sub(
            r"\b(?:United States(?: of America)?|USA|US)\b",
            "",
            state_candidate,
            flags=re.IGNORECASE,
        )
        state_region = _state_code(state_candidate)
        if state_region:
            break
    if not state_region:
        label_without_hq = re.sub(r"\s*\(HQ\)\s*", "", office_label, flags=re.IGNORECASE)
        state_region = _state_code(label_without_hq)
    if not state_region:
        return None
    return city, state_region, postal_code


def _us_office_blocks_from_text(
    company: Company,
    text: str,
    source_url: str,
    source_date: str,
) -> list[Office]:
    lines = _markdown_lines(text)
    confidence = _source_confidence(source_url, company)
    offices = []
    for index, line in enumerate(lines):
        street_match = _US_STREET_LINE_PATTERN.fullmatch(line)
        if street_match is None or index == 0 or index + 1 >= len(lines):
            continue
        office_label = lines[index - 1]
        context = " ".join(lines[max(0, index - 2) : min(len(lines), index + 3)])
        if not _source_has_office_context(company, source_url, context):
            continue
        location = _us_location_from_line(lines[index + 1], office_label)
        if location is None:
            continue
        city, state_region, postal_code = location
        label_suffix = "" if office_label.casefold() == "hq" else " office"
        offices.append(
            Office(
                company_domain=company.company_domain,
                company_name=company.company_name,
                office_name=f"{company.company_name} {office_label}{label_suffix}",
                street=_clean_us_street(street_match.group("street")),
                city=city,
                state_region=state_region,
                postal_code=postal_code,
                country_code="US",
                source="parallel_extract",
                confidence=confidence,
                **_evidence_fields(source_url, source_date, context),
            )
        )
    return offices


def _generic_offices_from_text(
    company: Company,
    text: str,
    source_url: str,
    source_date: str,
    country_code: str,
) -> list[Office]:
    postal_pattern = _POSTAL_PATTERNS.get(country_code)
    if postal_pattern is None:
        return []
    confidence = _source_confidence(source_url, company)
    offices: list[Office] = []
    for match in postal_pattern.finditer(text):
        window = text[max(0, match.start() - 140) : min(len(text), match.end() + 50)]
        if not _source_has_office_context(company, source_url, window):
            continue
        markers = list(_ADDRESS_MARKER.finditer(window))
        if markers:
            window = window[markers[-1].end() :]
        window = re.split(r"[;|\n]", window, maxsplit=1)[0]
        candidate = _normalize_spaces(window).strip(" ,.-")
        parts = [part.strip() for part in candidate.split(",") if part.strip()]
        if len(parts) < 2 or not re.search(r"\d", parts[0]):
            continue
        postal_code = match.group(0).upper()
        street = parts[0]
        city = parts[-1].replace(postal_code, "").strip(" ,.-")
        state_region = ""
        if len(parts) >= 3:
            city = parts[-2]
            state_region = parts[-1].replace(postal_code, "").strip(" ,.-")
        offices.append(
            Office(
                company_domain=company.company_domain,
                company_name=company.company_name,
                office_name=f"{company.company_name} office",
                street=street,
                city=city,
                state_region=state_region,
                postal_code=postal_code,
                country_code=country_code,
                source="parallel_search",
                confidence=confidence,
                **_evidence_fields(source_url, source_date, window),
            )
        )
    return offices


def offices_from_search_results(
    company: Company,
    results: Iterable[object],
    *,
    country_code: str,
    max_offices: int,
) -> list[Office]:
    candidates: list[Office] = []
    for result in results:
        source_url = str(getattr(result, "url", "") or "")
        source_date = str(getattr(result, "publish_date", "") or "")
        excerpts = getattr(result, "excerpts", None) or []
        for excerpt in excerpts:
            raw_text = str(excerpt)
            text = _normalize_spaces(raw_text)
            if not _is_company_source(
                source_url, company
            ) and not _mentions_verified_domain(company, f"{source_url} {text}"):
                continue
            if country_code == "US":
                candidates.extend(
                    _us_offices_from_text(
                        company,
                        text,
                        source_url,
                        source_date,
                    )
                )
                candidates.extend(
                    _us_office_blocks_from_text(
                        company,
                        raw_text,
                        source_url,
                        source_date,
                    )
                )
            else:
                candidates.extend(
                    _generic_offices_from_text(
                        company,
                        text,
                        source_url,
                        source_date,
                        country_code,
                    )
                )

    grouped: dict[tuple[str, str, str], list[Office]] = {}
    for office in candidates:
        key = _us_office_key(office) if country_code == "US" else (
            re.sub(r"[^a-z0-9]+", "", office.street.casefold()),
            office.city.casefold(),
            office.postal_code.casefold(),
        )
        grouped.setdefault(key, []).append(office)

    offices = [
        _aggregate_office_candidates(group, company) for group in grouped.values()
    ]
    confidence_rank = {"high": 0, "medium": 1, "low": 2}
    status_rank = {"verified": 0, "review_required": 1, "rejected": 2}
    return sorted(
        offices,
        key=lambda office: (
            status_rank.get(office.validation_status, 3),
            confidence_rank.get(office.confidence, 3),
            -_source_priority(office.source_url, company),
            office.city,
            office.street,
        ),
    )[:max_offices]


def discover_company_offices(
    company: Company,
    api_key: str,
    *,
    country_code: str = "US",
    max_offices: int = 10,
    mode: str = "basic",
    client: Parallel | None = None,
) -> list[Office]:
    if not api_key.strip():
        raise ValueError("PARALLEL_API_KEY is missing.")

    current_year = date.today().year
    objective = (
        f"Determine the current physical headquarters or office street addresses for "
        f"{company.company_name} at {company.company_domain} in {country_code} as of "
        f"{current_year}. Return excerpts that explicitly associate the company with each "
        "complete street address. Prefer official office, locations, contact, or careers pages. "
        "When no operational company page exists, find at least two independent sources that "
        "agree on the address. Exclude legal-only addresses, former or closed locations, "
        "registered agents, mailboxes, coworking spaces, and virtual offices."
    )
    search_queries = [
        f'"{company.company_name}" "{company.company_domain}" current office address',
        f'"{company.company_name}" "{company.company_domain}" office lease {current_year}',
        f'"{company.company_name}" "{company.company_domain}" headquarters address',
        f"site:{company.company_domain} address location",
    ]

    try:
        search_client = client or Parallel(api_key=api_key.strip())
        search_settings = {
            "location": country_code.lower(),
            "max_results": 20,
            "excerpt_settings": {"max_chars_per_result": 2_500},
        }
        result = search_client.search(
            objective=objective,
            search_queries=search_queries,
            mode=mode,
            max_chars_total=20_000,
            advanced_settings=search_settings
            | {
                "source_policy": {
                    "exclude_domains": sorted(_LOW_TRUST_SOURCE_DOMAINS)
                }
            },
            timeout=15,
        )
        combined_results = list(result.results)
        official_location_urls = []
        for search_result in result.results:
            source_url = str(getattr(search_result, "url", "") or "")
            if _source_kind(source_url, company) == "official_operational":
                official_location_urls.append(source_url)
        official_location_urls = list(dict.fromkeys(official_location_urls))[:3]
        if official_location_urls and hasattr(search_client, "extract"):
            try:
                extract_result = search_client.extract(
                    urls=official_location_urls,
                    objective=(
                        f"Extract every current physical {company.company_name} office in "
                        f"{country_code}. Preserve each office label, street address, city, "
                        "state or region, and postal code when provided. Include entries whose "
                        "page omits a postal code."
                    ),
                    search_queries=[
                        f"{country_code} office locations",
                        "street addresses",
                        "headquarters offices",
                    ],
                    max_chars_total=40_000,
                    session_id=getattr(result, "session_id", None),
                    advanced_settings={
                        "excerpt_settings": {"max_chars_per_result": 20_000}
                    },
                    timeout=20,
                )
                combined_results.extend(extract_result.results)
            except Exception:
                pass
    except Exception as exc:
        raise ParallelOfficeError(
            f"Parallel Search failed for {company.company_domain}: {exc}"
        ) from exc

    return offices_from_search_results(
        company,
        combined_results,
        country_code=country_code,
        max_offices=max_offices,
    )
