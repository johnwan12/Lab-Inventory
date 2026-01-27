# streamlit_app.py - Laboratory Reagent Inventory System
# Single-file version (no external modules)
# Full CRUD using Google Sheets API v4
# Hardened for multi-user labs (soft-lock + audit log)
# Location dropdown + CustomEntry
# Slack + Email alerts (optional)
# Revised: January 2026

import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import urllib.request
import smtplib
from email.message import EmailMessage
import time

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
WORKSHEET_INVENTORY = "template"   # inventory tab name
WORKSHEET_LOCKS = "locks"         # locks tab name (must exist)
WORKSHEET_AUDIT = "audit_log"     # audit tab name (must exist)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

EXPECTED_COLS = [
    "id", "name", "cas_number", "supplier", "location",
    "quantity", "unit", "expiration_date", "low_stock_threshold"
]

LOCATION_CHOICES = [
    "Scappy-Doo (-30c)",
    "Daphne (-30c)",
    "Tom (-80c)",
    "Jerry (-80c)",
    "Sammy (-80c)",
    "Scooby-Doo (-30c)",
    "Velma (4c)",
    "CustomEntry",
]

READ_RANGE = f"{WORKSHEET_INVENTORY}!A1:Z5000"

# ─────────────────────────────────────────────────────────────────────────────
# APP UI
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")
st.caption("Streamlit + Google Sheets API v4 • Multi-user CRUD • Alerts")

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def now_utc():
    return datetime.now(timezone.utc)

def with_retries(fn, tries=4, base_sleep=0.5):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(base_sleep * (2 ** i))
    raise last

def safe_str(x) -> str:
    return "" if x is None else str(x)

def colnum_to_a1(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

def build_header_map(headers: list[str]) -> dict[str, int]:
    return {h: i + 1 for i, h in enumerate(headers) if str(h).strip()}

def location_widget(label: str, value: str, key: str) -> str:
    default_idx = LOCATION_CHOICES.index(value) if value in LOCATION_CHOICES else LOCATION_CHOICES.index("CustomEntry")
    choice = st.selectbox(label, LOCATION_CHOICES, index=default_idx, key=f"{key}_choice")
    if choice == "CustomEntry":
        custom = st.text_input(
            "Custom location",
            value=value if value not in LOCATION_CHOICES else "",
            key=f"{key}_custom"
        )
        return custom.strip()
    return choice

# ─────────────────────────────────────────────────────────────────────────────
# NOTIFY (Slack + Email) — optional
# ─────────────────────────────────────────────────────────────────────────────
def send_slack(text: str):
    url = st.secrets.get("slack", {}).get("webhook_url", "")
    if not url:
        return
    payload = {"text": text}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)

def send_email(subject: str, body: str):
    cfg = st.secrets.get("email", {})
    host = cfg.get("smtp_host")
    port = int(cfg.get("smtp_port", 587))
    user = cfg.get("smtp_user")
    pwd  = cfg.get("smtp_pass")
    to   = cfg.get("to")
    if not (host and user and pwd and to):
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=15) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)

# ─────────────────────────────────────────────────────────────────────────────
# GOOGLE SHEETS INIT
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Connecting to Google Sheets...")
def get_sheets_service_and_id():
    sa_info = st.secrets["google_service_account"]
    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    svc = build("sheets", "v4", credentials=creds).spreadsheets()
    spreadsheet_id = st.secrets["connections"]["gsheets"]["spreadsheet"]
    return svc, spreadsheet_id

sheets, SPREADSHEET_ID = get_sheets_service_and_id()

def get_sheet_id_by_title(sheet_title: str) -> int:
    meta = with_retries(lambda: sheets.get(spreadsheetId=SPREADSHEET_ID).execute())
    for s in meta.get("sheets", []):
        props = s.get("properties", {})
        if props.get("title") == sheet_title:
            return int(props.get("sheetId"))
    raise ValueError(f"Sheet tab '{sheet_title}' not found. Check WORKSHEET_* constants.")

