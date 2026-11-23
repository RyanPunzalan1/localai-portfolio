"""Theme tokens and CSS for the dashboard.

Surface and text tokens copy app.py's values so the chat app and the dashboard look like one product. They are copied,
not imported: importing app.py would start the chat app.

Status colours are reserved for outcomes and always ship with an icon and a word, never colour alone.
"""

from __future__ import annotations

# ------------------------------------------------------------------ tokens
PALETTES = {
    "dark": {
        "bg": "#070707", "panel": "#0a0a0a", "raised": "#1a1a1b", "line": "#2a2a2b",
        "text": "#fafafa", "muted": "#8a8a8e", "accent": "#fafafa", "accent-ink": "#0a0a0a",
        # status (fixed steps, all >= 3:1 on the dark panel)
        "good": "#22c55e", "bad": "#e5534b", "warn": "#e9b730", "serious": "#ee7d33", "unk": "#8e8ea6",
        "grid": "#1c1c1d",
    },
    "light": {
        "bg": "#f6f6f7", "panel": "#ffffff", "raised": "#f0f0f2", "line": "#e1e1e5",
        "text": "#141416", "muted": "#6b6b74", "accent": "#141416", "accent-ink": "#ffffff",
        # warn and serious are under 3:1 on white by design; the icon + label pairing carries the meaning
        "good": "#0ca30c", "bad": "#d03b3b", "warn": "#fab219", "serious": "#ec835a", "unk": "#7b7b93",
        "grid": "#e6e6ef",
    },
}

# Display group -> (label, icon name, colour token). Groups come from dashboard.data.LABEL_GROUPS.
GROUPS = {
    "succeeded": ("Succeeded", "alert", "bad"),
    "blocked": ("Blocked", "check", "good"),
    "unattributed": ("Unattributed", "help", "unk"),
    "no_attempt": ("No attempt", "minus", "unk"),
    "benign_completed": ("Completed", "check", "good"),
    "false_positive": ("False positive", "block", "warn"),
    "control_passed": ("Control passed", "check", "good"),
    "control_failed": ("Control failed", "alert", "serious"),
    "stopped_at_approval": ("Stopped at approval", "block", "warn"),
    "not_reached": ("Not reached", "minus", "unk"),
    "inconclusive": ("Inconclusive", "help", "unk"),
    "other": ("Other", "dot", "unk"),
    "unverified": ("Unverified", "eye_off", "unk"),
}

ATTRIBUTION = {
    "observed": ("Observed", "The record says the layer's denial was observed directly."),
    "inferred": ("Inferred", "The record says the layer was inferred from the configuration."),
    "unspecified": ("Not stated", "The record names the layer but does not say whether it was observed or inferred."),
}

# Small inline icons (24px grid, stroked) for HTML fragments. Streamlit's :material/: icons only work in widgets.
_ICON_PATHS = {
    "alert": '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.8 2.8L16.5 9.5"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.3a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.2-2.4 3.6M12 16.8h.01"/>',
    "minus": '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
    "block": '<circle cx="12" cy="12" r="9"/><path d="m5.7 5.7 12.6 12.6"/>',
    "dot": '<circle cx="12" cy="12" r="4"/>',
    "eye_off": '<path d="M3 3l18 18M10.6 6.1A9.8 9.8 0 0 1 12 6c5 0 8.5 4.3 9.5 6-.4.7-1.3 2-2.6 3.2M6.6 6.6C4.6 7.9 3.2 9.8 2.5 12c1 1.7 4.5 6 9.5 6 1.6 0 3-.4 4.3-1.1M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    "shield": '<path d="M12 3 5 6v5c0 4.4 3 8.3 7 10 4-1.7 7-5.6 7-10V6z"/>',
    "shield_check": '<path d="M12 3 5 6v5c0 4.4 3 8.3 7 10 4-1.7 7-5.6 7-10V6z"/><path d="m9 12 2.2 2.2L15.5 10"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.5h.01"/>',
    "database": '<ellipse cx="12" cy="5.5" rx="7" ry="2.5"/><path d="M5 5.5v13c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-13M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "calendar": '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M4 10h16M9 3v4M15 3v4"/>',
    "chevron_updown": '<path d="m7 9 5-5 5 5M7 15l5 5 5-5"/>',
    "flask":'<path d="M9 3h6M10 3v6L4.8 18.2A2 2 0 0 0 6.5 21h11a2 2 0 0 0 1.7-2.8L14 9V3"/><path d="M7.5 15h9"/>',
}


