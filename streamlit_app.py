# streamlit_app.py - Laboratory Reagent Inventory System
# Revised - Safe read (no usecols), gspread for writes, debug helpers

import streamlit as st
import pandas as pd
from datetime import date
import hashlib
import gspread
from google.oauth2.service_account import Credentials
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")
st.caption("Streamlit + Google Sheets • Safe read + gspread writes")

# ── Connections ─────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Connecting to Google Sheets (read)...")
def get_gsheet_conn():
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        test_df = conn.read(nrows=1)
        st.success("Basic read connection OK")
    except Exception as e:
        st.error(f"Basic connection test failed: {e}")
    return conn

@st.cache_resource(show_spinner="Initializing gspread (write)...")
def get_gspread_client():
    try:
        creds_info = st.secrets["gsheets_service_account"]
        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        return gspread.authorize(creds)
    except KeyError:
        st.error("Missing [gsheets_service_account] in secrets.toml / Cloud Secrets")
        st.stop()
    except Exception as e:
        st.error(f"gspread init failed: {e}")
        st.stop()

conn = get_gsheet_conn()

# Debug: Show what secrets keys are available (remove after testing)
if st.session_state.get("debug_secrets", False):
    st.write("Available secrets sections:", list(st.secrets.keys()))

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

# ── Load Data (safe version - no forced usecols) ────────────────────────────
@st.cache_data(ttl="5min", show_spinner="Loading inventory...")
def load_reagents(_conn):
    try:
        # Read full worksheet first (avoids 400 from bad usecols)
        df = _conn.read(worksheet="template")

        # Debug: show actual columns found
        st.session_state["sheet_columns"] = df.columns.tolist()
        if "debug" in st.query_params:
            st.info(f"Columns found in sheet: {df.columns.tolist()}")

        # Select only expected columns if they exist
        expected = [
            "id", "name", "cas_number", "supplier", "location",
            "quantity", "unit", "expiration_date", "low_stock_threshold"
        ]
        available = [col for col in expected if col in df.columns]
        if available:
            df = df[available]
        else:
            st.warning("None of the expected columns found. Check row 1 headers.")

        if not df.empty:
            if "expiration_date" in df.columns:
                df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce").dt.date
            df = df.sort_values("name")

        # Defaults
        if "quantity" in df.columns:
            df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)
        if "low_stock_threshold" in df.columns:
            df["low_stock_threshold"] = pd.to_numeric(df["low_stock_threshold"], errors="coerce").fillna(10.0)

        return df

    except Exception as e:
        st.error(f"Failed to load data: {str(e)}\n"
                 f"- Worksheet must be named exactly 'template'\n"
                 f"- Row 1 must have headers\n"
                 f"- Service account needs Editor access")
        return pd.DataFrame(columns=[
            "id", "name", "cas_number", "supplier", "location",
            "quantity", "unit", "expiration_date", "low_stock_threshold"
        ])

reagents_df = load_reagents(conn)

# ── Alerts ──────────────────────────────────────────────────────────────────
alerts = []
today = date.today()
for _, row in reagents_df.iterrows():
    qty = row.get("quantity", 0)
    thresh = row.get("low_stock_threshold", 10.0)
    if qty <= thresh and pd.notna(qty):
        alerts.append(f"⚠️ Low Stock: {row.get('name', 'Unknown')} — {qty:.2f} {row.get('unit', '?')}")
    exp = row.get("expiration_date")
    if pd.notnull(exp) and exp < today:
        alerts.append(f"❌ Expired: {row.get('name', 'Unknown')} ({exp})")

if alerts:
    st.warning("\n".join(alerts), icon="🚨")

# ── Tabs ────────────────────────────────────────────────────────────────────
tab_catalog, tab_add, tab_log, tab_qr, tab_admin = st.tabs([
    "📋 Catalog", "➕ Add Reagent", "📉 Log Usage", "🔲 QR Tools", "🛠 Admin"
])

