from __future__ import annotations

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


class HeadquartersAddress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    street: str = ""
    city: str = ""
    state: str = ""
    state_code: str = ""
    postal_code: str = ""
    country_code: str = ""


class Company(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input_domain: str
    organization_id: int = Field(exclude=True)
    company_name: str
    company_domain: str
    sumble_domain: str = ""
    company_slug: str = ""
    headquarters_country: str = ""
    headquarters_address: HeadquartersAddress | None = None
    sumble_url: str = ""


class Office(BaseModel):
    model_config = ConfigDict(extra="ignore")

    company_domain: str
    company_name: str = ""
    office_name: str = "Office"
    street: str = ""
    city: str
    state_region: str = ""
    postal_code: str = ""
    country_code: str = "US"
    latitude: float | None = None
    longitude: float | None = None
    geocode_source: str = ""
    geocode_match: str = ""
    geocode_validation: str = ""
    source: str = "uploaded"
    source_url: str = ""
    source_date: str = ""
    evidence_excerpt: str = ""
    evidence_json: str = ""
    evidence_urls: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    confidence: str = ""
    validation_status: str = "review_required"
    validation_reason: str = ""
    checked_at: str = Field(
        default="",
        validation_alias=AliasChoices("checked_at", "last_verified_at"),
    )

    @field_validator("company_domain", mode="before")
    @classmethod
    def normalize_company_domain(cls, value: object) -> str:
        return str(value or "").strip().lower()

    @property
    def address(self) -> str:
        parts = [
            self.street,
            self.city,
            self.state_region,
            self.postal_code,
            self.country_code,
        ]
        return ", ".join(part.strip() for part in parts if part and part.strip())


class Person(BaseModel):
    model_config = ConfigDict(extra="ignore")

    person_id: int = Field(exclude=True)
    company_domain: str
    company_name: str
    person_name: str
    current_title: str = ""
    job_function: str = ""
    job_level: str = ""
    person_location: str = ""
    country: str = ""
    linkedin_url: str = ""
    sumble_url: str = ""
    latitude: float | None = None
    longitude: float | None = None
