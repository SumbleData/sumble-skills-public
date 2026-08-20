import marimo

__generated_with = "0.23.16"
app = marimo.App(width="full")


@app.cell
def _():
    import os
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from pathlib import Path

    import marimo as mo

    from direct_mail.catalog import (
        DEFAULT_JOB_FUNCTIONS,
        DEFAULT_JOB_LEVELS,
        JOB_FUNCTION_OPTIONS,
        JOB_LEVEL_OPTIONS,
        build_people_query,
    )
    from direct_mail.environment import load_environment, masked_key_status
    from direct_mail.geocoding import CachedGeocoder, geocode_offices, geocode_people
    from direct_mail.matching import (
        build_audience,
        companies_dataframe,
        merge_offices,
        offices_dataframe,
        parse_domains,
        parse_offices_csv,
        people_dataframe,
        sumble_headquarters_offices,
    )
    from direct_mail.parallel_offices import discover_company_offices
    from direct_mail.sumble_api import SumbleClient

    return (
        CachedGeocoder,
        DEFAULT_JOB_FUNCTIONS,
        DEFAULT_JOB_LEVELS,
        JOB_FUNCTION_OPTIONS,
        JOB_LEVEL_OPTIONS,
        Path,
        SumbleClient,
        ThreadPoolExecutor,
        as_completed,
        build_audience,
        build_people_query,
        companies_dataframe,
        discover_company_offices,
        geocode_offices,
        geocode_people,
        load_environment,
        masked_key_status,
        merge_offices,
        mo,
        offices_dataframe,
        os,
        parse_domains,
        parse_offices_csv,
        people_dataframe,
        sumble_headquarters_offices,
    )


@app.cell
def _(Path, load_environment, os):
    project_dir = Path(__file__).resolve().parent
    load_environment(project_dir)
    sumble_api_key = os.environ.get("SUMBLE_API_KEY", "").strip()
    parallel_api_key = os.environ.get("PARALLEL_API_KEY", "").strip()
    sumble_api_base_url = os.environ.get(
        "SUMBLE_API_BASE_URL",
        "https://api.sumble.com/v9",
    ).strip()
    geocoder_user_agent = os.environ.get(
        "DIRECT_MAIL_GEOCODER_USER_AGENT",
        "direct-mail-audience-builder",
    ).strip()
    geocode_cache_path = project_dir / ".cache" / "geocodes.sqlite3"
    return (
        geocode_cache_path,
        geocoder_user_agent,
        parallel_api_key,
        sumble_api_base_url,
        sumble_api_key,
    )


@app.cell
def _(mo):
    mo.md("""
    # Direct-mail audience builder

    Find people in selected roles and seniority bands who live near a company office.
    The app resolves companies and people through the public Sumble API, researches
    current offices with Parallel, and calculates distance locally.

    Work through the four stages below. Each stage runs only when you submit it.
    """)
    return


@app.cell
def _(mo):
    get_pipeline_status, set_pipeline_status = mo.state(
        {
            "companies": "Ready",
            "offices": "Waiting",
            "people": "Waiting",
            "matching": "Waiting",
        },
        allow_self_loops=True,
    )
    return get_pipeline_status, set_pipeline_status


@app.cell
def _(get_pipeline_status, mo):
    _status = get_pipeline_status()
    _steps = [
        ("1", "Companies", _status["companies"]),
        ("2", "Offices", _status["offices"]),
        ("3", "People", _status["people"]),
        ("4", "Distance match", _status["matching"]),
    ]
    _kind = {
        "Ready": "info",
        "Waiting": "neutral",
        "Running": "warn",
        "Complete": "success",
        "Failed": "danger",
    }
    mo.hstack(
        [
            mo.callout(
                mo.md(f"**{number}. {label}**\n\n{status}"),
                kind=_kind[status],
            )
            for number, label, status in _steps
        ],
        widths="equal",
        gap=1,
    )
    return


@app.cell
def _(masked_key_status, mo):
    _sumble_status = masked_key_status("SUMBLE_API_KEY")
    _parallel_status = masked_key_status("PARALLEL_API_KEY")
    _kind = "success" if _sumble_status == _parallel_status == "Available" else "warn"
    mo.callout(
        mo.md(
            f"""
            API key status

            | Service | Status |
            | --- | --- |
            | Sumble | {_sumble_status} |
            | Parallel | {_parallel_status} |

            Keys load from `.env` and remain on this machine.
            """
        ),
        kind=_kind,
    )
    return


