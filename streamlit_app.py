# streamlit_app.py - Laboratory Reagent Inventory System
# Single-file version (no external modules)
# Full CRUD using Google Sheets API v4
# Multi-user hardening: soft-lock + audit log (optional sheets)
# Location dropdown + CustomEntry
# Scan & Add: Camera + Bulletproof Uploader (stores bytes in session_state)
# OCR: Cloud OCR-ready hooks + local parser; preview is Streamlit-version-safe
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
import re
import io
import base64

import requests

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# Pillow optional (preview + optional local crop; OCR can be cloud)
PIL_AVAILABLE = True
try:
    from PIL import Image
except Exception:
    PIL_AVAILABLE = False
    Image = None

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
WORKSHEET_INVENTORY = "template"   # inventory tab name
WORKSHEET_LOCKS = "locks"         # optional locks tab (recommended)
WORKSHEET_AUDIT = "audit_log"     # optional audit tab (recommended)

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
st.caption("Streamlit + Google Sheets API v4 • Multi-user CRUD • Mobile Scan & Add")

# ─────────────────────────────────────────────────────────────────────────────
# STREAMLIT VERSION SAFE UI HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def st_image_safe(img, caption=None):
    """Works on old and new Streamlit (use_container_width vs use_column_width)."""
    try:
        st.image(img, caption=caption, use_container_width=True)
    except TypeError:
        st.image(img, caption=caption, use_column_width=True)

def st_dataframe_safe(df, **kwargs):
    """Works on old and new Streamlit (use_container_width vs use_column_width)."""
    try:
        st.dataframe(df, use_container_width=True, **kwargs)
    except TypeError:
        st.dataframe(df, use_column_width=True, **kwargs)

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

def NA(v) -> str:
    v = "" if v is None else str(v).strip()
    return v if v else "N/A"

def location_widget(label: str, value: str, key: str) -> str:
    default_idx = LOCATION_CHOICES.index(value) if value in LOCATION_CHOICES else LOCATION_CHOICES.index("CustomEntry")
    choice = st.selectbox(label, LOCATION_CHOICES, index=default_idx, key=f"{key}_choice")
    if choice == "CustomEntry":
        custom = st.text_input("Custom location", value=value if value not in LOCATION_CHOICES else "", key=f"{key}_custom")
        return custom.strip()
    return choice

# ─────────────────────────────────────────────────────────────────────────────
# CLOUD OCR (Google Vision) - optional usage
# ─────────────────────────────────────────────────────────────────────────────
def vision_available() -> bool:
    
    return bool(st.secrets.get("gcp_vision", {}).get("api_key", ""))

def vision_text_detection(image_bytes: bytes) -> dict:
    """Google Vision TEXT_DETECTION using API key in secrets: [gcp_vision] api_key=..."""
    r = requests.post(url, json=payload, timeout=25)
r.raise_for_status()
return r.json()
    api_key = st.secrets["gcp_vision"]["api_key"]
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
    payload = {
        "requests": [{
            "image": {"content": b64},
            "features": [{"type": "TEXT_DETECTION"}]
        }]
    }
    
    
    r = requests.post(url, json=payload, timeout=25)
    r.raise_for_status()
    return r.json()

def vision_extract_full_text(resp_json: dict) -> str:
    try:
        ann = resp_json["responses"][0].get("textAnnotations", [])
        return ann[0]["description"] if ann else ""
    except Exception:
        return ""

def vision_compute_text_bbox(resp_json: dict):
    """
    Compute bbox around detected word boxes (excludes full-page annotation).
    Returns (min_x, min_y, max_x, max_y) or None.
    """
    try:
        ann = resp_json["responses"][0].get("textAnnotations", [])
        if len(ann) <= 1:
            return None
        xs, ys = [], []
        for a in ann[1:]:
            poly = a.get("boundingPoly", {}).get("vertices", [])
            for v in poly:
                if "x" in v and "y" in v:
                    xs.append(int(v["x"]))
                    ys.append(int(v["y"]))
        if not xs or not ys:
            return None
        return (min(xs), min(ys), max(xs), max(ys))
    except Exception:
        return None

