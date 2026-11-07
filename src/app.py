"""Read-only Streamlit control tower for recorded Highway run artifacts.

Run: python -m streamlit run src/app.py --server.address 127.0.0.1
Set HIGHWAY_RUN_DIR to inspect a particular evidence directory.
"""
from __future__ import annotations

import html
import json
import os
from collections import Counter
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
READ_TOOLS = {"mes.get_schedule", "crm.loaner_availability"}
LABELS = {"supplier_delay": "Supplier delay", "plant_outage": "Plant outage",
          "quality_hold": "Quality hold", "noise": "Noise", "unconfirmed": "Unconfirmed"}
STATUS_LABELS = {"complete": "Complete", "no_action": "No action", "escalated": "Escalated",
                 "halted": "Halted", "needs_review": "Needs review", "unverified": "Unverified"}
COLORS = {"Shipment": "#65bfff", "Part": "#aa97ff", "Model": "#8b9bb0",
          "Plant": "#65bfff", "ProductionOrder": "#ffb064", "CustomerOrder": "#50d6b4",
          "Vehicle": "#ffb064", "Lot": "#aa97ff", "Dealer": "#50d6b4", "Customer": "#a5da79"}

CSS = """
<style>
:root {color-scheme: dark;}
.stApp {background:#0b1120;color:#e8edf4;}
[data-testid="stHeader"] {background:rgba(11,17,32,.94);}
[data-testid="stSidebar"] {background:#10192a;border-right:1px solid #253149;}
[data-testid="stSidebar"] * {color:#d4deec;}
.block-container {max-width:1560px;padding-top:2.0rem;padding-bottom:3rem;}
h1,h2,h3 {color:#f6f8fc;letter-spacing:-.035em;}
h1 {font-size:2.55rem!important;font-weight:700!important;}
h2 {font-size:1.45rem!important;}
h3 {font-size:1.12rem!important;}
p,li,label {line-height:1.55;}
[data-testid="stMetric"] {background:#121e31;border:1px solid #27344c;border-radius:12px;padding:16px 19px;}
[data-testid="stMetricLabel"] {color:#97a9c2;font-size:.78rem;letter-spacing:.03em;}
[data-testid="stMetricValue"] {color:#f7f9fc;font-size:1.75rem;font-weight:650;}
[data-testid="stVerticalBlockBorderWrapper"] {border-color:#28364c!important;border-radius:12px;}
[data-testid="stCaptionContainer"] {color:#91a3bc;}
[data-baseweb="select"] > div {background:#142137!important;border-color:#30415c!important;color:#e9eef7!important;}
[data-baseweb="popover"] {background:#152037!important;color:#e9eef7!important;}
[data-testid="stTextInput"] input {background:#142137;color:#eef4ff;}
[data-testid="stButton"] button,[data-testid="stDownloadButton"] button {border:1px solid #344864;background:#142138;color:#e8eef7;border-radius:8px;}
[data-testid="stButton"] button:hover,[data-testid="stDownloadButton"] button:hover {border-color:#50d6b4;color:#50d6b4;}
[data-testid="stDataFrame"] {border:1px solid #28364c;border-radius:10px;}
.eyebrow {color:#8fa1ba;font-size:.7rem;font-weight:700;letter-spacing:.18em;margin-bottom:9px;}
.brand {display:flex;align-items:center;gap:11px;margin:4px 0 18px;}
.brand-mark {background:#fa725b;color:#101624;font-weight:900;font-size:1.15rem;letter-spacing:-.12em;width:41px;height:41px;border-radius:10px;display:flex;align-items:center;justify-content:center;padding-right:3px;}
.brand-name {font-weight:750;color:#f6f9fc;letter-spacing:.06em;font-size:.83rem;}
.brand-sub {color:#8c9fb8;font-size:.7rem;letter-spacing:.06em;}
.run-card {border:1px solid #2d3e56;border-radius:10px;background:#142238;padding:12px 14px;margin-bottom:18px;}
.run-card b {color:#eaf1fa;font-size:.86rem;}
.run-card p {margin:4px 0 0;color:#93a7c3;font-size:.73rem;}
.tag {display:inline-block;border:1px solid #3a5069;border-radius:30px;padding:4px 10px;color:#bacbe0;background:#16243a;font-size:.71rem;font-weight:650;letter-spacing:.04em;}
.tag.good {color:#6ce1c2;border-color:#246657;background:#102e2b;}
.tag.warn {color:#f4c56a;border-color:#775a29;background:#302617;}
.tag.bad {color:#ffa49b;border-color:#824139;background:#382221;}
.event-head {display:flex;align-items:center;gap:9px;margin-top:3px;}
.source-text {color:#d7e2f0;font-size:.97rem;line-height:1.75;white-space:pre-wrap;margin:12px 0 5px;}
.agent {height:128px;background:#121e31;border:1px solid #2b3b53;border-top:3px solid #50d6b4;border-radius:10px;padding:14px 16px;}
.agent.planner {border-top-color:#65bfff;}.agent.care {border-top-color:#ffb064;}.agent.quality {border-top-color:#aa97ff;}
.agent .label {color:#8ea3bf;font-size:.66rem;letter-spacing:.11em;text-transform:uppercase;}
.agent .name {color:#eef3fa;font-size:.87rem;font-weight:700;margin:5px 0;}
.agent .detail {color:#9fb1ca;font-size:.76rem;line-height:1.45;}
.decision {border-left:3px solid #50d6b4;background:#10242a;padding:13px 17px;border-radius:0 8px 8px 0;margin:12px 0;}
.decision.warn {border-left-color:#f4c56a;background:#292419;}
.decision p {margin:0;color:#cedee9;font-size:.9rem;}
.graph-wrap {border:1px solid #2a3c55;border-radius:12px;background:linear-gradient(130deg,#121f34,#0e192b);overflow:auto;}
.path-note {font-family:ui-monospace,SFMono-Regular,Consolas,monospace;color:#9ab0cc;font-size:.72rem;overflow-wrap:anywhere;padding:10px 4px;}
.quiet {color:#9eb0c8;font-size:.88rem;}
.footer-line {border-top:1px solid #27344b;margin-top:24px;padding-top:14px;color:#7e93af;font-size:.73rem;}
[data-testid="stRadio"] label {font-size:.82rem;}
[data-testid="stTabs"] button {color:#bacbe0;}
[data-testid="stTabs"] button[aria-selected="true"] {color:#69dec3;border-color:#69dec3;}
</style>
"""


