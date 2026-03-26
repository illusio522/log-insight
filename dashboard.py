import os

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, date
import requests

# Configuration
API_URL = os.getenv("API_URL", "http://localhost:8000")
PAGE_SIZE = 20

st.set_page_config(
    page_title="Log Insight Dashboard",
    page_icon="📊",
    layout="wide",
)

st.title("Log Insight Dashboard")


# ---------------------------------------------------------------------------
# Cached fetch functions
# ---------------------------------------------------------------------------


@st.cache_data(ttl=60)
def fetch_stats():
    """Fetch statistics from API."""
    try:
        response = requests.get(f"{API_URL}/stats", timeout=5)
        return response.json()
    except Exception as e:
        st.error(f"Failed to fetch stats: {e}")
        return None


@st.cache_data(ttl=60)
def fetch_errors(limit=100, offset=0, **filters):
    """Fetch errors from API."""
    try:
        params = {"limit": limit, "offset": offset, **{k: v for k, v in filters.items() if v}}
        response = requests.get(f"{API_URL}/errors", params=params, timeout=5)
        data = response.json()
        return data.get("errors", []), data.get("total", 0)
    except Exception as e:
        st.error(f"Failed to fetch errors: {e}")
        return [], 0


@st.cache_data(ttl=60)
def fetch_patterns():
    """Fetch error patterns from API."""
    try:
        response = requests.get(f"{API_URL}/patterns", timeout=5)
        return response.json().get("patterns", [])
    except Exception as e:
        st.error(f"Failed to fetch patterns: {e}")
        return []


@st.cache_data(ttl=60)
def fetch_errors_by_app():
    """Fetch errors grouped by application."""
    try:
        response = requests.get(f"{API_URL}/errors/by-application", timeout=5)
        return response.json().get("data", [])
    except Exception as e:
        st.error(f"Failed to fetch data: {e}")
        return []


@st.cache_data(ttl=60)
def fetch_errors_by_time(interval="hour"):
    """Fetch errors over time."""
    try:
        response = requests.get(
            f"{API_URL}/errors/by-time", params={"interval": interval}, timeout=5
        )
        return response.json().get("data", [])
    except Exception as e:
        st.error(f"Failed to fetch data: {e}")
        return []


# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

st.sidebar.header("Filters")
application_filter = st.sidebar.text_input("Application")
domain_filter = st.sidebar.text_input("Domain")
api_filter = st.sidebar.text_input("API Path", placeholder="*/domain1/*")
exception_filter = st.sidebar.text_input("Exception Class")
time_interval = st.sidebar.selectbox("Time Interval", ["hour", "day", "minute"])

st.sidebar.divider()
st.sidebar.subheader("Sort")
sort_by = st.sidebar.selectbox("Sort By", ["timestamp", "application", "exception_class"])
sort_order = st.sidebar.selectbox("Order", ["desc", "asc"], format_func=lambda x: "Newest First" if x == "desc" else "Oldest First")

st.sidebar.divider()
st.sidebar.subheader("Date Range")
today = date.today()
start_date = st.sidebar.date_input("Start Date", value=today - timedelta(days=7))
end_date = st.sidebar.date_input("End Date", value=today + timedelta(days=1))

# Convert dates to datetime strings for API
start_time_str = datetime.combine(start_date, datetime.min.time()).isoformat() if start_date else None
end_time_str = datetime.combine(end_date, datetime.max.time()).isoformat() if end_date else None

st.sidebar.divider()
auto_refresh = st.sidebar.toggle("Auto Refresh (60s)", value=False)

if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()
    st.rerun()

# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

stats = fetch_stats()

