# streamlit_app.py - Laboratory Reagent Inventory System
# Revised: January 2026

import streamlit as st
import pandas as pd
from datetime import date
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")

# ────────────────────────────────────────────────
# Google Sheets Connection
# ────────────────────────────────────────────────
@st.cache_resource(show_spinner="Connecting to Google Sheets...")
def get_sheets_service():
    try:
        # Load service account from Streamlit secrets
        creds_info = st.secrets["gcp_service_account"]
        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        service = build("sheets", "v4", credentials=creds)
        SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]
        return service, SPREADSHEET_ID
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets: {e}")
        return None, None

sheets_service, SPREADSHEET_ID = get_sheets_service()
if sheets_service is None:
    st.stop()  # Stop app if connection fails

# Optional: GSheetsConnection wrapper for reads
@st.cache_resource(show_spinner="Connecting to GSheets wrapper...")
def get_gsheet_conn():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        # Minimal test read
        test_df = conn.read(nrows=1)
        st.success("Connection to Google Sheets successful!")
        return conn
    except Exception as e:
        st.error(f"GSheetsConnection failed: {e}")
        return None

conn = get_gsheet_conn()
if conn is None:
    st.stop()

# ────────────────────────────────────────────────
# Utility functions
# ────────────────────────────────────────────────

def load_reagents():
    try:
        df = conn.read()
        return df
    except Exception as e:
        st.error(f"Failed to read data: {e}")
        return pd.DataFrame()

def add_reagent(new_data: dict):
    try:
        df = pd.DataFrame([new_data])
        conn.write(df, append=True)
        st.success(f"Reagent '{new_data.get('Name', '')}' added successfully!")
    except Exception as e:
        st.error(f"Failed to add reagent: {e}")

# ────────────────────────────────────────────────
# Streamlit UI
# ────────────────────────────────────────────────

st.title("🧪 Laboratory Reagent Inventory")

tab1, tab2 = st.tabs(["Inventory", "Add Reagent"])

with tab1:
    st.subheader("Current Inventory")
    df = load_reagents()
    if not df.empty:
        st.data_editor(df, use_container_width=True)
    else:
        st.info("No data available.")

with tab2:
    st.subheader("Add New Reagent")
    with st.form("add_reagent_form"):
        name = st.text_input("Reagent Name")
        quantity = st.number_input("Quantity", min_value=0, step=1)
        location = st.text_input("Storage Location")
        expiry = st.date_input("Expiry Date", value=date.today())
        submit = st.form_submit_button("Add Reagent")
        if submit:
            if not name or not location:
                st.warning("Please fill all required fields.")
            else:
                add_reagent({
                    "Name": name,
                    "Quantity": quantity,
                    "Location": location,
                    "Expiry": expiry.strftime("%Y-%m-%d")
                })
