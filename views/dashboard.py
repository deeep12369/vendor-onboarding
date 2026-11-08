"""Screen 2 — Dashboard: every run, its status and why."""
import pandas as pd
import streamlit as st

from engine import db, pipeline
from views.common import ai_config, ist, load_cases

st.title("Dashboard")
st.caption("Every submission the process has handled. Select a row to open its evidence and audit trail.")

runs = [r for r in db.list_runs() if r["finished_at"]]

# ---------------------------------------------------------------- counts
pending_vendor = sum(1 for r in runs if r["final_status"] == "Pending" and r["flag"] == "Awaiting vendor")
pending_review = sum(1 for r in runs if r["final_status"] == "Pending" and r["flag"] == "Needs human review")
m = st.columns(5)
m[0].metric("Submissions", len(runs))
m[1].metric("Approved", sum(1 for r in runs if r["final_status"] == "Approved"))
m[2].metric("Waiting on vendor", pending_vendor)
m[3].metric("Needs human review", pending_review)
m[4].metric("Rejected", sum(1 for r in runs if r["final_status"] == "Rejected"))

# ---------------------------------------------------------------- actions
a1, a2, _ = st.columns([1.3, 1, 3])
if a1.button("Run all demo cases", icon=":material/playlist_play:", type="primary"):
    cfg = ai_config()
    cases = load_cases()
    bar = st.progress(0.0, text="Starting…")
    for i, case in enumerate(cases):
        bar.progress(i / len(cases), text=f"Running {case['title']}…")
        try:
            pipeline.run(case["form"], case["files"], cfg, case_label=case["key"])
        except Exception as exc:
            st.error(f"{case['title']}: {exc}")
    bar.progress(1.0, text="Done")
    st.rerun()
with a2.popover("Reset history", icon=":material/delete_sweep:"):
    st.write("Delete all runs from the dashboard? Saved AI answers are kept.")
    if st.button("Yes, reset", type="primary"):
        db.clear_runs()
        st.session_state.pop("last_result", None)
        st.rerun()

if not runs:
    st.info("No runs yet. Use **Run all demo cases** above, or submit one on the New submission screen.",
            icon=":material/inbox:")
    st.stop()

# ---------------------------------------------------------------- table
status_filter = st.segmented_control("Show", ["All", "Approved", "Pending", "Rejected"], default="All")
shown = [r for r in runs if status_filter in (None, "All") or r["final_status"] == status_filter]
df = pd.DataFrame([{
    "Run": r["run_id"], "Vendor": r["vendor_name"], "Case": r["case_label"],
    "Status": r["final_status"] + (" (overridden)" if r["final_status"] != r["machine_status"] else ""),
    "Flag": r["flag"] or "", "Top reason": r["top_reason"], "AI": r["ai_mode"],
    "Finished (IST)": ist(r["finished_at"]),
} for r in shown])


def colour_status(col):
    c = {"Approved": "#e6f4ea", "Pending": "#fdf0e1", "Rejected": "#fce8e8"}
    return [f"background-color: {c.get(v.split(' ')[0], '')}" for v in col]


event = st.dataframe(df.style.apply(colour_status, subset=["Status"]), hide_index=True, width="stretch",
                     on_select="rerun", selection_mode="single-row", key="runs_table",
                     column_config={"Top reason": st.column_config.TextColumn(width="large")})
rows = event.selection.rows if event and event.selection else []
if rows:
    st.session_state["selected_run"] = df.iloc[rows[0]]["Run"]
    st.switch_page("views/detail.py")
