# streamlit_app.py - Laboratory Reagent Inventory System
# Full CRUD using Google Sheets API v4 (no st-gsheets-connection)
# Revised: January 2026

import streamlit as st
creds = st.secrets["service_account"]
import pandas as pd
from datetime import date
import hashlib
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")
st.caption("Streamlit + Google Sheets API v4 • Full CRUD operations")

# ── Initialize Google Sheets API client ─────────────────────────────────────
@st.cache_resource(show_spinner="Connecting to Google Sheets...")
def get_sheets_service():
    try:
        sa_info = st.secrets["google_service_account"]
        creds = Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        service = build('sheets', 'v4', credentials=creds).spreadsheets()
        spreadsheet_id = st.secrets.connections.gsheets.spreadsheet
        return service, spreadsheet_id
    except KeyError as e:
        st.error(f"Missing secrets key: {e}\n\nPlease check Streamlit Cloud Secrets.")
        st.stop()
    except Exception as e:
        st.error(f"Failed to initialize Sheets service: {str(e)}")
        st.stop()

sheets_service, SPREADSHEET_ID = get_sheets_service()

WORKSHEET = "template"                # ← your sheet tab name
READ_RANGE = f"{WORKSHEET}!A1:I1000"  # ← adjust if you have more columns/rows

# ── Authentication ──────────────────────────────────────────────────────────
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
@st.cache_data(ttl=300, show_spinner="Loading inventory...")
def load_reagents():
    try:
        result = sheets_service.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=READ_RANGE
        ).execute()
        
        values = result.get('values', [])
        if not values:
            return pd.DataFrame()
        
        headers = values[0]
        data = values[1:]
        df = pd.DataFrame(data, columns=headers)
        
        expected = [
            "id", "name", "cas_number", "supplier", "location",
            "quantity", "unit", "expiration_date", "low_stock_threshold"
        ]
        df = df[[c for c in expected if c in df.columns]]
        
        if "expiration_date" in df.columns:
            df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce").dt.date
        
        df["quantity"] = pd.to_numeric(df.get("quantity", 0), errors="coerce").fillna(0.0)
        df["low_stock_threshold"] = pd.to_numeric(df.get("low_stock_threshold", 10.0), errors="coerce").fillna(10.0)
        
        return df.sort_values("name")
    
    except Exception as e:
        st.error(f"Failed to load data: {str(e)}\n\nCheck: sheet ID, tab name, service account permissions")
        return pd.DataFrame()

reagents_df = load_reagents()

# ── Alerts ──────────────────────────────────────────────────────────────────
alerts = []
today = date.today()
for _, row in reagents_df.iterrows():
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
    "📋 Catalog", "➕ Add", "📉 Log Usage", "🔲 QR", "🛠 Admin"
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
            low_stock_threshold = st.number_input("Low Stock Threshold", min_value=0.0, value=10.0, step=1.0)

        submitted = st.form_submit_button("➕ Add", type="primary", use_container_width=True)

        if submitted:
            if not name.strip():
                st.error("Reagent name is required.")
            else:
                row = [
                    "", name.strip(), cas_number.strip() or "", supplier.strip() or "",
                    location.strip() or "", str(quantity), unit,
                    exp_date.strftime("%Y-%m-%d") if exp_date else "",
                    str(low_stock_threshold)
                ]
                body = {"values": [row]}
                try:
                    sheets_service.values().append(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f"{WORKSHEET}!A:A",
                        valueInputOption="RAW",
                        insertDataOption="INSERT_ROWS",
                        body=body
                    ).execute()
                    st.success(f"Added **{name}**")
                    load_reagents.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Add failed: {str(e)}")

