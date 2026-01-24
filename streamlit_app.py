# streamlit_app.py - Laboratory Reagent Inventory System (Google Sheets version)
# Last revised: January 2026 - Secure secrets + GSheetsConnection best practices

#import streamlit as st
import pandas as pd
from datetime import date
import hashlib

import streamlit as st
from st_gsheets_connection import GSheetsConnection

conn = st.connection(
    "gsheets",
    type=GSheetsConnection
)

df = conn.read()
st.dataframe(df)


from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")
st.caption("Powered by Streamlit + Google Sheets • Secure service account connection")

# ── Secure Google Sheets Connection ─────────────────────────────────────────
@st.cache_resource
def get_gsheet_conn():
    try:
        conn = st.connection(
            "gsheets",
            type=GSheetsConnection,
            # Optional: override spreadsheet if not set in secrets
            # spreadsheet="https://docs.google.com/spreadsheets/d/1xorAPoWd81bUE2yeJN4QsEhpEoUZ5yvdGIm2h9MHbkQ/edit"
        )
        # Smoke test: try to read 1 row
        conn.read(worksheet="template", nrows=1)
        return conn
    except Exception as e:
        st.error(f"Failed to connect to Google Sheets: {str(e)}", icon="🚨")
        st.info(
            "Checklist:\n"
            "• Service account JSON correctly saved in Streamlit Cloud Secrets under **[gcp_service_account]**\n"
            "• Service account email added as **Editor** to the spreadsheet\n"
            "• Google Sheets API and Drive API enabled in Google Cloud Console\n"
            "• No typos in private_key (line breaks must be preserved)"
        )
        st.stop()


# ── Simple Session-based Authentication ─────────────────────────────────────
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
        
        submitted = st.form_submit_button("Login", use_container_width=True, type="primary")

        if submitted:
            hashed = hashlib.sha256(password.encode()).hexdigest()
            if username == "admin" and hashed == hashlib.sha256("admin123".encode()).hexdigest():
                st.session_state.update({"authenticated": True, "username": username, "role": "admin"})
            elif username == "user" and hashed == hashlib.sha256("user123".encode()).hexdigest():
                st.session_state.update({"authenticated": True, "username": username, "role": "user"})

            if st.session_state.authenticated:
                st.success(f"Welcome back, {username}! ({st.session_state.role.capitalize()})")
                st.rerun()
            else:
                st.error("Invalid credentials. Try again.")
    st.stop()

# Logout
if st.sidebar.button("🚪 Logout", use_container_width=True):
    for key in list(st.session_state.keys()):
        if key in ["authenticated", "username", "role"]:
            del st.session_state[key]
    st.rerun()

st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})", icon="👤")


# ── Load Reagents ───────────────────────────────────────────────────────────
@st.cache_data(ttl="10min")
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

        df["low_stock_threshold"] = df.get("low_stock_threshold", 1.0)

        return df

    except Exception as e:
        st.error(f"Data load failed: {str(e)}")
        return pd.DataFrame(columns=[
            "id", "name", "cas_number", "supplier", "location",
            "quantity", "unit", "expiration_date", "low_stock_threshold"
        ])


conn = get_gsheet_conn()
reagents_df = load_reagents(conn)


# ── Generate Alerts ─────────────────────────────────────────────────────────
alerts = []
today = date.today()

for _, row in reagents_df.iterrows():
    qty = row.get("quantity")
    threshold = row.get("low_stock_threshold", 1.0)
    if pd.notna(qty) and qty <= threshold:
        alerts.append(
            f"⚠️ **Low stock**: {row['name']} → {qty:.2f} {row['unit']} "
            f"(threshold: {threshold})"
        )

    exp = row.get("expiration_date")
    if pd.notnull(exp) and exp < today:
        alerts.append(f"❌ **Expired**: {row['name']} ({exp})")

if alerts:
    st.warning("\n".join(alerts), icon="🚨")


# ── Main Tabs ───────────────────────────────────────────────────────────────
tab_catalog, tab_add, tab_log, tab_qr, tab_admin = st.tabs([
    "📋 Catalog", "➕ Add Reagent", "📉 Log Usage", "🔲 QR Tools", "🛠 Admin"
])

# ── Catalog Tab ─────────────────────────────────────────────────────────────
with tab_catalog:
    st.header("Reagent Catalog")

    search_term = st.text_input("Search by name, CAS, supplier or location", key="search")
    
    df_view = reagents_df
    if search_term:
        mask = (
            df_view["name"].str.contains(search_term, case=False, na=False) |
            df_view["cas_number"].str.contains(search_term, case=False, na=False) |
            df_view["supplier"].str.contains(search_term, case=False, na=False) |
            df_view["location"].str.contains(search_term, case=False, na=False)
        )
        df_view = df_view[mask]

    if df_view.empty:
        st.info("No matching reagents found.")
    else:
        if st.session_state.role == "admin":
            # Placeholder: implement editing later with conn.update / upsert
            st.dataframe(
                df_view.style.format({"quantity": "{:.2f}"}),
                use_container_width=True,
                hide_index=True
            )
            st.info("Admin → Edit/Delete coming soon (using conn.update / conn.upsert)")
        else:
            st.dataframe(
                df_view.style.format({"quantity": "{:.2f}"}),
                use_container_width=True,
                hide_index=True
            )


# ── Add Reagent Tab (placeholder) ───────────────────────────────────────────
with tab_add:
    st.header("Add New Reagent")
    st.info("Form + conn.insert_rows() implementation pending")


# ── Log Usage Tab (placeholder) ─────────────────────────────────────────────
with tab_log:
    st.header("Log Reagent Usage")
    st.info("Select reagent → reduce quantity → conn.update implementation pending")


# ── QR Tools Tab (placeholder) ──────────────────────────────────────────────
with tab_qr:
    st.header("QR Code Tools")
    st.info("Generate / scan QR codes for quick lookup – coming soon")


# ── Admin Dashboard ─────────────────────────────────────────────────────────
with tab_admin:
    if st.session_state.role != "admin":
        st.error("Admin access only.", icon="🔒")
    else:
        st.header("Admin Overview")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Reagents", len(reagents_df))
        col2.metric("Low Stock Items", sum(1 for a in alerts if "Low" in a))
        col3.metric("Expired Items", sum(1 for a in alerts if "Expired" in a))

        st.markdown("---")
        st.caption("Next steps: implement CRUD operations with `conn.insert_rows()`, `conn.update()`, `conn.upsert()`")


st.caption("Laboratory Reagent Inventory • Streamlit + Google Sheets • January 2026")

