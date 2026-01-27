# streamlit_app.py - Laboratory Reagent Inventory System
# Full CRUD using Google Sheets API v4 (no st-gsheets-connection)
# Revised: January 2026

import streamlit as st
import pandas as pd
from datetime import date
import hashlib
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ─────────────────────────────────────────────────────────────────────────────
# App config
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")
st.caption("Streamlit + Google Sheets API v4 • Full CRUD operations")

WORKSHEET = "template"  # <-- your sheet tab name

EXPECTED_COLS = [
    "id", "name", "cas_number", "supplier", "location",
    "quantity", "unit", "expiration_date", "low_stock_threshold"
]

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def colnum_to_a1(n: int) -> str:
    """1 -> A, 2 -> B, 27 -> AA ..."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

@st.cache_resource(show_spinner="Connecting to Google Sheets...")
def get_sheets_service():
    try:
        sa_info = st.secrets["google_service_account"]
        creds = Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        service = build("sheets", "v4", credentials=creds).spreadsheets()

        # Works on Streamlit Cloud secrets TOML like:
        # [connections.gsheets]
        # spreadsheet = "YOUR_SHEET_ID"
        spreadsheet_id = st.secrets["connections"]["gsheets"]["spreadsheet"]
        return service, spreadsheet_id
    except KeyError as e:
        st.error(f"Missing secrets key: {e}\n\nPlease check Streamlit Cloud Secrets.")
        st.stop()
    except Exception as e:
        st.error(f"Failed to initialize Sheets service: {str(e)}")
        st.stop()

def get_sheet_id_by_title(sheet_title: str) -> int:
    meta = sheets_service.get(spreadsheetId=SPREADSHEET_ID).execute()
    for s in meta.get("sheets", []):
        props = s.get("properties", {})
        if props.get("title") == sheet_title:
            return int(props.get("sheetId"))
    raise ValueError(f"Sheet tab '{sheet_title}' not found. Check WORKSHEET.")

def build_header_map(headers: list[str]) -> dict[str, int]:
    """Return mapping header->1-based column index."""
    return {h: i + 1 for i, h in enumerate(headers) if str(h).strip() != ""}

def safe_str(x) -> str:
    return "" if x is None else str(x)

# ─────────────────────────────────────────────────────────────────────────────
# Init Sheets
# ─────────────────────────────────────────────────────────────────────────────
sheets_service, SPREADSHEET_ID = get_sheets_service()

# ─────────────────────────────────────────────────────────────────────────────
# Authentication (simple demo)
# ─────────────────────────────────────────────────────────────────────────────
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

st.sidebar.success(
    f"Logged in as **{st.session_state.username}** ({st.session_state.role})",
    icon="👤",
)

# ─────────────────────────────────────────────────────────────────────────────
# Load data + header mapping
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner="Loading inventory...")
def load_reagents():
    # Read big range; resize if needed
    read_range = f"{WORKSHEET}!A1:Z5000"
    result = sheets_service.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=read_range
    ).execute()

    values = result.get("values", [])
    if not values:
        return pd.DataFrame(), {}, []

    headers = [safe_str(x).strip() for x in values[0]]
    header_map = build_header_map(headers)

    data = values[1:]
    # Normalize row length to headers
    norm = []
    for row in data:
        row = list(row)
        if len(row) < len(headers):
            row += [""] * (len(headers) - len(row))
        norm.append(row[:len(headers)])

    df = pd.DataFrame(norm, columns=headers)

    # Ensure expected columns exist (create empty if missing)
    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = ""

    # Stable sheet row mapping (row 1 header)
    df["_row"] = [i + 2 for i in range(len(df))]

    # Type cleanup
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)
    df["low_stock_threshold"] = pd.to_numeric(df["low_stock_threshold"], errors="coerce").fillna(10.0)
    df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce").dt.date

    # Keep only expected + _row in display df
    df = df[EXPECTED_COLS + ["_row"]]

    return df, header_map, headers

reagents_df, HEADER_MAP, RAW_HEADERS = load_reagents()

# Precompute letters for expected cols if they exist in sheet
COL_LETTER = {}
for c in EXPECTED_COLS:
    if c in HEADER_MAP:
        COL_LETTER[c] = colnum_to_a1(HEADER_MAP[c])

# ─────────────────────────────────────────────────────────────────────────────
# Alerts
# ─────────────────────────────────────────────────────────────────────────────
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

# ─────────────────────────────────────────────────────────────────────────────
# CRUD functions
# ─────────────────────────────────────────────────────────────────────────────
def update_row_cells(rownum: int, updates: dict):
    """Update individual cells in a given sheet row."""
    for col, val in updates.items():
        if col not in COL_LETTER:
            # Column missing in sheet header
            continue
        a1 = f"{WORKSHEET}!{COL_LETTER[col]}{rownum}"
        sheets_service.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=a1,
            valueInputOption="RAW",
            body={"values": [[val]]},
        ).execute()

def append_row(values_by_col: dict):
    """Append new reagent row using the sheet's header order."""
    # Ensure header exists
    if not RAW_HEADERS:
        raise ValueError("Sheet has no header row. Put headers in row 1 first.")

    new_row = []
    for h in RAW_HEADERS:
        if h in EXPECTED_COLS:
            new_row.append(values_by_col.get(h, ""))
        else:
            # for non-expected columns, append blank
            new_row.append("")
    sheets_service.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{WORKSHEET}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [new_row]},
    ).execute()