def autocrop_bytes_using_vision(image_bytes: bytes, margin_ratio: float = 0.06) -> bytes:
    """
    Auto-crop based on Vision bbox. Requires Pillow for actual crop.
    If Pillow not available or bbox not found, returns original bytes.
    """
    if not (PIL_AVAILABLE and vision_available()):
        return image_bytes

    resp = vision_text_detection(image_bytes)
    bbox = vision_compute_text_bbox(resp)
    if not bbox:
        return image_bytes

    try:
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        x0, y0, x1, y1 = bbox

        mx = int(w * margin_ratio)
        my = int(h * margin_ratio)

        x0 = max(0, x0 - mx)
        y0 = max(0, y0 - my)
        x1 = min(w, x1 + mx)
        y1 = min(h, y1 + my)

        if x1 - x0 < 40 or y1 - y0 < 40:
            return image_bytes

        cropped = img.crop((x0, y0, x1, y1))
        out = io.BytesIO()
        cropped.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return image_bytes

# ─────────────────────────────────────────────────────────────────────────────
# PARSING (CAS, supplier, expiration; missing => N/A)
# ─────────────────────────────────────────────────────────────────────────────
def _find_first(patterns, text, flags=re.IGNORECASE):
    for p in patterns:
        m = re.search(p, text, flags)
        if m:
            return m.group(1).strip()
    return None

def parse_reagent_fields(text: str) -> dict:
    """Best-effort parser; fills missing values with N/A. Uses cas_number only."""
    t = " ".join(text.split())

    cas = _find_first(
        [
            r"CAS[:\s]*([0-9]{2,7}-[0-9]{2}-[0-9])",
            r"CAS\s*No\.?[:\s]*([0-9]{2,7}-[0-9]{2}-[0-9])",
        ],
        t
    )

    supplier = _find_first(
        [
            r"(?:Supplier|Manufacturer|Mfr\.?)[:\s]*([A-Za-z0-9 &\-\.,]+)",
        ],
        t
    )

    exp_raw = _find_first(
        [
            r"(?:Exp(?:iration)?|Expiry|Use\s*By|Best\s*Before)[:\s]*([0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2})",
            r"(?:Exp(?:iration)?|Expiry|Use\s*By|Best\s*Before)[:\s]*([0-9]{1,2}[-/][0-9]{1,2}[-/][0-9]{2,4})",
        ],
        t
    )

    exp_iso = ""
    if exp_raw:
        dt = pd.to_datetime(exp_raw, errors="coerce")
        if pd.notnull(dt):
            exp_iso = dt.date().isoformat()

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    name_guess = "N/A"
    for ln in lines[:10]:
        if len(ln) >= 4 and not re.fullmatch(r"[A-Z0-9\-_]+", ln):
            name_guess = ln
            break

    return {
        "id": "N/A",
        "name": NA(name_guess),
        "cas_number": NA(cas),
        "supplier": NA(supplier),
        "location": "N/A",
        "quantity": "0",
        "unit": "N/A",
        "expiration_date": exp_iso if exp_iso else "N/A",
    }

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

def sheet_exists(sheet_title: str) -> bool:
    try:
        get_sheet_id_by_title(sheet_title)
        return True
    except Exception:
        return False

LOCKS_ENABLED = sheet_exists(WORKSHEET_LOCKS)
AUDIT_ENABLED = sheet_exists(WORKSHEET_AUDIT)

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

st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})", icon="👤")

