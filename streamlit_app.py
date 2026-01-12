# streamlit_app.py - Laboratory Reagent Inventory System
# Added: warning if expiration date is past or today

import streamlit as st
import pandas as pd
from datetime import date, datetime
import qrcode
from io import BytesIO
import hashlib
import easyocr
from PIL import Image
import numpy as np

# SQLite compatibility for Streamlit Cloud
try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")

DB_FILE = "reagents.db"

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
                 low_stock_threshold REAL DEFAULT 10.0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS usage_logs (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 reagent_id INTEGER,
                 user TEXT,
                 quantity_used REAL,
                 timestamp TEXT,
                 notes TEXT)''')
    
    hashed_admin = hashlib.sha256("admin123".encode()).hexdigest()
    hashed_user = hashlib.sha256("user123".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
              ("admin", hashed_admin, "admin"))
    c.execute("INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
              ("user", hashed_user, "user"))
    
    conn.commit()
    conn.close()

init_db()

# Authentication
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.role = None

if not st.session_state.authenticated:
    st.subheader("🔐 Login Required")
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        if submitted:
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
        del st.session_state[key]
    st.rerun()

st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})")

# Load Reagents
@st.cache_data(ttl=60)
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

# Alerts
alerts = []
today = date.today()
for _, row in reagents_df.iterrows():
    if row['quantity'] <= row['low_stock_threshold']:
        alerts.append(f"⚠️ **Low Stock**: {row['name']} — {row['quantity']:.2f} {row['unit']}")
    if pd.notnull(row['expiration_date']) and row['expiration_date'] < today:
        alerts.append(f"❌ **Expired**: {row['name']} ({row['expiration_date']})")

if alerts:
    st.warning("\n\n".join(alerts))

# Define Tabs FIRST!
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Catalog", "Add Reagent", "Log Usage", "QR Tools", "Admin"])

# Catalog (admin-only delete)
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
            editable_df["Delete"] = False
            
            edited_df = st.data_editor(
                editable_df,
                column_config={
                    "Delete": st.column_config.CheckboxColumn("Delete", help="Check to delete (Admin only)", default=False),
                    "id": "ID",
                    "name": "Name",
                    "cas_number": "CAS Number",
                    "supplier": "Supplier",
                    "location": "Location",
                    "quantity": st.column_config.NumberColumn("Quantity", format="%.2f"),
                    "unit": "Unit",
                    "expiration_date": "Expiration Date",
                    "low_stock_threshold": "Low Stock Threshold",
                },
                hide_index=True,
                use_container_width=True,
                key="catalog_editor"
            )
            
            to_delete = edited_df[edited_df["Delete"] == True]["id"].tolist()
            if to_delete:
                st.warning(f"Selected {len(to_delete)} reagent(s) for deletion.")
                if st.button("🗑️ Confirm Delete Selected", type="primary"):
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
            st.info("Only admin users can delete reagents.")

# Add Reagent - with expiration date warning
with tab2:
    st.header("Add New Reagent")
    
    if "add_form_key" not in st.session_state:
        st.session_state.add_form_key = 0
    
    with st.form(key=f"add_form_{st.session_state.add_form_key}"):
        col1, col2 = st.columns(2)
        
        name = col1.text_input("Name*", help="Required")
        cas = col1.text_input("CAS Number")
        supplier = col2.text_input("Supplier")
        
        location_preset = col2.selectbox(
            "Location*",
            options=[
                "Scrappy-Doo", "Daphne", "Tom", "Jerry",
                "Scooby-Doo", "Velma", "Custom input"
            ]
        )
        
        custom_location = ""
        if location_preset == "Custom input":
            custom_location = col2.text_input("Custom Location", placeholder="e.g., Cabinet B - Shelf 4")
        
        final_location = custom_location.strip() if location_preset == "Custom input" else location_preset
        
        quantity = col1.number_input("Initial Quantity*", min_value=0.0, step=0.1)
        unit = col1.selectbox("Unit", ["g", "mg", "ml", "L", "bottles", "vials", "kg"])
        
        exp_date = col2.date_input("Expiration Date", value=None)
        
        # Expiration date warning
        today = date.today()
        if exp_date:
            if exp_date < today:
                st.error(f"⚠️ Warning: Expiration date ({exp_date}) is already past! "
                         f"(Today is {today}) This reagent may be expired.")
            elif exp_date == today:
                st.warning(f"⚠️ Note: Expiration date is today ({exp_date}). "
                           "Consider using or discarding soon.")
        
        threshold = col2.number_input("Low Stock Threshold", value=10.0, min_value=0.0)

        submitted = st.form_submit_button("Add Reagent")
        if submitted:
            if not name.strip() or not final_location:
                st.error("Name and Location are required!")
            else:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("""INSERT INTO reagents 
                            (name, cas_number, supplier, location, quantity, unit, expiration_date, low_stock_threshold)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                          (name, cas or None, supplier or None, final_location, quantity, unit,
                           str(exp_date) if exp_date else None, threshold))
                conn.commit()
                conn.close()
                
                st.success(f"Added '{name}' successfully!")
                st.session_state.add_form_key += 1
                st.cache_data.clear()
                st.rerun()

    # Photo OCR
    st.subheader("Quick Entry via Photo (OCR)")
    photo = st.camera_input("Take photo") or st.file_uploader("Upload photo", type=["jpg","png","jpeg"])
    if photo:
        st.image(photo, width=400)
        with st.spinner("OCR..."):
            try:
                reader = easyocr.Reader(['en'], gpu=False)
                result = reader.readtext(np.array(Image.open(photo)), detail=0)
                text = " ".join(result).upper()
                st.text_area("Extracted", text, height=100)
                st.info("Copy relevant info to the form above.")
            except Exception as e:
                st.error(f"OCR failed: {str(e)}")

# Other tabs unchanged
with tab3:
    st.header("Log Reagent Usage")
    # ... your existing log usage code ...

with tab4:
    st.header("QR Code Tools")
    # ... your existing QR code code ...

with tab5:
    if st.session_state.role != "admin":
        st.error("Admin access only")
    else:
        st.header("Admin Dashboard")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Reagents", len(reagents_df))
        col2.metric("Low Stock", len([a for a in alerts if "Low" in a]))
        col3.metric("Expired", len([a for a in alerts if "Expired" in a]))

st.caption("Laboratory Reagent Inventory • Streamlit • January 2026")