if stats:
    # Metrics row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Logs", stats.get("total_logs", 0))
    with col2:
        st.metric("Total Errors", stats.get("total_errors", 0))
    with col3:
        st.metric("Unique Patterns", stats.get("unique_patterns", 0))
    with col4:
        error_rate = (
            (stats.get("total_errors", 0) / stats.get("total_logs", 1) * 100)
            if stats.get("total_logs", 0) > 0
            else 0
        )
        st.metric("Error Rate", f"{error_rate:.1f}%")

    st.divider()

    # Charts row
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Top Exceptions")
        top_exceptions = stats.get("top_exceptions", [])
        if top_exceptions:
            df = pd.DataFrame(top_exceptions)
            fig = px.bar(
                df,
                x="count",
                y="exception",
                orientation="h",
                color="count",
                color_continuous_scale="Reds",
            )
            fig.update_layout(
                yaxis={"categoryorder": "total ascending"},
                showlegend=False,
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No exceptions found")

    with col2:
        st.subheader("Errors by Application")
        errors_by_app = fetch_errors_by_app()
        if errors_by_app:
            df = pd.DataFrame(errors_by_app)
            fig = px.pie(
                df,
                values="error_count",
                names="application",
                hole=0.4,
            )
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data available")

    st.divider()

    # Time series chart
    st.subheader("Errors Over Time")
    errors_by_time = fetch_errors_by_time(time_interval)
    if errors_by_time:
        df = pd.DataFrame(errors_by_time)
        if not df.empty and "time_bucket" in df.columns:
            fig = px.area(
                df,
                x="time_bucket",
                y="count",
                color="application",
                line_group="application",
            )
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No time series data available")

    st.divider()

    # Error patterns
    st.subheader("Error Patterns")
    patterns = fetch_patterns()
    if patterns:
        df = pd.DataFrame(patterns)
        st.dataframe(
            df,
            column_config={
                "cluster_id": st.column_config.NumberColumn("Pattern ID"),
                "template": st.column_config.TextColumn("Template", width="large"),
                "count": st.column_config.NumberColumn("Count"),
            },
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No patterns discovered yet")

    st.divider()

    # Recent errors table with pagination (fragment to avoid scroll-to-top)
    st.subheader("Recent Errors")

    @st.fragment(run_every=60 if auto_refresh else None)
    def error_table_fragment():
        # Initialize page state
        if "error_page" not in st.session_state:
            st.session_state.error_page = 0

        current_page = st.session_state.error_page
        frag_offset = current_page * PAGE_SIZE

        errors, total_errors = fetch_errors(
            limit=PAGE_SIZE,
            offset=frag_offset,
            application=application_filter or None,
            domain=domain_filter or None,
            exception_class=exception_filter or None,
            api=api_filter or None,
            start_time=start_time_str,
            end_time=end_time_str,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        total_pages = max(1, (total_errors + PAGE_SIZE - 1) // PAGE_SIZE)

        if errors:
            df = pd.DataFrame(errors)
            display_cols = [
                "timestamp",
                "application",
                "domain",
                "language",
                "root_cause_class",
                "exception_message",
                "api",
                "user_id",
            ]
            available_cols = [c for c in display_cols if c in df.columns]
            if available_cols:
                selection = st.dataframe(
                    df[available_cols],
                    column_config={
                        "timestamp": st.column_config.DatetimeColumn("Time"),
                        "application": st.column_config.TextColumn("Application"),
                        "domain": st.column_config.TextColumn("Domain"),
                        "language": st.column_config.TextColumn("Language"),
                        "root_cause_class": st.column_config.TextColumn("Exception"),
                        "exception_message": st.column_config.TextColumn(
                            "Message", width="large"
                        ),
                        "api": st.column_config.TextColumn("API"),
                        "user_id": st.column_config.TextColumn("User"),
                    },
                    use_container_width=True,
                    hide_index=True,
                    selection_mode="single-row",
                    on_select="rerun",
                )

                # Show stack trace for selected row
                selected_rows = selection.selection.rows
                if selected_rows:
                    idx = selected_rows[0]
                    error = errors[idx]
                    if error.get("stack_trace"):
                        st.subheader(f"Stack Trace - {error.get('root_cause_class', 'Unknown')}")
                        st.code(error["stack_trace"], language="java")
                    else:
                        st.info("This log entry has no stack trace.")
                else:
                    st.caption("Select a row to view its stack trace.")

            # Pagination controls
            pcol1, pcol2, pcol3 = st.columns([1, 2, 1])
            with pcol1:
                if st.button("Previous", disabled=(current_page == 0)):
                    st.session_state.error_page = current_page - 1
                    st.rerun(scope="fragment")
            with pcol2:
                st.markdown(
                    f"<div style='text-align:center'>Page {current_page + 1} / {total_pages} ({total_errors} errors)</div>",
                    unsafe_allow_html=True,
                )
            with pcol3:
                if st.button("Next", disabled=(current_page >= total_pages - 1)):
                    st.session_state.error_page = current_page + 1
                    st.rerun(scope="fragment")
        else:
            st.info("No errors found matching filters")

    error_table_fragment()

else:
    st.warning("Could not connect to the parser service. Make sure it's running on port 8000.")
    st.code("uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload")
