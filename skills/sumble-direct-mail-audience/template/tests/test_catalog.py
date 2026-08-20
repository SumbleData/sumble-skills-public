import pytest

from direct_mail.catalog import build_people_query


def test_build_people_query_uses_selected_functions_levels_and_country() -> None:
    query = build_people_query(
        ["Data Engineer", "Revenue Operations"],
        ["Director", "VP"],
        "US",
    )

    assert query == (
        "job_function IN ('Data Engineer', 'Revenue Operations') "
        "AND job_level IN ('Director', 'VP') AND country EQ 'US'"
    )


def test_build_people_query_requires_a_function_and_level() -> None:
    with pytest.raises(ValueError, match="job function"):
        build_people_query([], ["VP"], "US")

    with pytest.raises(ValueError, match="job level"):
        build_people_query(["Engineer"], [], "US")
