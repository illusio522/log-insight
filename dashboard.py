import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import requests

# Configuration
API_URL = "http://localhost:8000"

st.set_page_config(
    page_title="Log Insight Dashboard",
    page_icon="📊",
    layout="wide",
)

st.title("Log Insight Dashboard")


def fetch_stats():
    """Fetch statistics from API."""
    try:
        response = requests.get(f"{API_URL}/stats", timeout=5)
        return response.json()
    except Exception as e:
        st.error(f"Failed to fetch stats: {e}")
        return None


def fetch_errors(limit=100, **filters):
    """Fetch errors from API."""
    try:
        params = {"limit": limit, **{k: v for k, v in filters.items() if v}}
        response = requests.get(f"{API_URL}/errors", params=params, timeout=5)
        return response.json().get("errors", [])
    except Exception as e:
        st.error(f"Failed to fetch errors: {e}")
        return []


def fetch_patterns():
    """Fetch error patterns from API."""
    try:
        response = requests.get(f"{API_URL}/patterns", timeout=5)
        return response.json().get("patterns", [])
    except Exception as e:
        st.error(f"Failed to fetch patterns: {e}")
        return []


def fetch_errors_by_app():
    """Fetch errors grouped by application."""
    try:
        response = requests.get(f"{API_URL}/errors/by-application", timeout=5)
        return response.json().get("data", [])
    except Exception as e:
        st.error(f"Failed to fetch data: {e}")
        return []


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


# Sidebar filters
st.sidebar.header("Filters")
application_filter = st.sidebar.text_input("Application")
domain_filter = st.sidebar.text_input("Domain")
exception_filter = st.sidebar.text_input("Exception Class")
time_interval = st.sidebar.selectbox("Time Interval", ["hour", "day", "minute"])

if st.sidebar.button("Refresh Data"):
    st.rerun()

# Main content
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

    # Recent errors table
    st.subheader("Recent Errors")
    errors = fetch_errors(
        limit=50,
        application=application_filter or None,
        domain=domain_filter or None,
        exception_class=exception_filter or None,
    )
    if errors:
        df = pd.DataFrame(errors)
        display_cols = [
            "timestamp",
            "application",
            "domain",
            "root_cause_class",
            "exception_message",
            "api",
            "user_id",
        ]
        available_cols = [c for c in display_cols if c in df.columns]
        if available_cols:
            st.dataframe(
                df[available_cols],
                column_config={
                    "timestamp": st.column_config.DatetimeColumn("Time"),
                    "application": st.column_config.TextColumn("Application"),
                    "domain": st.column_config.TextColumn("Domain"),
                    "root_cause_class": st.column_config.TextColumn("Exception"),
                    "exception_message": st.column_config.TextColumn(
                        "Message", width="large"
                    ),
                    "api": st.column_config.TextColumn("API"),
                    "user_id": st.column_config.TextColumn("User"),
                },
                use_container_width=True,
                hide_index=True,
            )

            # Expandable details
            with st.expander("View Stack Traces"):
                for i, error in enumerate(errors[:10]):
                    if error.get("stack_trace"):
                        st.text(f"Error {i + 1}: {error.get('root_cause_class', 'Unknown')}")
                        st.code(error["stack_trace"], language="java")
    else:
        st.info("No errors found matching filters")

else:
    st.warning("Could not connect to the parser service. Make sure it's running on port 8000.")
    st.code("uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload")
