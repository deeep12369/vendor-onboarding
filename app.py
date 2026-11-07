"""
app.py — the front door.

Start the app with:   streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="Vendor Onboarding", page_icon=":material/verified_user:", layout="wide")

from views.common import sidebar  # noqa: E402  (after set_page_config)

pages = [
    st.Page("views/submit.py", title="New submission", icon=":material/add_task:", default=True),
    st.Page("views/dashboard.py", title="Dashboard", icon=":material/dashboard:"),
    st.Page("views/detail.py", title="Vendor detail", icon=":material/manage_search:"),
    st.Page("views/how_it_works.py", title="How it works", icon=":material/schema:"),
]
nav = st.navigation(pages)
with st.sidebar:
    st.markdown("### :material/verified_user: Vendor Onboarding")
    st.caption("Tag · check completeness · triangulate · decide")
sidebar()
nav.run()
