# streamlit_app.py - Laboratory Reagent Inventory System
# Streamlit + Google Sheets API v4 • Full CRUD
# Updated January 2026 – improved Log Usage clarity

import streamlit as st
import pandas as pd
from datetime import date
import hashlib
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory")
st.caption("Streamlit + Google Sheets API v4")

# ── Google Sheets client ──────────────────────────────────────────────────────
@st.cache_resource
def get_sheets_service():
    try:
        creds = Credentials.from_service_account_info(
            st.secrets["google_service_account"],
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        service = build('sheets', 'v4', credentials=creds).spreadsheets()
        spreadsheet_id = st.secrets["connections"]["gsheets"]["spreadsheet"]
        return service, spreadsheet_id
    except Exception as e:
        st.error(f"Google Sheets connection failed:\n{str(e)}")
        st.stop()

sheets_service, SPREADSHEET_ID = get_sheets_service()
SHEET_NAME = "template"               # ← change if your tab name is different
READ_RANGE = f"{SHEET_NAME}!A1:Z1000"

# Column mapping (1-based → letter)
COL = {
    "id":               "A",
    "name":             "B",
    "cas_number":       "C",
    "supplier":         "D",
    "location":         "E",
    "quantity":         "F",
    "unit":             "G",
    "expiration_date":  "H",
    "low_stock_threshold": "I",
}

# ── Simple login (demo only) ──────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.role = None

if not st.session_state.authenticated:
    st.subheader("Login")
    with st.form("login_form", clear_on_submit=True):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Login", type="primary"):
            hashed = hashlib.sha256(password.encode()).hexdigest()
            if username == "admin" and hashed == hashlib.sha256("admin123".encode()).hexdigest():
                st.session_state.update(authenticated=True, username=username, role="admin")
            elif username == "user" and hashed == hashlib.sha256("user123".encode()).hexdigest():
                st.session_state.update(authenticated=True, username=username, role="user")
            if st.session_state.authenticated:
                st.rerun()
            else:
                st.error("Invalid credentials")
    st.stop()

if st.sidebar.button("Logout", use_container_width=True):
    for key in list(st.session_state.keys()):
        if key in ["authenticated", "username", "role"]:
            del st.session_state[key]
    st.rerun()

st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})")

# ── Load data ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=120)
def load_inventory():
    try:
        result = sheets_service.values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=READ_RANGE
        ).execute()

        values = result.get('values', [])
        if not values:
            return pd.DataFrame()

        headers = values[0]
        df = pd.DataFrame(values[1:], columns=headers)

        keep_cols = [c for c in COL if c in df.columns]
        df = df[keep_cols]

        if "expiration_date" in df.columns:
            df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors='coerce').dt.date

        df["quantity"] = pd.to_numeric(df["quantity"], errors='coerce').fillna(0)
        df["low_stock_threshold"] = pd.to_numeric(df["low_stock_threshold"], errors='coerce').fillna(10)

        return df.sort_values("name").reset_index(drop=True)

    except Exception as e:
        st.error(f"Could not load data: {str(e)}")
        return pd.DataFrame()

df = load_inventory()

# ── Low stock / expired alerts ────────────────────────────────────────────────
today = date.today()
alerts = []
for _, r in df.iterrows():
    qty = r.get("quantity", 0)
    thresh = r.get("low_stock_threshold", 10)
    name = r.get("name", "—")
    unit = r.get("unit", "?")
    if qty <= thresh:
        alerts.append(f"Low stock: **{name}**  ({qty:.1f} {unit})")
    if pd.notnull(r.get("expiration_date")) and r["expiration_date"] < today:
        alerts.append(f"Expired: **{name}**  ({r['expiration_date']})")

if alerts:
    st.warning("\n\n".join(alerts), icon="⚠️")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_view, tab_add, tab_use, tab_qr, tab_admin = st.tabs([
    "📋 Catalog", "➕ Add", "📉 Log Usage", "🔲 QR", "🛠 Admin"
])

