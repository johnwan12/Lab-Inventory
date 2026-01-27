# streamlit_app.py - Laboratory Reagent Inventory System
# Streamlit + Google Sheets API v4 (Production-safe)
# Revised: Jan 2026

import streamlit as st

import streamlit as st
# st.write("DEBUG secrets keys:", list(st.secrets.keys()))
# st.stop()

# st.write("Secrets keys:", list(st.secrets.keys()))
# st.write("SA keys:", list(st.secrets["google_service_account"].keys()))
# st.stop()

import pandas as pd
from datetime import date
import hashlib
import uuid

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ─────────────────────────────────────────────────────────────
# Page setup
# ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")
st.caption("Streamlit + Google Sheets API v4 • Production-safe CRUD")

# ─────────────────────────────────────────────────────────────
# Google Sheets init
# ─────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Connecting to Google Sheets...")
# def get_sheets_service():
#     sa_info = st.secrets["google_service_account"]
#     creds = Credentials.from_service_account_info(
#         sa_info,
#         scopes=["https://www.googleapis.com/auth/spreadsheets"]
#     )
#     service = build("sheets", "v4", credentials=creds).spreadsheets()
#     spreadsheet_id = st.secrets.connections.gsheets.spreadsheet
#     return service, spreadsheet_id






@st.cache_resource
def get_sheet_id(service, spreadsheet_id, worksheet_name):
    meta = service.get(spreadsheetId=spreadsheet_id).execute()
    for s in meta["sheets"]:
        props = s["properties"]
        if props["title"] == worksheet_name:
            return props["sheetId"]
    raise ValueError(f"Worksheet '{worksheet_name}' not found")


sheets_service, SPREADSHEET_ID = get_sheets_service()

# ── DEBUG: verify spreadsheet access ─────────────────────────
try:
    meta = sheets_service.get(
        spreadsheetId=SPREADSHEET_ID
    ).execute()

    st.success("✅ Spreadsheet access OK")

    sheet_titles = [
        s["properties"]["title"]
        for s in meta["sheets"]
    ]
    st.write("Available worksheets:", sheet_titles)

except Exception as e:
    st.error("❌ Cannot access spreadsheet")
    st.exception(e)
    st.stop()
# ─────────────────────────────────────────────────────────────

WORKSHEET = "template"
READ_RANGE = f"{WORKSHEET}!A1:I2000"

SHEET_ID = get_sheet_id(sheets_service, SPREADSHEET_ID, WORKSHEET)

SHEET_COLUMNS = {
    "id": "A",
    "name": "B",
    "cas_number": "C",
    "supplier": "D",
    "location": "E",
    "quantity": "F",
    "unit": "G",
    "expiration_date": "H",
    "low_stock_threshold": "I",
}

# ─────────────────────────────────────────────────────────────
# Authentication (demo-level)
# ─────────────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.role = None

if not st.session_state.authenticated:
    st.subheader("🔐 Login Required")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Login", type="primary"):
            h = hashlib.sha256(password.encode()).hexdigest()
            if username == "admin" and h == hashlib.sha256("admin123".encode()).hexdigest():
                st.session_state.update(authenticated=True, username=username, role="admin")
            elif username == "user" and h == hashlib.sha256("user123".encode()).hexdigest():
                st.session_state.update(authenticated=True, username=username, role="user")
            else:
                st.error("Invalid credentials")
                st.stop()
            st.rerun()
    st.stop()

if st.sidebar.button("🚪 Logout", use_container_width=True):
    st.session_state.clear()
    st.rerun()

st.sidebar.success(
    f"Logged in as **{st.session_state.username}** ({st.session_state.role})",
    icon="👤"
)

# ─────────────────────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner="Loading inventory...")
def load_reagents():
    result = sheets_service.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=READ_RANGE
    ).execute()

    values = result.get("values", [])
    if not values:
        return pd.DataFrame()

    df = pd.DataFrame(values[1:], columns=values[0])

    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)
    df["low_stock_threshold"] = pd.to_numeric(
        df["low_stock_threshold"], errors="coerce"
    ).fillna(10.0)

    df["expiration_date"] = pd.to_datetime(
        df["expiration_date"], errors="coerce"
    ).dt.date

    return df.sort_values("name")


reagents_df = load_reagents()

# ─────────────────────────────────────────────────────────────
# Alerts
# ─────────────────────────────────────────────────────────────
alerts = []
today = date.today()

for _, r in reagents_df.iterrows():
    if r["quantity"] <= r["low_stock_threshold"]:
        alerts.append(f"⚠️ Low stock: {r['name']} ({r['quantity']} {r['unit']})")
    if pd.notnull(r["expiration_date"]) and r["expiration_date"] < today:
        alerts.append(f"❌ Expired: {r['name']} ({r['expiration_date']})")

if alerts:
    st.warning("\n".join(alerts), icon="🚨")