def delete_sheet_row(rownum: int):
    sheet_id = get_sheet_id_by_title(WORKSHEET)
    sheets_service.batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={
            "requests": [{
                "deleteDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "startIndex": rownum - 1,  # 0-based
                        "endIndex": rownum
                    }
                }
            }]
        }
    ).execute()

# ─────────────────────────────────────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────────────────────────────────────
tab_catalog, tab_add, tab_log, tab_qr, tab_admin = st.tabs([
    "📋 Catalog", "➕ Add", "📉 Log Usage", "🔲 QR", "🛠 Admin"
])

# ── Catalog ────────────────────────────────────────────────────────────────
with tab_catalog:
    st.header("Reagent Catalog")

    if not HEADER_MAP:
        st.error(
            "Your sheet header row is missing or unreadable.\n\n"
            "Row 1 must contain column names like: "
            + ", ".join(EXPECTED_COLS)
        )
        st.stop()

    search = st.text_input("Search", "")
    df_view = reagents_df.copy()

    if search and not df_view.empty:
        search_df = df_view.drop(columns=["_row"], errors="ignore").astype(str)
        mask = search_df.apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)
        df_view = df_view[mask].reset_index(drop=True)

    if df_view.empty:
        st.info("No matching reagents.")
    else:
        st.dataframe(
            df_view.drop(columns=["_row"], errors="ignore"),
            use_container_width=True,
            hide_index=True
        )

        st.subheader("Row actions (Edit / Delete)")

        # If some expected columns are missing in sheet header, warn once
        missing_cols = [c for c in EXPECTED_COLS if c not in HEADER_MAP]
        if missing_cols:
            st.warning(
                "These columns are missing from your sheet header, so they cannot be edited/written:\n"
                + ", ".join(missing_cols)
            )

        for _, r in df_view.iterrows():
            rownum = int(r.get("_row", 0))
            name = safe_str(r.get("name", "")).strip() or "(no name)"

            if rownum <= 1:
                continue

            with st.expander(f"{name} • sheet row {rownum}", expanded=False):
                cols = st.columns([3, 1])

                # LEFT: edit
                with cols[0]:
                    with st.form(f"edit_{rownum}"):
                        name2 = st.text_input("Name", value=safe_str(r.get("name", "")))
                        cas2 = st.text_input("CAS Number", value=safe_str(r.get("cas_number", "")))
                        sup2 = st.text_input("Supplier", value=safe_str(r.get("supplier", "")))
                        loc2 = st.text_input("Location", value=safe_str(r.get("location", "")))

                        qty2 = st.number_input(
                            "Quantity",
                            min_value=0.0,
                            value=float(r.get("quantity", 0.0) or 0.0),
                            step=0.1,
                        )
                        unit2 = st.text_input("Unit", value=safe_str(r.get("unit", "")))

                        exp_val = r.get("expiration_date")
                        has_exp = st.checkbox(
                            "Has expiration date",
                            value=pd.notnull(exp_val),
                            key=f"hasexp_{rownum}",
                        )
                        exp2 = None
                        if has_exp:
                            exp2 = st.date_input(
                                "Expiration Date",
                                value=exp_val if pd.notnull(exp_val) else date.today(),
                                key=f"exp_{rownum}",
                            )

                        low2 = st.number_input(
                            "Low stock threshold",
                            min_value=0.0,
                            value=float(r.get("low_stock_threshold", 10.0) or 10.0),
                            step=1.0,
                        )

                        if st.form_submit_button("💾 Save row", type="primary"):
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
                            update_row_cells(rownum, updates)
                            st.success("Row updated.")
                            load_reagents.clear()
                            st.rerun()

                # RIGHT: delete
                with cols[1]:
                    st.write("")
                    confirm = st.checkbox("Confirm delete", key=f"confirm_del_{rownum}")
                    if st.button("🗑️ Delete row", key=f"del_{rownum}", disabled=not confirm):
                        delete_sheet_row(rownum)
                        st.success("Row deleted.")
                        load_reagents.clear()
                        st.rerun()

