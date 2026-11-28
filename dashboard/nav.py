"""The dashboard's pages, in sidebar order. Views use page() to link to each other."""

import streamlit as st

from dashboard.views import comparison, experiments, live, models, overview, readiness, reports, settings

PAGES = [
    st.Page(overview.render, title="Overview", icon=":material/dashboard:", url_path="overview", default=True),
    st.Page(live.render, title="Live Monitor", icon=":material/monitor_heart:", url_path="live"),
    st.Page(experiments.render, title="Experiments", icon=":material/science:", url_path="experiments"),
    st.Page(comparison.render, title="Security Comparison", icon=":material/shield:", url_path="comparison"),
    st.Page(readiness.render, title="Security Readiness", icon=":material/verified_user:", url_path="readiness"),
    st.Page(reports.render, title="Reports", icon=":material/description:", url_path="reports"),
    st.Page(models.render, title="Models", icon=":material/memory:", url_path="models"),
    st.Page(settings.render, title="Settings", icon=":material/settings:", url_path="settings"),
]


def page(url_path: str):
    return next(p for p in PAGES if p.url_path == url_path)
