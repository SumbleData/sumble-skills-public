from __future__ import annotations

from collections.abc import Iterable

JOB_FUNCTION_OPTIONS: dict[str, str] = {
    "Engineering / Engineer": "Engineer",
    "Engineering / Software Engineer": "Software Engineer",
    "Engineering / Data Engineer": "Data Engineer",
    "Engineering / Machine Learning": "Machine Learning",
    "Engineering / AI Engineer": "AI Engineer",
    "Engineering / DevOps": "DevOps",
    "Engineering / Security": "Security",
    "Data / Data Scientist": "Data Scientist",
    "Data / Data Analyst": "Data Analyst",
    "Product / Product Management": "Product Management",
    "Product / Product Design": "Product Design",
    "Sales / Account Executive": "Account Executive",
    "Sales / Sales Development": "SDR",
    "Sales / Sales Operations": "Sales Operations",
    "Sales / Solutions": "Solutions",
    "Revenue / Revenue Operations": "Revenue Operations",
    "Revenue / Business Development": "Business Development",
    "Marketing / Marketing": "Marketing",
    "Marketing / Product Marketing": "Product Marketing",
    "Marketing / Growth": "Growth",
    "Marketing / Content": "Content",
    "Marketing / Digital Marketing": "Digital Marketing",
    "Customer / Customer Success": "Customer Success",
    "Customer / Customer Support": "Customer Support",
    "Finance / Finance": "Finance",
    "Finance / Accountant": "Accountant",
    "Finance / Financial Analyst": "Financial Analyst",
    "People / Human Resources": "Human Resources",
    "Legal / Legal & Compliance": "Legal & Compliance",
    "Operations / Operations": "Operations",
    "Other / Consultant": "Consultant",
    "Other / Government": "Government",
    "Other / Education": "Education",
    "Other / Healthcare Services": "Healthcare Services",
}


JOB_LEVELS_HIGH_TO_LOW = [
    "Board Member",
    "CXO",
    "EVP",
    "CVP",
    "SVP",
    "RVP",
    "AVP",
    "VP",
    "Executive Director",
    "Senior Director",
    "Director",
    "General Manager",
    "Head",
    "Associate Director",
    "Senior Manager",
    "Manager",
    "Principal",
    "Lead",
    "Senior",
    "Individual Contributor",
]

JOB_LEVEL_OPTIONS = {level: level for level in JOB_LEVELS_HIGH_TO_LOW}
DEFAULT_JOB_FUNCTIONS = ["Marketing", "Revenue Operations"]
DEFAULT_JOB_LEVELS = JOB_LEVELS_HIGH_TO_LOW[:11]


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_people_query(
    job_functions: Iterable[str],
    job_levels: Iterable[str],
    country_code: str | None,
) -> str:
    functions = list(dict.fromkeys(value.strip() for value in job_functions if value.strip()))
    levels = list(dict.fromkeys(value.strip() for value in job_levels if value.strip()))
    if not functions:
        raise ValueError("Select at least one job function.")
    if not levels:
        raise ValueError("Select at least one job level.")

    clauses = [
        f"job_function IN ({', '.join(sql_string(value) for value in functions)})",
        f"job_level IN ({', '.join(sql_string(value) for value in levels)})",
    ]
    if country_code:
        clauses.append(f"country EQ {sql_string(country_code)}")
    return " AND ".join(clauses)


def level_rank(level: str | None) -> int:
    if not level or level not in JOB_LEVELS_HIGH_TO_LOW:
        return -1
    return len(JOB_LEVELS_HIGH_TO_LOW) - JOB_LEVELS_HIGH_TO_LOW.index(level)
