# streamlit_app.py
# Laboratory Reagent Inventory System
# Streamlit + Google Sheets (Read: st.connection, Write: Sheets API v4)
# Revised & Hardened — Jan 2026

import streamlit as st
import pandas as pd
from datetime import date
import hashlib
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from streamlit_gsheets import GSheetsConnection

# ─────────────────────────────────────────────────────────────────────────────
# App Config
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")
st.caption("Streamlit + Google Sheets API v4")

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
WORKSHEET = "template"

COLUMNS = [
    "id",
    "name",
    "cas_number",
    "supplier",
    "location",
    "quantity",
    "unit",
    "expiration_date",
    "low_stock_threshold",
]

COL_INDEX = {c: i for i, c in enumerate(COLUMNS)}

# ─────────────────────────────────────────────────────────────────────────────
# Connections
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Initializing Google Sheets...")
def init_sheets():
    read_conn = st.connection("gsheets", type=GSheetsConnection)

    sa_info = st.secrets["google_service_account"]
    creds = Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )

    sheets = build("sheets", "v4", credentials=creds).spreadsheets()
    spreadsheet_id = st.secrets.connections.gsheets.spreadsheet

    return read_conn, sheets, spreadsheet_id


read_conn, sheets_service, SPREADSHEET_ID = init_sheets()

# ─────────────────────────────────────────────────────────────────────────────
# Authentication (Simple / Demo)
# ─────────────────────────────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.update(authenticated=False, username=None, role=None)

if not st.session_state.authenticated:
    st.subheader("🔐 Login Required")

    with st.form("login_form", clear_on_submit=True):
        c1, c2 = st.columns([3, 2])
        username = c1.text_input("Username")
        password = c2.text_input("Password", type="password")

        if st.form_submit_button("Login", type="primary", use_container_width=True):
            hashed = hashlib.sha256(password.encode()).hexdigest()

            users = {
                "admin": ("admin123", "admin"),
                "user": ("user123", "user"),
            }

            if username in users:
                pw, role = users[username]
                if hashed == hashlib.sha256(pw.encode()).hexdigest():
                    st.session_state.update(
                        authenticated=True,
                        username=username,
                        role=role,
                    )
                    st.success(f"Welcome, {username} ({role})")
                    st.rerun()

            st.error("Invalid username or password")

    st.stop()

# Logout
if st.sidebar.button("🚪 Logout", use_container_width=True):
    st.session_state.clear()
    st.rerun()

st.sidebar.success(
    f"Logged in as **{st.session_state.username}** ({st.session_state.role})"
)

# ─────────────────────────────────────────────────────────────────────────────
# Load Inventory
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner="Loading inventory...")
def load_reagents(_conn):
    try:
        df = _conn.read(worksheet=WORKSHEET)

        if df.empty:
            return pd.DataFrame(columns=COLUMNS)

        df = df[[c for c in COLUMNS if c in df.columns]]

        if "expiration_date" in df.columns:
            df["expiration_date"] = pd.to_datetime(
                df["expiration_date"], errors="coerce"
            ).dt.date

        df["quantity"] = pd.to_numeric(
            df.get("quantity", 0), errors="coerce"
        ).fillna(0.0)

        df["low_stock_threshold"] = pd.to_numeric(
            df.get("low_stock_threshold", 10), errors="coerce"
        ).fillna(10.0)

        return df.sort_values("name")

    except Exception as e:
        st.error(f"Load failed: {e}")
        return pd.DataFrame(columns=COLUMNS)


reagents_df = load_reagents(read_conn)

# ─────────────────────────────────────────────────────────────────────────────
# Alerts
# ─────────────────────────────────────────────────────────────────────────────
alerts = []
today = date.today()

for _, r in reagents_df.iterrows():
    if r["quantity"] <= r["low_stock_threshold"]:
        alerts.append(f"⚠️ Low Stock: {r['name']}")

    if pd.notnull(r.get("expiration_date")) and r["expiration_date"] < today:
        alerts.append(f"❌ Expired: {r['name']}")

if alerts:
    st.warning("\n".join(alerts), icon="🚨")

# ─────────────────────────────────────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────────────────────────────────────
tab_cat, tab_add, tab_log, tab_qr, tab_admin = st.tabs(
    ["📋 Catalog", "➕ Add", "📉 Usage", "🔲 QR", "🛠 Admin"]
)

# ── Catalog
with tab_cat:
    st.dataframe(reagents_df, use_container_width=True, hide_index=True)

# ── Add Reagent
with tab_add:
    st.header("Add New Reagent")

    with st.form("add_reagent", clear_on_submit=True):
        name = st.text_input("Name *")
        quantity = st.number_input("Quantity", min_value=0.0, value=100.0)
        unit = st.selectbox("Unit", ["g", "mg", "L", "mL", "pcs"])
        has_exp = st.checkbox("Has expiration date?")
        exp_date = st.date_input(
            "Expiration Date", value=date.today(), disabled=not has_exp
        )
        threshold = st.number_input("Low stock threshold", value=5.0)

        if st.form_submit_button("➕ Add", type="primary"):
            if not name.strip():
                st.error("Name is required")
                st.stop()

            row = [
                "",
                name,
                "",
                "",
                "",
                str(quantity),
                unit,
                exp_date.isoformat() if has_exp else "",
                str(threshold),
            ]

            try:
                sheets_service.values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{WORKSHEET}!A:A",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row]},
                ).execute()

                load_reagents.clear()
                st.success(f"{name} added")
                st.rerun()

            except HttpError as e:
                st.error(f"API error: {e}")

# ── Usage Log
with tab_log:
    if reagents_df.empty:
        st.info("No reagents loaded")
        st.stop()

    reagent = st.selectbox("Reagent", reagents_df["name"])
    row = reagents_df[reagents_df["name"] == reagent].iloc[0]

    used = st.number_input(
        "Amount used", min_value=0.01, max_value=float(row["quantity"])
    )

    if st.button("📉 Update Stock", type="primary"):
        new_qty = row["quantity"] - used
        df_idx = reagents_df.index.get_loc(row.name)
        sheet_row = df_idx + 2

        qty_col_letter = chr(ord("A") + COL_INDEX["quantity"])
        cell = f"{WORKSHEET}!{qty_col_letter}{sheet_row}"

        sheets_service.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=cell,
            valueInputOption="RAW",
            body={"values": [[str(new_qty)]]},
        ).execute()

        load_reagents.clear()
        st.success("Stock updated")
        st.rerun()

# ── QR
with tab_qr:
    st.info("QR scanning & generation coming soon")

# ── Admin
with tab_admin:
    if st.session_state.role != "admin":
        st.error("Admin only")
    else:
        st.metric("Total reagents", len(reagents_df))
        st.metric("Alerts", len(alerts))

st.caption("Laboratory Reagent Inventory • Jan 2026")
