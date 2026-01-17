# streamlit_app.py - Laboratory Reagent Inventory System (revised Jan 2026)
import streamlit as st
import pandas as pd
from datetime import date, datetime
import hashlib
from PIL import Image
import os
from pathlib import Path

try:
    import pytesseract
except ImportError:
    pytesseract = None

try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3

# For Streamlit Cloud
TESSERACT_PATH = '/usr/bin/tesseract'
if pytesseract:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")

DB_FILE = "reagents.db"

# ── Preset Locations ────────────────────────────────────────────────────────
LOCATION_PRESETS = [
    "Scooby-Doo", "Shaggy", "Fred", "Daphne", "Velma", "Scrappy-Doo",
    "Tom", "Jerry",
    "Custom input"
]

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 username TEXT UNIQUE NOT NULL,
                 password_hash TEXT NOT NULL,
                 role TEXT NOT NULL)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS reagents (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 name TEXT NOT NULL,
                 cas_number TEXT,
                 supplier TEXT,
                 location TEXT NOT NULL,
                 quantity REAL NOT NULL,
                 unit TEXT NOT NULL,
                 expiration_date TEXT,
                 low_stock_threshold REAL DEFAULT 1.0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS usage_logs (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 reagent_id INTEGER,
                 user TEXT,
                 quantity_used REAL,
                 timestamp TEXT,
                 notes TEXT)''')
    
    # Better hashing recommended in future (scrypt / argon2)
    hashed_admin = hashlib.sha256("admin123".encode()).hexdigest()
    hashed_user  = hashlib.sha256("user123".encode()).hexdigest()
    
    c.execute("INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
              ("admin", hashed_admin, "admin"))
    c.execute("INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
              ("user", hashed_user, "user"))
    
    conn.commit()
    conn.close()

init_db()

# ── Session state & Auth ────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.role = None

if not st.session_state.authenticated:
    st.subheader("🔐 Login Required")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT role FROM users WHERE username=? AND password_hash=?",
                      (username, hashlib.sha256(password.encode()).hexdigest()))
            result = c.fetchone()
            conn.close()
            if result:
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.role = result[0]
                st.success(f"Welcome, {username}! ({result[0].capitalize()})")
                st.rerun()
            else:
                st.error("Invalid username or password")
    st.stop()

if st.sidebar.button("🚪 Logout"):
    for key in ["authenticated", "username", "role"]:
        st.session_state.pop(key, None)
    st.rerun()

st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})")

# ── Tab persistence ─────────────────────────────────────────────────────────
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Catalog"

# ── Load data ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_reagents():
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query("SELECT * FROM reagents ORDER BY name", conn)
        conn.close()
        if not df.empty:
            df['expiration_date'] = pd.to_datetime(df['expiration_date'], errors='coerce').dt.date
        return df
    except:
        return pd.DataFrame(columns=['id','name','cas_number','supplier','location','quantity','unit','expiration_date','low_stock_threshold'])

reagents_df = load_reagents()

# ── Alerts ──────────────────────────────────────────────────────────────────
alerts = []
today = date.today()
for _, row in reagents_df.iterrows():
    threshold = row.get('low_stock_threshold', 1.0)
    if row['quantity'] <= threshold:
        alerts.append(f"⚠️ **Low Stock**: {row['name']} — {row['quantity']:.2f} {row['unit']} (threshold: {threshold})")
    if pd.notnull(row['expiration_date']) and row['expiration_date'] < today:
        alerts.append(f"❌ **Expired**: {row['name']} ({row['expiration_date']})")

if alerts:
    st.warning("\n\n".join(alerts))

# ── Tabs ────────────────────────────────────────────────────────────────────
tab_names = ["Catalog", "Add Reagent", "Log Usage", "QR Tools", "Admin"]
active_index = tab_names.index(st.session_state.active_tab) if st.session_state.active_tab in tab_names else 0
tab1, tab2, tab3, tab4, tab5 = st.tabs(tab_names)

# ── Catalog ─────────────────────────────────────────────────────────────────
with tab1:
    st.header("Reagent Catalog")
    search = st.text_input("🔍 Search by Name, CAS, or Location")

    display_df = reagents_df
    if search:
        display_df = reagents_df[
            reagents_df['name'].str.contains(search, case=False, na=False) |
            reagents_df['cas_number'].str.contains(search, case=False, na=False) |
            reagents_df['location'].str.contains(search, case=False, na=False)
        ]

    if display_df.empty:
        st.info("No reagents found.")
    else:
        if st.session_state.role == "admin":
            editable_df = display_df.copy()
            editable_df["Edit"] = False
            editable_df["Delete"] = False

            edited_df = st.data_editor(
                editable_df,
                column_config={
                    "Edit": st.column_config.CheckboxColumn("Edit", default=False),
                    "Delete": st.column_config.CheckboxColumn("Delete", default=False),
                    "quantity": st.column_config.NumberColumn(format="%.2f"),
                    "low_stock_threshold": st.column_config.NumberColumn(format="%.1f"),
                },
                hide_index=True,
                use_container_width=True,
                key="catalog_editor"
            )

            # ── Handle Edit ─────────────────────────────────────────────────
            to_edit = edited_df[edited_df["Edit"] == True]["id"].unique().tolist()
            if to_edit:
                edit_id = to_edit[0]  # take first one for simplicity
                reagent = reagents_df[reagents_df['id'] == edit_id].iloc[0]

                with st.expander(f"✏️ Edit: {reagent['name']} (ID: {edit_id})", expanded=True):
                    e_name = st.text_input("Name*", value=reagent['name'])
                    e_cas = st.text_input("CAS Number", value=reagent['cas_number'] or "")
                    e_supplier = st.text_input("Supplier", value=reagent['supplier'] or "")

                    # ── Unified Location selector (same as Add) ─────────────
                    current_loc = reagent['location']
                    if current_loc in LOCATION_PRESETS[:-1]:  # exclude "Custom input"
                        loc_index = LOCATION_PRESETS.index(current_loc)
                    else:
                        loc_index = len(LOCATION_PRESETS) - 1  # Custom input

                    e_location_preset = st.selectbox(
                        "Location*",
                        options=LOCATION_PRESETS,
                        index=loc_index,
                        help="Select a preset or choose 'Custom input'"
                    )

                    e_custom_location = ""
                    if e_location_preset == "Custom input":
                        e_custom_location = st.text_input(
                            "Custom location*",
                            value=current_loc if current_loc not in LOCATION_PRESETS[:-1] else "",
                            placeholder="e.g., Cabinet B - Shelf 4, Freezer -80°C"
                        )

                    final_location = e_custom_location.strip() if e_location_preset == "Custom input" else e_location_preset

                    e_quantity = st.number_input("Quantity", value=float(reagent['quantity']), step=0.01, min_value=0.0)
                    e_unit = st.selectbox("Unit", ["g","mg","ml","L","bottles","vials","kg"], index=["g","mg","ml","L","bottles","vials","kg"].index(reagent['unit']))
                    e_exp = st.date_input("Expiration Date", value=reagent['expiration_date'] if pd.notnull(reagent['expiration_date']) else None)
                    e_threshold = st.number_input("Low Stock Threshold", value=float(reagent.get('low_stock_threshold', 1.0)), min_value=0.0, step=0.1)

                    if st.button("Save Changes", type="primary"):
                        if not e_name.strip():
                            st.error("Name is required.")
                        elif not final_location:
                            st.error("Location is required.")
                        elif e_exp and e_exp < today:
                            st.error(f"Cannot save: Expiration date is in the past ({today}).")
                        else:
                            conn = sqlite3.connect(DB_FILE)
                            c = conn.cursor()
                            c.execute("""UPDATE reagents SET
                                        name=?, cas_number=?, supplier=?, location=?,
                                        quantity=?, unit=?, expiration_date=?, low_stock_threshold=?
                                        WHERE id=?""",
                                      (e_name.strip(), e_cas or None, e_supplier or None, final_location,
                                       e_quantity, e_unit, str(e_exp) if e_exp else None, e_threshold, edit_id))
                            conn.commit()
                            conn.close()
                            st.success("Reagent updated!")
                            st.cache_data.clear()
                            st.rerun()

            # ── Handle Delete ───────────────────────────────────────────────
            to_delete = edited_df[edited_df["Delete"] == True]["id"].tolist()
            if to_delete and st.button("🗑️ Confirm Delete Selected", type="primary"):
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                for rid in to_delete:
                    c.execute("DELETE FROM reagents WHERE id = ?", (rid,))
                conn.commit()
                conn.close()
                st.success(f"Deleted {len(to_delete)} reagent(s)!")
                st.cache_data.clear()
                st.rerun()

        else:
            st.dataframe(display_df.style.format({"quantity": "{:.2f}"}), use_container_width=True)
            st.info("Only admin users can edit or delete reagents.")

# ── Add Reagent (rest remains mostly unchanged, just using same LOCATION_PRESETS) ──
with tab2:
    st.header("Add Reagent")

    # ... (bulk Excel import section remains the same)

    st.markdown("---")

    with st.form(key=f"add_form_{st.session_state.get('add_form_key', 0)}"):
        col1, col2 = st.columns(2)
        
        name = col1.text_input("Name*", help="Required")
        cas = col1.text_input("CAS Number")
        supplier = col2.text_input("Supplier")

        location_preset = col2.selectbox(
            "Location*",
            options=LOCATION_PRESETS,
            help="Select a preset or choose 'Custom input' to enter your own"
        )

        custom_location = ""
        if location_preset == "Custom input":
            custom_location = col2.text_input(
                "Custom location*",
                value="",
                placeholder="e.g., Cabinet B - Shelf 4, Freezer -80°C, Cold Room 4°C"
            )

        final_location = custom_location.strip() if location_preset == "Custom input" else location_preset

        quantity = col1.number_input("Initial Quantity*", min_value=0.0, step=0.01)
        unit = col1.selectbox("Unit", ["g", "mg", "ml", "L", "bottles", "vials", "kg"])
        exp_date = col2.date_input("Expiration Date", value=None)
        threshold = col2.number_input("Low Stock Threshold", value=1.0, min_value=0.0, step=0.1)

        submitted = st.form_submit_button("Add Reagent", type="primary")

        if submitted:
            errors = []
            if not name.strip():
                errors.append("Name is required.")
            if not final_location:
                errors.append("Location is required.")

            if errors:
                for err in errors:
                    st.error(err)
            else:
                if exp_date and exp_date < today:
                    st.warning(f"Note: Expiration date is in the past or today ({exp_date}).")
                
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("""INSERT INTO reagents
                            (name, cas_number, supplier, location, quantity, unit, expiration_date, low_stock_threshold)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                          (name.strip(), cas or None, supplier or None, final_location,
                           quantity, unit, str(exp_date) if exp_date else None, threshold))
                conn.commit()
                conn.close()
                
                st.success(f"Added **{name.strip()}** at **{final_location}**")
                st.session_state['add_form_key'] = st.session_state.get('add_form_key', 0) + 1
                st.cache_data.clear()
                st.rerun()

    # ... (OCR section remains the same)

# ── Other tabs (Log Usage, QR Tools, Admin) remain unchanged for now ────────

st.caption("Laboratory Reagent Inventory • Streamlit • January 2026")