@app.cell
def _(mo):
    resolve_companies_form = (
        mo.md(
            """
            ## 1. Resolve companies

            Paste domains below, upload a CSV with a `domain` column, or use both.

            {domains_text}

            {domains_file}
            """
        )
        .batch(
            domains_text=mo.ui.text_area(
                label="Company domains",
                placeholder="acme.com\nexample.com",
                rows=8,
                full_width=True,
            ),
            domains_file=mo.ui.file(
                filetypes=[".csv"],
                label="Optional domains CSV",
                kind="area",
            ),
        )
        .form(submit_button_label="Resolve companies")
    )
    resolve_companies_form
    return (resolve_companies_form,)


@app.cell
def _(
    SumbleClient,
    mo,
    parse_domains,
    resolve_companies_form,
    set_pipeline_status,
    sumble_api_base_url,
    sumble_api_key,
):
    mo.stop(resolve_companies_form.value is None)
    _uploaded_files = resolve_companies_form.value["domains_file"] or []
    _uploaded_contents = _uploaded_files[0].contents if _uploaded_files else None
    requested_domains = parse_domains(
        resolve_companies_form.value["domains_text"],
        _uploaded_contents,
    )
    mo.stop(
        not requested_domains,
        mo.callout("Enter at least one company domain.", kind="warn"),
    )
    mo.stop(
        not sumble_api_key,
        mo.callout("SUMBLE_API_KEY is missing.", kind="danger"),
    )

    set_pipeline_status(
        lambda status: status
        | {"companies": "Running", "offices": "Waiting", "people": "Waiting"}
    )
    try:
        with (
            mo.status.spinner(
                title=f"Resolving {len(requested_domains)} companies in Sumble"
            ),
            SumbleClient(sumble_api_key, sumble_api_base_url) as _client,
        ):
            resolved_companies, unmatched_domains = _client.resolve_companies(
                requested_domains
            )
    except Exception as _exc:
        set_pipeline_status(lambda status: status | {"companies": "Failed"})
        mo.stop(
            True,
            mo.callout(f"Sumble company lookup failed: {_exc}", kind="danger"),
        )

    set_pipeline_status(
        lambda status: status | {"companies": "Complete", "offices": "Ready"}
    )
    return resolved_companies, unmatched_domains


@app.cell
def _(companies_dataframe, mo, resolved_companies, unmatched_domains):
    resolved_companies_df = companies_dataframe(resolved_companies)
    _content = [
        mo.callout(
            f"Resolved {len(resolved_companies):,} companies through Sumble.",
            kind="success",
        ),
        mo.ui.table(resolved_companies_df, page_size=15, selection=None),
    ]
    if unmatched_domains:
        _content.append(
            mo.callout(
                "Unmatched or rejected identity matches: "
                + ", ".join(unmatched_domains),
                kind="warn",
            )
        )
    mo.vstack(_content, gap=1)
    return


@app.cell
def _(mo, resolved_companies):
    _company_count = len(resolved_companies)
    office_form = (
        mo.md(
            f"""
            ## 2. Find and verify offices

            Sumble identified {_company_count:,} companies and supplies a structured headquarters
            address when available. Upload known offices if you have them. Parallel researches
            additional locations or fills gaps. Third-party evidence must name the exact company
            domain. The app discards mailboxes, registered-agent addresses, and unrelated namesakes.

            {{offices_file}}

            {{research_mode}}

            {{office_country}} {{max_offices}}
            """
        )
        .batch(
            offices_file=mo.ui.file(
                filetypes=[".csv"],
                label="Optional offices CSV",
                kind="area",
            ),
            research_mode=mo.ui.radio(
                options={
                    "Research additional offices for every company": "all",
                    "Research only companies without a known office": "missing",
                    "Use only Sumble and the uploaded office CSV": "none",
                },
                value="Research additional offices for every company",
                label="Parallel research",
            ),
            office_country=mo.ui.dropdown(
                options=["US", "CA", "GB", "AU", "DE", "FR", "NL", "SG"],
                value="US",
                label="Office country",
            ),
            max_offices=mo.ui.number(
                start=1,
                stop=25,
                step=1,
                value=10,
                label="Maximum offices per company",
            ),
        )
        .form(submit_button_label="Build office list")
    )
    office_form
    return (office_form,)