def icon(name: str, color_token: str | None = None, size: int = 16) -> str:
    """Inline SVG icon. Colour comes from a theme token, so it follows light/dark."""
    stroke = f"var(--{color_token})" if color_token else "currentColor"
    return (f'<svg class="ico" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{stroke}" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'{_ICON_PATHS.get(name, _ICON_PATHS["dot"])}</svg>')


def _tokens(theme: str) -> str:
    return "".join(f"--{k}:{v};" for k, v in PALETTES[theme].items()) + f"color-scheme:{theme};"


# The page follows the system light/dark setting in the browser. Streamlit's default theme ("use system setting")
# follows the same setting, so its tables and widgets match. The server is never asked which theme is active:
# st.context.theme can be wrong on first load and during a change (Streamlit issue #11920).
ROOT_CSS = (f"<style>:root{{{_tokens('dark')}}}"
            f"@media (prefers-color-scheme: light){{:root{{{_tokens('light')}}}}}</style>")


# ------------------------------------------------------------------ base CSS
# Shared patterns follow app.py (sidebar, inputs, popovers, bordered containers) so behaviour matches.
BASE_CSS = """
<style>
:root {--radius: 10px;}
html, body, [class*="css"], .stApp {font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                                    font-size: 14px;}
.stApp {background: var(--bg); color: var(--text);}
#MainMenu, footer, [data-testid="stAppDeployButton"] {visibility: hidden;}
header[data-testid="stHeader"] {background: transparent;}
div[data-testid="stDecoration"] {display: none;}
.block-container {max-width: 1280px; padding-top: 1.6rem; padding-bottom: 4rem;}
.stApp, .stApp p, .stApp label, .stApp li, .stApp h1, .stApp h2, .stApp h3,
.stApp [data-testid="stMarkdownContainer"] {color: var(--text);}
.stApp [data-testid="stCaptionContainer"], .stApp small {color: var(--muted);}
.num {font-variant-numeric: tabular-nums;}
.mono {font-family: ui-monospace, Menlo, monospace; font-size: .85em;}
.ico {vertical-align: -3px; flex: none;}

/* Sidebar: brand, nav links, footer */
section[data-testid="stSidebar"] {background: var(--panel); border-right: 1px solid var(--line);}
section[data-testid="stSidebar"] .block-container {padding: 1.2rem .9rem;}
.brand {display: flex; align-items: center; gap: .6rem; font-size: 1.05rem; font-weight: 650; letter-spacing: -.01em;}
.brand .logo {display: inline-flex; width: 1.9rem; height: 1.9rem; border-radius: 8px; align-items: center;
              justify-content: center; background: var(--accent); color: var(--accent-ink);}
.brand-sub {color: var(--muted); font-size: .72rem; margin: .15rem 0 1.1rem;}
section[data-testid="stSidebar"] [data-testid="stPageLink"] a {border-radius: 10px; padding: .62rem .8rem;
    color: var(--muted); transition: background .12s ease;}
section[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {background: var(--raised);}
section[data-testid="stSidebar"] [data-testid="stPageLink"] a span,
section[data-testid="stSidebar"] [data-testid="stPageLink"] a p {color: var(--muted) !important; font-size: .95rem;}
section[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"],
section[data-testid="stSidebar"] [data-testid="stPageLink"] a[data-active="true"] {background: var(--raised);}
section[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"] span,
section[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"] p {color: var(--text) !important;
    font-weight: 550;}
.org {display: flex; align-items: center; gap: .6rem; padding: .25rem .3rem 1rem; border-bottom: 1px solid var(--line);
     margin-bottom: .8rem; font-weight: 600;}
.org-logo {width: 1.9rem; height: 1.9rem; border-radius: 8px; background: var(--raised); border: 1px solid var(--line);
           display: inline-flex; align-items: center; justify-content: center; font-weight: 700;}
.org-name {font-size: .98rem;}
.org-pill {font-size: .7rem; font-weight: 600; padding: 1px 7px; border-radius: 999px; color: var(--accent);
           border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent);}
.org .ico {margin-left: auto;}
.nav-div {height: 1px; background: var(--line); margin: .7rem .2rem;}
.user-foot {display: flex; align-items: center; gap: .6rem; position: fixed; bottom: 1.1rem; left: 1.1rem;
            width: 17rem; font-size: .85rem; line-height: 1.35;}
.user-foot .muted {color: var(--muted); font-size: .72rem;}
.avatar {width: 1.9rem; height: 1.9rem; border-radius: 50%; background: var(--accent); display: inline-flex;
         align-items: center; justify-content: center; flex: none;}
.side-foot {border: 1px solid var(--line); border-radius: var(--radius); padding: .6rem .75rem; margin-top: 1.4rem;
            font-size: .75rem; color: var(--muted); line-height: 1.5;}
.side-foot b {color: var(--text); font-weight: 550;}
[data-testid="stSidebarCollapseButton"] *, [data-testid="stSidebarCollapsedControl"] * {
    color: var(--muted) !important; fill: var(--muted) !important;}
[data-testid="stExpandSidebarButton"] {background: var(--raised) !important; border: 1px solid var(--line);
    border-radius: 8px;}
[data-testid="stExpandSidebarButton"] * {color: var(--text) !important; fill: var(--text) !important;}

/* Page header */
.page-head {display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; flex-wrap: wrap;
            margin-bottom: 1.1rem;}
.page-head h1 {font-size: 1.75rem; font-weight: 650; letter-spacing: -.02em; margin: 0; padding: 0; line-height: 1.2;}
.page-head .sub {color: var(--muted); font-size: .92rem; margin-top: .25rem;}
.chips {display: flex; gap: .5rem; flex-wrap: wrap;}
.chip {display: inline-flex; align-items: center; gap: .4rem; border: 1px solid var(--line); background: var(--panel);
       border-radius: 8px; padding: .35rem .7rem; font-size: .75rem; color: var(--text); white-space: nowrap;}
.chip .dot {width: 7px; height: 7px; border-radius: 50%; background: var(--good);}

/* KPI tiles */
.kpi {padding: .2rem .25rem; height: 100%;}
.kpi-label {display: flex; align-items: center; gap: .5rem; color: var(--muted); font-size: .9rem; font-weight: 400;}
.kpi-value {font-size: 2.6rem; font-weight: 600; letter-spacing: -.02em; line-height: 1.1; margin: .55rem 0 .3rem;
            font-variant-numeric: tabular-nums;}
.kpi-value .of {font-size: 1rem; color: var(--muted); font-weight: 500; margin-left: .2rem;}
.kpi-sub {color: var(--muted); font-size: .78rem;}

/* Status badge and attribution tag (icon + word + colour) */
.badge {display: inline-flex; align-items: center; gap: .35rem; padding: 2px 8px 2px 6px; border-radius: 999px;
        font-size: .76rem; font-weight: 550; color: var(--text); white-space: nowrap;
        border: 1px solid color-mix(in srgb, var(--c) 45%, transparent);
        background: color-mix(in srgb, var(--c) 14%, transparent);}
.tag {display: inline-flex; align-items: center; padding: 1px 7px; border-radius: 5px; font-size: .7rem;
      border: 1px solid var(--line); color: var(--muted); background: var(--raised); white-space: nowrap;}

/* Cards and section titles */
/* Cards: keyed bordered containers (components.card) so the selector does not depend on Streamlit internals */
[class*="st-key-card-"] {border: 1px solid var(--line) !important; background: var(--panel); border-radius: 12px;
                         padding: 1rem 1.1rem;}
.section-title {display: flex; align-items: center; gap: .55rem; font-size: 1rem; font-weight: 600; margin: .1rem 0 .4rem;}
.section-note {color: var(--muted); font-size: .78rem; display: flex; align-items: center; gap: .4rem;}

/* Evidence panel and execution timeline */
.ev-head {display: flex; justify-content: space-between; gap: .8rem; flex-wrap: wrap; align-items: flex-start;
          margin-bottom: .6rem;}
.ev-item {font-size: .95rem; font-weight: 600; word-break: break-all;}
.ev-meta {color: var(--muted); font-size: .78rem; margin-top: .15rem;}
.ev-badges {display: flex; gap: .35rem; flex-wrap: wrap; align-items: center;}
.tl {list-style: none; margin: .2rem 0 .8rem; padding: 0; position: relative;}
.tl::before {content: ""; position: absolute; left: 6px; top: 10px; bottom: 10px; width: 2px; background: var(--line);}
.tl-step {display: flex; align-items: flex-start; gap: .75rem; padding: .35rem 0; position: relative;}
.tl-dot {width: 14px; height: 14px; border-radius: 50%; background: var(--c); flex: none; margin-top: 2px;
         box-shadow: 0 0 0 2px var(--panel);}
.tl-body {flex: 1; min-width: 0;}
.tl-title {font-size: .86rem; font-weight: 550;}
.tl-detail {color: var(--muted); font-size: .76rem; word-break: break-word;}
.tl-detail:empty {display: none;}
.ev-grid {display: grid; grid-template-columns: max-content 1fr; gap: .25rem .9rem; font-size: .8rem;
          border-top: 1px solid var(--line); padding-top: .6rem; margin-bottom: .6rem;}
.ev-k {color: var(--muted);}
.ev-v {word-break: break-word;}

/* Charts: theme-dependent details come from the page tokens (see dashboard.charts) */
.outcome_segments_marks path {stroke: var(--panel) !important;}
.outcome_labels_marks text {fill: var(--text) !important;}
.matrix_cells_marks path, .layer_cells_marks path {stroke: var(--panel) !important;}
.st-key-card-c_matrix [data-testid="stVegaLiteChart"], .st-key-card-c_layers [data-testid="stVegaLiteChart"] {
    overflow-x: auto; max-width: 100%;}

/* Live Monitor: the only animation in the dashboard (switched off by prefers-reduced-motion) */
.banner .muted {color: var(--muted); font-weight: 400;}
.live-on {border-color: color-mix(in srgb, var(--good) 55%, var(--line));}
.live-dot {width: 10px; height: 10px; border-radius: 50%; background: var(--good); flex: none;
           box-shadow: 0 0 0 0 color-mix(in srgb, var(--good) 60%, transparent); animation: live-pulse 1.6s ease-out infinite;}
@keyframes live-pulse {0% {box-shadow: 0 0 0 0 color-mix(in srgb, var(--good) 60%, transparent);}
                       70% {box-shadow: 0 0 0 9px transparent;} 100% {box-shadow: 0 0 0 0 transparent;}}

/* Live run progress and event feed */
.prog-label {font-size: .86rem; margin-bottom: .4rem;}
.prog {height: 10px; border-radius: 999px; background: var(--raised); border: 1px solid var(--line); overflow: hidden;}
.prog-fill {height: 100%; background: var(--accent); border-radius: 999px; transition: width .4s ease;}
.tl.feed {max-height: 520px; overflow-y: auto; padding-right: .3rem;}
.tl.feed .tl-step:first-child {animation: feed-in .5s ease-out;}
@keyframes feed-in {from {opacity: 0; transform: translateY(-4px);} to {opacity: 1; transform: none;}}

/* Empty state and mock banner */
.empty {border: 1px dashed var(--line); border-radius: 12px; padding: 2rem 1.2rem; text-align: center;
        background: var(--panel);}
.empty h3 {font-size: 1.02rem; font-weight: 600; margin: .5rem 0 .3rem;}
.empty p {color: var(--muted) !important; font-size: .86rem; margin: 0 auto; max-width: 36rem;}
.mock-banner {display: flex; align-items: center; gap: .6rem; border: 1px solid var(--warn); border-radius: 10px;
              padding: .55rem .9rem; margin-bottom: 1rem; font-size: .85rem; font-weight: 600;
              background: color-mix(in srgb, var(--warn) 14%, transparent);}
.banner {display: flex; align-items: center; gap: .6rem; border: 1px solid var(--line); border-radius: 10px;
         padding: .55rem .9rem; margin-bottom: 1rem; font-size: .84rem; background: var(--panel);}

/* Inputs, dropdowns and popovers follow the theme (same approach as app.py) */
.stApp input, .stApp textarea, .stApp div[data-baseweb="select"] > div,
.stApp div[data-baseweb="input"] {background: var(--raised) !important; color: var(--text) !important;
                                  border-color: var(--line) !important;}
div[data-baseweb="select"] svg {color: var(--text) !important; fill: var(--text) !important;}
[data-baseweb="popover"] [data-baseweb="menu"], [data-baseweb="popover"] ul[role="listbox"] {
    background: var(--panel) !important; border: 1px solid var(--line);}
[data-baseweb="popover"] li[role="option"] {background: var(--panel) !important; color: var(--text) !important;}
[data-baseweb="popover"] li[role="option"]:hover, [data-baseweb="popover"] li[aria-selected="true"] {
    background: var(--raised) !important;}
[data-baseweb="tag"] {background: var(--raised) !important; color: var(--text) !important;}
[data-baseweb="tag"] span {color: var(--text) !important;}
/* Streamlit 1.65 inputs (react-aria): field boxes, selected-value tags, date fields */
[data-testid="stMultiSelect"] [role="group"], [data-testid="stDateInputField"],
[data-testid="stSelectbox"] [role="group"] {background: var(--raised) !important; border-color: var(--line) !important;
    color: var(--text) !important;}
[data-testid="stMultiSelect"] *, [data-testid="stDateInputField"] * {color: var(--text) !important;}
[data-testid="stMultiSelectTagsContainer"] [data-tag] {background: color-mix(in srgb, var(--accent) 22%, var(--raised)) !important;
    color: var(--text) !important; border: 1px solid color-mix(in srgb, var(--accent) 50%, transparent);}
[data-testid="stMultiSelectTagsContainer"] [data-tag] * {color: var(--text) !important; fill: var(--text) !important;}
[data-testid="stMultiSelect"] input::placeholder {color: var(--muted) !important; opacity: 1;}
.stApp pre, .stApp code {background: var(--raised) !important; color: var(--text) !important;}
.stButton > button {border-radius: 8px; border: 1px solid var(--line); background: var(--text); color: var(--bg); font-weight: 600;}
.stButton > button:hover {border-color: var(--text); color: var(--bg); opacity: .9;}
label:has([role="switch"]) > div:first-of-type {background: var(--line) !important;}
label:has([role="switch"][aria-checked="true"]) > div:first-of-type {background: var(--accent) !important;}
div[data-testid="stExpander"] {border: 1px solid var(--line); border-radius: var(--radius);}
div[data-testid="stExpander"] summary {background: var(--panel) !important; color: var(--text) !important;}
div[data-testid="stExpander"] summary * {color: var(--text) !important;}

/* Reference look: card headers with a divider, full-width list rows, big figures, donut total */
[class*="st-key-head-"] {margin: -1rem -1.1rem .35rem; padding: .85rem 1.1rem; border-bottom: 1px solid var(--line);
                         align-items: center;}
[class*="st-key-head-"] [data-testid="stHorizontalBlock"] {align-items: center; gap: .5rem;}
.card-title {font-size: .95rem; font-weight: 500; line-height: 1.4;}
[class*="st-key-head-"] [data-testid="stPageLink"] {display: flex; justify-content: flex-end;}
[class*="st-key-head-"] [data-testid="stPageLink"] a {padding: 0; background: transparent !important;}
[class*="st-key-head-"] [data-testid="stPageLink"] [data-testid="stIconMaterial"], [class*="st-key-head-"] [data-testid="stPageLink"] a img {display: none;}
[class*="st-key-head-"] [data-testid="stPageLink"] a p {color: var(--muted) !important; font-size: .82rem;}
.li {display: flex; align-items: center; justify-content: space-between; gap: .8rem; margin: 0 -1.1rem;
     padding: .95rem 1.1rem; border-bottom: 1px solid var(--line); font-size: .92rem;}
[data-testid="stElementContainer"]:last-child > div > .li, [data-testid="stElementContainer"]:last-child .li {border-bottom: none;}
.li-name {overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0;}
.pill {font-size: .8rem; font-weight: 600; padding: 3px 10px; border-radius: 8px; flex: none;
       color: var(--c); background: color-mix(in srgb, var(--c) 14%, transparent);}
.dots {display: flex; gap: .85rem; flex: none;}
.dotn {display: inline-flex; align-items: center; gap: .35rem; color: var(--muted); font-size: .85rem;}
.dotn .dot {width: 8px; height: 8px; border-radius: 50%; background: var(--c);}
.st-key-ring-wrap {position: relative;}
.ring-total {position: absolute; top: 108px; left: 0; right: 0; transform: translateY(-50%); text-align: center;
             pointer-events: none; color: var(--muted); font-size: .85rem; line-height: 1.5;}
.ring-total b {display: block; color: var(--text); font-size: 1.5rem; font-weight: 600;}
.dot-sw {display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: .55rem;}
.muted-n {color: var(--muted); font-size: .85rem; flex: none;}
.big {text-align: right; font-size: 2.1rem; font-weight: 600; letter-spacing: -.02em; line-height: 1.1;
      margin: .8rem 0 .2rem;}
.big span {font-size: .9rem; font-weight: 400; color: var(--muted); margin-left: .35rem; letter-spacing: 0;}
.big-left {font-size: 1.6rem; font-weight: 600; margin: .8rem 0 .2rem;}
.big-left span {font-size: .85rem; font-weight: 400; color: var(--muted); margin: 0 .9rem 0 .3rem;}
.kpi-value .note {font-size: .85rem; font-weight: 400; margin-left: .5rem; letter-spacing: 0; color: var(--c, var(--muted));}

.st-key-cta a {background: #fafafa !important; border-radius: 10px; padding: .55rem 1rem !important; justify-content: center;}
.st-key-cta a p, .st-key-cta a span {color: #0a0a0a !important; font-weight: 600; font-size: .9rem;}
.st-key-tools [data-testid="stPopover"] button {border-radius: 10px; border: 1px solid var(--line); background: var(--panel);
                                               color: var(--text); width: 100%; justify-content: flex-start;}

/* Phone width: tiles and header stack */
@media (max-width: 640px) {
  .page-head h1 {font-size: 1.45rem;}
  .kpi {min-height: 0;}
  .kpi-value {font-size: 1.7rem;}
}
@media (prefers-reduced-motion: reduce) { * {transition: none !important; animation: none !important;} }
</style>
"""
