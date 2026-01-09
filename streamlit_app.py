# streamlit_app.py - Laboratory Reagent Inventory Web App (Streamlit version)
# Features match your blueprint: QR/barcode, alerts, search, logging, roles, etc.

import streamlit as st
import pandas as pd
from datetime import date, datetime
import qrcode
from io import BytesIO
import base64
import sqlite3
import hashlib

# Page config
st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")

# Database setup (SQLite for simplicity - persists on Streamlit Cloud via volume if needed)
DB_FILE = "reagents.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                 id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reagents (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, cas_number TEXT,
                 supplier TEXT, location TEXT, quantity REAL, unit TEXT,
                 expiration_date TEXT, low_stock_threshold REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS usage_logs (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, reagent_id INTEGER,
                 user TEXT, quantity_used REAL, timestamp TEXT, notes TEXT)''')
    
    # Default admin/user (password: admin123 / user123 - change ASAP!)
    c.execute("INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
              ("admin", hashlib.sha256("admin123".encode()).hexdigest(), "admin"))
    c.execute("INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
              ("user", hashlib.sha256("user123".encode()).hexdigest(), "user"))
    conn.commit()
    conn.close()

init_db()

# Auth functions
def check_password(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT password_hash, role FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if row and hashlib.sha256(password.encode()).hexdigest() == row[0]:
        return row[1]
    return None

# Session state for login
if "user" not in st.session_state:
    st.session_state.user = None
    st.session_state.role = None

# Login sidebar
with st.sidebar:
    st.title("Login")
    if st.session_state.user:
        st.success(f"Logged in as {st.session_state.user} ({st.session_state.role})")
        if st.button("Logout"):
            st.session_state.user = None
            st.session_state.role = None
            st.rerun()
    else:
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            role = check_password(username, password)
            if role:
                st.session_state.user = username
                st.session_state.role = role
                st.success("Logged in!")
                st.rerun()
            else:
                st.error("Invalid credentials")

if not st.session_state.user:
    st.stop()

# Load data
def load_reagents():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM reagents", conn)
    conn.close()
    if not df.empty:
        df['expiration_date'] = pd.to_datetime(df['expiration_date'], errors='coerce').dt.date
    return df

def load_logs():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM usage_logs", conn)
    conn.close()
    return df

reagents_df = load_reagents()

# Alerts
alerts = []
today = date.today()
for _, r in reagents_df.iterrows():
    if r['quantity'] <= r['low_stock_threshold']:
        alerts.append(f"⚠️ Low stock: {r['name']} ({r['quantity']} {r['unit']})")
    if pd.notnull(r['expiration_date']) and r['expiration_date'] < today:
        alerts.append(f"❌ Expired: {r['name']} ({r['expiration_date']})")

if alerts:
    st.warning("\n".join(alerts))

# Search & Filter
st.header("Reagent Catalog")
search = st.text_input("Search by name, CAS, or location")
filtered_df = reagents_df[
    reagents_df['name'].str.contains(search, case=False, na=False) |
    reagents_df['cas_number'].str.contains(search, case=False, na=False) |
    reagents_df['location'].str.contains(search, case=False, na=False)
]

st.dataframe(filtered_df, use_container_width=True)

# Add Reagent (Admin only if desired)
if st.session_state.role == "admin" or True:  # Allow all for simplicity
    with st.expander("Add New Reagent"):
        with st.form("add_form"):
            col1, col2 = st.columns(2)
            name = col1.text_input("Name*")
            cas = col1.text_input("CAS Number")
            supplier = col2.text_input("Supplier")
            location = col2.text_input("Location*")
            qty = col1.number_input("Quantity*", min_value=0.0)
            unit = col1.selectbox("Unit", ["g", "ml", "L", "mg", "bottles"])
            exp_date = col2.date_input("Expiration Date", value=None)
            threshold = col2.number_input("Low Stock Threshold", value=10.0)
            submitted = st.form_submit_button("Add")
            if submitted and name and location:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("""INSERT INTO reagents 
                             (name, cas_number, supplier, location, quantity, unit, expiration_date, low_stock_threshold)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                          (name, cas, supplier, location, qty, unit, str(exp_date) if exp_date else None, threshold))
                conn.commit()
                conn.close()
                st.success("Added!")
                st.rerun()

# QR Code Generation & Scanning
st.header("QR Code Tools")
selected_id = st.selectbox("Select reagent for QR", options=filtered_df['id'].tolist(), format_func=lambda x: filtered_df[filtered_df['id']==x]['name'].values[0] if not filtered_df.empty else "")
if selected_id:
    row = reagents_df[reagents_df['id'] == selected_id].iloc[0]
    qr_data = f"https://your-app-url.streamlit.app/?reagent_id={selected_id}"  # Or just the ID/details
    qr_img = qrcode.make(qr_data)
    buf = BytesIO()
    qr_img.save(buf, format="PNG")
    byte_im = buf.getvalue()
    st.image(byte_im, caption=f"QR for {row['name']}")
    st.download_button("Download QR Label", byte_im, file_name=f"{row['name']}_QR.png")

# Camera QR Scan (basic - uses uploaded image)
st.subheader("Scan QR to View/Update")
uploaded_qr = st.file_uploader("Upload scanned QR image", type=["png", "jpg"])
if uploaded_qr:
    # In production, use pyzbar or similar for decoding
    st.image(uploaded_qr)
    st.info("QR decoding not implemented in this MVP - manually enter ID below.")
    manual_id = st.number_input("Or enter Reagent ID")
    if manual_id:
        # Show details & log usage
        row = reagents_df[reagents_df['id'] == manual_id]
        if not row.empty:
            st.write(row.T)

# Usage Logging
st.header("Log Usage")
log_id = st.selectbox("Reagent to use", options=reagents_df['id'].tolist(), format_func=lambda x: reagents_df[reagents_df['id']==x]['name'].values[0])
if log_id:
    qty_used = st.number_input("Quantity used", min_value=0.0)
    notes = st.text_area("Notes")
    if st.button("Log"):
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO usage_logs (reagent_id, user, quantity_used, timestamp, notes) VALUES (?, ?, ?, ?, ?)",
                  (log_id, st.session_state.user, qty_used, datetime.now().isoformat(), notes))
        c.execute("UPDATE reagents SET quantity = quantity - ? WHERE id = ?", (qty_used, log_id))
        conn.commit()
        conn.close()
        st.success("Logged!")
        st.rerun()

# Admin Dashboard
if st.session_state.role == "admin":
    st.header("Admin Dashboard")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Reagents", len(reagents_df))
    col2.metric("Low Stock", len([a for a in alerts if "Low" in a]))
    col3.metric("Expired", len([a for a in alerts if "Expired" in a]))
    st.subheader("Usage History")
    logs_df = load_logs()
    st.dataframe(logs_df)

st.sidebar.info("Built with Streamlit - Deploy instantly on Streamlit Cloud!")