def escape(value):
    return html.escape(str(value), quote=True)


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        st.error(f"Could not load {path.name}: {type(exc).__name__}")
        return default


def as_records(value, key="events"):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        nested = value.get(key)
        return nested if isinstance(nested, list) else list(value.values())
    return []


def run_directory():
    override = os.environ.get("HIGHWAY_RUN_DIR")
    if override:
        return Path(override).expanduser().resolve()
    for name in ("submission", "dry-run", "preliminary"):
        folder = ROOT / "runs" / name
        if (folder / "traces.json").exists():
            return folder
    return ROOT / "runs" / "submission"


def load_bundle(folder):
    traces = as_records(read_json(folder / "traces.json", []), "traces")
    parsed = as_records(read_json(folder / "parsed.json", []))
    events = as_records(read_json(folder / "events.json", []))
    if not events:
        events = [trace["event"] for trace in traces if isinstance(trace.get("event"), dict)]
    if not events:
        events = [{"event_id": trace["event_id"], "text": "Source text was not recorded in this artifact."}
                  for trace in traces]
    audit = read_json(folder / "audit.json", {})
    if not audit:
        audit = read_json(folder / "audit_report.json", {})
    summary = read_json(folder / "summary.json", {})
    log_path = folder / "action_log.jsonl"
    log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    rows = []
    for line in log_text.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            st.error("The action log contains an invalid JSON line.")
            break
    return {"traces": {t["event_id"]: t for t in traces}, "parsed": {p["event_id"]: p for p in parsed},
            "events": events, "audit": audit, "summary": summary, "rows": rows, "log_text": log_text}