# ─────────────────────────────────────────────────────────────────────────────
# AUTH (demo)
# ─────────────────────────────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.role = None

if not st.session_state.authenticated:
    st.subheader("🔐 Login Required")
    with st.form("login_form", clear_on_submit=True):
        c1, c2 = st.columns([3, 2])
        with c1:
            username = st.text_input("Username")
        with c2:
            password = st.text_input("Password", type="password")

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
                st.error("Invalid username or password")
    st.stop()

if st.sidebar.button("🚪 Logout", use_container_width=True):
    for k in ["authenticated", "username", "role"]:
        st.session_state.pop(k, None)
    st.rerun()

st.sidebar.success(
    f"Logged in as **{st.session_state.username}** ({st.session_state.role})",
    icon="👤"
)

# ─────────────────────────────────────────────────────────────────────────────
# LOCKS (soft lock)
# ─────────────────────────────────────────────────────────────────────────────
def try_lock_row(rownum: int, user: str, purpose: str, lease_seconds=90) -> bool:
    rng = f"{WORKSHEET_LOCKS}!A1:D5000"
    res = with_retries(lambda: sheets.values().get(spreadsheetId=SPREADSHEET_ID, range=rng).execute())
    vals = res.get("values", [])
    locks = vals[1:] if len(vals) > 1 else []

    now = now_utc()
    until = now + timedelta(seconds=lease_seconds)
    until_iso = until.isoformat()

    for r in locks:
        if len(r) < 3:
            continue
        try:
            locked_row = int(r[0])
        except:
            continue
        if locked_row != rownum:
            continue

        locked_by = r[1] if len(r) > 1 else ""
        locked_until = r[2] if len(r) > 2 else ""
        try:
            locked_until_dt = datetime.fromisoformat(locked_until)
        except:
            locked_until_dt = now - timedelta(days=365)

        # Someone else holds a non-expired lock
        if locked_until_dt > now and locked_by and locked_by != user:
            return False

    # Append a lock record
    with_retries(lambda: sheets.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{WORKSHEET_LOCKS}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [[str(rownum), user, until_iso, purpose]]},
    ).execute())
    return True

# ─────────────────────────────────────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────────────────────────────────────
def audit(action: str, row: int, reagent_name: str, details: str):
    ts = now_utc().isoformat()
    with_retries(lambda: sheets.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{WORKSHEET_AUDIT}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [[ts, st.session_state.username, st.session_state.role, action, str(row), reagent_name, details]]},
    ).execute())

# ─────────────────────────────────────────────────────────────────────────────
# LOAD INVENTORY
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=120, show_spinner="Loading inventory...")
def load_inventory():
    result = with_retries(lambda: sheets.values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=READ_RANGE
    ).execute())

    values = result.get("values", [])
    if not values:
        return pd.DataFrame(), {}, []

    headers = [safe_str(x).strip() for x in values[0]]
    header_map = build_header_map(headers)

    data = values[1:]
    norm = []
    for row in data:
        row = list(row)
        if len(row) < len(headers):
            row += [""] * (len(headers) - len(row))
        norm.append(row[:len(headers)])

    df = pd.DataFrame(norm, columns=headers)

    # Ensure expected columns exist
    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = ""

    # Sheet row number mapping (row 1 is header)
    df["_row"] = [i + 2 for i in range(len(df))]

    # Types
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)
    df["low_stock_threshold"] = pd.to_numeric(df["low_stock_threshold"], errors="coerce").fillna(10.0)

    # expiration_date becomes python date OR NaT; guard later with pd.notnull
    df["expiration_date"] = pd.to_datetime(df["expiration_date"], errors="coerce").dt.date

    df = df[EXPECTED_COLS + ["_row"]]
    return df, header_map, headers

reagents_df, HEADER_MAP, RAW_HEADERS = load_inventory()

