"""Screen 1 — New submission and the live run view."""
import time

import streamlit as st

from engine import pipeline
from engine.ai import DOC_LABELS
from engine.validators import ENTITY_LABELS
from views.common import (SEVERITY_STYLE, STAGE_LABEL, ai_config, load_cases, render_result, sev_badge)

FORM_FIELDS = ["legal_name", "entity_type", "proprietor_name", "pan", "gstin", "address", "city", "state",
               "pincode", "contact_name", "email", "phone", "account_number", "ifsc", "account_holder_name",
               "category", "expected_annual_spend_inr"]
ENTITY_KEYS = list(ENTITY_LABELS)


def load_case(case):
    for f in FORM_FIELDS:
        v = case["form"].get(f, "")
        st.session_state[f"f_{f}"] = "" if v is None else (str(v) if f != "entity_type" else v)
    st.session_state["demo_case"] = case
    st.session_state["form_data"] = {f: st.session_state[f"f_{f}"] for f in FORM_FIELDS}
    st.session_state.pop("last_result", None)


def clear_form():
    for f in FORM_FIELDS:
        st.session_state[f"f_{f}"] = "private_limited" if f == "entity_type" else ""
    st.session_state.pop("demo_case", None)
    st.session_state.pop("form_data", None)
    st.session_state.pop("last_result", None)


st.title("New vendor submission")
st.caption("A vendor fills a short form and uploads documents without labelling them. "
           "The process tags each file, checks completeness, triangulates every fact, and decides.")

# ---------------------------------------------------------------- demo picker
cases = load_cases()
with st.container(border=True):
    c1, c2, c3 = st.columns([3, 1, 1], vertical_alignment="bottom")
    titles = {c["key"]: c["title"] for c in cases}
    pick = c1.selectbox("Load a demo case", list(titles), format_func=titles.get, key="case_pick")
    chosen = next(c for c in cases if c["key"] == pick)
    c2.button("Load case", type="secondary", on_click=load_case, args=(chosen,), width="stretch",
              icon=":material/upload_file:")
    c3.button("Clear form", on_click=clear_form, width="stretch", icon=":material/restart_alt:")
    demo = st.session_state.get("demo_case")
    if demo:
        st.markdown(f"**Loaded:** {demo['title']}  \n{demo['story']}  \n"
                    f"Expected outcome: :blue-background[{demo['expected']}]")

# ---------------------------------------------------------------- the form
# Streamlit forgets a page's input boxes when you visit another page, so the form is
# also kept in "form_data" and restored from it when you come back.
saved = st.session_state.get("form_data", {})
for f in FORM_FIELDS:
    if f"f_{f}" not in st.session_state:
        st.session_state[f"f_{f}"] = saved.get(f) or ("private_limited" if f == "entity_type" else "")

col_a, col_b, col_c = st.columns(3)
with col_a:
    st.markdown("**Company and tax**")
    st.text_input("Legal name", key="f_legal_name")
    st.selectbox("Entity type", ENTITY_KEYS, format_func=ENTITY_LABELS.get, key="f_entity_type")
    if st.session_state["f_entity_type"] == "proprietorship":
        st.text_input("Proprietor name", key="f_proprietor_name")
    st.text_input("PAN", key="f_pan", placeholder="ABCDE1234F")
    st.text_input("GSTIN", key="f_gstin", placeholder="07ABCDE1234F1Z5")
with col_b:
    st.markdown("**Address and contact**")
    st.text_input("Address", key="f_address")
    cc1, cc2 = st.columns(2)
    cc1.text_input("City", key="f_city")
    cc2.text_input("State", key="f_state")
    st.text_input("Pincode", key="f_pincode")
    st.text_input("Contact name", key="f_contact_name")
    cc3, cc4 = st.columns(2)
    cc3.text_input("Email", key="f_email")
    cc4.text_input("Phone", key="f_phone")
with col_c:
    st.markdown("**Bank and commercial**")
    st.text_input("Bank account number", key="f_account_number")
    st.text_input("IFSC", key="f_ifsc", placeholder="HDFC0001234")
    st.text_input("Account holder name", key="f_account_holder_name")
    cc5, cc6 = st.columns(2)
    cc5.text_input("Category", key="f_category")
    cc6.text_input("Expected annual spend (₹)", key="f_expected_annual_spend_inr")