@app.cell
def _(
    CachedGeocoder,
    ThreadPoolExecutor,
    as_completed,
    discover_company_offices,
    geocode_cache_path,
    geocode_offices,
    geocoder_user_agent,
    merge_offices,
    mo,
    office_form,
    parallel_api_key,
    parse_offices_csv,
    resolved_companies,
    set_pipeline_status,
    sumble_headquarters_offices,
):
    mo.stop(office_form.value is None)
    _office_files = office_form.value["offices_file"] or []
    _office_contents = _office_files[0].contents if _office_files else None
    try:
        uploaded_offices = parse_offices_csv(_office_contents)
    except Exception as _exc:
        mo.stop(True, mo.callout(f"Office CSV could not be read: {_exc}", kind="danger"))

    _sumble_offices = sumble_headquarters_offices(
        resolved_companies,
        country_code=office_form.value["office_country"],
    )
    _known_offices = [*uploaded_offices, *_sumble_offices]
    _known_domains = {office.company_domain for office in _known_offices}
    _research_mode = office_form.value["research_mode"]
    if _research_mode == "all":
        _research_targets = resolved_companies
    elif _research_mode == "missing":
        _research_targets = [
            company
            for company in resolved_companies
            if company.company_domain not in _known_domains
            and company.input_domain not in _known_domains
        ]
    else:
        _research_targets = []

    mo.stop(
        bool(_research_targets) and not parallel_api_key,
        mo.callout("PARALLEL_API_KEY is missing.", kind="danger"),
    )
    set_pipeline_status(lambda status: status | {"offices": "Running"})
    _researched_offices = []
    office_research_errors = []
    if _research_targets:
        with (
            mo.status.progress_bar(
                total=len(_research_targets),
                title="Searching offices with Parallel",
            ) as _parallel_bar,
            ThreadPoolExecutor(
                max_workers=min(8, len(_research_targets))
            ) as _executor,
        ):
            _futures = {
                _executor.submit(
                    discover_company_offices,
                    _company,
                    parallel_api_key,
                    country_code=office_form.value["office_country"],
                    max_offices=int(office_form.value["max_offices"]),
                ): _company
                for _company in _research_targets
            }
            for _future in as_completed(_futures):
                _company = _futures[_future]
                try:
                    _researched_offices.extend(_future.result())
                except Exception as _exc:
                    office_research_errors.append(
                        f"{_company.company_domain}: {_exc}"
                    )
                _parallel_bar.update()

    _merged_offices = merge_offices(_known_offices, _researched_offices)
    mo.stop(
        not _merged_offices,
        mo.callout(
            "No offices were found. Upload an office CSV or enable Parallel research.",
            kind="warn",
        ),
    )
    _geocoder = CachedGeocoder(
        geocode_cache_path,
        user_agent=geocoder_user_agent,
    )
    with mo.status.progress_bar(
        total=len(_merged_offices),
        title="Geocoding offices",
    ) as _office_geo_bar:
        audience_offices = geocode_offices(
            _merged_offices,
            _geocoder,
            on_item=_office_geo_bar.update,
        )
    set_pipeline_status(
        lambda status: status | {"offices": "Complete", "people": "Ready"}
    )
    return audience_offices, office_research_errors


@app.cell
def _(audience_offices, mo, office_research_errors, offices_dataframe):
    audience_offices_df = offices_dataframe(audience_offices)
    _geocoded_count = int(
        (audience_offices_df["latitude"].notna() & audience_offices_df["longitude"].notna()).sum()
    )
    _verified_count = int(
        (audience_offices_df["validation_status"] == "verified").sum()
    )
    _review_count = int(
        (audience_offices_df["validation_status"] == "review_required").sum()
    )
    _rejected_count = int(
        (audience_offices_df["validation_status"] == "rejected").sum()
    )
    _office_content = [
        mo.callout(
            (
                f"Built {len(audience_offices_df):,} offices. {_verified_count:,} verified, "
                f"{_review_count:,} need review, and {_rejected_count:,} rejected. "
                f"{_geocoded_count:,} have coordinates. Only verified offices feed the audience."
            ),
            kind="success" if _verified_count else "warn",
        ),
        mo.ui.table(audience_offices_df, page_size=20, selection=None),
    ]
    if office_research_errors:
        _office_content.append(
            mo.accordion(
                {
                    f"Parallel errors ({len(office_research_errors)})": mo.md(
                        "\n".join(f"- {error}" for error in office_research_errors)
                    )
                }
            )
        )
    mo.vstack(_office_content, gap=1)
    return (audience_offices_df,)