# ─────────────────────────────────────────────────────────────────────────────
# CRUD OPS
# ─────────────────────────────────────────────────────────────────────────────
def update_row_cells(rownum: int, updates: dict):
    for col, val in updates.items():
        if col not in HEADER_MAP:
            continue
        letter = colnum_to_a1(HEADER_MAP[col])
        a1 = f"{WORKSHEET_INVENTORY}!{letter}{rownum}"
        with_retries(lambda: sheets.values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=a1,
            valueInputOption="RAW",
            body={"values": [[val]]},
        ).execute())

def append_row(values_by_col: dict):
    if not RAW_HEADERS:
        raise ValueError("Sheet header row missing in inventory sheet.")
    row = []
    for h in RAW_HEADERS:
        row.append(values_by_col.get(h, "") if h in values_by_col else "")
    with_retries(lambda: sheets.values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{WORKSHEET_INVENTORY}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute())

def delete_row(rownum: int):
    sheet_id = get_sheet_id_by_title(WORKSHEET_INVENTORY)
    with_retries(lambda: sheets.batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [{"deleteDimension": {"range": {
            "sheetId": sheet_id,
            "dimension": "ROWS",
            "startIndex": rownum - 1,
            "endIndex": rownum
        }}}]}
    ).execute())

# ─────────────────────────────────────────────────────────────────────────────
# ALERTS (FIXED NaT comparisons)
# ─────────────────────────────────────────────────────────────────────────────
def build_alerts(df: pd.DataFrame):
    low, expired = [], []
    today = date.today()

    if df.empty:
        return low, expired

    for _, row in df.iterrows():
        name = str(row.get("name", "") or "?")
        unit = str(row.get("unit", "") or "?")
        qty = float(row.get("quantity", 0) or 0)
        thresh = float(row.get("low_stock_threshold", 10) or 10)

        if qty <= thresh:
            low.append(f"{name}: {qty:.2f} {unit} (threshold {thresh:.2f})")

        exp = row.get("expiration_date")

        # ✅ Robust: handle NaT/NaN/None safely
        if pd.notnull(exp):
            exp_date = exp.date() if hasattr(exp, "date") else exp
            if exp_date < today:
                expired.append(f"{name}: expired {exp_date}")

    return low, expired

low_alerts, expired_alerts = build_alerts(reagents_df)

if low_alerts or expired_alerts:
    parts = []
    if low_alerts:
        parts.append("⚠️ **Low stock**\n" + "\n".join([f"- {x}" for x in low_alerts]))
    if expired_alerts:
        parts.append("❌ **Expired**\n" + "\n".join([f"- {x}" for x in expired_alerts]))
    st.warning("\n\n".join(parts), icon="🚨")

# ─────────────────────────────────────────────────────────────────────────────
# UI TABS
# ─────────────────────────────────────────────────────────────────────────────
tab_catalog, tab_add, tab_admin = st.tabs(["📋 Catalog", "➕ Add", "🛠 Admin"])

