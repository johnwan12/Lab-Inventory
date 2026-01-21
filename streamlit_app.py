# streamlit_app.py - Laboratory Reagent Inventory System (Google Sheets version)
# Updated January 2026 - with explicit credentials workaround + better debugging

import streamlit as st
import pandas as pd
from datetime import date, datetime
import hashlib
from PIL import Image
import os
from pathlib import Path

try:
    import pytesseract
except ImportError:
    pytesseract = None

from streamlit_gsheets import GSheetsConnection
from google.oauth2 import service_account

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System (Google Sheets)")

# ── Connection with explicit credentials (temporary for debugging) ──────────
def get_gsheet_conn():
    try:
        # === PASTE YOUR REAL SERVICE ACCOUNT VALUES HERE ===
        creds_dict = {
            "type": "service_account",
            "project_id": "YOUR_PROJECT_ID_HERE",
            "private_key_id": "YOUR_PRIVATE_KEY_ID_HERE",
            "private_key": """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC...
# Paste the FULL private key exactly as it appears in your JSON file
# Keep all line breaks and = padding characters
-----END PRIVATE KEY-----""",
            "client_email": "YOUR_SERVICE_ACCOUNT@project.iam.gserviceaccount.com",
            "client_id": "YOUR_CLIENT_ID_HERE",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/YOUR_SERVICE_ACCOUNT%40project.iam.gserviceaccount.com",
            "universe_domain": "googleapis.com"
        }

        creds = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        )

        conn = st.connection(
            "lab_gsheets_debug",
            type=GSheetsConnection,
            credentials=creds,
            spreadsheet="https://docs.google.com/spreadsheets/d/1xorAPoWd81bUE2yeJN4QsEhpEoUZ5yvdGIm2h9MHbkQ/edit",
            worksheet="template"
        )

        st.success("Google Sheets connection created successfully (debug mode)")
        return conn

    except Exception as e:
        st.error(f"Failed to create Google Sheets connection: {str(e)}")
        st.stop()


# ── Authentication (hardcoded for now) ──────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.role = None

if not st.session_state.authenticated:
    st.subheader("🔐 Login Required")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        if submitted:
            hashed = hashlib.sha256(password.encode()).hexdigest()
            if username == "admin" and hashed == hashlib.sha256("admin123".encode()).hexdigest():
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.role = "admin"
            elif username == "user" and hashed == hashlib.sha256("user123".encode()).hexdigest():
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.role = "user"
            
            if st.session_state.authenticated:
                st.success(f"Welcome, {username}! ({st.session_state.role.capitalize()})")
                st.rerun()
            else:
                st.error("Invalid username or password")
    st.stop()

if st.sidebar.button("🚪 Logout"):
    for key in ["authenticated", "username", "role"]:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})")


# ── Load Reagents ───────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_reagents():
    conn = get_gsheet_conn()
    try:
        df = conn.read(
            usecols=[
                "id", "name", "cas_number", "supplier", "location",
                "quantity", "unit", "expiration_date", "low_stock_threshold"
            ],
            dtype={
                "id": "Int64",
                "quantity": float,
                "low_stock_threshold": float
            }
        )
        if not df.empty:
            df['expiration_date'] = pd.to_datetime(df['expiration_date'], errors='coerce').dt.date
            df = df.sort_values("name")
        if "low_stock_threshold" not in df.columns:
            df["low_stock_threshold"] = 1.0
        st.info(f"Loaded {len(df)} reagents from sheet.")
        return df
    except Exception as e:
        st.error(f"Could not load data from Google Sheet: {str(e)}")
        return pd.DataFrame(columns=[
            'id','name','cas_number','supplier','location',
            'quantity','unit','expiration_date','low_stock_threshold'
        ])


reagents_df = load_reagents()