# ─────────────────────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────────────────────
tab_cat, tab_add, tab_use, tab_admin = st.tabs(
    ["📋 Catalog", "➕ Add", "📉 Log Usage", "🛠 Admin"]
)

# ─────────────────────────────────────────────────────────────
# Catalog
# ─────────────────────────────────────────────────────────────
with tab_cat:
    st.header("Reagent Catalog")
    q = st.text_input("Search")
    view = reagents_df
    if q:
        mask = view.astype(str).apply(
            lambda x: x.str.contains(q, case=False, na=False)
        ).any(axis=1)
        view = view[mask]
    st.dataframe(view, use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────────────────────
# Add reagent
# ─────────────────────────────────────────────────────────────
with tab_add:
    st.header("Add New Reagent")
    with st.form("add"):
        name = st.text_input("Name *")
        cas = st.text_input("CAS Number")
        supplier = st.text_input("Supplier")
        location = st.text_input("Location")
        qty = st.number_input("Quantity", min_value=0.0, value=100.0)
        unit = st.selectbox("Unit", ["g", "mg", "kg", "mL", "L", "pcs"])
        exp = st.date_input("Expiration Date", value=None)
        low = st.number_input("Low Stock Threshold", min_value=0.0, value=10.0)

        if st.form_submit_button("➕ Add", type="primary"):
            if not name.strip():
                st.error("Name required")
                st.stop()

            row = [
                str(uuid.uuid4()),
                name.strip(),
                cas.strip(),
                supplier.strip(),
                location.strip(),
                str(qty),
                unit,
                exp.strftime("%Y-%m-%d") if exp else "",
                str(low),
            ]

            sheets_service.values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{WORKSHEET}!A:A",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()

            load_reagents.clear()
            st.success("Reagent added")
            st.rerun()

# ─────────────────────────────────────────────────────────────
# Log usage
# ─────────────────────────────────────────────────────────────
with tab_use:
    st.header("Log Usage")

    ids = reagents_df["id"].tolist()
    selected = st.selectbox(
        "Select reagent",
        ids,
        format_func=lambda x: reagents_df.loc[
            reagents_df.id == x, "name"
        ].values[0],
    )

    if selected:
        row = reagents_df[reagents_df.id == selected].iloc[0]
        st.metric("Current Stock", f"{row.quantity} {row.unit}")

        used = st.number_input(
            "Amount used",
            min_value=0.01,
            max_value=float(row.quantity),
            step=0.1,
        )

        if st.button("📉 Update", type="primary"):
            new_qty = row.quantity - used
            idx = reagents_df[reagents_df.id == selected].index[0]
            sheet_row = idx + 2

            sheets_service.values().update(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{WORKSHEET}!{SHEET_COLUMNS['quantity']}{sheet_row}",
                valueInputOption="RAW",
                body={"values": [[str(new_qty)]]},
            ).execute()

            load_reagents.clear()
            st.success("Stock updated")
            st.rerun()

# ─────────────────────────────────────────────────────────────
# Admin
# ─────────────────────────────────────────────────────────────
with tab_admin:
    if st.session_state.role != "admin":
        st.error("Admin only")
        st.stop()

    st.header("Admin Dashboard")

    edited = st.data_editor(
        reagents_df,
        use_container_width=True,
        num_rows="dynamic",
    )

    if st.button("💾 Save Changes", type="primary"):
        updates = []

        for i, row in edited.iterrows():
            orig = reagents_df.iloc[i]
            if row.equals(orig):
                continue

            sheet_row = i + 2
            for col, val in row.items():
                if val != orig[col]:
                    if col == "expiration_date" and pd.notna(val):
                        val = pd.to_datetime(val).strftime("%Y-%m-%d")
                    updates.append({
                        "range": f"{WORKSHEET}!{SHEET_COLUMNS[col]}{sheet_row}",
                        "values": [[str(val)]],
                    })

        if updates:
            sheets_service.values().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"valueInputOption": "RAW", "data": updates},
            ).execute()
            load_reagents.clear()
            st.success("Changes saved")
            st.rerun()
        else:
            st.info("No changes")

    st.subheader("Delete Reagents")
    names = st.multiselect("Select", reagents_df["name"].tolist())
    if st.button("🗑 Delete"):
        requests = []
        for n in names:
            idx = reagents_df[reagents_df.name == n].index[0]
            sheet_row = idx + 2
            requests.append({
                "deleteDimension": {
                    "range": {
                        "sheetId": SHEET_ID,
                        "dimension": "ROWS",
                        "startIndex": sheet_row - 1,
                        "endIndex": sheet_row,
                    }
                }
            })

        if requests:
            sheets_service.batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body={"requests": requests},
            ).execute()
            load_reagents.clear()
            st.success("Deleted")
            st.rerun()

st.caption("Laboratory Reagent Inventory • 2026")







