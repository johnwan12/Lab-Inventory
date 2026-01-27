# streamlit_app.py - Laboratory Reagent Inventory System
# Full CRUD using Google Sheets API v4 (no st-gsheets-connection)
# Revised: January 2026

import streamlit as st
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

        values = result.get("values", [])
        if not values:
            return pd.DataFrame()

        headers = values[0]
        data = values[1:]
        df = pd.DataFrame(data, columns=headers)

        # ✅ stable sheet row number mapping (row 1 is header)
        df["_row"] = [i + 2 for i in range(len(df))]

        expected = [
            "id", "name", "cas_number", "supplier", "location",
            "quantity", "unit", "expiration_date", "low_stock_threshold"
        ]

        keep_cols = [c for c in expected if c in df.columns]
        df = df[keep_cols + ["_row"]]

        if "expiration_date" in df.columns:
            df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce").dt.date

        if "quantity" in df.columns:
            df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)

        if "low_stock_threshold" in df.columns:
            df["low_stock_threshold"] = pd.to_numeric(df["low_stock_threshold"], errors="coerce").fillna(10.0)

        return df.sort_values("name", kind="stable").reset_index(drop=True)

    except Exception as e:
        st.error(f"Failed to load data: {str(e)}\n\nCheck: sheet ID, tab name, service account permissions")
        return pd.DataFrame()


# ── Alerts ──────────────────────────────────────────────────────────────────
reagents_df = pd.DataFrame()  # ✅ placeholder so later code won't NameError
reagents_df = load_reagents()

alerts = []
today = date.today()

if not reagents_df.empty:
    for _, row in reagents_df.iterrows():
        qty = float(row.get("quantity", 0) or 0)
        thresh = float(row.get("low_stock_threshold", 10.0) or 10.0)

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

    # KEEP _row for edit/delete mapping
    df_view = reagents_df.copy()

    # search only on visible columns, but don't remove _row
    if search and not df_view.empty:
        search_df = df_view.drop(columns=["_row"], errors="ignore").astype(str)
        mask = search_df.apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)
        df_view = df_view[mask].reset_index(drop=True)

    if df_view.empty:
        st.info("No matching reagents.")
    else:
        # (optional) show table WITHOUT _row
        st.dataframe(
            df_view.drop(columns=["_row"], errors="ignore").style.format(precision=2),
            use_container_width=True,
            hide_index=True
        )

        st.subheader("Row actions")
        for _, r in df_view.iterrows():
            rownum = int(r.get("_row", 0))
            if rownum == 0:
                st.error("Internal error: missing _row mapping. Ensure load_reagents() adds df['_row'].")
                break

            name = str(r.get("name", ""))
            with st.expander(f"{name} • sheet row {rownum}", expanded=False):
                # your edit + delete UI here
                st.write("...")


                # --- EDIT FORM ---
                with c1:
                    with st.form(f"edit_{rownum}"):
                        name2 = st.text_input("name", value=str(r.get("name", "")))
                        cas2 = st.text_input("cas_number", value=str(r.get("cas_number", "")))
                        sup2 = st.text_input("supplier", value=str(r.get("supplier", "")))
                        loc2 = st.text_input("location", value=str(r.get("location", "")))

                        qty2 = st.number_input("quantity", min_value=0.0, value=float(r.get("quantity", 0.0)), step=0.1)
                        unit2 = st.text_input("unit", value=str(r.get("unit", "")))

                        exp_val = r.get("expiration_date", None)
                        has_exp = st.checkbox("has expiration date", value=bool(pd.notnull(exp_val)), key=f"hasexp_{rownum}")
                        exp2 = st.date_input("expiration_date", value=exp_val if has_exp and pd.notnull(exp_val) else date.today(), key=f"exp_{rownum}") if has_exp else None

                        low2 = st.number_input("low_stock_threshold", min_value=0.0, value=float(r.get("low_stock_threshold", 10.0)), step=1.0)

                        save = st.form_submit_button("💾 Save row", type="primary")

                        if save:
                            updates = {
                                "name": name2.strip(),
                                "cas_number": cas2.strip(),
                                "supplier": sup2.strip(),
                                "location": loc2.strip(),
                                "quantity": str(qty2),
                                "unit": unit2.strip(),
                                "expiration_date": exp2.isoformat() if exp2 else "",
                                "low_stock_threshold": str(low2),
                            }

                            # write changed fields only
                            for col, val in updates.items():
                                if col not in HEADER_MAP:
                                    continue
                                col_letter = colnum_to_a1(HEADER_MAP[col])
                                range_name = f"{WORKSHEET}!{col_letter}{rownum}"
                                sheets.values().update(
                                    spreadsheetId=SPREADSHEET_ID,
                                    range=range_name,
                                    valueInputOption="RAW",
                                    body={"values": [[val]]},
                                ).execute()

                            st.success("Row saved.")
                            load_reagents.clear()
                            st.rerun()

                # --- DELETE BUTTON ---
                with c2:
                    st.write("")
                    st.write("")
                    if st.button("🗑️ Delete row", key=f"del_{rownum}"):
                        sheet_id = get_sheet_id_by_title(WORKSHEET)
                        sheets.batchUpdate(
                            spreadsheetId=SPREADSHEET_ID,
                            body={
                                "requests": [{
                                    "deleteDimension": {
                                        "range": {
                                            "sheetId": sheet_id,
                                            "dimension": "ROWS",
                                            "startIndex": rownum - 1,
                                            "endIndex": rownum
                                        }
                                    }
                                }]
                            }
                        ).execute()

                        st.success("Row deleted.")
                        load_reagents.clear()
                        st.rerun()

st.caption("Laboratory Reagent Inventory • January 2026")






