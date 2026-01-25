# streamlit_app.py - Laboratory Reagent Inventory System
# Uses GSheetsConnection for reading + gspread for writing

import streamlit as st
import pandas as pd
from datetime import date
import hashlib
import gspread
from google.oauth2.service_account import Credentials
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")
st.caption("Streamlit + Google Sheets • Read via st.connection • Write via gspread")

# ── Connections ─────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Connecting to Google Sheets (read)...")
def get_read_connection():
    conn = st.connection("gsheets", type=GSheetsConnection)
    try:
        conn.read(nrows=1)
    except Exception as e:
        st.error(f"Read connection test failed: {e}")
        st.stop()
    return conn


@st.cache_resource(show_spinner="Initializing gspread client (write)...")
def get_write_client():
    try:
        sa_info = st.secrets["gsheets_service_account"]
        creds = Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        return gspread.authorize(creds)
    except KeyError:
        st.error(
            "Missing [gsheets_service_account] section in secrets.\n"
            "Please add your service account JSON to Streamlit Cloud Secrets "
            "or .streamlit/secrets.toml"
        )
        st.stop()
    except Exception as e:
        st.error(f"Failed to initialize gspread client: {str(e)}")
        st.stop()


conn = get_read_connection()

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
@st.cache_data(ttl="5min", show_spinner="Loading inventory...")
def load_reagents(_conn):
    try:
        # Read full sheet first → avoids column name validation errors
        df = _conn.read(worksheet="template")

        # Select desired columns if they exist
        cols = [
            "id", "name", "cas_number", "supplier", "location",
            "quantity", "unit", "expiration_date", "low_stock_threshold"
        ]
        existing_cols = [c for c in cols if c in df.columns]
        if existing_cols:
            df = df[existing_cols]
        else:
            st.warning("No expected columns found in the sheet.")

        if not df.empty:
            if "expiration_date" in df.columns:
                df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce").dt.date
            df = df.sort_values("name")

        # Apply defaults
        if "quantity" in df.columns:
            df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)
        if "low_stock_threshold" in df.columns:
            df["low_stock_threshold"] = pd.to_numeric(df["low_stock_threshold"], errors="coerce").fillna(10.0)

        return df

    except Exception as e:
        st.error(f"Failed to load reagents:\n{str(e)}\n\n"
                 "Checklist:\n"
                 "• Worksheet name = 'template' (case sensitive)\n"
                 "• First row contains headers\n"
                 "• Service account has Editor access to the spreadsheet")
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
    if pd.notna(qty) and qty <= thresh:
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
            cas = st.text_input("CAS Number")
            supplier = st.text_input("Supplier")
            location = st.text_input("Location")
        with col2:
            quantity = st.number_input("Quantity *", min_value=0.0, value=100.0, step=0.1)
            unit = st.selectbox("Unit", ["g", "mg", "L", "mL", "kg", "pcs", "bottles", "vials"])
            exp_date = st.date_input("Expiration Date", value=None)
            threshold = st.number_input("Low stock threshold", min_value=0.0, value=10.0, step=1.0)

        submitted = st.form_submit_button("Add", type="primary", use_container_width=True)

        if submitted:
            if not name.strip():
                st.error("Name is required.")
            else:
                with st.spinner("Adding..."):
                    try:
                        client = get_write_client()
                        ss = client.open_by_key(st.secrets.connections.gsheets.spreadsheet)
                        ws = ss.worksheet("template")

                        row = [
                            "",  # id – can use =ROW()-1 formula in sheet
                            name.strip(),
                            (cas or "").strip(),
                            (supplier or "").strip(),
                            (location or "").strip(),
                            quantity,
                            unit,
                            exp_date.strftime("%Y-%m-%d") if exp_date else "",
                            threshold
                        ]

                        ws.append_row(row)
                        st.success(f"Added **{name}**")
                        load_reagents.clear()
                        st.rerun()

                    except gspread.exceptions.WorksheetNotFound:
                        st.error("Worksheet 'template' not found.")
                    except Exception as e:
                        st.error(f"Add failed: {str(e)}")

with tab_log:
    st.header("Log Usage")
    if reagents_df.empty:
        st.info("No reagents loaded yet.")
    else:
        selected = st.selectbox("Reagent", [""] + reagents_df["name"].tolist())
        if selected:
            row = reagents_df[reagents_df["name"] == selected].iloc[0]
            curr_qty = float(row.get("quantity", 0))
            unit = row.get("unit", "unit")
            st.metric("Current stock", f"{curr_qty:.2f} {unit}")

            with st.form("usage_form"):
                used = st.number_input("Amount used", min_value=0.01, max_value=curr_qty or 9999, step=0.1, format="%.2f")
                submit = st.form_submit_button("Update stock", type="primary")

                if submit and used > 0:
                    new_qty = curr_qty - used
                    with st.spinner("Updating..."):
                        try:
                            client = get_write_client()
                            ss = client.open_by_key(st.secrets.connections.gsheets.spreadsheet)
                            ws = ss.worksheet("template")

                            idx = reagents_df[reagents_df["name"] == selected].index[0]
                            row_num = idx + 2  # 1 = header
                            col_idx = reagents_df.columns.get_loc("quantity")
                            col_letter = chr(65 + col_idx)
                            cell = f"{col_letter}{row_num}"

                            ws.update(cell, new_qty)
                            st.success(f"New quantity: **{new_qty:.2f} {unit}**")
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
        col1.metric("Total reagents", len(reagents_df))
        col2.metric("Low stock", sum(1 for a in alerts if "Low Stock" in a))
        col3.metric("Expired", sum(1 for a in alerts if "Expired" in a))

st.caption("Lab Inventory • January 2026")
