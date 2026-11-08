"""Screen 4 — How it works: the design in one page, for the reviewer or interviewer."""
import pandas as pd
import streamlit as st

from engine.pipeline import STAGES
from views.common import load_cases

st.title("How it works")
st.markdown("**Rules decide, AI assists.** Gemini turns messy documents into clean facts, each with a confidence. "
            "Plain Python rules turn facts into decisions, so the same input always gives the same verdict, "
            "with a written reason.")

st.subheader("The eight stages")
st.dataframe(pd.DataFrame([{"#": i, "Stage": name, "What happens": desc,
                            "Uses AI": "Yes" if key in ("tagging",) else ("Name matching only" if key == "triangulation" else "")}
                           for i, (key, name, desc) in enumerate(STAGES, 1)]),
             hide_index=True, width="stretch")

st.subheader("How the status is decided")
st.dataframe(pd.DataFrame([
    {"Worst failed rule": "BLOCK", "Status": "Rejected", "Meaning": "Fraud or eligibility signal; vendor gets a neutral note"},
    {"Worst failed rule": "REVIEW", "Status": "Pending", "Meaning": "A person decides; vendor told it is under review"},
    {"Worst failed rule": "FIX", "Status": "Pending", "Meaning": "Vendor gets an exact list of what to correct"},
    {"Worst failed rule": "INFO or none", "Status": "Approved", "Meaning": "Vendor code and welcome note"},
]), hide_index=True, width="stretch")

st.subheader("Triangulation")
st.markdown("Each key fact is checked across every source that carries it. The **GST registry** and the **bank "
            "(penny-drop)** are the anchors: a vendor can edit a PDF to match the form, but cannot change what "
            "the registry or the bank returns.")

st.subheader("Demo cases")
st.dataframe(pd.DataFrame([{"Case": c["title"], "What it tests": c["story"], "Expected": c["expected"]}
                           for c in load_cases()]), hide_index=True, width="stretch")

st.subheader("Assumptions")
st.markdown(
    "- Indian, GST-registered vendors; required documents are PAN card, GST certificate, cancelled cheque.\n"
    "- The GST registry, penny-drop and vendor master are **simulated** with mock data; each sits behind a "
    "function with the same inputs and outputs as a real API.\n"
    "- All documents are fictional and marked SPECIMEN.\n"
    "- Offline mode replays stored sample answers for the demo files, as a safety net when the AI is unavailable.")