# ── Add ─────────────────────────────────────────────────────────────────────
with tab_add:
    st.header("Add New Reagent")

    with st.form("add_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            new_id = st.text_input("ID", value="")
            new_name = st.text_input("Name", value="")
            new_cas = st.text_input("CAS Number", value="")
        with c2:
            new_supplier = st.text_input("Supplier", value="")
            new_location = st.text_input("Location", value="")
            new_unit = st.text_input("Unit", value="mL")
        with c3:
            new_qty = st.number_input("Quantity", min_value=0.0, value=0.0, step=0.1)
            new_low = st.number_input("Low stock threshold", min_value=0.0, value=10.0, step=1.0)
            has_exp = st.checkbox("Has expiration date?", value=False)
            new_exp = st.date_input("Expiration date", value=date.today()) if has_exp else None

        if st.form_submit_button("➕ Add reagent", type="primary", use_container_width=True):
            if not new_name.strip():
                st.error("Name is required.")
            else:
                payload = {
                    "id": new_id.strip(),
                    "name": new_name.strip(),
                    "cas_number": new_cas.strip(),
                    "supplier": new_supplier.strip(),
                    "location": new_location.strip(),
                    "quantity": str(new_qty),
                    "unit": new_unit.strip(),
                    "expiration_date": new_exp.isoformat() if new_exp else "",
                    "low_stock_threshold": str(new_low),
                }
                try:
                    append_row(payload)
                    st.success("Reagent added.")
                    load_reagents.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to add reagent: {e}")

# ── Log Usage (placeholder) ─────────────────────────────────────────────────
with tab_log:
    st.header("Log Usage")
    st.info("Placeholder tab. Add your usage log form + write to another worksheet or a log sheet.")

# ── QR (placeholder) ────────────────────────────────────────────────────────
with tab_qr:
    st.header("QR")
    st.info("Placeholder tab. Add QR scan/upload and auto-fill reagent form here.")

# ── Admin (placeholder) ─────────────────────────────────────────────────────
with tab_admin:
    st.header("Admin")
    st.write("Secrets check:")
    st.code(
        "Expect secrets:\n"
        "- [google_service_account]\n"
        "- [connections.gsheets] spreadsheet = '...'\n",
        language="text",
    )
    st.write("Sheet config:")
    st.write({"WORKSHEET": WORKSHEET, "SPREADSHEET_ID_prefix": SPREADSHEET_ID[:8] + "..."})

st.caption("Laboratory Reagent Inventory • January 2026")