def kinds(trace, parsed=None):
    return sorted({i.get("kind", "unconfirmed") for i in trace.get("incidents", (parsed or {}).get("incidents", []))})


def status_tag(status):
    css = "good" if status in {"complete", "no_action"} else "warn" if status in {"escalated", "unverified"} else "bad"
    return f'<span class="tag {css}">{escape(STATUS_LABELS.get(status, status))}</span>'


def graph_svg(path):
    nodes = path.get("nodes", [])
    edges = path.get("edges", [])
    width = max(720, len(nodes) * 192)
    gap = width / max(len(nodes), 1)
    pieces = [f'<div class="graph-wrap"><svg role="img" aria-label="Recorded knowledge graph path" viewBox="0 0 {width} 192" width="100%" xmlns="http://www.w3.org/2000/svg">',
              '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#596f8e"/></marker></defs>']
    for index, edge in enumerate(edges):
        x1, x2 = gap * (index + .5) + 73, gap * (index + 1.5) - 77
        pieces.append(f'<line x1="{x1}" y1="88" x2="{x2}" y2="88" stroke="#596f8e" stroke-width="1.6" marker-end="url(#arrow)"/>')
        relation = str(edge.get("relation", "related")).replace("_", " ").lower()
        pieces.append(f'<text x="{(x1+x2)/2}" y="135" text-anchor="middle" fill="#849bb9" font-size="10" font-family="sans-serif">{escape(relation)}</text>')
    for index, node in enumerate(nodes):
        kind, _, identity = str(node).partition(":")
        color, x = COLORS.get(kind, "#8fa8c8"), gap * (index + .5)
        pieces.extend([f'<rect x="{x-72}" y="54" width="144" height="68" rx="11" fill="#15253c" stroke="{color}" stroke-opacity=".65"/>',
                       f'<circle cx="{x-56}" cy="72" r="3" fill="{color}"/>',
                       f'<text x="{x}" y="77" text-anchor="middle" fill="{color}" font-size="10" font-family="sans-serif">{escape(kind)}</text>',
                       f'<text x="{x}" y="101" text-anchor="middle" fill="#eef4fc" font-size="13" font-weight="600" font-family="monospace">{escape(identity)}</text>'])
    pieces.append('</svg></div>')
    return "".join(pieces)


def target_summary(args):
    for key in ("production_order_id", "customer_order_id", "lot_id", "customer_id", "dealer_id", "plant_id"):
        if key in args:
            suffix = ""
            if "customer_order_ids" in args:
                suffix = f" · {len(args['customer_order_ids'])} orders"
            if "vins" in args:
                suffix = f" · {len(args['vins'])} VINs"
            if "new_date" in args:
                suffix = f" → {args.get('to_plant_id', 'same plant')} / {args['new_date']}"
            return str(args[key]) + suffix
    return str(args.get("reason", ""))[:100]


