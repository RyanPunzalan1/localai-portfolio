"""LocalAI security evaluation dashboard (read-only).

Run: .venv/bin/streamlit run security_dashboard.py --server.port 8502

A separate entrypoint from app.py on purpose: the chat app is untouched, and there is no root pages/ folder
(Streamlit would add it to app.py's navigation).
"""

import streamlit as st

from dashboard import theme
from dashboard.components import EXPLORER_KEYS, FILTER_KEYS, html
from dashboard.store import snapshot
from dashboard.nav import PAGES

st.set_page_config(page_title="LocalAI · Security evaluation", page_icon=":material/shield:", layout="wide")

ss = st.session_state

# Streamlit drops a widget's state when a page without that widget runs. Re-assigning the keys keeps
# filters and the superseded switch the same across pages.
for _key in (*FILTER_KEYS, *EXPLORER_KEYS, "include_superseded"):
    if _key in ss:
        ss[_key] = ss[_key]

html(theme.BASE_CSS)
html(theme.ROOT_CSS)

page = st.navigation(PAGES, position="hidden")

snap = snapshot()

with st.sidebar:
    html('<div class="org"><span class="org-logo">L</span><span class="org-name">LocalAI</span>'
         f'<span class="org-pill">Local</span>{theme.icon("chevron_updown", "muted", 16)}</div>')
    for i, p in enumerate(PAGES):
        if i == 6:  # divider before Models and Settings
            html('<div class="nav-div"></div>')
        st.page_link(p)
    n_files = len(snap.security_files) + len(snap.model_files)
    bad = f"<br>{len(snap.bad_lines)} unreadable line(s) skipped" if snap.bad_lines else ""
    sup = "<br>Including superseded runs" if ss.get("include_superseded") else ""
    html(f'<div class="user-foot"><span class="avatar">{theme.icon("shield", "accent-ink", 14)}</span>'
         f'<span><b>Local operator</b><br><span class="muted">{n_files} result files · read-only{sup}{bad}</span>'
         f'</span></div>')

page.run()
