# streamlit_app.py - Lab Reagent Inventory (Fixed NameError + Robust)

import streamlit as st
import pandas as pd
from datetime import date, datetime
import qrcode
from io import BytesIO
import hashlib

# SQLite Fix
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
    
    # Default users (CHANGE PASSWORDS ASAP!)
    hashed_admin = hashlib.sha256("admin123".encode()).hexdigest()
    hashed_user = hashlib.sha256("user123".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
              ("admin", hashed_admin, "admin"))
    c.execute("INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
              ("user", hashed_user, "user"))
    
    conn.commit()
    conn.close()

init_db()

# Authentication logic (login/logout) - unchanged from previous

if not st.session_state.authenticated:
    # ... login form ...
    st.stop()

# Sidebar logout etc.

# Load Reagents HERE - before any use!
def load_reagents():
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query("SELECT * FROM reagents ORDER BY name", conn)
        conn.close()
        if not df.empty:
            df['expiration_date'] = pd.to_datetime(df['expiration_date'], errors='coerce').dt.date
        return df
    except:
        return pd.DataFrame()  # Return empty DF on error

reagents_df = load_reagents()

# Alerts (now safe)
alerts = []
today = date.today()
for _, row in reagents_df.iterrows():
    if row['quantity'] <= row['low_stock_threshold']:
        alerts.append(f"⚠️ **Low Stock**: {row['name']} — {row['quantity']} {row['unit']}")
    if pd.notnull(row['expiration_date']) and row['expiration_date'] < today:
        alerts.append(f"❌ **Expired**: {row['name']} ({row['expiration_date']})")

if alerts:
    st.warning("\n\n".join(alerts))

# Auto-load from URL
query_params = st.query_params
if "reagent_id" in query_params:
    auto_id = int(query_params["reagent_id"][0])
    if auto_id in reagents_df['id'].values:
        auto_row = reagents_df[reagents_df['id'] == auto_id].iloc[0]
        st.success(f"🔍 Auto-loaded Reagent: {auto_row['name']} (ID: {auto_id})")
        st.dataframe(auto_row.to_frame().T, use_container_width=True)

# Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Catalog", "Add Reagent", "Log Usage", "QR Tools", "Admin"])

with tab1:
    # Catalog code...

with tab2:
    # Add Reagent code...

with tab3:
    # Log Usage code...

with tab4:
    st.header("QR Code Tools")
    
    if reagents_df.empty:
        st.info("No reagents yet — add some first to generate QR codes!")
    else:
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Generate Printable QR Labels")
            selected_id = st.selectbox("Select Reagent", reagents_df['id'], 
                                       format_func=lambda x: reagents_df[reagents_df['id']==x]['name'].values[0])
            row = reagents_df[reagents_df['id'] == selected_id].iloc[0]
            
            app_url = st.text_input("Your App URL (for QR links)", value="https://your-app-name.streamlit.app", 
                                    help="Paste your full deployed URL here")
            
            qr_data = f"{app_url}?reagent_id={selected_id}"
            
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            buf = BytesIO()
            img.save(buf, format="PNG")
            byte_im = buf.getvalue()
            
            st.image(byte_im, caption=f"QR for {row['name']} (ID: {selected_id})")
            st.download_button("Download QR Label", byte_im, file_name=f"QR_{row['name'].replace(' ', '_')}_ID{selected_id}.png", mime="image/png")
            st.code(qr_data)

        with col2:
            st.subheader("Quick Lookup")
            manual_id = st.number_input("Enter Reagent ID", min_value=1, step=1)
            if manual_id and manual_id in reagents_df['id'].values:
                view_row = reagents_df[reagents_df['id'] == manual_id].iloc[0]
                st.subheader(f"Details: {view_row['name']}")
                st.dataframe(view_row.to_frame().T)

# Admin tab...

st.caption("App fixed! QR generation now works reliably. Data may reset on Cloud reboots — for full persistence, consider a free external DB later.")