# ─────────────────────────────────────────────────────────────────────────────
# LOCKS (soft-lock)
# ─────────────────────────────────────────────────────────────────────────────
def try_lock_row(rownum: int, user: str, purpose: str, lease_seconds=90) -> bool:
    if not LOCKS_ENABLED:
        return True

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

        if locked_until_dt > now and locked_by and locked_by != user:
            return False

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
    if not AUDIT_ENABLED:
        return
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
    result = with_retries(lambda: sheets.values().get(spreadsheetId=SPREADSHEET_ID, range=READ_RANGE).execute())
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

    for c in EXPECTED_COLS:
        if c not in df.columns:
            df[c] = ""

    df["_row"] = [i + 2 for i in range(len(df))]
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0.0)
    df["low_stock_threshold"] = pd.to_numeric(df["low_stock_threshold"], errors="coerce").fillna(10.0)
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
# ALERTS (NaT-safe)
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
# SCAN IMAGE STORAGE (prevents uploader/camera from disappearing on rerun)
# ─────────────────────────────────────────────────────────────────────────────
def set_scan_image_bytes(b: bytes, source: str, meta: dict):
    st.session_state["scan_image_bytes"] = b
    st.session_state["scan_image_source"] = source
    st.session_state["scan_image_meta"] = meta

def clear_scan_image_bytes():
    st.session_state.pop("scan_image_bytes", None)
    st.session_state.pop("scan_image_source", None)
    st.session_state.pop("scan_image_meta", None)

# ─────────────────────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────────────────────
tab_catalog, tab_add, tab_scan, tab_admin = st.tabs(["📋 Catalog", "➕ Add", "📷 Scan & Add", "🛠 Admin"])

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
        st_dataframe_safe(df_view.drop(columns=["_row"], errors="ignore"), hide_index=True)

        st.subheader("Row actions (Edit / Delete)")
        for _, r in df_view.iterrows():
            rownum = int(r.get("_row", 0))
            name = str(r.get("name", "") or "(no name)")

            with st.expander(f"{name} • sheet row {rownum}", expanded=False):
                cols = st.columns([3, 1])

                with cols[0]:
                    with st.form(f"edit_{rownum}"):
                        name2 = st.text_input("Name", value=str(r.get("name", "")))
                        cas2 = st.text_input("CAS Number", value=str(r.get("cas_number", "")))
                        sup2 = st.text_input("Supplier", value=str(r.get("supplier", "")))
                        loc2 = location_widget("Location", value=str(r.get("location", "")), key=f"loc_{rownum}")
                        qty2 = st.number_input("Quantity", min_value=0.0, value=float(r.get("quantity", 0.0) or 0.0), step=0.1)
                        unit2 = st.text_input("Unit", value=str(r.get("unit", "")))

                        exp_val = r.get("expiration_date")
                        has_exp = st.checkbox("Has expiration date", value=pd.notnull(exp_val), key=f"hasexp_{rownum}")
                        exp2 = st.date_input(
                            "Expiration date",
                            value=(exp_val if pd.notnull(exp_val) else date.today()),
                            key=f"exp_{rownum}"
                        ) if has_exp else None

                        low2 = st.number_input("Low stock threshold", min_value=0.0, value=float(r.get("low_stock_threshold", 10.0) or 10.0), step=1.0)

                        if st.form_submit_button("💾 Save row", type="primary"):
                            if not try_lock_row(rownum, st.session_state.username, "edit"):
                                st.error("This row is being edited by someone else. Try again in ~1 minute.")
                                st.stop()

                            updates = {
                                "name": NA(name2),
                                "cas_number": NA(cas2),
                                "supplier": NA(sup2),
                                "location": NA(loc2),
                                "quantity": str(qty2),
                                "unit": NA(unit2),
                                "expiration_date": (exp2.isoformat() if exp2 else "N/A"),
                                "low_stock_threshold": str(low2),
                            }
                            update_row_cells(rownum, updates)
                            audit("UPDATE", rownum, NA(name2), json.dumps(updates, ensure_ascii=False))
                            st.success("Row updated.")
                            load_inventory.clear()
                            st.rerun()

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
            if NA(new_name) == "N/A":
                st.error("Name is required (cannot be blank).")
                st.stop()

            payload = {
                "id": NA(new_id),
                "name": NA(new_name),
                "cas_number": NA(new_cas),
                "supplier": NA(new_supplier),
                "location": NA(new_location),
                "quantity": str(new_qty),
                "unit": NA(new_unit),
                "expiration_date": (new_exp.isoformat() if new_exp else "N/A"),
                "low_stock_threshold": str(new_low),
            }
            append_row(payload)
            audit("CREATE", 0, payload["name"], json.dumps(payload, ensure_ascii=False))
            st.success("Reagent added.")
            load_inventory.clear()
            st.rerun()