st.session_state["form_data"] = {f: st.session_state.get(f"f_{f}") for f in FORM_FIELDS}

# ---------------------------------------------------------------- documents
st.markdown("**Documents** — upload in any order, with any file names")
files = []
if demo:
    use_demo = st.checkbox(f"Use the {len(demo['files'])} files from the demo case", value=True)
    if use_demo:
        files = list(demo["files"])
        st.caption(" · ".join(f":material/description: {n}" for n, _ in files))
uploads = st.file_uploader("Add files (PDF, JPG, PNG)", type=["pdf", "jpg", "jpeg", "png"],
                           accept_multiple_files=True, label_visibility="collapsed")
files += [(u.name, u.getvalue()) for u in uploads or []]

run_clicked = st.button("Run onboarding check", type="primary", icon=":material/play_arrow:",
                        disabled=not files, width="content")
if not files:
    st.caption("Load a demo case or add at least one file to run.")

# ---------------------------------------------------------------- live run view
if run_clicked:
    st.session_state.pop("last_result", None)
    cfg = ai_config()
    submission = {f: st.session_state.get(f"f_{f}") for f in FORM_FIELDS}
    st.divider()
    st.subheader("Live run")
    left, right = st.columns([3, 2], gap="large")
    holders = {key: left.empty() for key, _, _ in pipeline.STAGES}
    boxes = {}
    right.markdown("**Documents as they are tagged**")
    doc_area = right.container()
    pace = 0.4 if cfg["mode"] == "offline" else 0  # offline is instant; pace it so each stage is visible

    def on_event(kind, stage, payload):
        if kind == "stage_start":
            desc = next(d for k, _, d in pipeline.STAGES if k == stage)
            boxes[stage] = holders[stage].status(f"{STAGE_LABEL[stage]} — {desc}", state="running", expanded=True)
            time.sleep(pace)
        elif kind == "file_start":
            boxes[stage].write(f":material/hourglass_top: Reading **{payload}**…")
        elif kind == "wait":
            boxes[stage].warning(payload, icon=":material/timer:")
        elif kind == "file_done":
            with doc_area.container(border=True):
                conf = payload.get("doc_type_confidence") or 0
                st.markdown(f"**{payload['file_name']}**  \n→ :blue-background[{DOC_LABELS.get(payload.get('doc_type'))}] "
                            f"confidence {conf:.2f}")
                st.caption(f"{payload.get('notes', '')}  \nvia {payload.get('source')}"
                           + (f" · {payload.get('seconds')}s" if payload.get("seconds") else ""))
            time.sleep(pace / 2)
        elif kind == "stage_done":
            box = boxes[stage]
            failed = [r for r in payload if not r["passed"]]
            for r in payload:
                box.markdown(f"{sev_badge(r['severity'])} **{r['rule']}** · {r['reason']}")
            worst = {r["severity"] for r in failed}
            state = "error" if "BLOCK" in worst else "complete"
            if stage == "decision":
                return
            summary = f"{len(payload) - len(failed)} passed" + "".join(
                f" · {sum(1 for r in failed if r['severity'] == s)} {SEVERITY_STYLE[s][0].lower()}"
                for s in ("BLOCK", "REVIEW", "FIX", "INFO") if s in worst)
            box.update(label=f"{STAGE_LABEL[stage]} — {summary}", state=state, expanded=bool(worst - {"INFO"}))
        elif kind == "done":
            boxes["decision"].update(label=f"{STAGE_LABEL['decision']} — {payload['status']}"
                                     + (f" ({payload['flag']})" if payload.get("flag") else ""),
                                     state="error" if payload["status"] == "Rejected" else "complete", expanded=False)

    case_label = demo["key"] if demo and files[: len(demo["files"])] == list(demo["files"]) else "Custom"
    try:
        result = pipeline.run(submission, files, cfg, case_label=case_label, on_event=on_event)
        st.session_state["last_result"] = result
        st.session_state["last_files"] = files
    except Exception as exc:  # keep the demo standing even if something unexpected happens
        st.error(f"The run stopped: {exc}. Try offline mode in the sidebar, or run again.")

if st.session_state.get("last_result"):
    st.divider()
    st.subheader("Outcome")
    render_result(st.session_state["last_result"], show_files=st.session_state.get("last_files"))
