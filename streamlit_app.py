# streamlit_app.py
# Laboratory Reagent Inventory System (Google Sheets version)
# Revised January 2026 — Fully Streamlit Cloud ready

import streamlit as st
import pandas as pd
from datetime import date
import hashlib
import gspread
from google.oauth2.service_account import Credentials

# ── Page Config
st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")
st.caption("Powered by Streamlit + Google Sheets • Secure service account connection")

# ── Google Sheets Connection (robust to escaped \n in private_key)
@st.cache_resource
def get_gsheet_conn():
    try:
        service_account_info = st.secrets["gcp_service_account"].copy()

        # Fix escaped line breaks in private_key
        if "private_key" in service_account_info:
            service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]

        creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
        client = gspread.authorize(creds)

        # Open spreadsheet URL from secrets
        sheet = client.open_by_url(st.secrets["spreadsheet_url"])
        worksheet = sheet.worksheet("template")
        return worksheet

    except Exception as e:
        st.error("🚨 Failed to connect to Google Sheets")
        st.exception(e)
        st.stop()

# ── Load Reagents safely
@st.cache_data(ttl=600)
def load_reagents(ws):
    try:
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty and "expiration_date" in df.columns:
            df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce").dt.date
        if "low_stock_threshold" not in df.columns:
            df["low_stock_threshold"] = 1.0
        return df
    except Exception as e:
        st.error("Failed to load reagent data")
        st.exception(e)
        return pd.DataFrame(columns=[
            "id", "name", "cas_number", "supplier", "location",
            "quantity", "unit", "expiration_date", "low_stock_threshold"
        ])

# ── Session-based Authentication
if "authenticated" not in st.session_state:
    st.session_state.update(authenticated=False, username=None, role=None)

if not st.session_state.authenticated:
    st.subheader("🔐 Login Required")
    with st.form("login_form", clear_on_submit=True):
        col1, col2 = st.columns([3, 2])
        with col1:
            username = st.text_input("Username")
        with col2:
            password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True, type="primary")

        if submitted:
            hashed = hashlib.sha256(password.encode()).hexdigest()
            if username == "admin" and hashed == hashlib.sha256("admin123".encode()).hexdigest():
                st.session_state.update(authenticated=True, username=username, role="admin")
            elif username == "user" and hashed == hashlib.sha256("user123".encode()).hexdigest():
                st.session_state.update(authenticated=True, username=username, role="user")

            if st.session_state.authenticated:
                st.success(f"Welcome back, {username} ({st.session_state.role})")
                st.rerun()
            else:
                st.error("Invalid credentials")
    st.stop()

# ── Sidebar Logout
if st.sidebar.button("🚪 Logout", use_container_width=True):
    for key in ("authenticated", "username", "role"):
        st.session_state.pop(key, None)
    st.rerun()

st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})", icon="👤")

# ── Load Reagents DataFrame
worksheet = get_gsheet_conn()
reagents_df = load_reagents(worksheet)

# ── Alerts: Low Stock / Expired
alerts = []
today = date.today()

if not reagents_df.empty:
    for _, row in reagents_df.iterrows():
        qty = row.get("quantity")
        threshold = row.get("low_stock_threshold", 1.0)
        if pd.notna(qty) and qty <= threshold:
            alerts.append(f"⚠️ **Low stock**: {row['name']} → {qty:.2f} {row.get('unit', '')} (threshold: {threshold})")
        exp = row.get("expiration_date")
        if pd.notnull(exp) and exp < today:
            alerts.append(f"❌ **Expired**: {row['name']} ({exp})")

if alerts:
    st.warning("\n".join(alerts), icon="🚨")

# ── Tabs
tab_catalog, tab_add, tab_log, tab_qr, tab_admin = st.tabs(
    ["📋 Catalog", "➕ Add Reagent", "📉 Log Usage", "🔲 QR Tools", "🛠 Admin"]
)

# ── Catalog Tab
with tab_catalog:
    st.header("Reagent Catalog")
    search_term = st.text_input("Search by name, CAS, supplier or location")

    df_view = reagents_df.copy()
    if search_term and not df_view.empty:
        mask = (
            df_view["name"].str.contains(search_term, case=False, na=False) |
            df_view.get("cas_number", "").str.contains(search_term, case=False, na=False) |
            df_view.get("supplier", "").str.contains(search_term, case=False, na=False) |
            df_view.get("location", "").str.contains(search_term, case=False, na=False)
        )
        df_view = df_view[mask]

    if df_view.empty:
        st.info("No matching reagents found.")
    else:
        st.dataframe(df_view.style.format({"quantity": "{:.2f}"}), use_container_width=True, hide_index=True)
        if st.session_state.role == "admin":
            st.info("Admin editing (upsert/update) coming next")

# ── Add Reagent Tab (placeholder)
with tab_add:
    st.header("Add New Reagent")
    st.info("Form + worksheet.append_row() coming soon")

# ── Log Usage Tab (placeholder)
with tab_log:
    st.header("Log Reagent Usage")
    st.info("Quantity deduction + audit log coming soon")

# ── QR Tools Tab (placeholder)
with tab_qr:
    st.header("QR Code Tools")
    st.info("QR generate / scan coming soon")

# ── Admin Tab
with tab_admin:
    if st.session_state.role != "admin":
        st.error("Admin access only", icon="🔒")
    else:
        st.header("Admin Overview")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Reagents", len(reagents_df))
        col2.metric("Low Stock Items", sum("Low stock" in a for a in alerts))
        col3.metric("Expired Items", sum("Expired" in a for a in alerts))
        st.markdown("---")
        st.caption("Next steps: implement CRUD with worksheet.update() / append_row()")

st.caption("Laboratory Reagent Inventory • Streamlit + Google Sheets • 2026")
