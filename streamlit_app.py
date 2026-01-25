# streamlit_app.py - Laboratory Reagent Inventory System (Google Sheets)
# Revised January 2026 - Uses GSheetsConnection + secrets.toml / Cloud Secrets

import streamlit as st
import pandas as pd
from datetime import date
import hashlib
from streamlit_gsheets import GSheetsConnection
from google.oauth2.service_account import Credentials
#from googleapiclient.discovery import build

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")
st.caption("Streamlit + Google Sheets • Private connection via service account")

# ── Google Sheets Connection ────────────────────────────────────────────────
@st.cache_resource(show_spinner="Connecting to Google Sheets...")
def get_gsheet_conn():
    try:
        conn = st.connection("gsheets", type=GSheetsConnection)
        # Test read
        test_df = conn.read(nrows=1)
        sheet_info = "first sheet"
        if hasattr(conn, '_client') and conn.spreadsheet:
            try:
                sheet_info = conn._client.open_by_key(conn.spreadsheet).sheet1.title
            except:
                pass
        st.success(f"Connection successful! Test read from: **{sheet_info}**")
        return conn
    except Exception as e:
        st.error(f"Connection failed: {str(e)}")
        st.stop()

conn = get_gsheet_conn()

# ── Simple Authentication (upgrade to streamlit-authenticator later if needed) ──
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

# Logout
if st.sidebar.button("🚪 Logout", use_container_width=True):
    for key in ["authenticated", "username", "role"]:
        st.session_state.pop(key, None)
    st.rerun()

st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})", icon="👤")

# ── Load Data ───────────────────────────────────────────────────────────────
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
        # Ensure low_stock_threshold exists
        if "low_stock_threshold" not in df.columns or df["low_stock_threshold"].isna().all():
            df["low_stock_threshold"] = 10.0
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
    qty = row.get("quantity", 0)
    thresh = row.get("low_stock_threshold", 10.0)
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

# ── Catalog Tab ─────────────────────────────────────────────────────────────
with tab_catalog:
    st.header("Reagent Catalog")

    search = st.text_input("Search by name, CAS, supplier, or location", "")

    df_view = reagents_df
    if search:
        mask = df_view.astype(str).apply(
            lambda x: x.str.contains(search, case=False, na=False)
        ).any(axis=1)
        df_view = df_view[mask]

    if df_view.empty:
        st.info("No matching reagents found.")
    else:
        st.dataframe(
            df_view.style.format({"quantity": "{:.2f}", "low_stock_threshold": "{:.1f}"}),
            use_container_width=True,
            hide_index=True
        )
        if st.session_state.role != "admin":
            st.info("Admin role required for editing/deleting entries.")

# ── Add Reagent Tab ─────────────────────────────────────────────────────────
with tab_add:
    st.header("Add New Reagent")

    with st.form("add_reagent_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Reagent Name *", key="add_name")
            cas_number = st.text_input("CAS Number")
            supplier = st.text_input("Supplier / Manufacturer")
            location = st.text_input("Storage Location (fridge, cabinet, etc.)")

        with col2:
            quantity = st.number_input("Initial Quantity *", min_value=0.0, value=100.0, step=0.1)
            unit = st.selectbox("Unit", ["g", "mg", "kg", "L", "mL", "pcs", "bottles", "vials", "tubes"])
            expiration_date = st.date_input("Expiration Date", value=None)
            low_stock_threshold = st.number_input("Low Stock Alert Threshold", min_value=0.0, value=10.0, step=1.0)

        notes = st.text_area("Notes / Comments (optional)", "")

        submitted = st.form_submit_button("➕ Add Reagent", type="primary", use_container_width=True)

        if submitted:
            if not name.strip():
                st.error("Reagent Name is required.")
            else:
                with st.spinner("Adding to Google Sheet..."):
                    try:
                        new_row = [
                            "",                     # id (leave blank → use formula =ROW()-1 in sheet if desired)
                            name.strip(),
                            cas_number.strip() if cas_number else "",
                            supplier.strip() if supplier else "",
                            location.strip() if location else "",
                            float(quantity),
                            unit,
                            expiration_date.strftime("%Y-%m-%d") if expiration_date else "",
                            float(low_stock_threshold),
                            # notes if you add "notes" column later
                        ]

                        conn.insert_rows(
                            new_row,
                            worksheet="template"
                        )

                        st.success(f"**{name}** added successfully!")
                        load_reagents.clear()
                        st.rerun()

                    except Exception as e:
                        st.error(f"Failed to add reagent:\n{str(e)}")

# ── Log Usage Tab ───────────────────────────────────────────────────────────
with tab_log:
    st.header("Log Usage / Dispense")

    if reagents_df.empty:
        st.info("No reagents available yet.")
    else:
        reagent_names = [""] + reagents_df["name"].tolist()
        selected_name = st.selectbox("Select Reagent", options=reagent_names)

        if selected_name:
            row = reagents_df[reagents_df["name"] == selected_name].iloc[0]
            current_qty = float(row["quantity"])
            unit = row["unit"]
            reagent_id = row["id"]

            st.metric("Current Stock", f"{current_qty:.2f} {unit}")

            with st.form("log_usage_form"):
                col1, col2 = st.columns([3, 2])
                with col1:
                    used_qty = st.number_input(
                        "Amount used / dispensed *",
                        min_value=0.01,
                        max_value=current_qty,
                        value=min(1.0, current_qty),
                        step=0.1,
                        format="%.2f"
                    )
                with col2:
                    st.selectbox("Unit", [unit], disabled=True)

                reason = st.text_input("Purpose / Experiment / User (optional)")

                submitted = st.form_submit_button("📉 Log & Update Stock", type="primary")

                if submitted:
                    if used_qty > current_qty:
                        st.error("Cannot dispense more than current stock!")
                    else:
                        new_quantity = current_qty - used_qty

                        with st.spinner("Updating stock..."):
                            try:
                                # Find row index (1-based: header + data offset)
                                df_idx = reagents_df[reagents_df["name"] == selected_name].index[0]
                                sheet_row = df_idx + 2  # header is row 1

                                # Find quantity column index (1-based)
                                qty_col_idx = reagents_df.columns.get_loc("quantity") + 1
                                cell_range = f"{chr(64 + qty_col_idx)}{sheet_row}"

                                conn.update_data(
                                    worksheet="template",
                                    range=cell_range,
                                    values=[[new_quantity]]
                                )

                                st.success(f"Stock updated → **{new_quantity:.2f} {unit}** remaining")
                                load_reagents.clear()
                                st.rerun()

                            except Exception as e:
                                st.error(f"Update failed: {str(e)}\nTry refreshing the app.")

# ── QR Tools & Admin Tabs (placeholders) ────────────────────────────────────
with tab_qr:
    st.header("QR Tools")
    st.info("QR code generation & scanning coming soon...")

with tab_admin:
    if st.session_state.role != "admin":
        st.error("Admin access only", icon="🔒")
    else:
        st.header("Admin Dashboard")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Reagents", len(reagents_df))
        col2.metric("Low Stock Items", sum(1 for a in alerts if "Low Stock" in a))
        col3.metric("Expired Items", sum(1 for a in alerts if "Expired" in a))
        st.info("More admin features (bulk edit, export, audit log) can be added here.")

st.caption("Laboratory Reagent Inventory • January 2026 • Powered by Streamlit + Google Sheets")