with tab_log:
    st.header("Log Usage")
    if reagents_df.empty:
        st.info("No reagents loaded yet.")
    else:
        selected_name = st.selectbox("Select Reagent", options=[""] + reagents_df["name"].tolist())
        if selected_name:
            row = reagents_df[reagents_df["name"] == selected_name].iloc[0]
            curr_qty = float(row.get("quantity", 0))
            unit = row.get("unit", "?")
            st.metric("Current Stock", f"{curr_qty:.2f} {unit}")

            with st.form("log_form"):
                used_qty = st.number_input("Amount used", min_value=0.01, max_value=curr_qty, step=0.1, format="%.2f")
                submitted = st.form_submit_button("📉 Update", type="primary")

                if submitted:
                    new_qty = curr_qty - used_qty
                    df_idx = reagents_df[reagents_df["name"] == selected_name].index[0]
                    sheet_row = df_idx + 2
                    
                    # ← IMPORTANT: change this to match your sheet structure
                    # A=1=id, B=2=name, C=3=cas_number, D=4=supplier, E=5=location, F=6=quantity
                    qty_col_letter = "F"
                    
                    range_name = f"{WORKSHEET}!{qty_col_letter}{sheet_row}"
                    body = {"values": [[str(new_qty)]]}
                    
                    try:
                        sheets_service.values().update(
                            spreadsheetId=SPREADSHEET_ID,
                            range=range_name,
                            valueInputOption="RAW",
                            body=body
                        ).execute()
                        st.success(f"Updated to **{new_qty:.2f} {unit}**")
                        load_reagents.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Update failed: {str(e)}")

with tab_qr:
    st.header("QR Tools")
    st.info("Coming soon...")

with tab_admin:
    if st.session_state.role != "admin":
        st.error("Admin access only", icon="🔒")
    else:
        st.header("Admin Dashboard")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Reagents", len(reagents_df))
        col2.metric("Low Stock", sum(1 for a in alerts if "Low Stock" in a))
        col3.metric("Expired", sum(1 for a in alerts if "Expired" in a))

        # Bulk edit
        st.subheader("Bulk Edit")
        edited_df = st.data_editor(
            reagents_df,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=False
        )

        if st.button("💾 Save Changes", type="primary"):
            if edited_df.equals(reagents_df):
                st.info("No changes detected.")
            else:
                for idx, row in edited_df.iterrows():
                    original = reagents_df.iloc[idx]
                    if not row.equals(original):
                        sheet_row = idx + 2
                        for col_name, new_val in row.items():
                            if pd.notna(new_val) and new_val != original[col_name]:
                                col_idx = edited_df.columns.get_loc(col_name)
                                col_letter = chr(65 + col_idx)
                                range_name = f"{WORKSHEET}!{col_letter}{sheet_row}"
                                body = {"values": [[str(new_val)]]}
                                try:
                                    sheets_service.values().update(
                                        spreadsheetId=SPREADSHEET_ID,
                                        range=range_name,
                                        valueInputOption="RAW",
                                        body=body
                                    ).execute()
                                except Exception as e:
                                    st.error(f"Update {col_name} failed: {e}")
                st.success("Changes saved")
                load_reagents.clear()
                st.rerun()

        # Delete
        st.subheader("Delete Reagents")
        to_delete = st.multiselect("Select reagents to delete", options=reagents_df["name"].tolist())
        if st.button("🗑️ Delete Selected"):
            if not to_delete:
                st.info("No selection.")
            else:
                for name in to_delete:
                    idx = reagents_df[reagents_df["name"] == name].index[0]
                    sheet_row = idx + 2
                    try:
                        sheets_service.batchUpdate(
                            spreadsheetId=SPREADSHEET_ID,
                            body={
                                "requests": [{
                                    "deleteDimension": {
                                        "range": {
                                            "sheetId": 0,  # ← change if your sheetId is different
                                            "dimension": "ROWS",
                                            "startIndex": sheet_row - 1,
                                            "endIndex": sheet_row
                                        }
                                    }
                                }]
                            }
                        ).execute()
                    except Exception as e:
                        st.error(f"Delete {name} failed: {e}")
                st.success(f"Deleted {len(to_delete)} reagent(s)")
                load_reagents.clear()
                st.rerun()

st.caption("Laboratory Reagent Inventory • January 2026")


