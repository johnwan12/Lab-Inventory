# streamlit_app.py - Laboratory Reagent Inventory System (Google Sheets)
# Revised - Uses GSheetsConnection for read + gspread for write

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
def get_gsheet_conn():
    conn = st.connection("gsheets", type=GSheetsConnection)
    # Quick test
    try:
        conn.read(nrows=1)
        st.success("Read connection ready")
    except Exception as e:
        st.error(f"Read connection test failed: {e}")
    return conn

@st.cache_resource(show_spinner="Initializing gspread (write)...")
def get_gspread_client():
    creds_info = st.secrets["gsheets_service_account"]
    creds = Credentials.from_service_account_info(
        creds_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return gspread.authorize(creds)

conn = get_gsheet_conn()

# ── Authentication ──────────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.role = None

if not st.session_state.authenticated:
    st.subheader("🔐 Login Required")
    with st.form("login_form", clear_on_submit=True):
        col1, col2 = st.columns([3, 2])
        with col1: username = st.text_input("Username")
        with col2: password = st.text_input("Password", type="password")

        if st.form_submit_button("Login", type="primary", use_container_width=True):
            hashed = hashlib.sha256(password.encode()).hexdigest()
            if username == "admin" and hashed == hashlib.sha256("admin123".encode()).hexdigest():
                st.session_state.update(authenticated=True, username=username, role="admin")
            elif username == "user" and hashed == hashlib.sha256("user123".encode()).hexdigest():
                st.session_state.update(authenticated=True, username=username, role="user")

            if st.session_state.authenticated:
                st.success(f"Welcome, {username}! ({st.session_state.role})")
                st.rerun()
            else:
                st.error("Invalid credentials")
    st.stop()

if st.sidebar.button("🚪 Logout", use_container_width=True):
    for k in ["authenticated", "username", "role"]:
        st.session_state.pop(k, None)
    st.rerun()

st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})", icon="👤")

# ── Load Data ───────────────────────────────────────────────────────────────
@st.cache_data(ttl="5min", show_spinner="Loading inventory...")
def load_reagents(_conn):
    try:
        df = _conn.read(
            worksheet="template",
            usecols=["id", "name", "cas_number", "supplier", "location", "quantity", "unit", "expiration_date", "low_stock_threshold"],
            dtype={"id": "Int64", "quantity": float, "low_stock_threshold": float}
        )
        if not df.empty:
            df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce").dt.date
            df = df.sort_values("name")
        df["low_stock_threshold"] = df["low_stock_threshold"].fillna(10.0)
        return df
    except Exception as e:
        st.error(f"Load failed: {str(e)}\nCheck: worksheet='template', headers match, service account has Editor access.")
        return pd.DataFrame(columns=["id", "name", "cas_number", "supplier", "location", "quantity", "unit", "expiration_date", "low_stock_threshold"])

reagents_df = load_reagents(conn)

# ── Alerts ──────────────────────────────────────────────────────────────────
alerts = []
today = date.today()
for _, row in reagents_df.iterrows():
    qty = row.get("quantity", 0)
    thresh = row.get("low_stock_threshold", 10.0)
    if qty <= thresh:
        alerts.append(f"⚠️ **Low**: {row['name']} ({qty:.2f} {row['unit']})")
    exp = row.get("expiration_date")
    if pd.notnull(exp) and exp < today:
        alerts.append(f"❌ **Expired**: {row['name']} ({exp})")

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
        st.info("No matches.")
    else:
        st.dataframe(
            df_view.style.format(precision=2, thousands=",", na_rep="-"),
            use_container_width=True,
            hide_index=True
        )

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
            qty = st.number_input("Quantity *", min_value=0.0, value=50.0, step=0.1)
            unit = st.selectbox("Unit", ["g", "mg", "L", "mL", "kg", "pcs", "bottles"])
            exp_date = st.date_input("Expiration", value=None)
            threshold = st.number_input("Low Stock Threshold", min_value=0.0, value=10.0, step=1.0)

        if st.form_submit_button("➕ Add", type="primary", use_container_width=True):
            if not name.strip():
                st.error("Name required.")
            else:
                try:
                    client = get_gspread_client()
                    ss = client.open_by_key(st.secrets.connections.gsheets.spreadsheet)
                    ws = ss.worksheet("template")

                    row = [
                        "",  # id (use =ROW()-1 in sheet A2:A if desired)
                        name.strip(),
                        cas.strip() or "",
                        supplier.strip() or "",
                        location.strip() or "",
                        qty,
                        unit,
                        exp_date.strftime("%Y-%m-%d") if exp_date else "",
                        threshold
                    ]
                    ws.append_row(row)
                    st.success(f"Added **{name}**")
                    load_reagents.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Add failed: {e}")

with tab_log:
    st.header("Log Usage")
    if reagents_df.empty:
        st.info("No reagents yet.")
    else:
        names = [""] + reagents_df["name"].tolist()
        selected = st.selectbox("Reagent", names)
        if selected:
            row = reagents_df[reagents_df["name"] == selected].iloc[0]
            curr_qty = float(row["quantity"])
            unit = row["unit"]
            st.metric("Current", f"{curr_qty:.2f} {unit}")

            with st.form("usage_form"):
                used = st.number_input("Used amount", min_value=0.01, max_value=curr_qty, step=0.1, format="%.2f")
                st.form_submit_button("📉 Update", type="primary")

                if st.session_state.get("usage_form_submitted", False) and used > 0:
                    new_qty = curr_qty - used
                    try:
                        client = get_gspread_client()
                        ss = client.open_by_key(st.secrets.connections.gsheets.spreadsheet)
                        ws = ss.worksheet("template")

                        idx = reagents_df[reagents_df["name"] == selected].index[0]
                        row_num = idx + 2  # 1 = header
                        col_letter = chr(65 + reagents_df.columns.get_loc("quantity"))
                        cell = f"{col_letter}{row_num}"

                        ws.update(cell, new_qty)
                        st.success(f"Updated → {new_qty:.2f} {unit}")
                        load_reagents.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Update failed: {e}")

with tab_qr:
    st.info("QR features coming soon...")

with tab_admin:
    if st.session_state.role != "admin":
        st.error("Admin only")
    else:
        st.header("Admin")
        col1, col2, col3 = st.columns(3)
        col1.metric("Reagents", len(reagents_df))
        col2.metric("Low Stock", sum("Low" in a for a in alerts))
        col3.metric("Expired", sum("Expired" in a for a in alerts))

st.caption("Lab Inventory • 2026")
