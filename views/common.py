"""Shared pieces for the screens: AI settings, demo cases, and how a result is displayed."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from engine import db
from engine.ai import DOC_LABELS
from engine.pipeline import STAGES
from engine.validators import ENTITY_LABELS, normalize_name

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "test_cases"
IST = timezone(timedelta(hours=5, minutes=30))

SEVERITY_STYLE = {  # label shown, Streamlit colour
    "PASS": ("Pass", "green"), "INFO": ("Info", "blue"), "FIX": ("Fix", "orange"),
    "REVIEW": ("Review", "violet"), "BLOCK": ("Block", "red"),
}
STATUS_STYLE = {"Approved": "green", "Pending": "orange", "Rejected": "red", "Running": "gray"}
STAGE_LABEL = {k: f"{i}. {name}" for i, (k, name, _) in enumerate(STAGES, 1)}


# ---------------------------------------------------------------------------
# AI configuration
# ---------------------------------------------------------------------------
def _secret(name):
    try:
        return st.secrets.get(name)
    except Exception:
        return None


def api_key():
    return _secret("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")


def ai_config():
    key = api_key()
    offline = st.session_state.get("offline_mode", not bool(key))
    mode = "offline" if (offline or not key) else "live"
    return {"mode": mode, "api_key": key, "model": _secret("GEMINI_MODEL") or os.environ.get("GEMINI_MODEL")}


def sidebar():
    with st.sidebar:
        st.markdown("#### AI mode")
        key = api_key()
        if key:
            st.toggle("Offline mode (stored sample answers)", key="offline_mode", value=False,
                      help="Use when Gemini is slow or rate-limited. Works only for the demo files.")
        else:
            st.session_state["offline_mode"] = True
            st.caption("No Gemini API key found, so the app runs in offline mode. Add GEMINI_API_KEY to the "
                       "app's secrets to switch on live AI.")
        cfg = ai_config()
        if cfg["mode"] == "live":
            st.success("Live: Gemini reads every document", icon=":material/bolt:")
        else:
            st.warning("Offline: stored sample answers for demo files", icon=":material/cloud_off:")
        st.divider()
        st.caption("Rules decide, AI assists. Every decision is written to the audit log.")


# ---------------------------------------------------------------------------
# Demo cases
# ---------------------------------------------------------------------------
@st.cache_data
def load_cases():
    cases = []
    for folder in sorted(CASES.iterdir()):
        if not (folder / "submission.json").exists():
            continue
        meta = json.loads((folder / "submission.json").read_text(encoding="utf-8"))
        files = [(p.name, p.read_bytes()) for p in sorted(folder.iterdir()) if p.name != "submission.json"]
        cases.append({"key": folder.name, **meta, "files": files})
    return cases


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def ist(ts):
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).astimezone(IST).strftime("%d %b, %H:%M:%S")
    except ValueError:
        return ts


def sev_badge(sev):
    label, colour = SEVERITY_STYLE.get(sev, (sev, "gray"))
    return f":{colour}-background[{label}]"


def status_line(status, flag):
    colour = STATUS_STYLE.get(status, "gray")
    return f":{colour}-background[**{status}**]" + (f" · {flag}" if flag else "")


def rules_frame(rules):
    rows = [{"Rule": r["rule"], "Stage": STAGE_LABEL.get(r["stage"], r["stage"]),
             "Result": SEVERITY_STYLE.get(r["severity"], (r["severity"],))[0],
             "Reason": r["reason"] + (f"  ({r['note']})" if r.get("note") else "")} for r in rules]
    return pd.DataFrame(rows)


def style_result(col):
    colours = {"Pass": "#e6f4ea", "Info": "#e8f0fe", "Fix": "#fdf0e1", "Review": "#f1eafd", "Block": "#fce8e8"}
    return [f"background-color: {colours.get(v, '')}" for v in col]


# ---------------------------------------------------------------------------
# Triangulation matrix
# ---------------------------------------------------------------------------
SOURCES = ["Form", "PAN card", "GST certificate", "Cheque", "GST registry", "Bank (penny-drop)"]


def matrix_frame(result):
    by_rule = {}
    for r in result["rules"]:
        if r["rule"].startswith("T"):
            by_rule.setdefault(r["rule"], r)
    rows, colours = [], []
    for m in result["matrix"]:
        rule = by_rule.get(m["rule"])
        passed = rule["passed"] if rule else True
        base = normalize_name(m.get("Form") or "")
        row, row_col = {"Fact": m["Fact"]}, {"Fact": ""}
        for s in SOURCES:
            v = m.get(s)
            row[s] = v if v else "—"
            if not v:
                row_col[s] = "color: #9aa1ad"
            elif passed or s == "Form" or normalize_name(v) == base:
                row_col[s] = "background-color: #e6f4ea"
            else:
                row_col[s] = "background-color: #fce8e8; font-weight: 600"
        row["Check"] = f"{m['rule']} · " + ("agrees" if passed else SEVERITY_STYLE[rule["severity"]][0].lower())
        row_col["Check"] = "" if passed else "color: #b3261e; font-weight: 600"
        rows.append(row)
        colours.append(row_col)
    df = pd.DataFrame(rows)
    styles = pd.DataFrame(colours)[df.columns]
    return df.style.apply(lambda _: styles, axis=None)


# ---------------------------------------------------------------------------
# A full result (used on the Submit screen and the Vendor detail screen)
# ---------------------------------------------------------------------------
def render_result(result, events=None, show_files=None):
    status, flag = result["status"], result.get("flag")
    colour = {"Approved": st.success, "Pending": st.warning, "Rejected": st.error}[status]
    counts = result.get("counts", {})
    summary = ", ".join(f"{n} {k.lower()}" for k, n in counts.items() if n) or "no issues"
    colour(f"**{status}**" + (f" — {flag}" if flag else "") + f"  \n{result.get('top_reason', '')}  \n"
           f"Rules failed: {summary} · {result.get('seconds', 0)}s · AI mode: {result.get('ai_mode')}",
           icon={"Approved": ":material/check_circle:", "Pending": ":material/schedule:",
                 "Rejected": ":material/block:"}[status])
    notes = [r["note"] for r in result["rules"] if r.get("note")]
    for n in notes:
        st.info(n, icon=":material/info:")

    tabs = st.tabs(["Why", "Triangulation", "Documents", "Vendor message", "Audit log"])
    with tabs[0]:
        failed = [r for r in result["rules"] if not r["passed"]]
        if failed:
            st.markdown("**What needs attention**")
            for r in sorted(failed, key=lambda x: ["BLOCK", "REVIEW", "FIX", "INFO"].index(x["severity"])):
                st.markdown(f"{sev_badge(r['severity'])} **{r['rule']}** · {r['reason']}")
        st.markdown("**Every rule that ran**")
        df = rules_frame(result["rules"])
        st.dataframe(df.style.apply(style_result, subset=["Result"]), hide_index=True,
                     width="stretch", height=min(38 * (len(df) + 1), 620))
    with tabs[1]:
        st.caption("Each fact checked across every source that carries it. The GST registry and the bank are the "
                   "anchors: a vendor can edit a PDF, not what they return. Red = disagrees with the form.")
        st.dataframe(matrix_frame(result), hide_index=True, width="stretch")
        if result.get("names"):
            with st.expander("Name comparisons (how each pair was judged)"):
                st.dataframe(pd.DataFrame([{"Pair": k.replace("_", " "), "Result": v["match_class"],
                                            "Reason": v["reason"], "Decided by": v.get("source")}
                                           for k, v in result["names"].items()]),
                             hide_index=True, width="stretch")
    with tabs[2]:
        file_bytes = dict(show_files or [])
        for d in result["documents"]:
            label = DOC_LABELS.get(d.get("doc_type"))
            with st.container(border=True):
                c1, c2 = st.columns([1, 2])
                with c1:
                    data = file_bytes.get(d["file_name"])
                    if data and not d["file_name"].lower().endswith(".pdf") and d.get("doc_type") != "aadhaar":
                        st.image(data, width="stretch")
                    elif d.get("doc_type") == "aadhaar":
                        st.caption("Aadhaar image not displayed or stored.")
                    else:
                        st.caption(":material/picture_as_pdf: PDF")
                with c2:
                    st.markdown(f"**{d['file_name']}** → :blue-background[{label}] "
                                f"confidence {d.get('doc_type_confidence') or 0:.2f}")
                    st.caption(f"{d.get('notes', '')}  \nRead by: {d.get('source')} · fingerprint {d['sha256'][:12]}…")
                    if d.get("quality_issue"):
                        st.markdown(f":orange-background[Quality: {d['quality_issue']}]")
                    if d.get("fields"):
                        st.dataframe(pd.DataFrame([{"Field": k.replace("_", " "), "Value": v.get("value") or "—",
                                                    "Confidence": v.get("confidence"),
                                                    "Trusted": "yes" if (v.get("confidence") or 0) >= 0.8 else "no"}
                                                   for k, v in d["fields"].items()]),
                                     hide_index=True, width="stretch")
                    meta = d.get("metadata")
                    if meta and meta.get("checked"):
                        st.caption(f"PDF metadata — producer: {meta.get('producer')}; created: {meta.get('created')}; "
                                   f"modified: {meta.get('modified')}")
    with tabs[3]:
        msg = result.get("message") or {}
        st.caption(f"Drafted by: {msg.get('source')}. Not sent: a person reviews it first. "
                   + ("Rejections stay neutral on purpose: a suspected fraudster is never told which check failed."
                      if status == "Rejected" else ""))
        st.text_input("Subject", msg.get("subject", ""), key=f"subj_{result['run_id']}")
        st.text_area("Body", msg.get("body", ""), height=280, key=f"body_{result['run_id']}")
    with tabs[4]:
        evs = events if events is not None else db.get_events(result["run_id"])
        st.dataframe(pd.DataFrame([{"Time (IST)": ist(e["at"]), "Actor": e["actor"], "Action": e["action"],
                                    "Detail": e["detail"]} for e in evs]),
                     hide_index=True, width="stretch")
        st.caption(f"Run {result['run_id']}" + (f" · follows earlier run {result['previous_run_id']}"
                                                  if result.get("previous_run_id") else ""))
