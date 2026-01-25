# streamlit_app.py - Laboratory Reagent Inventory System
# Using Google Sheets API v4 for writes + st.connection for reads
# Revised: January 2026

import streamlit as st
import pandas as pd
from datetime import date
import hashlib
import time
from streamlit_gsheets import GSheetsConnection
from google.oauth2.service_account import Credentials
#from googleapiclient.discovery import build
#from googleapiclient.errors import HttpError

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")
st.caption("Streamlit + Google Sheets API v4 • Read via st.connection • Write via API")

# ── Connections ─────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Initializing connections...")
def init_sheets():
    # Read connection
    read_conn = st.connection("gsheets", type=GSheetsConnection)
    
    # Write connection (Sheets API v4)
    sa_info = st.secrets["google_service_account"]
    creds = Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    sheets_service = build('sheets', 'v4', credentials=creds).spreadsheets()
    
    spreadsheet_id = st.secrets.connections.gsheets.spreadsheet
    
    return read_conn, sheets_service, spreadsheet_id

#read_conn, sheets_service, SPREADSHEET_ID = init_sheets()

WORKSHEET = "template"
READ_RANGE = f"{WORKSHEET}!A:I"   # adjust columns as needed (A to I = 9 columns)

# ── Simple Authentication ───────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.role = None

if not st.session_state.authenticated:
    st.subheader("🔐 Login Required")
    with st.form("login_form", clear_on_submit=True):
        col1, col2 = st.columns([3, 2])
        with col1:
            username = st.text_input("Username")
        with col2:
            password = st.text_input("Password", type="password")

        if st.form_submit_button("Login", type="primary", use_container_width=True):
            hashed = hashlib.sha256(password.encode()).hexdigest()
            if username == "admin" and hashed == hashlib.sha256("admin123".encode()).hexdigest():
                st.session_state.update(authenticated=True, username=username, role="admin")
            elif username == "user" and hashed == hashlib.sha256("user123".encode()).hexdigest():
                st.session_state.update(authenticated=True, username=username, role="user")

            if st.session_state.authenticated:
                st.success(f"Welcome, {username}! ({st.session_state.role.capitalize()})")
                st.rerun()
            else:
                st.error("Invalid username or password")
    st.stop()

if st.sidebar.button("🚪 Logout", use_container_width=True):
    for key in ["authenticated", "username", "role"]:
        st.session_state.pop(key, None)
    st.rerun()

st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})", icon="👤")

# ── Load Data ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner="Loading inventory...")  # 5 minutes
def load_reagents(_conn):
    try:
        df = _conn.read(worksheet=WORKSHEET)
        
        # Select relevant columns if they exist
        cols = [
            "id", "name", "cas_number", "supplier", "location",
            "quantity", "unit", "expiration_date", "low_stock_threshold"
        ]
        avail = [c for c in cols if c in df.columns]
        if avail:
            df = df[avail]
        
        if not df.empty:
            if "expiration_date" in df.columns:
                df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce").dt.date
            df = df.sort_values("name")
        
        df["quantity"] = pd.to_numeric(df.get("quantity", 0), errors="coerce").fillna(0.0)
        df["low_stock_threshold"] = pd.to_numeric(df.get("low_stock_threshold", 10.0), errors="coerce").fillna(10.0)
        
        return df
    except Exception as e:
        st.error(f"Could not load data: {str(e)}")
        return pd.DataFrame()

#reagents_df = load_reagents(read_conn)

# ── Alerts ──────────────────────────────────────────────────────────────────
alerts = []
today = date.today()
#for _, row in reagents_df.iterrows():
    qty = row.get("quantity", 0)
    thresh = row.get("low_stock_threshold", 10.0)
    if qty <= thresh:
        alerts.append(f"⚠️ **Low Stock**: {row.get('name','?')} — {qty:.2f} {row.get('unit','?')}")
    exp = row.get("expiration_date")
    if pd.notnull(exp) and exp < today:
        alerts.append(f"❌ **Expired**: {row.get('name','?')} ({exp})")

if alerts:
    st.warning("\n".join(alerts), icon="🚨")

# ── Tabs ────────────────────────────────────────────────────────────────────
tab_catalog, tab_add, tab_log, tab_qr, tab_admin = st.tabs([
    "📋 Catalog", "➕ Add Reagent", "📉 Log Usage", "🔲 QR Tools", "🛠 Admin"
])