@app.cell
def _(
    DEFAULT_JOB_FUNCTIONS,
    DEFAULT_JOB_LEVELS,
    JOB_FUNCTION_OPTIONS,
    JOB_LEVEL_OPTIONS,
    audience_offices,
    mo,
):
    mo.stop(not audience_offices)
    _default_function_labels = [
        label
        for label, value in JOB_FUNCTION_OPTIONS.items()
        if value in DEFAULT_JOB_FUNCTIONS
    ]
    people_filter_form = (
        mo.md(
            """
            ## 3. Choose the audience

            Select normalized Sumble job functions and every seniority level you want included.
            The app will show the exact public API query before it runs.

            {job_functions}

            {job_levels}

            {country_code} {maximum_people}

            {radius_miles} {max_people_per_company}

            Optional local title filters are applied after Sumble returns candidates.

            {include_titles}

            {exclude_titles}
            """
        )
        .batch(
            job_functions=mo.ui.multiselect(
                options=JOB_FUNCTION_OPTIONS,
                value=_default_function_labels,
                label="Job functions",
            ),
            job_levels=mo.ui.multiselect(
                options=JOB_LEVEL_OPTIONS,
                value=DEFAULT_JOB_LEVELS,
                label="Job levels",
            ),
            country_code=mo.ui.dropdown(
                options=["US", "CA", "GB", "AU", "DE", "FR", "NL", "SG"],
                value="US",
                label="People country",
            ),
            maximum_people=mo.ui.number(
                start=100,
                stop=10_000,
                step=100,
                value=2_000,
                label="Maximum Sumble candidates",
            ),
            radius_miles=mo.ui.slider(
                start=5,
                stop=200,
                step=5,
                value=50,
                label="Office radius in miles",
                show_value=True,
            ),
            max_people_per_company=mo.ui.number(
                start=1,
                stop=100,
                step=1,
                value=25,
                label="Final people per company",
            ),
            include_titles=mo.ui.text_area(
                label="Title must contain one of these phrases",
                placeholder="Optional, one phrase per line",
                rows=3,
                full_width=True,
            ),
            exclude_titles=mo.ui.text_area(
                label="Exclude titles containing these phrases",
                placeholder="assistant\nchief of staff",
                rows=3,
                full_width=True,
            ),
        )
        .form(submit_button_label="Review Sumble query")
    )
    people_filter_form
    return (people_filter_form,)


@app.cell
def _(build_people_query, mo, people_filter_form):
    mo.stop(people_filter_form.value is None)
    try:
        sumble_people_query = build_people_query(
            people_filter_form.value["job_functions"],
            people_filter_form.value["job_levels"],
            people_filter_form.value["country_code"],
        )
    except ValueError as _exc:
        mo.stop(True, mo.callout(str(_exc), kind="warn"))

    selected_radius_miles = float(people_filter_form.value["radius_miles"])
    selected_max_people_per_company = int(
        people_filter_form.value["max_people_per_company"]
    )
    selected_maximum_people = int(people_filter_form.value["maximum_people"])
    selected_include_title_terms = [
        line.strip()
        for line in people_filter_form.value["include_titles"].splitlines()
        if line.strip()
    ]
    selected_exclude_title_terms = [
        line.strip()
        for line in people_filter_form.value["exclude_titles"].splitlines()
        if line.strip()
    ]
    mo.callout(
        mo.md(f"""Public Sumble people query

    ```text
    {sumble_people_query}
    ```
    """),
        kind="info",
    )
    return (
        selected_exclude_title_terms,
        selected_include_title_terms,
        selected_max_people_per_company,
        selected_maximum_people,
        selected_radius_miles,
        sumble_people_query,
    )


@app.cell
def _(mo, people_filter_form, sumble_people_query):
    mo.stop(people_filter_form.value is None or not sumble_people_query)
    find_people_button = mo.ui.run_button(label="Run Sumble people search")
    mo.hstack(
        [
            find_people_button,
            mo.md("This uses Sumble credits. The app does not request email or phone data."),
        ],
        justify="start",
        gap=1,
    )
    return (find_people_button,)


