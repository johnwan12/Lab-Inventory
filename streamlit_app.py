# streamlit_app.py - Laboratory Reagent Inventory System
# Updated: default Low Stock Threshold = 2

import streamlit as st
import pandas as pd
from datetime import date, datetime
import qrcode
from io import BytesIO
import hashlib
import easyocr
from PIL import Image
import numpy as np

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
                 low_stock_threshold REAL DEFAULT 2.0)''')  # Changed default to 2.0
    
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

# Authentication (unchanged)
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
@st.cache_data(ttl=30)
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

# Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Catalog", "Add Reagent", "Log Usage", "QR Tools", "Admin"])

# Catalog (admin-only edit & delete)
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
            editable_df["Edit"]   = False
            
            edited_df = st.data_editor(
                editable_df,
                column_config={
                    "Edit":   st.column_config.CheckboxColumn("Edit",   help="Check to edit",   default=False),
                    "Delete": st.column_config.CheckboxColumn("Delete", help="Check to delete", default=False),
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
            
            # Edit logic (unchanged)
            to_edit = edited_df[edited_df["Edit"] == True]["id"].tolist()
            if to_edit:
                edit_id = to_edit[0]
                reagent = reagents_df[reagents_df['id'] == edit_id].iloc[0]
                
                with st.expander(f"✏️ Edit: {reagent['name']} (ID: {edit_id})", expanded=True):
                    e_name      = st.text_input("Name", value=reagent['name'])
                    e_cas       = st.text_input("CAS Number", value=reagent['cas_number'] or "")
                    e_supplier  = st.text_input("Supplier", value=reagent['supplier'] or "")
                    e_location  = st.text_input("Location", value=reagent['location'])
                    e_quantity  = st.number_input("Quantity", value=float(reagent['quantity']), step=0.1, min_value=0.0)
                    e_unit      = st.selectbox("Unit", ["g","mg","ml","L","bottles","vials","kg"], index=["g","mg","ml","L","bottles","vials","kg"].index(reagent['unit']))
                    e_exp       = st.date_input("Expiration Date", value=reagent['expiration_date'] if pd.notnull(reagent['expiration_date']) else None)
                    e_threshold = st.number_input("Low Stock Threshold", value=float(reagent['low_stock_threshold']), min_value=0.0)
                    
                    if st.button("Save Changes", type="primary"):
                        today = date.today()
                        if e_exp and e_exp < today:
                            st.error(f"Cannot save: Expiration date is in the past.")
                        else:
                            conn = sqlite3.connect(DB_FILE)
                            c = conn.cursor()
                            c.execute("""UPDATE reagents SET
                                        name=?, cas_number=?, supplier=?, location=?,
                                        quantity=?, unit=?, expiration_date=?, low_stock_threshold=?
                                        WHERE id=?""",
                                      (e_name, e_cas or None, e_supplier or None, e_location,
                                       e_quantity, e_unit, str(e_exp) if e_exp else None, e_threshold, edit_id))
                            conn.commit()
                            conn.close()
                            st.success("Updated!")
                            st.cache_data.clear()
                            st.rerun()
            
            # Delete logic (unchanged)
            to_delete = edited_df[edited_df["Delete"] == True]["id"].tolist()
            if to_delete:
                st.warning(f"Selected {len(to_delete)} item(s) for deletion.")
                if st.button("🗑️ Confirm Delete", type="primary"):
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
            st.info("Only admin can edit/delete.")

# Add Reagent – with default low stock threshold = 2
with tab2:
    st.header("Add Reagent")
    
    # Bulk Excel import (unchanged)
    st.subheader("Bulk Add from Excel")
    uploaded_excel = st.file_uploader("Upload Excel (.xlsx/.xls)", type=["xlsx", "xls"])
    
    if uploaded_excel is not None:
        try:
            df_excel = pd.read_excel(uploaded_excel)
            df_excel.columns = df_excel.columns.str.strip().str.lower()
            
            rename_map = {
                'item': 'name',
                'supplier item identifier': 'cas_number',
            }
            df_excel = df_excel.rename(columns=rename_map)
            
            keep_cols = ['name', 'cas_number', 'supplier']
            available_cols = [c for c in keep_cols if c in df_excel.columns]
            preview_df = df_excel[available_cols].copy()
            
            st.write("Preview (first 10 rows):")
            st.dataframe(preview_df.head(10), use_container_width=True)
            
            if 'name' not in preview_df.columns:
                st.error("Excel must contain a column named 'Item' (case insensitive).")
            else:
                if st.button("Confirm Import All Valid Rows", type="primary"):
                    conn = sqlite3.connect(DB_FILE)
                    c = conn.cursor()
                    imported = 0
                    
                    for _, row in df_excel.iterrows():
                        name = str(row.get('name', '')).strip()
                        if not name:
                            continue
                        
                        cas = str(row.get('cas_number', '')).strip() or None
                        supplier = str(row.get('supplier', '')).strip() or None
                        
                        location = "Default Location"
                        quantity = 1.0
                        unit = "bottles"
                        exp_date = None
                        threshold = 2.0  # Default low stock threshold = 2
                        
                        c.execute("""INSERT INTO reagents 
                                    (name, cas_number, supplier, location, quantity, unit, expiration_date, low_stock_threshold)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                                  (name, cas, supplier, location, quantity, unit,
                                   str(exp_date) if exp_date else None, threshold))
                        imported += 1
                    
                    conn.commit()
                    conn.close()
                    
                    st.success(f"Imported {imported} reagents successfully!")
                    st.cache_data.clear()
                    st.rerun()
        except Exception as e:
            st.error(f"Error reading Excel: {str(e)}")
    
    st.markdown("---")
    
    # Single entry form – default low stock threshold = 2
    if "add_form_key" not in st.session_state:
        st.session_state.add_form_key = 0
    
    with st.form(key=f"add_form_{st.session_state.add_form_key}"):
        col1, col2 = st.columns(2)
        
        name = col1.text_input("Name*", help="Required")
        cas = col1.text_input("CAS Number")
        supplier = col2.text_input("Supplier")
        
        location_preset = col2.selectbox(
            "Location*",
            options=["Scrappy-Doo", "Daphne", "Tom", "Jerry", "Scooby-Doo", "Velma", "Custom input"]
        )
        
        custom_location = ""
        if location_preset == "Custom input":
            custom_location = col2.text_input("Custom Location", placeholder="e.g., Cabinet B - Shelf 4")
        
        final_location = custom_location.strip() if location_preset == "Custom input" else location_preset
        
        quantity = col1.number_input("Initial Quantity*", min_value=0.0, step=0.1)
        unit = col1.selectbox("Unit", ["g", "mg", "ml", "L", "bottles", "vials", "kg"])
        
        exp_date = col2.date_input("Expiration Date", value=None)
        
        today = date.today()
        if exp_date:
            if exp_date < today:
                st.error(f"⚠️ Warning: Expiration date ({exp_date}) already passed! (Today: {today})")
            elif exp_date == today:
                st.warning(f"⚠️ Note: Expires today ({exp_date}).")
        
        threshold = col2.number_input("Low Stock Threshold", value=2.0, min_value=0.0)  # Changed default to 2.0

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

    # Photo OCR (unchanged)
    st.subheader("Quick Entry via Photo (OCR)")
    photo = st.camera_input("Take photo") or st.file_uploader("Upload photo", type=["jpg","png","jpeg"])
    if photo:
        st.image(photo, width=400)
        with st.spinner("OCR..."):
            try:
                reader = easyocr.Reader(['en'], gpu=False)
                result = reader.readtext(np.array(Image.open(photo)), detail=0)
                text = " ".join(result).upper()
                st.text_area("Extracted Text", text, height=100)
                st.info("Copy relevant info to the form above.")
            except Exception as e:
                st.error(f"OCR failed: {str(e)}")

# Log Reagent Usage (unchanged)
with tab3:
    st.header("Log Reagent Usage")
    if reagents_df.empty:
        st.warning("No reagents in inventory yet.")
        st.info("Please add some reagents first in the 'Add Reagent' tab.")
        if st.button("Refresh Inventory"):
            st.cache_data.clear()
            st.rerun()
    else:
        current_reagents = load_reagents()
        
        reagent_options = current_reagents['id'].tolist()
        reagent_labels = [
            f"{row['name']} (ID: {row['id']}) – {row['quantity']:.2f} {row['unit']} left"
            for _, row in current_reagents.iterrows()
        ]
        
        selected_id = st.selectbox(
            "Select Reagent",
            options=reagent_options,
            format_func=lambda x: next((l for i,l in zip(reagent_options, reagent_labels) if i == x), str(x)),
            key="log_usage_select"
        )
        
        if selected_id:
            row = current_reagents[current_reagents['id'] == selected_id].iloc[0]
            
            col1, col2 = st.columns(2)
            qty_used = col1.number_input(
                "Quantity Used",
                min_value=0.01,
                max_value=float(row['quantity']),
                step=0.1,
                value=0.01,
                help=f"Available: {row['quantity']:.2f} {row['unit']}"
            )
            notes = col2.text_area("Notes (optional)", height=80)
            
            if st.button("Record Usage", type="primary"):
                if qty_used > row['quantity']:
                    st.error("Cannot use more than available quantity!")
                else:
                    try:
                        conn = sqlite3.connect(DB_FILE)
                        c = conn.cursor()
                        c.execute("UPDATE reagents SET quantity = quantity - ? WHERE id = ?",
                                  (qty_used, selected_id))
                        c.execute("INSERT INTO usage_logs (reagent_id, user, quantity_used, timestamp, notes) VALUES (?, ?, ?, ?, ?)",
                                  (selected_id, st.session_state.username, qty_used, datetime.now().isoformat(), notes))
                        conn.commit()
                        conn.close()
                        
                        st.success(f"Usage logged! Deducted {qty_used} {row['unit']} from {row['name']}.")
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error logging usage: {str(e)}")

# QR Tools & Admin (simplified)
with tab4:
    st.header("QR Code Tools")
    if reagents_df.empty:
        st.info("Add reagents first.")
    else:
        selected_id = st.selectbox("Select Reagent", reagents_df['id'],
                                  format_func=lambda x: reagents_df[reagents_df['id']==x]['name'].values[0])
        row = reagents_df[reagents_df['id'] == selected_id].iloc[0]
        
        app_url = st.text_input("App URL", "https://your-app.streamlit.app")
        qr_data = f"{app_url}?reagent_id={selected_id}"
        
        qr = qrcode.QRCode(version=1, error_correction=qrcode.ERROR_CORRECT_L, box_size=3, border=2)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        img.save(buf, "PNG")
        byte_im = buf.getvalue()
        
        st.image(byte_im)
        st.download_button("Download QR", byte_im, f"QR_{row['name']}_{selected_id}.png", "image/png")

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