# ──────────────────────────────────────────────────────────────────────────────
#  CATALOG
# ──────────────────────────────────────────────────────────────────────────────
with tab_view:
    st.header("Reagent Catalog")

    search = st.text_input("Search", "")
    view_df = df
    if search:
        mask = view_df.astype(str).apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)
        view_df = view_df[mask]

    if view_df.empty:
        st.info("No matching reagents found.")
    else:
        st.dataframe(
            view_df.style.format(precision=2),
            use_container_width=True,
            hide_index=True
        )

# ──────────────────────────────────────────────────────────────────────────────
#  ADD NEW
# ──────────────────────────────────────────────────────────────────────────────
with tab_add:
    st.header("Add New Reagent")

    with st.form("add_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Name **required**", "")
            cas = st.text_input("CAS Number")
            supplier = st.text_input("Supplier")
            location = st.text_input("Location / Cabinet")
        with col2:
            qty = st.number_input("Initial quantity", min_value=0.0, value=100.0, step=0.1)
            unit = st.selectbox("Unit", ["g", "mg", "L", "mL", "kg", "pcs", "bottles"])
            exp_date = st.date_input("Expiration date", value=None)
            low_thresh = st.number_input("Low stock alert threshold", min_value=0.0, value=10.0, step=1.0)

        if st.form_submit_button("Add Reagent", type="primary", use_container_width=True):
            if not name.strip():
                st.error("Name is required.")
            elif name.strip() in df["name"].values:
                st.error("A reagent with this name already exists.")
            else:
                row = [
                    "", name.strip(), cas.strip() or "", supplier.strip() or "",
                    location.strip() or "", str(qty), unit,
                    exp_date.strftime("%Y-%m-%d") if exp_date else "",
                    str(low_thresh)
                ]
                try:
                    sheets_service.values().append(
                        spreadsheetId=SPREADSHEET_ID,
                        range=f"{SHEET_NAME}!A:A",
                        valueInputOption="RAW",
                        insertDataOption="INSERT_ROWS",
                        body={"values": [row]}
                    ).execute()
                    st.success(f"**{name}** added successfully.")
                    load_inventory.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to add reagent: {e}")

# ──────────────────────────────────────────────────────────────────────────────
#  LOG USAGE  ←  quantity updated immediately after submit
# ──────────────────────────────────────────────────────────────────────────────
with tab_use:
    st.header("Log Usage / Deduct Stock")

    if df.empty:
        st.info("No reagents in inventory yet.")
    else:
        selected = st.selectbox(
            "Select reagent",
            options=[""] + df["name"].sort_values().tolist()
        )

        if selected:
            row = df[df["name"] == selected].iloc[0]
            current_qty = float(row["quantity"])
            unit = row["unit"]

            st.metric("Current stock", f"{current_qty:.2f} {unit}")

            with st.form("usage_form", clear_on_submit=False):
                used = st.number_input(
                    "Amount used",
                    min_value=0.01,
                    max_value=current_qty,
                    value=0.0,
                    step=0.1,
                    format="%.2f"
                )

                submitted = st.form_submit_button("Confirm & Update Stock", type="primary")

                if submitted and used > 0:
                    new_quantity = current_qty - used
                    idx = df[df["name"] == selected].index[0]
                    row_number = idx + 2   # header + 0-based index

                    range_update = f"{SHEET_NAME}!{COL['quantity']}{row_number}"

                    try:
                        sheets_service.values().update(
                            spreadsheetId=SPREADSHEET_ID,
                            range=range_update,
                            valueInputOption="RAW",
                            body={"values": [[str(new_quantity)]]}
                        ).execute()

                        st.success(f"Stock updated → **{new_quantity:.2f} {unit}** remaining")
                        load_inventory.clear()
                        st.rerun()

                    except Exception as e:
                        st.error(f"Could not update quantity: {str(e)}")

# ──────────────────────────────────────────────────────────────────────────────
#  Placeholder tabs
# ──────────────────────────────────────────────────────────────────────────────
with tab_qr:
    st.header("QR Code Tools")
    st.info("QR generation and scanning – coming soon")

with tab_admin:
    st.header("Admin")
    if st.session_state.role != "admin":
        st.error("Admin access only.")
    else:
        st.metric("Total items", len(df))
        st.caption("Use the Catalog and Log Usage tabs for most operations.")

st.caption("Laboratory Reagent Inventory • 2026")