# ── Catalog ─────────────────────────────────────────────────────────────────
with tab_catalog:
    st.header("Reagent Catalog")
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
        for _, r in df_view.iterrows():
            rownum = int(r.get("_row", 0))
            name = str(r.get("name", "") or "(no name)")

            with st.expander(f"{name} • sheet row {rownum}", expanded=False):
                cols = st.columns([3, 1])

                # EDIT
                with cols[0]:
                    with st.form(f"edit_{rownum}"):
                        name2 = st.text_input("Name", value=str(r.get("name", "")))
                        cas2 = st.text_input("CAS Number", value=str(r.get("cas_number", "")))
                        sup2 = st.text_input("Supplier", value=str(r.get("supplier", "")))

                        loc2 = location_widget("Location", value=str(r.get("location", "")), key=f"loc_{rownum}")

                        qty2 = st.number_input(
                            "Quantity",
                            min_value=0.0,
                            value=float(r.get("quantity", 0.0) or 0.0),
                            step=0.1
                        )
                        unit2 = st.text_input("Unit", value=str(r.get("unit", "")))

                        exp_val = r.get("expiration_date")
                        has_exp = st.checkbox("Has expiration date", value=pd.notnull(exp_val), key=f"hasexp_{rownum}")
                        exp2 = st.date_input(
                            "Expiration date",
                            value=(exp_val if pd.notnull(exp_val) else date.today()),
                            key=f"exp_{rownum}"
                        ) if has_exp else None

                        low2 = st.number_input(
                            "Low stock threshold",
                            min_value=0.0,
                            value=float(r.get("low_stock_threshold", 10.0) or 10.0),
                            step=1.0
                        )

                        if st.form_submit_button("💾 Save row", type="primary"):
                            if not try_lock_row(rownum, st.session_state.username, "edit"):
                                st.error("This row is being edited by someone else. Try again in ~1 minute.")
                                st.stop()

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
                            audit("UPDATE", rownum, name2, json.dumps(updates, ensure_ascii=False))

                            st.success("Row updated.")
                            load_inventory.clear()
                            st.rerun()

                # DELETE (admin only)
                with cols[1]:
                    if st.session_state.role != "admin":
                        st.info("Delete: admin only")
                    else:
                        confirm = st.checkbox("Confirm delete", key=f"confirm_del_{rownum}")
                        if st.button("🗑️ Delete row", key=f"del_{rownum}", disabled=not confirm):
                            if not try_lock_row(rownum, st.session_state.username, "delete"):
                                st.error("This row is being edited by someone else. Try again in ~1 minute.")
                                st.stop()

                            delete_row(rownum)
                            audit("DELETE", rownum, name, "deleted row")

                            st.success("Row deleted.")
                            load_inventory.clear()
                            st.rerun()

# ── Add ─────────────────────────────────────────────────────────────────────
with tab_add:
    st.header("Add New Reagent")
    with st.form("add_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            new_id = st.text_input("ID", "")
            new_name = st.text_input("Name", "")
            new_cas = st.text_input("CAS Number", "")
        with c2:
            new_supplier = st.text_input("Supplier", "")
            new_location = location_widget("Location", value="", key="add_loc")
            new_unit = st.text_input("Unit", "mL")
        with c3:
            new_qty = st.number_input("Quantity", min_value=0.0, value=0.0, step=0.1)
            new_low = st.number_input("Low stock threshold", min_value=0.0, value=10.0, step=1.0)
            has_exp = st.checkbox("Has expiration date?", value=False)
            new_exp = st.date_input("Expiration date", value=date.today()) if has_exp else None

        if st.form_submit_button("➕ Add reagent", type="primary", use_container_width=True):
            if not new_name.strip():
                st.error("Name is required.")
                st.stop()

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

            append_row(payload)
            audit("CREATE", 0, new_name, json.dumps(payload, ensure_ascii=False))

            st.success("Reagent added.")
            load_inventory.clear()
            st.rerun()

# ── Admin ───────────────────────────────────────────────────────────────────
with tab_admin:
    st.header("Admin")

    if st.session_state.role != "admin":
        st.info("Admin only")
    else:
        st.subheader("Send alerts now (optional)")
        if st.button("Send Slack + Email alerts"):
            lines = []
            if low_alerts:
                lines.append("LOW STOCK:\n" + "\n".join(low_alerts))
            if expired_alerts:
                lines.append("EXPIRED:\n" + "\n".join(expired_alerts))
            msg = "\n\n".join(lines) if lines else "No alerts."

            try:
                send_slack(msg)
            except Exception as e:
                st.warning(f"Slack not sent: {e}")

            try:
                send_email("Lab Inventory Alerts", msg)
            except Exception as e:
                st.warning(f"Email not sent: {e}")

            st.success("Done (sent if configured).")

        st.subheader("Secrets check")
        st.write("Has Slack webhook:", bool(st.secrets.get("slack", {}).get("webhook_url")))
        st.write("Has Email config:", bool(st.secrets.get("email", {}).get("smtp_user")))

st.caption("Laboratory Reagent Inventory • January 2026")