with tab_catalog:
    st.header("Reagent Catalog")
    search = st.text_input("Search by name, CAS, supplier, location", "")
    df_view = reagents_df
    if search:
        mask = df_view.astype(str).apply(
            lambda x: x.str.contains(search, case=False, na=False)
        ).any(axis=1)
        df_view = df_view[mask]
    if df_view.empty:
        st.info("No matching reagents.")
    else:
        st.dataframe(
            df_view.style.format(precision=2),
            use_container_width=True,
            hide_index=True
        )

with tab_add:
    st.header("Add New Reagent")
    with st.form("add_reagent_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Reagent Name *")
            cas_number = st.text_input("CAS Number")
            supplier = st.text_input("Supplier")
            location = st.text_input("Location")
        with col2:
            quantity = st.number_input("Initial Quantity *", min_value=0.0, value=100.0, step=0.1)
            unit = st.selectbox("Unit", ["g", "mg", "kg", "L", "mL", "pcs", "bottles", "vials"])
            expiration_date = st.date_input("Expiration Date", value=None)
            low_stock_threshold = st.number_input("Low Stock Threshold", min_value=0.0, value=10.0, step=1.0)

        submitted = st.form_submit_button("➕ Add Reagent", type="primary", use_container_width=True)

        if submitted:
            if not name.strip():
                st.error("Reagent Name is required.")
            else:
                try:
                    client = get_gspread_client()
                    ss = client.open_by_key(st.secrets.connections.gsheets.spreadsheet)
                    ws = ss.worksheet("template")

                    new_row = [
                        "",  # id – use =ROW()-1 in sheet if wanted
                        name.strip(),
                        cas_number.strip() or "",
                        supplier.strip() or "",
                        location.strip() or "",
                        quantity,
                        unit,
                        expiration_date.strftime("%Y-%m-%d") if expiration_date else "",
                        low_stock_threshold
                    ]
                    ws.append_row(new_row)
                    st.success(f"**{name}** added!")
                    load_reagents.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Add failed: {str(e)}")

with tab_log:
    st.header("Log Usage")
    if reagents_df.empty:
        st.info("No reagents loaded yet.")
    else:
        selected_name = st.selectbox("Select Reagent", [""] + reagents_df["name"].tolist())
        if selected_name:
            row = reagents_df[reagents_df["name"] == selected_name].iloc[0]
            current_qty = float(row.get("quantity", 0))
            unit = row.get("unit", "?")
            st.metric("Current Stock", f"{current_qty:.2f} {unit}")

            with st.form("log_form"):
                used_qty = st.number_input("Amount used", min_value=0.01, max_value=current_qty, step=0.1, format="%.2f")
                submit_log = st.form_submit_button("📉 Log & Update", type="primary")

                if submit_log and used_qty > 0:
                    new_qty = current_qty - used_qty
                    try:
                        client = get_gspread_client()
                        ss = client.open_by_key(st.secrets.connections.gsheets.spreadsheet)
                        ws = ss.worksheet("template")

                        idx = reagents_df[reagents_df["name"] == selected_name].index[0]
                        row_num = idx + 2  # header = 1
                        col_idx = reagents_df.columns.get_loc("quantity")
                        col_letter = chr(65 + col_idx)
                        cell = f"{col_letter}{row_num}"

                        ws.update(cell, new_qty)
                        st.success(f"Updated → **{new_qty:.2f} {unit}**")
                        load_reagents.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Update failed: {str(e)}")

with tab_qr:
    st.header("QR Tools")
    st.info("Coming soon...")

with tab_admin:
    if st.session_state.role != "admin":
        st.error("Admin only", icon="🔒")
    else:
        st.header("Admin Dashboard")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Reagents", len(reagents_df))
        col2.metric("Low Stock", sum(1 for a in alerts if "Low Stock" in a))
        col3.metric("Expired", sum(1 for a in alerts if "Expired" in a))

        # Debug toggle
        st.checkbox("Show debug info (columns, etc.)", key="debug", value=False)
        if st.session_state.debug:
            st.write("Loaded columns:", st.session_state.get("sheet_columns", []))

st.caption("Laboratory Reagent Inventory • January 2026")