# ── Alerts ──────────────────────────────────────────────────────────────────
alerts = []
today = date.today()
for _, row in reagents_df.iterrows():
    threshold = row.get('low_stock_threshold', 1.0)
    if pd.notna(row.get('quantity')) and row['quantity'] <= threshold:
        alerts.append(f"⚠️ **Low Stock**: {row['name']} — {row['quantity']:.2f} {row['unit']} (threshold: {threshold})")
    if pd.notnull(row.get('expiration_date')) and row['expiration_date'] < today:
        alerts.append(f"❌ **Expired**: {row['name']} ({row['expiration_date']})")

if alerts:
    st.warning("\n\n".join(alerts))


# ── Tabs ────────────────────────────────────────────────────────────────────
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Catalog"

tab_names = ["Catalog", "Add Reagent", "Log Usage", "QR Tools", "Admin"]
tab1, tab2, tab3, tab4, tab5 = st.tabs(tab_names)


# ── Catalog ────────────────────────────────────────────────────────────────
with tab1:
    st.header("Reagent Catalog")
    search = st.text_input("🔍 Search by Name, CAS, or Location")

    display_df = reagents_df
    if search:
        display_df = reagents_df[
            reagents_df['name'].str.contains(search, case=False, na=False) |
            reagents_df['cas_number'].str.contains(search, case=False, na=False) |
            reagents_df['location'].str.contains(search, case=False, na=False)
        ]

    if display_df.empty:
        st.info("No reagents found.")
    else:
        if st.session_state.role == "admin":
            editable_df = display_df.copy()
            editable_df["Delete"] = False
            editable_df["Edit"] = False

            edited_df = st.data_editor(
                editable_df,
                column_config={
                    "Edit": st.column_config.CheckboxColumn("Edit", default=False),
                    "Delete": st.column_config.CheckboxColumn("Delete", default=False),
                    "id": "ID",
                    "name": "Name",
                    "cas_number": "CAS Number",
                    "supplier": "Supplier",
                    "location": "Location",
                    "quantity": st.column_config.NumberColumn("Quantity", format="%.2f"),
                    "unit": "Unit",
                    "expiration_date": "Expiration Date",
                    "low_stock_threshold": st.column_config.NumberColumn("Low Stock Threshold", format="%.1f"),
                },
                hide_index=True,
                use_container_width=True,
                key="catalog_editor"
            )

            # Edit logic (simplified version - same as before)
            to_edit = edited_df[edited_df["Edit"] == True]["id"].dropna().astype(int).tolist()
            if to_edit:
                edit_id = to_edit[0]
                reagent = reagents_df[reagents_df['id'] == edit_id].iloc[0]

                with st.expander(f"✏️ Edit: {reagent['name']} (ID: {edit_id})", expanded=True):
                    # ... (keep your existing edit form code) ...
                    # Update logic remains the same
                    pass  # ← replace with your full edit/save code

            # Delete logic (same as before)
            to_delete = edited_df[edited_df["Delete"] == True]["id"].dropna().astype(int).tolist()
            if to_delete:
                # ... (keep your delete code) ...
                pass

        else:
            st.dataframe(display_df.style.format({"quantity": "{:.2f}"}), use_container_width=True)
            st.info("Only admin users can edit or delete reagents.")


# ── Add Reagent, Log Usage, etc. ───────────────────────────────────────────
# (keep the rest of your code unchanged - Add Reagent, Log Usage, OCR, tabs 4 & 5)

# Example placeholder for remaining tabs
with tab2:
    st.header("Add Reagent")
    st.info("Add form & bulk upload code here (same as previous version)")

with tab3:
    st.header("Log Usage")
    st.info("Log usage code here")

with tab4:
    st.header("QR Tools")
    st.info("Coming soon...")

with tab5:
    if st.session_state.role != "admin":
        st.error("Admin access only")
    else:
        st.header("Admin Dashboard")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Reagents", len(reagents_df))
        col2.metric("Low Stock", sum(1 for a in alerts if "Low" in a))
        col3.metric("Expired", sum(1 for a in alerts if "Expired" in a))

st.caption("Laboratory Reagent Inventory • Streamlit + Google Sheets • January 2026")
