# streamlit_app.py - Laboratory Reagent Inventory Web App
# Fully compatible with Streamlit Community Cloud (2026)

import streamlit as st
import pandas as pd
from datetime import date, datetime
import qrcode
from io import BytesIO
import base64
import hashlib

# --- Critical Fix for Streamlit Cloud SQLite Compatibility ---
# Streamlit Cloud has an old system SQLite; pysqlite3-binary provides a modern drop-in replacement
try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3  # Fallback to built-in (may have limitations on Cloud)
# --------------------------------------------------------------

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")

DB_FILE = "reagents.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Users table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 username TEXT UNIQUE NOT NULL,
                 password_hash TEXT NOT NULL,
                 role TEXT NOT NULL)''')
    
    # Reagents table
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
    
    # Usage logs
    c.execute('''CREATE TABLE IF NOT EXISTS usage_logs (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 reagent_id INTEGER,
                 user TEXT,
                 quantity_used REAL,
                 timestamp TEXT,
                 notes TEXT)''')
    
    # Default users (CHANGE THESE PASSWORDS IMMEDIATELY IN PRODUCTION!)
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
def check_login(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT role FROM users WHERE username = ? AND password_hash = ?",
              (username, hashlib.sha256(password.encode()).hexdigest()))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.role = None

# Login Form
if not st.session_state.authenticated:
    with st.form("login_form"):
        st.subheader("Login")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
        
        if submit:
            role = check_login(username, password)
            if role:
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.role = role
                st.success(f"Welcome, {username}! ({role})")
                st.rerun()
            else:
                st.error("Invalid username or password")
    st.stop()

# Logout
if st.sidebar.button("Logout"):
    for key in ["authenticated", "username", "role"]:
        del st.session_state[key]
    st.rerun()

st.sidebar.success(f"Logged in as: **{st.session_state.username}** ({st.session_state.role})")

# Load Data
@st.cache_data(ttl=60)  # Refresh every minute
def load_reagents():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM reagents ORDER BY name", conn)
    conn.close()
    if not df.empty:
        df['expiration_date'] = pd.to_datetime(df['expiration_date'], errors='coerce').dt.date
    return df

@st.cache_data(ttl=300)
def load_logs():
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM usage_logs ORDER BY timestamp DESC", conn)
    conn.close()
    return df

reagents_df = load_reagents()

# Alerts
alerts = []
today = date.today()
for _, row in reagents_df.iterrows():
    if row['quantity'] <= row['low_stock_threshold']:
        alerts.append(f"⚠️ **Low Stock**: {row['name']} — {row['quantity']} {row['unit']}")
    if pd.notnull(row['expiration_date']) and row['expiration_date'] < today:
        alerts.append(f"❌ **Expired**: {row['name']} ({row['expiration_date']})")

if alerts:
    st.warning("\n\n".join(alerts))

# Tabs for Navigation
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Catalog", "Add Reagent", "Log Usage", "QR Tools", "Admin"])

with tab1:
    st.header("Reagent Catalog")
    search = st.text_input("🔍 Search by Name, CAS, or Location")
    filtered = reagents_df
    if search:
        filtered = reagents_df[
            reagents_df['name'].str.contains(search, case=False, na=False) |
            reagents_df['cas_number'].str.contains(search, case=False, na=False) |
            reagents_df['location'].str.contains(search, case=False, na=False)
        ]
    st.dataframe(filtered.style.format({"quantity": "{:.2f}"}), use_container_width=True)

with tab2:
    st.header("Add New Reagent")
    with st.form("add_reagent"):
        col1, col2 = st.columns(2)
        name = col1.text_input("Reagent Name*", help="Required")
        cas = col1.text_input("CAS Number")
        supplier = col2.text_input("Supplier")
        location = col2.text_input("Storage Location*", help="e.g., Cabinet A, Shelf 3")
        quantity = col1.number_input("Initial Quantity*", min_value=0.0, step=0.1)
        unit = col1.selectbox("Unit", ["g", "mg", "ml", "L", "bottles", "vials", "kg"])
        exp_date = col2.date_input("Expiration Date (if any)", value=None)
        threshold = col2.number_input("Low Stock Alert Threshold", value=10.0, min_value=0.0)
        
        if st.form_submit_button("Add Reagent"):
            if not name or not location:
                st.error("Name and Location are required!")
            else:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("""INSERT INTO reagents 
                            (name, cas_number, supplier, location, quantity, unit, expiration_date, low_stock_threshold)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                          (name, cas or None, supplier or None, location, quantity, unit,
                           str(exp_date) if exp_date else None, threshold))
                conn.commit()
                conn.close()
                st.success(f"Added {name} successfully!")
                st.cache_data.clear()
                st.rerun()

with tab3:
    st.header("Log Reagent Usage")
    if reagents_df.empty:
        st.info("No reagents yet. Add some first!")
    else:
        reagent_id = st.selectbox(
            "Select Reagent",
            options=reagents_df['id'].tolist(),
            format_func=lambda x: f"{reagents_df.loc[reagents_df['id']==x, 'name'].values[0]} ({reagents_df.loc[reagents_df['id']==x, 'quantity'].values[0]} {reagents_df.loc[reagents_df['id']==x, 'unit'].values[0]} left)"
        )
        col1, col2 = st.columns(2)
        qty_used = col1.number_input("Quantity Used", min_value=0.01, step=0.1)
        notes = col2.text_area("Notes (optional)")
        
        if st.button("Record Usage"):
            current_qty = reagents_df.loc[reagents_df['id'] == reagent_id, 'quantity'].values[0]
            if qty_used > current_qty:
                st.error("Cannot use more than available stock!")
            else:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("UPDATE reagents SET quantity = quantity - ? WHERE id = ?", (qty_used, reagent_id))
                c.execute("INSERT INTO usage_logs (reagent_id, user, quantity_used, timestamp, notes) VALUES (?, ?, ?, ?, ?)",
                          (reagent_id, st.session_state.username, qty_used, datetime.now().isoformat(), notes))
                conn.commit()
                conn.close()
                st.success("Usage recorded!")
                st.cache_data.clear()
                st.rerun()

with tab4:
    st.header("QR Code Tools")
    if not reagents_df.empty:
        selected_id = st.selectbox("Select Reagent for QR Code", reagents_df['id'], format_func=lambda x: reagents_df[reagents_df['id']==x]['name'].values[0])
        row = reagents_df[reagents_df['id'] == selected_id].iloc[0]
        
        # Generate QR linking to a view page (use app URL + ID)
        app_url = st.text_input("App Base URL (for QR links)", value="https://your-app-name.streamlit.app", help="Change to your deployed URL")
        qr_data = f"{app_url}?reagent_id={selected_id}"
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buf = BytesIO()
        img.save(buf, format="PNG")
        byte_im = buf.getvalue()
        
        st.image(byte_im, caption=f"QR Code for {row['name']}")
        st.download_button(
            label="Download QR Label",
            data=byte_im,
            file_name=f"QR_{row['name'].replace(' ', '_')}_{selected_id}.png",
            mime="image/png"
        )
        
        st.info("Print and stick on bottle for quick scanning!")

with tab5:
    if st.session_state.role != "admin":
        st.error("Admin access only")
    else:
        st.header("Admin Dashboard")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Reagents", len(reagents_df))
        col2.metric("Low Stock Items", len([a for a in alerts if "Low" in a]))
        col3.metric("Expired Items", len([a for a in alerts if "Expired" in a]))
        col4.metric("Total Usage Logs", len(load_logs()))
        
        st.subheader("Recent Usage History")
        st.dataframe(load_logs().head(20))

st.caption("Laboratory Reagent Inventory System © 2026 • Built with Streamlit")
