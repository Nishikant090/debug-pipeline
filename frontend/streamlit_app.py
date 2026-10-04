"""
Debug Pipeline — Streamlit Dashboard

Run:  streamlit run frontend/streamlit_app.py
API:  uvicorn app.main:app --port 8088

Talks to the FastAPI backend over HTTP only — no app/ imports — so the
dashboard and the API can run on different machines (set DEBUG_PIPELINE_API).
"""
from __future__ import annotations

import html
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import requests
import streamlit as st

API_ROOT = os.environ.get("DEBUG_PIPELINE_API", "http://127.0.0.1:8088").rstrip("/")
API = f"{API_ROOT}/api/v1"
PROJECT_ROOT = Path(__file__).resolve().parent.parent

st.set_page_config(
    page_title="Debug Pipeline",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Severity → status colour (icon + label always accompany the colour) ───────
SEVERITY = {
    "critical": {"color": "#d03b3b", "icon": "⛔", "rank": 0},
    "high":     {"color": "#ec835a", "icon": "🔺", "rank": 1},
    "medium":   {"color": "#fab219", "icon": "⚠️", "rank": 2},
    "low":      {"color": "#0ca30c", "icon": "✅", "rank": 3},
}

st.markdown(
    """
<style>
:root {
  --dp-border: rgba(128,128,128,.22);
  --dp-muted: rgba(128,128,128,.95);
  --dp-soft: rgba(128,128,128,.08);
}
.block-container { padding-top: 3.5rem; max-width: 1280px; }
.dp-hero h1 { font-size: 1.9rem; margin: 0 0 .15rem 0; padding: 0; }
.dp-hero p  { color: var(--dp-muted); margin: 0 0 1.2rem 0; }
.dp-chain { display: grid; grid-template-columns: repeat(4, 1fr); gap: .75rem; margin: .5rem 0 1.25rem; }
@media (max-width: 800px) { .dp-chain { grid-template-columns: repeat(2, 1fr); } }
.dp-step { border: 1px solid var(--dp-border); border-radius: 12px; padding: .85rem 1rem; background: var(--dp-soft); }
.dp-step .n { font-size: .72rem; letter-spacing: .06em; text-transform: uppercase; color: var(--dp-muted); }
.dp-step .t { font-weight: 600; margin: .15rem 0; }
.dp-step .s { font-size: .85rem; color: var(--dp-muted); }
.dp-dot { display:inline-block; width:.55rem; height:.55rem; border-radius:50%; margin-right:.4rem; vertical-align: middle; }
.dp-on  { background:#0ca30c; } .dp-off { background:rgba(128,128,128,.6); } .dp-busy { background:#fab219; }
.dp-card { border: 1px solid var(--dp-border); border-left: 4px solid var(--sev); border-radius: 10px;
           padding: .7rem 1rem; margin-bottom: .55rem; }
.dp-card .top { display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap; font-size:.8rem; color:var(--dp-muted); }
.dp-card .msg { font-family: ui-monospace, Consolas, monospace; font-size: .9rem; margin: .3rem 0 .2rem; word-break: break-word; }
.dp-card .cause { font-size: .88rem; }
.dp-pill { display:inline-block; border:1px solid var(--dp-border); border-radius: 999px; padding: 0 .55rem;
           font-size:.75rem; margin-right:.3rem; }
.dp-bars .row { display:grid; grid-template-columns: 7.5rem 1fr 2.5rem; align-items:center; gap:.6rem; margin:.45rem 0; font-size:.88rem; }
.dp-bars .track { height: .7rem; border-radius: 4px; background: var(--dp-soft); overflow: hidden; }
.dp-bars .fill { height: 100%; border-radius: 0 4px 4px 0; }
.dp-bars .v { text-align: right; font-variant-numeric: tabular-nums; }
</style>
""",
    unsafe_allow_html=True,
)


# ── API helpers ───────────────────────────────────────────────────────────────

def api(method: str, path: str, timeout: float = 15, quiet: bool = False, **kwargs):
    """Call the backend. Returns the Response, or None after showing an error."""
    url = path if path.startswith("http") else f"{API}{path}"
    try:
        return requests.request(method, url, timeout=timeout, **kwargs)
    except requests.exceptions.Timeout:
        if not quiet:
            st.error(f"⏱ The API took longer than {timeout:.0f}s to respond.")
    except requests.exceptions.ConnectionError:
        if not quiet:
            st.error(f"🔌 Cannot reach the API at `{API_ROOT}` — is `uvicorn app.main:app --port 8088` running?")
    except requests.exceptions.RequestException as e:
        if not quiet:
            st.error(f"Request error: {e}")
    return None


def get_json(path: str, default=None, timeout: float = 15, quiet: bool = True):
    r = api("GET", path, timeout=timeout, quiet=quiet)
    if r is not None and r.ok:
        try:
            return r.json()
        except ValueError:
            pass
    return default


def error_detail(r) -> str:
    try:
        return str(r.json().get("detail", r.text))
    except ValueError:
        return r.text[:300]


# ── Formatting helpers ────────────────────────────────────────────────────────

def ev_message(ev: dict) -> str:
    entry = ev["error"]["log_entry"]
    return str(entry.get("message") or entry.get("msg") or "No message")


def ev_service(ev: dict) -> str:
    return str(ev["error"]["log_entry"].get("service") or "unknown-service")


def sev_label(sev: str) -> str:
    return f"{SEVERITY.get(sev, {}).get('icon', '•')} {sev.upper()}"


def event_card(ev: dict) -> None:
    sev = ev["step2"]["severity"]
    color = SEVERITY.get(sev, {}).get("color", "#888")
    jira = ev.get("jira")
    jira_html = (
        f'<a href="{html.escape(jira["ticket_url"])}" target="_blank">🎫 {html.escape(jira["ticket_id"])}</a>'
        if jira else "no ticket"
    )
    st.markdown(
        f"""
<div class="dp-card" style="--sev:{color}">
  <div class="top">
    <span><b>{sev_label(sev)}</b> · {html.escape(ev_service(ev))} · {ev['error']['detected_at'][:19].replace('T', ' ')}</span>
    <span>confidence {ev['step2']['confidence_score']:.0%} · {jira_html}</span>
  </div>
  <div class="msg">{html.escape(ev_message(ev)[:220])}</div>
  <div class="cause">{html.escape(ev['step2']['root_cause'][:260])}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def event_detail(ev: dict) -> None:
    s1, s2, jira = ev["step1"], ev["step2"], ev.get("jira")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Severity", sev_label(s2["severity"]), border=True)
    c2.metric("Analysis confidence", f"{s2['confidence_score']:.0%}", border=True)
    c3.metric("Function match confidence", f"{s1['confidence']:.0%}", border=True)
    c4.metric("JIRA ticket", jira["ticket_id"] if jira else "—", border=True)

    if jira:
        st.link_button(f"Open {jira['ticket_id']} in JIRA ↗", jira["ticket_url"])

    st.markdown("#### Root cause")
    st.write(s2["root_cause"])

    tab_fix, tab_debug, tab_tech, tab_step1, tab_raw = st.tabs(
        ["🛠 Fixes", "🔎 Debugging steps", "📖 Explanation", "🎯 Suspected functions", "🧾 Raw log"]
    )
    with tab_fix:
        for i, fix in enumerate(s2["possible_fixes"], 1):
            with st.container(border=True):
                st.markdown(fix if fix.lower().startswith("fix") else f"**Fix {i}.** {fix}")
    with tab_debug:
        for i, step in enumerate(s2["debugging_steps"], 1):
            st.markdown(f"{i}. {step}")
    with tab_tech:
        st.write(s2["technical_explanation"])
        if s2.get("affected_components"):
            st.markdown("**Affected components:** " + ", ".join(f"`{c}`" for c in s2["affected_components"]))
    with tab_step1:
        if s1["suspected_functions"]:
            st.markdown(" ".join(f"`{f}`" for f in s1["suspected_functions"]))
        else:
            st.warning(
                "No indexed function matched this error — the analysis is based on the log entry alone. "
                "Index the codebase that produced these logs for code-level results."
            )
        st.caption(s1["reasoning"])
    with tab_raw:
        st.json(ev["error"]["log_entry"])


def severity_bars(events: list[dict]) -> None:
    counts = Counter(ev["step2"]["severity"] for ev in events)
    peak = max(counts.values(), default=0) or 1
    rows = []
    for sev in sorted(SEVERITY, key=lambda s: SEVERITY[s]["rank"]):
        n = counts.get(sev, 0)
        pct = n / peak * 100
        rows.append(
            f'<div class="row" title="{sev}: {n} incident(s)"><span>{sev_label(sev)}</span>'
            f'<div class="track"><div class="fill" style="width:{pct:.1f}%;background:{SEVERITY[sev]["color"]}"></div></div>'
            f'<span class="v">{n}</span></div>'
        )
    st.markdown(f'<div class="dp-bars">{"".join(rows)}</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGES
# ══════════════════════════════════════════════════════════════════════════════

def page_overview() -> None:
    health = get_json(f"{API_ROOT}/health", timeout=3)
    dbg = get_json("/monitor/debug", default={}, timeout=5)
    events = get_json("/monitor/events?limit=200", default=[])

    st.markdown(
        '<div class="dp-hero"><h1>🔍 Debug Pipeline</h1>'
        "<p>Errors in your logs → AI root-cause analysis against your code → a fully triaged JIRA ticket.</p></div>",
        unsafe_allow_html=True,
    )
    if health is None:
        st.error(f"The API at `{API_ROOT}` is offline. Start it with `uvicorn app.main:app --port 8088`.")
        st.stop()

    tickets = sum(1 for e in events if e.get("jira"))
    queued = dbg.get("errors_queued_for_analysis", 0)
    running = dbg.get("monitor_running", False)
    fn_count = dbg.get("index_functions", 0)
    target = dbg.get("health_url") if dbg.get("monitor_type") == "health" else dbg.get("log_path")

    def step(n, title, ok, text, busy=False):
        dot = "dp-busy" if busy else ("dp-on" if ok else "dp-off")
        return (f'<div class="dp-step"><div class="n">Step {n}</div>'
                f'<div class="t"><span class="dp-dot {dot}"></span>{title}</div>'
                f'<div class="s">{html.escape(text)}</div></div>')

    st.markdown(
        '<div class="dp-chain">'
        + step(1, "Index code", fn_count > 0, f"{fn_count} functions indexed" if fn_count else "No index yet")
        + step(2, "Monitor", running, (Path(target).name if target and dbg.get("monitor_type") != "health" else target) or "Stopped")
        + step(3, "AI analysis", len(events) > 0, f"{queued} in queue" if queued else f"{len(events)} analysed", busy=queued > 0)
        + step(4, "JIRA tickets", tickets > 0, f"{tickets} created")
        + "</div>",
        unsafe_allow_html=True,
    )

    k1, k2, k3, k4 = st.columns(4)
    urgent = sum(1 for e in events if e["step2"]["severity"] in ("critical", "high"))
    avg_conf = sum(e["step2"]["confidence_score"] for e in events) / len(events) if events else 0
    k1.metric("Incidents analysed", len(events), border=True)
    k2.metric("Critical + high", urgent, border=True)
    k3.metric("JIRA tickets", tickets, border=True)
    k4.metric("Avg. confidence", f"{avg_conf:.0%}" if events else "—", border=True)

    if not events:
        st.info("No incidents yet. **1)** Index your code on **Codebase**, **2)** start a monitor on **Live Monitor**.")
        c1, c2 = st.columns(2)
        c1.page_link(PAGES["index"], label="Go to Codebase", icon="📦")
        c2.page_link(PAGES["monitor"], label="Go to Live Monitor", icon="📡")
        return

    left, right = st.columns([1, 2], gap="large")
    with left:
        st.markdown("##### Incidents by severity")
        severity_bars(events)
        st.markdown("##### Top services")
        for svc, n in Counter(ev_service(e) for e in events).most_common(5):
            st.markdown(f'<span class="dp-pill">{html.escape(svc)}</span> {n}', unsafe_allow_html=True)
    with right:
        st.markdown("##### Latest incidents")
        for ev in events[:5]:
            event_card(ev)
        st.page_link(PAGES["incidents"], label="See all incidents", icon="📋")


def page_index() -> None:
    st.title("📦 Codebase index")
    st.caption(
        "One-time setup: every function's name, docstring and source is extracted so the AI can match "
        "errors to real code. Python, JavaScript/TypeScript, Java and Go are supported."
    )

    status = get_json("/index/status")
    if status is None:
        st.error(f"Cannot reach the API at `{API_ROOT}`.")
        st.stop()
    if status["indexed"]:
        c1, c2, c3 = st.columns(3)
        c1.metric("Files", status["total_files"], border=True)
        c2.metric("Functions", status["total_functions"], border=True)
        c3.metric("Built", (status.get("created_at") or "")[:16].replace("T", " "), border=True)
        st.caption(f"Root: `{status['root_path']}`")
    else:
        st.warning("No index yet — build one below.")

    st.subheader("Build or rebuild the index")
    tab_zip, tab_path = st.tabs(["📦 Upload a ZIP", "📁 Folder on the API server"])
    result = None
    with tab_zip:
        uploaded = st.file_uploader("Backend source as a .zip", type="zip")
        if st.button("Build index from ZIP", type="primary", disabled=uploaded is None):
            with st.spinner("Extracting functions…"):
                r = api("POST", "/index/upload", timeout=180,
                        files={"file": (uploaded.name, uploaded.getvalue(), "application/zip")})
            if r is not None and r.ok:
                result = r.json()
            elif r is not None:
                st.error(f"Indexing failed: {error_detail(r)}")
    with tab_path:
        dir_path = st.text_input("Absolute folder path", placeholder="C:/projects/my-backend")
        if st.button("Build index from folder", type="primary", disabled=not dir_path):
            with st.spinner("Extracting functions…"):
                r = api("POST", "/index/path", timeout=180, params={"directory": dir_path})
            if r is not None and r.ok:
                result = r.json()
            elif r is not None:
                st.error(f"Indexing failed: {error_detail(r)}")
    if result:
        s = result["summary"]
        st.success(f"Index built — {s['total_files']} files, {s['total_functions']} functions, "
                   f"{s['total_classes']} classes, {s['total_routes']} API routes.")

    # The API saves the index next to where it runs; read it for the browser.
    idx_file = PROJECT_ROOT / "backend_index.json"
    if status["indexed"] and idx_file.exists():
        try:
            idx = json.loads(idx_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            st.caption(f"Function browser unavailable: {e}")
            return
        st.subheader("Function browser")
        langs = idx["summary"].get("languages_detected", {})
        if langs:
            st.markdown(" ".join(f'<span class="dp-pill">{html.escape(k)} · {v}</span>' for k, v in langs.items()),
                        unsafe_allow_html=True)
        rows = [
            {"Function": fn["name"], "File": f["path"], "Lines": f"{fn['start_line']}–{fn['end_line']}",
             "Description": fn["description"][:140]}
            for f in idx.get("files", []) for fn in f.get("functions", [])
        ]
        query = st.text_input("Search functions", placeholder="e.g. login, jira, parse")
        if query:
            q = query.lower()
            rows = [r for r in rows if q in r["Function"].lower() or q in r["File"].lower() or q in r["Description"].lower()]
        st.dataframe(rows, use_container_width=True, hide_index=True, height=380)
        st.caption(f"{len(rows)} function(s)")


def page_monitor() -> None:
    st.title("📡 Live monitor")
    dbg = get_json("/monitor/debug", default=None, timeout=5)
    if dbg is None:
        st.error(f"Cannot reach the API at `{API_ROOT}`.")
        st.stop()
    running = dbg.get("monitor_running", False)

    if not dbg.get("groq_key_looks_valid", True):
        st.error("`GROQ_API_KEY` looks invalid (must start with `gsk_`). Fix `.env` and restart the API.")
    if dbg.get("index_functions", 0) == 0:
        st.warning("No codebase index — the AI can only reason from log text. Build one on **Codebase** first.")

    with st.container(border=True):
        top_l, top_r = st.columns([3, 1])
        with top_l:
            if running:
                target = dbg.get("health_url") if dbg.get("monitor_type") == "health" else dbg.get("log_path")
                st.markdown(f'<span class="dp-dot dp-on"></span>**Watching** `{target}`', unsafe_allow_html=True)
            else:
                st.markdown('<span class="dp-dot dp-off"></span>**Stopped**', unsafe_allow_html=True)
        with top_r:
            if st.button("⏹ Stop", disabled=not running, use_container_width=True):
                api("POST", "/monitor/stop")
                st.rerun()

        mode = st.segmented_control(
            "Source", ["Log file", "Health-check URL"], default="Health-check URL" if dbg.get("monitor_type") == "health" else "Log file",
        ) or "Log file"
        if mode == "Log file":
            default_path = st.session_state.get("monitor_path", "test_logs/live.log")
            path = st.text_input("JSON log file (absolute, or relative to the project folder)", value=default_path)
            if path and not Path(path).is_absolute():
                path = str(PROJECT_ROOT / path)
            payload = {"monitor_type": "log", "log_path": path}
            ready = bool(path)
        else:
            url = st.text_input("URL to poll", placeholder="https://example.com/health")
            c1, c2 = st.columns(2)
            interval = c1.number_input("Check every (s)", 1, 3600, 3)
            threshold = c2.number_input("Failures before alert", 1, 100, 3)
            payload = {"monitor_type": "health", "health_url": url,
                       "check_interval_sec": int(interval), "failure_threshold": int(threshold)}
            ready = bool(url)

        if st.button("🔄 Restart monitor" if running else "▶ Start monitor", type="primary", disabled=not ready):
            if running:
                api("POST", "/monitor/stop")
            r = api("POST", "/monitor/start", json=payload)
            if r is not None and r.ok:
                st.rerun()
            elif r is not None:
                st.error(f"Could not start ({r.status_code}): {error_detail(r)}")

    live_feed()


@st.fragment(run_every=4)
def live_feed() -> None:
    dbg = get_json("/monitor/debug", default={}, timeout=5)
    events = get_json("/monitor/events?limit=20", default=[])
    health_mode = dbg.get("monitor_type") == "health"

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Failed checks" if health_mode else "Errors detected",
              dbg.get("health_failures" if health_mode else "errors_detected_in_log", 0), border=True)
    c2.metric("Analysing now", dbg.get("errors_queued_for_analysis", 0), border=True)
    c3.metric("Analysed", dbg.get("errors_fully_analyzed", 0), border=True)
    c4.metric("JIRA tickets", sum(1 for e in events if e.get("jira")), border=True)

    if dbg.get("errors_queued_for_analysis", 0):
        st.info(f"⏳ {dbg['errors_queued_for_analysis']} error(s) with the AI — about 10–30 s each.")
    elif dbg.get("last_error_message"):
        st.caption(f"Last detected: `{dbg['last_error_message'][:160]}`")

    head_l, head_r = st.columns([4, 1])
    head_l.markdown("##### Incident feed")
    if head_r.button("Clear events", use_container_width=True, disabled=not events):
        api("DELETE", "/monitor/events", timeout=5)
        st.rerun()
    if not events:
        st.caption("Nothing yet — incidents appear here as soon as they are analysed. This view refreshes every 4 s.")
    for ev in events:
        event_card(ev)


def page_incidents() -> None:
    st.title("📋 Incidents")
    events = get_json("/monitor/events?limit=200", default=None)
    if events is None:
        st.error(f"Cannot reach the API at `{API_ROOT}`.")
        st.stop()
    if not events:
        st.info("No analysed incidents yet.")
        return

    f1, f2 = st.columns([2, 3])
    sev_filter = f1.pills("Severity", list(SEVERITY), selection_mode="multi", default=list(SEVERITY),
                          format_func=sev_label)
    query = f2.text_input("Search message, service or root cause")
    shown = [
        e for e in events
        if e["step2"]["severity"] in (sev_filter or [])
        and (not query or query.lower() in (ev_message(e) + ev_service(e) + e["step2"]["root_cause"]).lower())
    ]
    st.caption(f"{len(shown)} of {len(events)} incident(s)")
    if not shown:
        return

    rows = [
        {"Detected": e["error"]["detected_at"][:19].replace("T", " "), "Severity": sev_label(e["step2"]["severity"]),
         "Service": ev_service(e), "Message": ev_message(e)[:90],
         "Confidence": e["step2"]["confidence_score"],
         "JIRA": e["jira"]["ticket_url"] if e.get("jira") else None}
        for e in shown
    ]
    sel = st.dataframe(
        rows, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row",
        column_config={
            "Confidence": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1),
            "JIRA": st.column_config.LinkColumn(display_text=r"browse/(.*)$"),
        },
    )
    picked = sel.selection.rows[0] if sel.selection.rows else 0
    st.divider()
    st.caption("Select a row above to inspect it.")
    st.subheader(ev_message(shown[picked])[:120])
    event_detail(shown[picked])


def page_settings() -> None:
    st.title("⚙️ Settings & connections")
    health = get_json(f"{API_ROOT}/health", timeout=3)
    dbg = get_json("/monitor/debug", default={}, timeout=5)

    c1, c2 = st.columns(2)
    with c1.container(border=True):
        st.markdown("**Backend API**")
        if health:
            st.markdown(f'<span class="dp-dot dp-on"></span>Online at `{API_ROOT}`', unsafe_allow_html=True)
            st.caption(f"Model: `{health['model']}`")
        else:
            st.markdown(f'<span class="dp-dot dp-off"></span>Offline (`{API_ROOT}`)', unsafe_allow_html=True)
    with c2.container(border=True):
        st.markdown("**Groq API key**")
        ok = dbg.get("groq_key_looks_valid")
        st.markdown(f'<span class="dp-dot {"dp-on" if ok else "dp-off"}"></span>'
                    f'{"Looks valid" if ok else "Missing or invalid"} · `{dbg.get("groq_key_preview", "—")}`',
                    unsafe_allow_html=True)

    st.subheader("JIRA")
    st.caption("Reads `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN` and `JIRA_PROJECT_KEY` from `.env`. "
               "Restart the API after changing them.")
    if st.button("🔌 Test JIRA connection", type="primary"):
        with st.spinner("Contacting Atlassian…"):
            data = get_json("/monitor/jira-test", default=None, timeout=45, quiet=False)
        if data is None:
            st.stop()
        if data.get("ok"):
            st.success(f"Connected as **{data.get('logged_in_as')}** to **{data.get('project_name')}** "
                       f"(`{data.get('jira_project_key')}`) at {data.get('jira_base_url')}")
            a, b = st.columns(2)
            a.markdown("**Issue types:** " + ", ".join(f"`{t}`" for t in data.get("issue_types", [])))
            if "Bug" not in data.get("issue_types", []):
                a.caption("No `Bug` type in this project — tickets are created as `Task`.")
            b.markdown("**Priorities:** " + ", ".join(f"`{p}`" for p in data.get("priorities", [])))
        else:
            st.error(f"JIRA connection failed: `{data.get('error')}`")
            st.markdown(
                "- **Base URL** must be just `https://<site>.atlassian.net`\n"
                "- **Email** is the one you log in to Atlassian with\n"
                "- **API token**: create one at https://id.atlassian.com/manage-profile/security/api-tokens\n"
                "- **Project key** is the prefix of ticket IDs (e.g. `KAN` in `KAN-1`)"
            )


def page_generator() -> None:
    st.title("🧪 Test log generator")
    st.caption("Writes realistic JSON logs (auth, API, database, payments, cache, workers) with injected "
               "ERROR / CRITICAL / FATAL lines, so you can watch the pipeline work end to end.")
    script = PROJECT_ROOT / "log_generator" / "fake_log_generator.py"

    left, right = st.columns(2, gap="large")
    with left:
        out_path = st.text_input("Output file (appended to)", value="test_logs/live.log")
        n_lines = st.slider("Lines to write", 10, 1000, 50, step=10)
        error_rate = st.slider("Error rate", 0.05, 0.60, 0.15, step=0.05,
                               help="Every error becomes an AI analysis and, with JIRA configured, a ticket.")
        est = round(n_lines * error_rate)
        st.caption(f"≈ {est} error line(s) → ≈ {est} AI analyses" + (" and JIRA tickets." if est else "."))

        b1, b2, b3 = st.columns(3)
        gen = b1.button("▶ Generate", type="primary", use_container_width=True, disabled=not out_path)
        clear = b2.button("Clear file", use_container_width=True, disabled=not out_path)
        use = b3.button("Monitor it", use_container_width=True, disabled=not out_path)

    full_path = Path(out_path) if Path(out_path).is_absolute() else PROJECT_ROOT / out_path
    if gen:
        with st.spinner(f"Writing {n_lines} lines…"):
            res = subprocess.run(
                [sys.executable, str(script), "--output", str(full_path), "--count", str(n_lines),
                 "--interval", "0", "--error-rate", str(error_rate)],
                capture_output=True, text=True, timeout=120, cwd=PROJECT_ROOT,
            )
        if res.returncode == 0:
            left.success(f"Wrote {n_lines} lines to `{out_path}`.")
        else:
            left.error(f"Generator failed: {res.stderr[-500:]}")
    if clear:
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text("", encoding="utf-8")
        left.success(f"Cleared `{out_path}`.")
    if use:
        st.session_state["monitor_path"] = out_path
        st.switch_page(PAGES["monitor"])

    with right:
        st.markdown("##### File contents")
        if full_path.exists():
            lines = [l for l in full_path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
            errs = 0
            for line in lines:
                try:
                    errs += json.loads(line).get("level") in ("ERROR", "CRITICAL", "FATAL")
                except ValueError:
                    pass
            m1, m2 = st.columns(2)
            m1.metric("Lines", len(lines), border=True)
            m2.metric("Error lines", errs, border=True)
            st.code("\n".join(lines[-8:]) or "(empty)", language="json")
        else:
            st.caption("File doesn't exist yet — it is created on first generate.")

    with st.expander("Live stream from a terminal"):
        st.code(f'python log_generator/fake_log_generator.py --output {out_path} --interval 1.0 --error-rate 0.15',
                language="bash")
        st.caption("Streams one line per second until you press Ctrl+C. Start the monitor on the same file first.")


# ── Navigation ────────────────────────────────────────────────────────────────

PAGES = {
    "overview":  st.Page(page_overview,  title="Overview",     icon="🏠", default=True),
    "monitor":   st.Page(page_monitor,   title="Live Monitor", icon="📡", url_path="monitor"),
    "incidents": st.Page(page_incidents, title="Incidents",    icon="📋", url_path="incidents"),
    "index":     st.Page(page_index,     title="Codebase",     icon="📦", url_path="codebase"),
    "generator": st.Page(page_generator, title="Test Logs",    icon="🧪", url_path="test-logs"),
    "settings":  st.Page(page_settings,  title="Settings",     icon="⚙️", url_path="settings"),
}

with st.sidebar:
    st.markdown("### 🔍 Debug Pipeline")
    st.caption("AI root-cause analysis → JIRA")
    h = get_json(f"{API_ROOT}/health", timeout=2)
    if h:
        st.markdown(
            f'<span class="dp-dot dp-on"></span>API online<br>'
            f'<span class="dp-dot {"dp-on" if h["monitoring"] else "dp-off"}"></span>'
            f'Monitor {"running" if h["monitoring"] else "stopped"}<br>'
            f'<span class="dp-dot {"dp-on" if h["index_loaded"] else "dp-off"}"></span>'
            f'Index {"loaded" if h["index_loaded"] else "missing"}',
            unsafe_allow_html=True,
        )
    else:
        st.markdown('<span class="dp-dot dp-off"></span>API offline', unsafe_allow_html=True)

nav = st.navigation(
    {"Dashboard": [PAGES["overview"], PAGES["monitor"], PAGES["incidents"]],
     "Setup": [PAGES["index"], PAGES["generator"], PAGES["settings"]]},
)
nav.run()
