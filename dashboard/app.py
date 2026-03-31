"""
VR-OPS Combined Dashboard — Performance tracking + SOP document manager.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import requests
import streamlit as st

# ── Page config (must be first Streamlit call) ───────────────────────────────

st.set_page_config(
    page_title="VR-OPS Dashboard",
    page_icon=":bar_chart:",
    layout="wide",
)

st.markdown(
    """
    <style>
    div[data-testid="metric-container"] span[data-testid="stMetricValue"] {
        white-space: normal;
        word-break: break-word;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Shared constants ─────────────────────────────────────────────────────────

API_BASE = "http://localhost:8000"
POSTGREST_URL = os.environ.get("POSTGREST_URL", "http://localhost:3000")
DEFAULT_DATA_PATH = Path(__file__).parent / "trainee_performance_sample.xlsx"

STEP_NUMBERS = list(range(1, 13))
STEP_APPRAISAL_COLUMNS = [f"Step {step} Appraisal" for step in STEP_NUMBERS]
STEP_TIME_COLUMNS = [f"Step {step} Time" for step in STEP_NUMBERS]
REQUIRED_COLUMNS = [
    "Name",
    "Number of errors",
    "Completion Time (mins)",
    "Date",
    *STEP_APPRAISAL_COLUMNS,
    *STEP_TIME_COLUMNS,
]
HORIZON_OPTIONS = {
    "1 Day": timedelta(days=1),
    "1 Week": timedelta(weeks=1),
    "1 Month": timedelta(days=30),
    "3 Months": timedelta(days=90),
    "6 Months": timedelta(days=180),
    "1 Year": timedelta(days=365),
    "2 Years": timedelta(days=730),
    "3 Years": timedelta(days=1095),
}
DEFAULT_STEP_TRAINEE = "Aisha Khan"
DEFAULT_STEP_START_DATE = date(2023, 3, 14)
DEFAULT_STEP_END_DATE = date(2023, 3, 30)


# ── Performance dashboard helpers ────────────────────────────────────────────

def first_name(full_name: str) -> str:
    value = str(full_name).strip() if full_name else ""
    return value.split(" ", 1)[0] if value else ""


def _prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {', '.join(missing)}")

    cleaned = df.loc[:, REQUIRED_COLUMNS].copy()
    completion_dates = pd.to_datetime(cleaned["Date"], errors="coerce", utc=True).dt.tz_convert(None)
    errors = pd.to_numeric(cleaned["Number of errors"], errors="coerce")
    completion_minutes = pd.to_numeric(cleaned["Completion Time (mins)"], errors="coerce")

    mask = completion_dates.notna() & completion_minutes.notna()
    cleaned = cleaned.loc[mask].copy()
    cleaned["Date"] = completion_dates.loc[mask]
    cleaned["Number of errors"] = errors.loc[mask].fillna(0).round().astype(int)
    cleaned["Completion Time (mins)"] = completion_minutes.loc[mask].fillna(0).clip(lower=0)
    cleaned["Name"] = cleaned["Name"].astype(str).str.strip()

    for step in STEP_NUMBERS:
        appraisal_col = f"Step {step} Appraisal"
        time_col = f"Step {step} Time"
        cleaned[appraisal_col] = cleaned[appraisal_col].astype(str).str.strip().str.title()
        cleaned.loc[~cleaned[appraisal_col].isin(["Right", "Wrong"]), appraisal_col] = pd.NA
        cleaned[time_col] = pd.to_numeric(cleaned[time_col], errors="coerce")

    cleaned = cleaned[cleaned["Name"] != ""]
    return cleaned.sort_values("Date").reset_index(drop=True)


@st.cache_data(ttl="1h", show_spinner=False)
def load_performance_data() -> tuple[pd.DataFrame, str]:
    """Load from PostgREST; fall back to the sample xlsx if unavailable."""
    try:
        resp = requests.get(f"{POSTGREST_URL}/performance_wide", timeout=10)
        resp.raise_for_status()
        df = pd.DataFrame(resp.json())
        return _prepare_dataframe(df), "PostgreSQL database"
    except Exception:
        df = pd.read_excel(DEFAULT_DATA_PATH)
        return _prepare_dataframe(df), f"Sample data · {DEFAULT_DATA_PATH.name}"


def filter_by_horizon(df: pd.DataFrame, horizon_label: str) -> pd.DataFrame:
    if df.empty:
        return df
    latest = df["Date"].max()
    return df[df["Date"].between(latest - HORIZON_OPTIONS[horizon_label], latest)]


def most_wrong_step(df: pd.DataFrame) -> tuple[str, int]:
    """Return the step with the highest Wrong count and that count."""
    if df.empty:
        return "N/A", 0

    wrong_counts: dict[int, int] = {}
    for step in STEP_NUMBERS:
        appraisal_col = f"Step {step} Appraisal"
        wrong_counts[step] = int((df[appraisal_col] == "Wrong").sum())

    max_wrong = max(wrong_counts.values()) if wrong_counts else 0
    if max_wrong == 0:
        return "No wrong steps", 0

    top_step = min(step for step, count in wrong_counts.items() if count == max_wrong)
    return f"Step {top_step}", max_wrong


def render_error_step_card(container, title: str, step_label: str, error_count: int) -> None:
    """Render a styled card so the most-error step stands out clearly."""
    safe_step = step_label if step_label else "N/A"
    count_color = "#ef4444" if error_count > 0 else "#94a3b8"
    container.markdown(
        f"""
        <div style="
            border: 1px solid #314158;
            border-radius: 12px;
            background: linear-gradient(180deg, rgba(15,23,43,0.95), rgba(15,23,43,0.75));
            padding: 12px 14px;
            margin: 8px 0;
        ">
            <div style="font-size:0.82rem; color:#9fb0c8; margin-bottom:4px;">{title}</div>
            <div style="font-size:1.75rem; font-weight:700; color:#f8fafc; line-height:1.15;">{safe_step}</div>
            <div style="font-size:0.9rem; color:{count_color}; margin-top:6px; font-weight:600;">
                {error_count} errors
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def session_sort_key(session_label: str) -> int:
    """Sort labels like 'Session 1', 'Session 2', ... numerically."""
    value = str(session_label).strip()
    if value.startswith("Session "):
        number_text = value.replace("Session ", "", 1)
        if number_text.isdigit():
            return int(number_text)
    return 10**9


def session_focus_control(container, session_labels: list[str], key: str) -> str | None:
    """Let users click a session number to emphasize that session on the chart."""
    if len(session_labels) <= 1:
        return None
    with container:
        selected = st.pills(
            "Highlight session",
            options=["All sessions", *session_labels],
            selection_mode="single",
            default="All sessions",
            key=key,
            help="Select a session number to highlight its curve.",
            width="stretch",
        )
    return None if selected in (None, "All sessions") else selected


def step_chart_records(df: pd.DataFrame) -> pd.DataFrame:
    records = []
    for step in STEP_NUMBERS:
        appraisal_col = f"Step {step} Appraisal"
        time_col = f"Step {step} Time"
        step_slice = df[["Name", "Session", "Date", appraisal_col, time_col]].rename(
            columns={appraisal_col: "Appraisal", time_col: "Step Time (mins)"}
        )
        step_slice["Step"] = step
        records.append(step_slice)

    combined = pd.concat(records, ignore_index=True)
    combined["Step Time (mins)"] = pd.to_numeric(combined["Step Time (mins)"], errors="coerce")
    combined = combined.dropna(subset=["Step Time (mins)"])
    combined.loc[~combined["Appraisal"].isin(["Right", "Wrong"]), "Appraisal"] = pd.NA

    anchors = df[["Name", "Session", "Date"]].drop_duplicates().copy()
    anchors["Appraisal"] = pd.NA
    anchors["Step Time (mins)"] = 0.0
    anchors["Step"] = 0

    combined = pd.concat([anchors, combined], ignore_index=True)
    return combined.sort_values(["Session", "Step"]).reset_index(drop=True)


def step_segment_records(step_points: pd.DataFrame) -> pd.DataFrame:
    segments = []
    for session, session_rows in step_points.groupby("Session"):
        by_step = session_rows.sort_values("Step").set_index("Step")
        for step in STEP_NUMBERS:
            if step not in by_step.index or (step - 1) not in by_step.index:
                continue
            appraisal = by_step.loc[step, "Appraisal"]
            if pd.isna(appraisal) or appraisal not in {"Right", "Wrong"}:
                continue
            start_time = float(by_step.loc[step - 1, "Step Time (mins)"])
            end_time = float(by_step.loc[step, "Step Time (mins)"])
            session_date = by_step.loc[step, "Date"]
            segment_id = f"{session}|step-{step}"
            for s, t in [(step - 1, start_time), (step, end_time)]:
                segments.append({
                    "Session": session, "Date": session_date, "Segment": segment_id,
                    "Step": s, "Step Time (mins)": t, "Appraisal": appraisal,
                })

    if not segments:
        return pd.DataFrame()
    return pd.DataFrame(segments).sort_values(["Session", "Segment", "Step"])


def render_step_chart(
    step_records: pd.DataFrame,
    step_segments: pd.DataFrame,
    container,
    highlight_session: str | None = None,
) -> None:
    session_count = step_records["Session"].nunique()
    fill_palette = ["#86efac", "#fca5a5"]
    session_order = sorted(step_records["Session"].dropna().unique(), key=session_sort_key)
    has_session_focus = (
        session_count > 1
        and bool(highlight_session)
        and highlight_session in set(step_records["Session"].dropna().tolist())
    )
    if has_session_focus:
        step_records = step_records.assign(IsFocus=step_records["Session"] == highlight_session)
        step_segments = step_segments.assign(IsFocus=step_segments["Session"] == highlight_session)
    session_legend = alt.Legend(
        title="Session",
        orient="bottom",
        direction="horizontal",
        columns=max(1, min(12, len(session_order))),
        labelLimit=120,
    )

    x_axis = alt.X(
        "Step:Q", title="Step",
        scale=alt.Scale(domain=[0, 12], nice=False),
        axis=alt.Axis(values=list(range(0, 13))),
    )
    y_axis = alt.Y("Step Time (mins):Q", title="Time (mins)", scale=alt.Scale(domainMin=0), stack=None)

    if session_count <= 1:
        fill_opacity = alt.value(0.24)
    elif has_session_focus:
        fill_opacity = alt.condition("datum.IsFocus", alt.value(0.42), alt.value(0.03))
    else:
        fill_opacity = alt.value(0.24)
    fill_chart = alt.Chart(step_segments).mark_area(interpolate="linear").encode(
        x_axis, y_axis,
        detail="Segment:N",
        color=alt.Color(
            "Appraisal:N",
            scale=alt.Scale(domain=["Right", "Wrong"], range=fill_palette),
            legend=alt.Legend(title="Segment fill"),
        ),
        opacity=fill_opacity,
        tooltip=[
            alt.Tooltip("Session:N"), alt.Tooltip("Date:T"),
            alt.Tooltip("Step:Q"), alt.Tooltip("Appraisal:N"),
            alt.Tooltip("Step Time (mins):Q", format=".2f"),
        ],
    )

    line_kwargs = dict(color="#cbd5e1", strokeWidth=2.1, interpolate="linear")
    common_tooltip = [
        alt.Tooltip("Session:N"), alt.Tooltip("Date:T"),
        alt.Tooltip("Step:Q"), alt.Tooltip("Appraisal:N"),
        alt.Tooltip("Step Time (mins):Q", format=".2f"),
    ]

    if session_count == 1:
        line_chart = alt.Chart(step_records).mark_line(**line_kwargs).encode(
            x_axis, y_axis, detail="Session:N", tooltip=common_tooltip, opacity=alt.value(1.0),
        )
    else:
        line_opacity = (
            alt.condition("datum.IsFocus", alt.value(1.0), alt.value(0.08))
            if has_session_focus
            else alt.value(1.0)
        )
        line_width = (
            alt.condition("datum.IsFocus", alt.value(3.4), alt.value(0.9))
            if has_session_focus
            else alt.value(2.1)
        )
        line_chart = alt.Chart(step_records).mark_line(**line_kwargs).encode(
            x_axis, y_axis, detail="Session:N",
            strokeDash=alt.StrokeDash("Session:N", sort=session_order, legend=session_legend),
            opacity=line_opacity,
            strokeWidth=line_width,
            tooltip=common_tooltip,
        )

    with container:
        st.subheader("Individual Performance Review")
        st.altair_chart((fill_chart + line_chart).properties(height=350), use_container_width=True)


# ── SOP manager helpers ──────────────────────────────────────────────────────

def fetch_documents() -> list[dict]:
    try:
        resp = requests.get(f"{API_BASE}/documents", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot reach API at " + API_BASE + ". Is it running?")
        return []
    except Exception as e:
        st.error(f"Error fetching documents: {e}")
        return []


def ingest_file(file) -> tuple[bool, str]:
    try:
        resp = requests.post(
            f"{API_BASE}/documents/ingest",
            files={"file": (file.name, file.getvalue(), file.type)},
            timeout=120,
        )
        if resp.ok:
            return True, resp.json().get("message", "Ingested successfully.")
        return False, resp.json().get("detail", "Unknown error.")
    except requests.exceptions.ConnectionError:
        return False, "Cannot reach API."
    except Exception as e:
        return False, str(e)


def delete_document(doc_id: str, filename: str) -> tuple[bool, str]:
    try:
        resp = requests.delete(f"{API_BASE}/documents/{doc_id}", timeout=10)
        if resp.ok:
            return True, f"'{filename}' removed."
        return False, resp.json().get("detail", "Unknown error.")
    except requests.exceptions.ConnectionError:
        return False, "Cannot reach API."
    except Exception as e:
        return False, str(e)


def fetch_document_file(doc_id: str) -> bytes | None:
    try:
        resp = requests.get(f"{API_BASE}/documents/{doc_id}/download", timeout=30)
        return resp.content if resp.ok else None
    except Exception:
        return None


# ── Tabs ─────────────────────────────────────────────────────────────────────

st.title(":material/query_stats: VR OPS Dashboard")

tab_perf, tab_sop = st.tabs(["📊 Performance", "📋 SOP Manager"])


# ── Tab 1: Performance Dashboard ─────────────────────────────────────────────

with tab_perf:
    st.write("Monitor trainee accuracy trends and flip between mistakes and completion time views.")

    cols = st.columns([1, 3])
    top_left_cell = cols[0].container(border=True, height="stretch", vertical_alignment="center")
    right_cell = cols[1].container(border=True, height="stretch", vertical_alignment="center")
    bottom_left_cell = cols[0].container(border=True, height="stretch", vertical_alignment="center")

    try:
        data, data_source_label = load_performance_data()
        load_ok = True
    except Exception as exc:
        top_left_cell.error(f"Unable to load performance data: {exc}")
        load_ok = False

    if load_ok:
        trainees = sorted(data["Name"].unique())

        if not trainees:
            top_left_cell.warning("No trainee names were found in the dataset.")
        else:
            with top_left_cell:
                st.caption(f"Data source: {data_source_label}")
                selected_trainees = st.multiselect(
                    "Trainees", options=trainees, default=trainees,
                    placeholder="Choose trainees to compare.",
                )
                horizon = st.pills(
                    "Time horizon", options=list(HORIZON_OPTIONS.keys()), default="3 Years",
                )

            if not selected_trainees:
                top_left_cell.info("Pick at least one trainee to populate the dashboard.")
            else:
                main_filtered = data[data["Name"].isin(selected_trainees)].copy()
                filtered = filter_by_horizon(main_filtered, horizon)

                if filtered.empty:
                    top_left_cell.warning("No records match that trainee list and time horizon. Try widening the range.")
                else:
                    error_totals = filtered.groupby("Name")["Number of errors"].sum()
                    best_name = error_totals.idxmin()
                    worst_name = error_totals.idxmax()

                    with bottom_left_cell:
                        metric_cols = st.columns(2)
                        metric_cols[0].metric(
                            "Best employee", first_name(best_name),
                            delta=f"{error_totals[best_name]} errors", delta_color="normal", width="content",
                        )
                        metric_cols[1].metric(
                            "Needs attention", first_name(worst_name),
                            delta=f"{error_totals[worst_name]} errors", delta_color="inverse", width="content",
                        )

                    with right_cell:
                        show_completion = st.toggle(
                            "Trainee Error and Completion Trends", value=True,
                            help="Switch between mistakes and completion time.",
                        )
                        y_field = "Completion Time (mins)" if show_completion else "Number of errors"
                        y_title = "Completion time (mins)" if show_completion else "Number of mistakes"

                        st.altair_chart(
                            alt.Chart(filtered.sort_values("Date"))
                            .mark_line(point=True)
                            .encode(
                                alt.X("Date:T", title="Date"),
                                alt.Y(f"{y_field}:Q", title=y_title, scale=alt.Scale(zero=False)),
                                alt.Color("Name:N", title="Trainee"),
                                tooltip=["Name", "Date", "Number of errors", "Completion Time (mins)"],
                            )
                            .properties(height=420),
                            use_container_width=True,
                        )

                step_cols = st.columns([1, 3])
                step_filter_cell = step_cols[0].container(border=True, height="stretch", vertical_alignment="top")
                step_chart_cell = step_cols[1].container(border=True, height="stretch", vertical_alignment="center")

                step_source = main_filtered.sort_values("Date")
                step_trainees = sorted(step_source["Name"].unique())
                default_step_trainee_index = (
                    step_trainees.index(DEFAULT_STEP_TRAINEE)
                    if DEFAULT_STEP_TRAINEE in step_trainees
                    else 0
                )

                with step_filter_cell:
                    st.subheader("Step chart filters")
                    selected_step_trainee = st.selectbox(
                        "Trainee",
                        options=step_trainees,
                        index=default_step_trainee_index,
                    )
                step_prev_trainee_key = "step_prev_trainee"
                highlight_session_all_key = "highlight_session_all"
                highlight_session_range_key = "highlight_session_range"
                if st.session_state.get(step_prev_trainee_key) != selected_step_trainee:
                    st.session_state[highlight_session_all_key] = "All sessions"
                    st.session_state[highlight_session_range_key] = "All sessions"
                    st.session_state[step_prev_trainee_key] = selected_step_trainee

                selected_step_rows = (
                    step_source[step_source["Name"] == selected_step_trainee]
                    .sort_values("Date")
                    .reset_index(drop=True)
                )
                selected_step_rows["Session"] = (
                    "Session "
                    + (selected_step_rows.index + 1).astype(str)
                )
                date_min = selected_step_rows["Date"].min().date()
                date_max = selected_step_rows["Date"].max().date()
                default_start = max(date_min, min(DEFAULT_STEP_START_DATE, date_max))
                default_end = max(date_min, min(DEFAULT_STEP_END_DATE, date_max))
                if default_end < default_start:
                    default_end = default_start

                step_view_mode_key = "step_view_mode"
                step_prev_range_key = "step_prev_date_range"
                if step_view_mode_key not in st.session_state:
                    st.session_state[step_view_mode_key] = "range"

                with step_filter_cell:
                    selected_date_range = st.date_input(
                        "Date range", value=(default_start, default_end),
                        min_value=date_min, max_value=date_max,
                    )
                    normalized_date_range = (
                        tuple(selected_date_range)
                        if isinstance(selected_date_range, (tuple, list))
                        else selected_date_range
                    )
                    if st.session_state.get(step_prev_range_key) != normalized_date_range:
                        st.session_state[step_view_mode_key] = "range"
                        st.session_state[step_prev_range_key] = normalized_date_range

                    mode_cols = st.columns(2)
                    if mode_cols[0].button(
                        "All Sessions",
                        key="all_sessions_btn",
                        use_container_width=True,
                        help="Show all sessions across the full available date range for the selected trainee.",
                    ):
                        st.session_state[step_view_mode_key] = "all"
                    if mode_cols[1].button(
                        "Last Session",
                        key="last_session_btn",
                        use_container_width=True,
                        help="Show only the most recent session.",
                    ):
                        st.session_state[step_view_mode_key] = "last"

                step_view_mode = st.session_state[step_view_mode_key]

                single_date_selected = not (
                    isinstance(selected_date_range, (tuple, list)) and len(selected_date_range) == 2
                )
                trainee_wrong_step, trainee_wrong_count = "N/A", 0
                all_wrong_step, all_wrong_count = "N/A", 0
                trainee_range_rows = pd.DataFrame()
                all_range_rows = pd.DataFrame()

                if step_view_mode == "all":
                    trainee_range_rows = selected_step_rows
                    all_range_rows = step_source
                elif not single_date_selected:
                    step_start_date, step_end_date = selected_date_range
                    range_start_ts = pd.Timestamp(step_start_date)
                    range_end_ts = (
                        pd.Timestamp(step_end_date)
                        + pd.Timedelta(days=1)
                        - pd.Timedelta(seconds=1)
                    )
                    trainee_range_rows = selected_step_rows[
                        selected_step_rows["Date"].between(range_start_ts, range_end_ts)
                    ]
                    all_range_rows = step_source[
                        step_source["Date"].between(range_start_ts, range_end_ts)
                    ]

                if step_view_mode == "all" or not single_date_selected:
                    trainee_wrong_step, trainee_wrong_count = most_wrong_step(trainee_range_rows)
                    all_wrong_step, all_wrong_count = most_wrong_step(all_range_rows)

                with step_filter_cell:
                    render_error_step_card(
                        step_filter_cell,
                        "Step with Highest Error Count (Selected Trainee)",
                        trainee_wrong_step,
                        trainee_wrong_count,
                    )
                    render_error_step_card(
                        step_filter_cell,
                        "Step with Highest Error Count (All Trainees)",
                        all_wrong_step,
                        all_wrong_count,
                    )

                if step_view_mode == "all":
                    step_filtered = selected_step_rows
                    step_records = step_chart_records(step_filtered)
                    step_segments = step_segment_records(step_records)
                    if step_records.empty or step_segments.empty:
                        step_chart_cell.info("No step records found for the selected trainee.")
                    else:
                        highlight_session = session_focus_control(
                            step_filter_cell,
                            sorted(step_records["Session"].dropna().unique().tolist(), key=session_sort_key),
                            key=highlight_session_all_key,
                        )
                        with step_chart_cell:
                            st.caption(
                                f"Showing all sessions from {date_min:%Y-%m-%d} to {date_max:%Y-%m-%d}"
                            )
                        render_step_chart(
                            step_records,
                            step_segments,
                            step_chart_cell,
                            highlight_session=highlight_session,
                        )
                elif step_view_mode == "last":
                    step_filtered = selected_step_rows.tail(1)
                    step_records = step_chart_records(step_filtered)
                    step_segments = step_segment_records(step_records)
                    if step_records.empty or step_segments.empty:
                        step_chart_cell.info("No step records found for the last session.")
                    else:
                        last_session_date = step_filtered["Date"].iloc[-1]
                        with step_chart_cell:
                            st.caption(
                                f"Showing last session from {last_session_date:%Y-%m-%d %H:%M}"
                            )
                        render_step_chart(step_records, step_segments, step_chart_cell)
                elif single_date_selected:
                    step_chart_cell.caption("Please select both a start date and an end date.")
                else:
                    step_filtered = trainee_range_rows
                    step_records = step_chart_records(step_filtered)
                    step_segments = step_segment_records(step_records)
                    if step_records.empty or step_segments.empty:
                        step_chart_cell.info("No step records match the selected trainee and date range.")
                    else:
                        highlight_session = session_focus_control(
                            step_filter_cell,
                            sorted(step_records["Session"].dropna().unique().tolist(), key=session_sort_key),
                            key=highlight_session_range_key,
                        )
                        render_step_chart(
                            step_records,
                            step_segments,
                            step_chart_cell,
                            highlight_session=highlight_session,
                        )


# ── Tab 2: SOP Manager ───────────────────────────────────────────────────────

with tab_sop:
    st.subheader("SOP Document Manager")
    st.caption("Add or remove Standard Operating Procedure documents from the RAG system.")

    st.divider()

    st.subheader("Add SOP")
    uploaded = st.file_uploader(
        "Upload a .docx or .pdf file",
        type=["docx", "pdf"],
        accept_multiple_files=False,
    )

    if uploaded:
        st.write(f"**File:** `{uploaded.name}` ({uploaded.size:,} bytes)")
        if st.button("Ingest into RAG", type="primary"):
            with st.spinner(f"Ingesting `{uploaded.name}`… this may take a moment."):
                ok, msg = ingest_file(uploaded)
            if ok:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)

    st.divider()

    st.subheader("Ingested SOPs")
    docs = fetch_documents()

    if not docs:
        st.info("No documents ingested yet. Upload one above.")
    else:
        for doc in docs:
            col_name, col_chunks, col_date, col_dl, col_del = st.columns([3, 1, 2, 1, 1])
            col_name.write(f"**{doc['filename']}**")
            col_chunks.write(f"{doc['chunk_count']} chunks")
            col_date.write(doc.get("ingested_at", "")[:10])

            dl_key = f"dl_data_{doc['doc_id']}"
            if dl_key not in st.session_state:
                if col_dl.button("Download", key=f"dl_btn_{doc['doc_id']}", type="secondary"):
                    with st.spinner(f"Fetching `{doc['filename']}`…"):
                        file_bytes = fetch_document_file(doc["doc_id"])
                    if file_bytes:
                        st.session_state[dl_key] = file_bytes
                        st.rerun()
                    else:
                        col_dl.error("Not available.")
            else:
                col_dl.download_button(
                    "Save",
                    data=st.session_state[dl_key],
                    file_name=doc["filename"],
                    key=f"dl_save_{doc['doc_id']}",
                    type="primary",
                )

            if col_del.button("Delete", key=doc["doc_id"], type="secondary"):
                with st.spinner(f"Removing `{doc['filename']}`…"):
                    ok, msg = delete_document(doc["doc_id"], doc["filename"])
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