with tab_catalog:
    st.header("Reagent Catalog")
    search = st.text_input("Search", "")
    df_view = reagents_df
    if search:
        mask = df_view.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)
        df_view = df_view[mask]
    if df_view.empty:
        st.info("No matching reagents.")
    else:
        st.dataframe(df_view.style.format(precision=2), use_container_width=True, hide_index=True)

with tab_add:
    st.header("Add New Reagent")
    
    with st.form("add_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Name *")
            cas_number = st.text_input("CAS Number")
            supplier = st.text_input("Supplier")
            location = st.text_input("Location")
        with col2:
            quantity = st.number_input("Initial Quantity *", min_value=0.0, value=100.0, step=0.1)
            unit = st.selectbox("Unit", ["g", "mg", "L", "mL", "kg", "pcs", "bottles"])
            exp_date = st.date_input("Expiration Date", value=None)
            threshold = st.number_input("Low Stock Threshold", min_value=0.0, value=5.0, step=1.0)

        if st.form_submit_button("➕ Add Reagent", type="primary", use_container_width=True):
            if not name.strip():
                st.error("Reagent name is required.")
            else:
                try:
                    new_row = [
                        "",                             # id (optional – can use formula)
                        name.strip(),
                        cas_number.strip() or "",
                        supplier.strip() or "",
                        location.strip() or "",
                        str(quantity),
                        unit,
                        exp_date.strftime("%Y-%m-%d") if exp_date else "",
                        str(threshold)
                    ]
                    
                    body = {"values": [new_row]}
                    
                    sheets_service.values().append(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f"{WORKSHEET}!A:A",
                        valueInputOption="RAW",
                        insertDataOption="INSERT_ROWS",
                        body=body
                    ).execute()
                    
                    st.success(f"**{name}** added successfully")
                    load_reagents.clear()
                    st.rerun()
                except HttpError as he:
                    st.error(f"API error: {he}")
                except Exception as e:
                    st.error(f"Failed to add reagent: {str(e)}")

with tab_log:
    st.header("Log Usage")
    if reagents_df.empty:
        st.info("No reagents loaded yet.")
    else:
        selected = st.selectbox("Select Reagent", options=[""] + reagents_df["name"].tolist())
        if selected:
            row = reagents_df[reagents_df["name"] == selected].iloc[0]
            curr_qty = float(row.get("quantity", 0))
            unit = row.get("unit", "?")
            st.metric("Current stock", f"{curr_qty:.2f} {unit}")

            with st.form("log_form"):
                used_qty = st.number_input("Amount used", min_value=0.01, max_value=curr_qty, step=0.1, format="%.2f")
                submit = st.form_submit_button("📉 Update Stock", type="primary")

                if submit and used_qty > 0:
                    new_qty = curr_qty - used_qty
                    try:
                        # Find row index (0-based in df → +2 for sheet: header + 1-based)
                        df_idx = reagents_df[reagents_df["name"] == selected].index[0]
                        sheet_row = df_idx + 2

                        # Quantity column – IMPORTANT: adjust this letter!
                        qty_column_letter = "F"   # ← Change to correct column (A=id, B=name, C=cas, D=supplier, E=location, F=quantity)

                        range_name = f"{WORKSHEET}!{qty_column_letter}{sheet_row}"

                        body = {"values": [[str(new_qty)]]}

                        sheets_service.values().update(
                            spreadsheetId=SPREADSHEET_ID,
                            range=range_name,
                            valueInputOption="RAW",
                            body=body
                        ).execute()

                        st.success(f"Stock updated → **{new_qty:.2f} {unit}** remaining")
                        load_reagents.clear()
                        st.rerun()
                    except HttpError as he:
                        st.error(f"API error during update: {he}")
                    except Exception as e:
                        st.error(f"Update failed: {str(e)}")

with tab_qr:
    st.header("QR Tools")
    st.info("QR generation & scanning – coming soon")

with tab_admin:
    if st.session_state.role != "admin":
        st.error("Admin access only", icon="🔒")
    else:
        st.header("Admin Dashboard")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Reagents", len(reagents_df))
        col2.metric("Low Stock", sum(1 for a in alerts if "Low Stock" in a))
        col3.metric("Expired", sum(1 for a in alerts if "Expired" in a))

st.caption("Laboratory Reagent Inventory • January 2026")