# ── Scan & Add ──────────────────────────────────────────────────────────────

with tab_scan:
    st.header("📷 Scan & Add (Mobile-first)")
    st.write("Step 1: Take a photo (recommended) or upload. Step 2: OCR (cloud) → auto-fill. Step 3: Add.")

    if not vision_available():
        st.warning(
            "Cloud OCR is not configured. Add to Streamlit Secrets:\n\n"
            "[gcp_vision]\napi_key = \"YOUR_GOOGLE_VISION_API_KEY\"\n\n"
            "You can still capture/upload and manually fill fields below.",
            icon="⚠️"
        )
# st.write("Streamlit:", st.__version__)
# st.write("Cloud OCR configured:", vision_available())

    # Big buttons for phone scanning
    st.markdown("### Step 1 — Capture / Upload")

    cam = st.camera_input("📸 Take a photo of the label (best on phone)", key="scan_cam")
    if cam is not None:
        b = cam.getvalue()
        set_scan_image_bytes(
            b,
            source="camera",
            meta={"filename": "camera.jpg", "mime_type": getattr(cam, "type", "image/jpeg"), "size_bytes": len(b)}
        )
        st.success("Camera image captured ✅ (stored for this session)")

    up = st.file_uploader(
        "⬆️ Or upload a photo (JPG/PNG recommended)",
        type=["jpg", "jpeg", "png", "heic", "heif"],
        accept_multiple_files=False,
        key="scan_uploader",
    )
    if up is not None:
        b = up.getvalue()
        set_scan_image_bytes(
            b,
            source="upload",
            meta={"filename": up.name, "mime_type": up.type, "size_bytes": up.size}
        )
        st.success("File received ✅ (stored for this session)")
        st.write(st.session_state.get("scan_image_meta"))

    image_bytes = st.session_state.get("scan_image_bytes")

    if image_bytes:
        st.markdown("### Preview")
        if PIL_AVAILABLE:
            try:
                img = Image.open(io.BytesIO(image_bytes))
                st_image_safe(img, caption=f"Source: {st.session_state.get('scan_image_source','?')}")
            except Exception as e:
                st.error(f"Cannot open image for preview (preview only). Error: {e}")
        else:
            st.info("Pillow not available → skipping preview (OCR can still run).")

        st.markdown("### Step 2 — OCR (Cloud)")

        cols = st.columns([1, 1])
        with cols[0]:
            auto_crop = st.checkbox("🧪 Auto-crop label before OCR (improves accuracy)", value=True, disabled=(not PIL_AVAILABLE or not vision_available()))
        with cols[1]:
            show_ocr = st.checkbox("Show OCR text (debug)", value=False)

        if st.button("🔎 Run Cloud OCR", type="primary", use_container_width=True, disabled=not vision_available()):
            try:
                with st.spinner("Running Vision OCR..."):
                    bytes_for_ocr = autocrop_bytes_using_vision(image_bytes) if auto_crop else image_bytes
                    resp = vision_text_detection(bytes_for_ocr)
                    text = vision_extract_full_text(resp)

                st.session_state["ocr_text"] = text
                st.session_state["scan_fields"] = parse_reagent_fields(text)
                st.success('OCR complete. Review fields below (missing values are "N/A").')

                # If we cropped and can preview, show cropped preview
                if auto_crop and PIL_AVAILABLE and bytes_for_ocr != image_bytes:
                    try:
                        img2 = Image.open(io.BytesIO(bytes_for_ocr))
                        st_image_safe(img2, caption="Auto-cropped image used for OCR")
                    except Exception:
                        pass

                if show_ocr:
                    st.text_area("OCR output", text, height=200)

            except Exception as e:
                st.error(f"OCR failed: {e}")

        st.markdown("### Step 3 — Review & Add")

        fields = st.session_state.get("scan_fields") or {
            "id": "N/A", "name": "N/A", "cas_number": "N/A", "supplier": "N/A",
            "location": "N/A", "quantity": "0", "unit": "N/A", "expiration_date": "N/A"
        }

        with st.form("scan_add_form"):
            c1, c2, c3 = st.columns(3)

            with c1:
                scan_id = st.text_input("ID", value=fields.get("id", "N/A"))
                scan_name = st.text_input("Name", value=fields.get("name", "N/A"))
                scan_cas = st.text_input("CAS Number", value=fields.get("cas_number", "N/A"))

            with c2:
                scan_supplier = st.text_input("Supplier", value=fields.get("supplier", "N/A"))
                scan_location = location_widget("Location", value=fields.get("location", "N/A"), key="scan_loc")
                scan_unit = st.text_input("Unit", value=fields.get("unit", "N/A"))

            with c3:
                try:
                    qty_default = float(fields.get("quantity", "0") or 0)
                except Exception:
                    qty_default = 0.0
                scan_qty = st.number_input("Quantity", min_value=0.0, value=qty_default, step=0.1)

                scan_low = st.number_input("Low stock threshold", min_value=0.0, value=10.0, step=1.0)

                exp_str = fields.get("expiration_date", "N/A")
                has_exp = st.checkbox("Has expiration date?", value=(exp_str != "N/A"))
                scan_exp = None
                if has_exp:
                    dt = pd.to_datetime(exp_str, errors="coerce")
                    scan_exp = st.date_input("Expiration date", value=(dt.date() if pd.notnull(dt) else date.today()))

            if st.form_submit_button("➕ Add reagent", type="primary", use_container_width=True):
                if NA(scan_name) == "N/A":
                    st.error("Name is required. Please type it if OCR missed it.")
                    st.stop()

                payload = {
                    "id": NA(scan_id),
                    "name": NA(scan_name),
                    "cas_number": NA(scan_cas),
                    "supplier": NA(scan_supplier),
                    "location": NA(scan_location),
                    "quantity": str(scan_qty),
                    "unit": NA(scan_unit),
                    "expiration_date": (scan_exp.isoformat() if scan_exp else "N/A"),
                    "low_stock_threshold": str(scan_low),
                }

                append_row(payload)
                audit("CREATE_SCAN", 0, payload["name"], json.dumps(payload, ensure_ascii=False))

                st.success("Reagent added from scan.")
                load_inventory.clear()
                st.session_state.pop("scan_fields", None)
                st.session_state.pop("ocr_text", None)
                clear_scan_image_bytes()
                st.rerun()

        c = st.columns([1, 1, 1])
        with c[0]:
            if st.button("🧹 Clear image + OCR", use_container_width=True):
                clear_scan_bytes()
                clear_scan_image_bytes()
                st.rerun()
        with c[1]:
            st.caption("Tip: For best OCR, fill the screen with the label, good lighting, no glare.")
        with c[2]:
            pass
    else:
        st.info("No image stored yet. Use Camera or Upload above.")

# ── Admin ───────────────────────────────────────────────────────────────────
with tab_admin:
    st.header("Admin")

    st.subheader("Runtime info")
    st.write("Streamlit version:", st.__version__)
    st.write("Pillow available:", PIL_AVAILABLE)
    st.write("Cloud OCR configured:", vision_available())
    st.write("Locks sheet enabled:", LOCKS_ENABLED)
    st.write("Audit sheet enabled:", AUDIT_ENABLED)

    st.subheader("Secrets required for Cloud OCR")
    st.code('[gcp_vision]\napi_key = "YOUR_GOOGLE_VISION_API_KEY"\n', language="toml")

    st.subheader("Recommended sheet headers")
    st.code(
        "Inventory (template) header row:\n"
        + " | ".join(EXPECTED_COLS)
        + "\n\nLocks (locks) header row:\n"
          "row | locked_by | locked_until_iso | purpose\n\n"
          "Audit (audit_log) header row:\n"
          "ts_iso | user | role | action | row | reagent_name | details\n",
        language="text"
    )

st.caption("Laboratory Reagent Inventory • January 2026")