@app.cell
def _(
    SumbleClient,
    find_people_button,
    mo,
    resolved_companies,
    selected_maximum_people,
    set_pipeline_status,
    sumble_api_base_url,
    sumble_api_key,
    sumble_people_query,
):
    mo.stop(not find_people_button.value)
    set_pipeline_status(lambda status: status | {"people": "Running"})
    try:
        with (
            mo.status.spinner(
                title="Sumble is finding people and preparing the result"
            ),
            SumbleClient(sumble_api_key, sumble_api_base_url) as _client,
        ):
            people_candidates = _client.find_people(
                resolved_companies,
                sumble_people_query,
                max_people=selected_maximum_people,
            )
    except Exception as _exc:
        set_pipeline_status(lambda status: status | {"people": "Failed"})
        mo.stop(True, mo.callout(f"Sumble people search failed: {_exc}", kind="danger"))
    set_pipeline_status(
        lambda status: status | {"people": "Complete", "matching": "Ready"}
    )
    return (people_candidates,)


@app.cell
def _(mo, people_candidates, people_dataframe):
    people_candidates_df = people_dataframe(people_candidates)
    mo.vstack(
        [
            mo.callout(
                f"Sumble returned {len(people_candidates_df):,} candidate people.",
                kind="success" if len(people_candidates_df) else "warn",
            ),
            mo.ui.table(people_candidates_df, page_size=25, selection=None),
        ],
        gap=1,
    )
    return


@app.cell
def _(mo, people_candidates):
    match_people_button = mo.ui.run_button(label="Geocode people and calculate distance")
    mo.vstack(
        [
            mo.md(
                f"""
                ## 4. Calculate the final audience

                This stage geocodes the unique locations among {len(people_candidates):,} people,
                finds the nearest office, applies the radius, and ranks the results.
                """
            ),
            match_people_button,
        ],
        gap=1,
    )
    return (match_people_button,)


@app.cell
def _(
    CachedGeocoder,
    audience_offices,
    build_audience,
    geocode_cache_path,
    geocode_people,
    geocoder_user_agent,
    match_people_button,
    mo,
    people_candidates,
    selected_exclude_title_terms,
    selected_include_title_terms,
    selected_max_people_per_company,
    selected_radius_miles,
    set_pipeline_status,
):
    mo.stop(not match_people_button.value)
    set_pipeline_status(lambda status: status | {"matching": "Running"})
    _geocoder = CachedGeocoder(
        geocode_cache_path,
        user_agent=geocoder_user_agent,
    )
    with mo.status.progress_bar(
        total=len(people_candidates),
        title="Geocoding people locations",
    ) as _people_geo_bar:
        geocoded_people = geocode_people(
            people_candidates,
            _geocoder,
            on_item=_people_geo_bar.update,
        )
    audience_results_df = build_audience(
        geocoded_people,
        audience_offices,
        radius_miles=selected_radius_miles,
        max_people_per_company=selected_max_people_per_company,
        include_title_terms=selected_include_title_terms,
        exclude_title_terms=selected_exclude_title_terms,
    )
    set_pipeline_status(lambda status: status | {"matching": "Complete"})
    return (audience_results_df,)


@app.cell
def _(audience_offices_df, audience_results_df, mo):
    _audience_download = mo.download(
        data=audience_results_df.to_csv(index=False).encode("utf-8"),
        filename="audience_results.csv",
        mimetype="text/csv",
        label="Download audience results",
    )
    _offices_download = mo.download(
        data=audience_offices_df.to_csv(index=False).encode("utf-8"),
        filename="offices.csv",
        mimetype="text/csv",
        label="Download offices",
    )
    _results_kind = "success" if len(audience_results_df) else "warn"
    mo.vstack(
        [
            mo.callout(
                f"Final audience: {len(audience_results_df):,} people.",
                kind=_results_kind,
            ),
            mo.ui.tabs(
                {
                    "Audience results": mo.ui.table(
                        audience_results_df,
                        page_size=30,
                        selection=None,
                    ),
                    "Offices": mo.ui.table(
                        audience_offices_df,
                        page_size=30,
                        selection=None,
                    ),
                }
            ),
            mo.hstack([_audience_download, _offices_download], justify="start", gap=1),
        ],
        gap=1,
    )
    return


if __name__ == "__main__":
    app.run()
