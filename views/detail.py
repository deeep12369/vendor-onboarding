"""Screen 3 — Vendor detail: one run's evidence, history, audit log, and the reviewer's decision."""
import json

import streamlit as st

from engine import db
from views.common import ist, render_result, status_line

st.title("Vendor detail")

runs = [r for r in db.list_runs() if r["finished_at"]]
if not runs:
    st.info("No runs yet. Run a submission first.", icon=":material/inbox:")
    st.stop()

ids = [r["run_id"] for r in runs]
labels = {r["run_id"]: f"{r['vendor_name']} · {r['final_status']} · {r['run_id']}" for r in runs}
default = st.session_state.get("selected_run")
run_id = st.selectbox("Run", ids, index=ids.index(default) if default in ids else 0, format_func=labels.get)
st.session_state["selected_run"] = run_id
run = db.get_run(run_id)
result = json.loads(run["result_json"])

st.markdown(f"### {run['vendor_name']}")
st.markdown(f"Final status: {status_line(run['final_status'], run['flag'])}"
            + (f" · machine said **{run['machine_status']}**" if run["final_status"] != run["machine_status"] else "")
            + f" · finished {ist(run['finished_at'])} IST")

# History: every run for this vendor, oldest first
history = sorted([r for r in runs if r["vendor_name"] == run["vendor_name"]], key=lambda r: r["started_at"])
if len(history) > 1:
    st.caption("History for this vendor: " + "  →  ".join(
        f"{'**' if r['run_id'] == run_id else ''}{r['run_id']} ({r['final_status']}){'**' if r['run_id'] == run_id else ''}"
        for r in history))

# ---------------------------------------------------------------- reviewer panel
needs_review = run["final_status"] == "Pending"
with st.expander("Reviewer decision", expanded=needs_review and run["flag"] == "Needs human review",
                 icon=":material/gavel:"):
    st.caption("A person can override any machine verdict. The reason is required and both verdicts stay in the "
               "audit log.")
    with st.form(f"review_{run_id}", clear_on_submit=True):
        c1, c2 = st.columns([1, 1])
        decision = c1.radio("Set status to", ["Approved", "Rejected", "Pending"], horizontal=True)
        reviewer = c2.text_input("Reviewer name")
        reason = st.text_area("Reason", placeholder="e.g. Called the vendor; bank letter confirms the account "
                                                    "belongs to the business partner.")
        if st.form_submit_button("Record decision", type="primary"):
            if not reviewer.strip() or not reason.strip():
                st.error("Reviewer name and reason are both required.")
            else:
                db.override(run_id, decision, reviewer.strip(), reason.strip())
                st.success("Recorded in the audit log.")
                st.rerun()

render_result(result)