def render():
    st.set_page_config(page_title="Highway · Wacky Wheels Control Tower", page_icon="◈", layout="wide", initial_sidebar_state="expanded")
    st.markdown(CSS, unsafe_allow_html=True)
    folder = run_directory()
    bundle = load_bundle(folder)
    traces, parsed, events, audit = bundle["traces"], bundle["parsed"], bundle["events"], bundle["audit"]
    provenances = [parsed.get(e["event_id"], {}).get("provenance", traces.get(e["event_id"], {}).get("extraction", {})) for e in events]
    models = sorted({str(p["model"]) for p in provenances if p.get("model")})
    manual = ("preliminary" in folder.name.lower() or any(p.get("provider") == "manual" for p in provenances)
              or (bool(events) and not models))
    phase = "Policy-only preliminary" if manual else "Submission snapshot" if folder.name == "submission" else "Recorded run"
    with st.sidebar:
        st.markdown('<div class="brand"><div class="brand-mark">WW</div><div><div class="brand-name">WACKY WHEELS</div><div class="brand-sub">OPERATIONS CONTROL</div></div></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="run-card"><b>{escape(phase)}</b><p>WORLD · MON 08 MAR 2027<br>Source · {escape(folder.name)}</p></div>', unsafe_allow_html=True)
        st.caption("EVENT FEED")
        statuses = ["All statuses", *sorted({STATUS_LABELS.get(t.get("status", "unverified"), t.get("status", "unverified")) for t in traces.values()})]
        status_filter = st.selectbox("Status", statuses, key="status_filter")
        category_filter = st.multiselect("Incident types", list(LABELS.values()), key="category_filter")
        filtered = []
        for event in events:
            eid = event["event_id"]
            trace = traces.get(eid, {})
            status = STATUS_LABELS.get(trace.get("status", "unverified"), trace.get("status", "unverified"))
            categories = [LABELS.get(k, k) for k in kinds(trace, parsed.get(eid))]
            if (status_filter == "All statuses" or status_filter == status) and (not category_filter or set(categories) & set(category_filter)):
                filtered.append(eid)
        if filtered:
            if st.session_state.get("selected_event") not in filtered:
                st.session_state["selected_event"] = filtered[0]
            def feed_label(eid):
                labels = [LABELS.get(k, k) for k in kinds(traces.get(eid, {}), parsed.get(eid))]
                return f"{eid}  ·  {'Compound' if len(labels) > 1 else labels[0] if labels else 'Pending'}"
            selected = st.radio("Recorded events", filtered, format_func=feed_label, key="selected_event", label_visibility="collapsed")
        else:
            selected = None
            st.info("No events match these filters." if events else "Waiting for run artifacts.")
        st.caption(f"{len(filtered)} of {len(events)} recorded events")
        st.divider()
        st.caption("Review and playback only. This dashboard does not execute enterprise tools.")
        st.button("Refresh artifacts", on_click=lambda: None, width="stretch")

    st.markdown('<div class="eyebrow">HITACHI · HACK THE HIGHWAY</div>', unsafe_allow_html=True)
    head, marker = st.columns([4, 1])
    with head:
        st.title("Highway Control Tower")
        st.caption("Trace every disruption from source message to verified operational action.")
    with marker:
        st.markdown('<div style="padding-top:20px;text-align:right"><span class="tag">RECORDED EVIDENCE</span></div>', unsafe_allow_html=True)
    if not events:
        st.info("No completed run is available yet. Run the local coordinator, then refresh this view.")
        st.code("python scripts/run.py --out runs/submission", language="powershell")
        st.caption(f"Artifact directory: {folder}")
        return
    if manual:
        st.warning("Policy-only preliminary evidence. Inputs were manually normalized or have no recorded model provenance; live LLM extraction and final submission are not established by this snapshot.")
    rows = bundle["rows"]
    failed = sum(row.get("ok") is not True for row in rows)
    write_count = sum(row.get("tool") not in READ_TOOLS | {"escalate"} for row in rows)
    if not rows:
        write_count = sum(t.get("write_count", len([a for a in t.get("actions", []) if a.get("tool") != "escalate"])) for t in traces.values())
    metrics = st.columns(4)
    metrics[0].metric("EVENTS AUDITED", f"{audit.get('events_passed', '—')} / {audit.get('events_total', len(events))}")
    metrics[1].metric("OPERATIONAL WRITES", f"{write_count:,}")
    metrics[2].metric("FAILED CALLS", str(failed) if rows else "Not logged")
    metrics[3].metric("DO-NOTHING BASELINE", f"{audit.get('baseline_do_nothing_events_passed', '—')} / {audit.get('events_total', len(events))}")
    st.caption("Audit results are local policy checks, not a hidden judging score. Each event has an independent world; compound incidents share resources.")
    if selected is None:
        st.info("Choose another filter to inspect an event.")
        return
    event = next(e for e in events if e["event_id"] == selected)
    trace = traces.get(selected, {})
    incident_list = trace.get("incidents", parsed.get(selected, {}).get("incidents", []))
    active_status = trace.get("status", "unverified")
    index = filtered.index(selected)
    title_col, previous_col, next_col = st.columns([6, 1, 1])
    with title_col:
        labels = [LABELS.get(i.get("kind"), i.get("kind", "Pending")) for i in incident_list]
        st.markdown(f'<div class="event-head"><h2 style="margin:12px 0">{escape(selected)} · {escape(" + ".join(dict.fromkeys(labels)))}</h2>{status_tag(active_status)}</div>', unsafe_allow_html=True)
    def select_event(eid):
        st.session_state["selected_event"] = eid
    with previous_col:
        st.button("← Previous", disabled=index == 0, on_click=select_event,
                  args=(filtered[max(index - 1, 0)],), width="stretch")
    with next_col:
        st.button("Next →", disabled=index == len(filtered) - 1, on_click=select_event,
                  args=(filtered[min(index + 1, len(filtered) - 1)],), width="stretch")
    with st.container(border=True):
        st.caption(f"SOURCE · {event.get('source', 'Recorded feed').upper()}  /  {event.get('received_at', 'Time not recorded').replace('T', ' ')}")
        st.markdown(f'<div class="source-text">{escape(event.get("text", "Source text unavailable."))}</div>', unsafe_allow_html=True)
    action_counts = Counter(action.get("role", "Coordinator") for action in trace.get("actions", []))
    agent_specs = [("Coordinator", "Orchestration", "Validate • route • preserve event scope", ""),
                   ("Supply Chain Planner", "Specialist 01", "BOM impact • earliest slots • transfers", "planner"),
                   ("Dealer Network / Customer Care", "Specialist 02", "Dealer union • loaner priority", "care"),
                   ("Quality", "Specialist 03", "Lot hold • stop sale • owner care", "quality")]
    for column, (name, label, responsibility, css) in zip(st.columns(4), agent_specs):
        with column:
            short = "Dealer & Customer Care" if "Dealer Network" in name else name
            observed = action_counts.get(name, 0)
            detail = f"{observed} recorded action{'s' if observed != 1 else ''}" if name != "Coordinator" else f"{len(incident_list)} incident{'s' if len(incident_list) != 1 else ''} routed"
            st.markdown(f'<div class="agent {css}"><div class="label">{escape(label)} · {escape(detail)}</div><div class="name">{escape(short)}</div><div class="detail">{escape(responsibility)}</div></div>', unsafe_allow_html=True)
    st.markdown("<div style='height:18px'></div>", unsafe_allow_html=True)
    decision_tab, actions_tab, audit_tab = st.tabs(["Decision & graph", "Actions & playback", "Audit & provenance"])
    with decision_tab:
        if not incident_list:
            st.info("No incident trace has been recorded.")
        else:
            inc_index = st.selectbox("Incident", range(len(incident_list)),
                                     format_func=lambda n: f"{n+1:02} · {LABELS.get(incident_list[n].get('kind'), 'Incident')}",
                                     key=f"incident_{selected}")
            incident = incident_list[inc_index]
            reason = incident.get("reason", "Decision rationale was not recorded.")
            warn = incident.get("kind") == "unconfirmed"
            st.markdown(f'<div class="decision {"warn" if warn else ""}"><p>{escape(reason)}</p></div>', unsafe_allow_html=True)
            brief_cols = st.columns([1, 1, 2])
            brief_cols[0].metric("AFFECTED BUILDS", len(incident.get("affected_production_orders", [])))
            brief_cols[1].metric("AFFECTED VEHICLES", len(incident.get("affected_vehicles", [])))
            with brief_cols[2]:
                st.caption("JUSTIFIED ACTION KINDS")
                action_kinds = incident.get("action_kinds", [])
                st.markdown(" · ".join(f"`{kind}`" for kind in action_kinds) if action_kinds else "No operational action required.")
            paths = incident.get("graph_paths", [])
            if paths:
                st.subheader("Graph evidence")
                path_index = st.selectbox("Evidence path", range(len(paths)),
                                          format_func=lambda n: f"Path {n+1:02} · {str(paths[n].get('nodes', [''])[0]).split(':')[-1]} → {str(paths[n].get('nodes', [''])[-1]).split(':')[-1]}",
                                          key=f"path_{selected}_{inc_index}")
                path = paths[path_index]
                st.html(graph_svg(path))
                st.markdown(f'<div class="path-note">{escape(path.get("text", " → ".join(path.get("nodes", []))))}</div>', unsafe_allow_html=True)
                st.caption(f"Showing {len(path.get('nodes', []))} table-backed entities. {len(paths)} representative paths recorded for this incident.")
            elif incident.get("kind") == "unconfirmed":
                st.info("Human confirmation required. The event was escalated; no operational change was justified.")
            elif incident.get("kind") == "noise":
                st.info("Operational restraint: this message does not justify a production, customer-care or quality action.")
            else:
                st.warning("This incident has no recorded graph path.")
            with st.expander("Inspect affected IDs and normalized incident"):
                st.json(incident, expanded=False)
    with actions_tab:
        show_reads = st.checkbox("Include free schedule and loaner-pool reads", key=f"reads_{selected}")
        calls = trace.get("calls", [])
        visible_calls = [(number, call) for number, call in enumerate(calls, 1) if show_reads or call.get("tool") not in READ_TOOLS]
        if visible_calls:
            st.dataframe([{"Step": number, "Agent": call.get("role", "—"), "Tool": call.get("tool", "—"),
                           "Target / change": target_summary(call.get("args", {})), "Result": "Confirmed" if call.get("ok") else "Review required"}
                          for number, call in visible_calls], hide_index=True, width="stretch", height=330)
            chosen = st.select_slider("Replay recorded call", options=list(range(len(visible_calls))),
                                       format_func=lambda n: f"{visible_calls[n][0]:03} · {visible_calls[n][1].get('tool')}",
                                       key=f"replay_{selected}_{show_reads}") if len(visible_calls) > 1 else 0
            number, call = visible_calls[chosen]
            st.caption(f"RECORDED STEP {number} · {call.get('role', 'Agent')}")
            st.write(call.get("reason", "No call rationale recorded."))
            args_col, result_col = st.columns(2)
            with args_col:
                st.caption("VALIDATED ARGUMENTS")
                st.json(call.get("args", {}), expanded=True)
            with result_col:
                st.caption("SERVER RESPONSE")
                st.json(call.get("result", {}), expanded=True)
            st.caption("Playback displays recorded evidence; it never repeats the tool call.")
        else:
            st.info("No operational calls were recorded for this event.")
    with audit_tab:
        audit_event = next((row for row in audit.get("events", []) if row.get("event_id") == selected), None)
        if audit_event:
            if audit_event.get("passed"):
                st.success("Independent policy audit passed for this event.")
            else:
                st.error("Independent policy audit requires review for this event.")
            for error in audit_event.get("errors", []):
                st.write(error)
            with st.expander("Independent audit evidence", expanded=False):
                st.json(audit_event, expanded=True)
        else:
            st.warning("No independent audit result was recorded for this event.")
        provenance = parsed.get(selected, {}).get("provenance", trace.get("extraction", {}))
        st.subheader("Model provenance")
        if provenance.get("model"):
            st.write(f"**{provenance['model']}**")
            st.caption(f"Provider: {provenance.get('provider', 'not recorded')} · Revision: {provenance.get('revision', 'not recorded')}")
            st.caption("The model extracts incident structure. Deterministic code resolves entities and dates, selects affected records, and decides actions.")
        else:
            st.write("No model citation was recorded in this snapshot.")
        with st.expander("Recorded extraction and model output"):
            st.json(provenance or {"status": "No provenance recorded"}, expanded=False)
        downloads = st.columns(3)
        with downloads[0]:
            st.download_button("Download event trace", json.dumps(trace, indent=2), file_name=f"{selected}-trace.json", mime="application/json", width="stretch")
        with downloads[1]:
            st.download_button("Download action log", bundle["log_text"], file_name="action_log.jsonl", mime="application/x-ndjson", disabled=not bool(bundle["log_text"]), width="stretch")
        with downloads[2]:
            st.download_button("Download audit report", json.dumps(audit, indent=2), file_name="audit.json", mime="application/json", disabled=not bool(audit), width="stretch")
        st.caption(f"Artifact directory: {folder}")
    st.markdown('<div class="footer-line">Wacky Wheels Co. · Local enterprise simulation · Recorded run evidence · No enterprise writes from this interface</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    render()
