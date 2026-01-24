# streamlit_app.py - Laboratory Reagent Inventory System (Google Sheets)
# Revised January 2026 - Uses GSheetsConnection + secrets.toml / Cloud Secrets

import streamlit as st
import pandas as pd
from datetime import date
import hashlib

# Required import for the connection
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")
st.caption("Streamlit + Google Sheets • Private connection via service account")

# ── Google Sheets Connection (uses secrets) ─────────────────────────────────
@st.cache_resource(show_spinner="Connecting to Google Sheets...")
def get_gsheet_conn():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        
        # Test read: no worksheet= → uses first tab / Sheet1
        # nrows=1 → minimal, fast test
        test_df = conn.read(nrows=1)
        
        st.success(f"Connection & test read successful! {len(test_df)} row(s) fetched.", icon="✅")
        return conn
    except Exception as e:
        st.error(f"Failed: {str(e)}", icon="🚨")
        st.exception(e)  # Full traceback in app
        
        if "404" in str(e):
            st.markdown("""
            **404 fixes to try (in order):**
            1. Wrong spreadsheet ID – double-check URL: https://docs.google.com/spreadsheets/d/**ID**/edit
            2. Service account not shared as Editor – re-add email and wait 10 min
            3. Worksheet "template" missing – comment out worksheet in secrets/code
            4. Re-download fresh JSON key and re-paste private_key with real line breaks
            """)
        st.stop()


# ── Authentication (simple hash-based – consider st-authenticator later) ─────
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
        
        if st.form_submit_button("Login", use_container_width=True, type="primary"):
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

# Logout button
if st.sidebar.button("🚪 Logout", use_container_width=True):
    for key in ["authenticated", "username", "role"]:
        st.session_state.pop(key, None)
    st.rerun()

st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})", icon="👤")


# ── Load Data ───────────────────────────────────────────────────────────────
conn = get_gsheet_conn()

@st.cache_data(ttl="10min", show_spinner="Loading inventory...")
def load_reagents(_conn):
    try:
        df = _conn.read(
            worksheet="template",
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
            df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce").dt.date
            df = df.sort_values("name")

        # Default threshold if missing
        if "low_stock_threshold" not in df.columns:
            df["low_stock_threshold"] = 1.0

        return df

    except Exception as e:
        st.error(f"Failed to load reagents: {str(e)}")
        return pd.DataFrame(columns=[
            "id", "name", "cas_number", "supplier", "location",
            "quantity", "unit", "expiration_date", "low_stock_threshold"
        ])


reagents_df = load_reagents(conn)


# ── Alerts ──────────────────────────────────────────────────────────────────
alerts = []
today = date.today()

for _, row in reagents_df.iterrows():
    qty = row.get("quantity")
    thresh = row.get("low_stock_threshold", 1.0)
    if pd.notna(qty) and qty <= thresh:
        alerts.append(f"⚠️ **Low Stock**: {row['name']} — {qty:.2f} {row['unit']} (threshold: {thresh})")
    
    exp = row.get("expiration_date")
    if pd.notnull(exp) and exp < today:
        alerts.append(f"❌ **Expired**: {row['name']} ({exp})")

if alerts:
    st.warning("\n\n".join(alerts), icon="🚨")


# ── Tabs ────────────────────────────────────────────────────────────────────
tab_catalog, tab_add, tab_log, tab_qr, tab_admin = st.tabs([
    "📋 Catalog", "➕ Add Reagent", "📉 Log Usage", "🔲 QR Tools", "🛠 Admin"
])

with tab_catalog:
    st.header("Reagent Catalog")
    search = st.text_input("Search by name, CAS, supplier, or location")
    
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
            df_view.style.format({"quantity": "{:.2f}"}),
            use_container_width=True,
            hide_index=True
        )
        if st.session_state.role != "admin":
            st.info("Admin role required for editing/deleting.")


with tab_add:
    st.header("Add New Reagent")
    st.info("→ Add form + conn.insert_rows() implementation coming next (tell me if ready)")

with tab_log:
    st.header("Log Usage")
    st.info("→ Quantity reduction + update coming next")

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
        col2.metric("Low Stock", sum(1 for a in alerts if "Low" in a))
        col3.metric("Expired", sum(1 for a in alerts if "Expired" in a))


st.caption("Laboratory Reagent Inventory • January 2026")


