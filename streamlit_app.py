# streamlit_app.py - Laboratory Reagent Inventory System (Final Version)

import streamlit as st
import pandas as pd
from datetime import date, datetime
import qrcode
from io import BytesIO
import hashlib

# SQLite compatibility for Streamlit Cloud
try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")

DB_FILE = "reagents.db"

# -------------------------- Database Initialization --------------------------
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
    
    # Default users - CHANGE PASSWORDS IMMEDIATELY!
    hashed_admin = hashlib.sha256("admin123".encode()).hexdigest()
    hashed_user = hashlib.sha256("user123".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
              ("admin", hashed_admin, "admin"))
    c.execute("INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)",
              ("user", hashed_user, "user"))
    
    conn.commit()
    conn.close()

init_db()

# -------------------------- Authentication --------------------------
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

# -------------------------- Load Reagents --------------------------
@st.cache_data(ttl=60)
def load_reagents():
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query("SELECT * FROM reagents ORDER BY name", conn)
        conn.close()
        if not df.empty:
            df['expiration_date'] = pd.to_datetime(df['expiration_date'], errors='coerce').dt.date
        return df
    except Exception:
        return pd.DataFrame(columns=['id', 'name', 'cas_number', 'supplier', 'location',
                                    'quantity', 'unit', 'expiration_date', 'low_stock_threshold'])

reagents_df = load_reagents()

# -------------------------- Alerts --------------------------
alerts = []
today = date.today()
for _, row in reagents_df.iterrows():
    if row['quantity'] <= row['low_stock_threshold]:
        alerts.append(f"⚠️ **Low Stock**: {row['name']} — {row['quantity']:.2f} {row['unit']}")
    if pd.notnull(row['expiration_date']) and row['expiration_date'] < today:
        alerts.append(f"❌ **Expired**: {row['name']} ({row['expiration_date']})")

if alerts:
    st.warning("\n\n".join(alerts))

# Auto-load reagent from URL
query_params = st.query_params
if "reagent_id" in query_params:
    try:
        auto_id = int(query_params["reagent_id"][0])
        if auto_id in reagents_df['id'].values:
            auto_row = reagents_df[reagents_df['id'] == auto_id].iloc[0]
            st.success(f"🔍 Auto-loaded: {auto_row['name']} (ID: {auto_id})")
            st.dataframe(auto_row.to_frame().T, use_container_width=True)
    except:
        pass

# -------------------------- Main Tabs --------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Catalog", "Add Reagent", "Log Usage", "QR Tools", "Admin"])

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
    st.dataframe(display_df.style.format({"quantity": "{:.2f}"}), use_container_width=True)

with tab2:
    st.header("Add New Reagent")
    
    # Dynamic form key to reset all fields after successful add
    if "add_form_key" not in st.session_state:
        st.session_state.add_form_key = 0
    
    with st.form(key=f"add_form_{st.session_state.add_form_key}"):
        col1, col2 = st.columns(2)
        name = col1.text_input("Name*", help="Required")
        cas = col1.text_input("CAS Number")
        supplier = col2.text_input("Supplier")
        location = col2.text_input("Location*", help="e.g., Cabinet A - Shelf 2")
        quantity = col1.number_input("Initial Quantity*", min_value=0.0, step=0.1)
        unit = col1.selectbox("Unit", ["g", "mg", "ml", "L", "bottles", "vials", "kg"])
        exp_date = col2.date_input("Expiration Date", value=None)
        threshold = col2.number_input("Low Stock Threshold", value=10.0, min_value=0.0)

        submitted = st.form_submit_button("Add Reagent")
        if submitted:
            if not name.strip() or not location.strip():
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
                
                st.success(f"Added '{name}' successfully!")
                
                # Reset form by changing key
                st.session_state.add_form_key += 1
                
                st.cache_data.clear()
                st.rerun()

with tab3:
    st.header("Log Reagent Usage")
    if reagents_df.empty:
        st.info("No reagents available yet.")
    else:
        reagent_id = st.selectbox(
            "Select Reagent",
            options=reagents_df['id'],
            format_func=lambda x: f"{reagents_df.loc[reagents_df['id']==x, 'name'].values[0]} "
                                 f"({reagents_df.loc[reagents_df['id']==x, 'quantity'].values[0]:.2f} "
                                 f"{reagents_df.loc[reagents_df['id']==x, 'unit'].values[0]} left)"
        )
        col1, col2 = st.columns(2)
        qty_used = col1.number_input("Quantity Used", min_value=0.01, step=0.1)
        notes = col2.text_area("Notes (optional)")

        if st.button("Record Usage"):
            current_qty = reagents_df.loc[reagents_df['id'] == reagent_id, 'quantity'].values[0]
            if qty_used > current_qty:
                st.error("Not enough stock available!")
            else:
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("UPDATE reagents SET quantity = quantity - ? WHERE id = ?", (qty_used, reagent_id))
                c.execute("INSERT INTO usage_logs (reagent_id, user, quantity_used, timestamp, notes) "
                          "VALUES (?, ?, ?, ?, ?)",
                          (reagent_id, st.session_state.username, qty_used, datetime.now().isoformat(), notes))
                conn.commit()
                conn.close()
                st.success("Usage recorded successfully!")
                st.cache_data.clear()
                st.rerun()

with tab4:
    st.header("QR Code Tools")
    if reagents_df.empty:
        st.info("Add reagents first to generate QR codes.")
    else:
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Generate 5mm × 5mm QR Label")
            selected_id = st.selectbox(
                "Select Reagent",
                reagents_df['id'],
                format_func=lambda x: reagents_df[reagents_df['id']==x]['name'].values[0],
                key="qr_select"
            )
            row = reagents_df[reagents_df['id'] == selected_id].iloc[0]
            
            app_url = st.text_input(
                "Your App URL (for QR links)",
                value="https://your-app-name.streamlit.app",
                help="Replace with your actual deployed URL"
            )
            
            qr_data = f"{app_url}?reagent_id={selected_id}"
            
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.ERROR_CORRECT_L,
                box_size=3,   # Results in ~60px image → ~5mm at 300 DPI
                border=2,
            )
            qr.add_data(qr_data)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            byte_im = buf.getvalue()
            
            st.image(byte_im, caption=f"5mm QR – {row['name']} (ID: {selected_id})")
            st.download_button(
                label="📥 Download 5mm QR Label",
                data=byte_im,
                file_name=f"QR_5mm_{row['name'].replace(' ', '_')}_ID{selected_id}.png",
                mime="image/png"
            )
            st.code(qr_data, language=None)
            st.success("Ideal for small vials! Print on waterproof labels.")

        with col2:
            st.subheader("Quick Lookup by ID")
            manual_id = st.number_input("Enter Reagent ID", min_value=1, step=1, key="manual_lookup")
            if manual_id and manual_id in reagents_df['id'].values:
                view_row = reagents_df[reagents_df['id'] == manual_id].iloc[0]
                st.markdown(f"### {view_row['name']}")
                st.dataframe(view_row.to_frame().T, use_container_width=True)

with tab5:
    if st.session_state.role != "admin":
        st.error("🚫 Admin access required")
    else:
        st.header("Admin Dashboard")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Reagents", len(reagents_df))
        col2.metric("Low Stock Items", len([a for a in alerts if "Low" in a]))
        col3.metric("Expired Items", len([a for a in alerts if "Expired" in a]))
        
        st.subheader("Recent Usage Logs")
        conn = sqlite3.connect(DB_FILE)
        logs_df = pd.read_sql_query("SELECT * FROM usage_logs ORDER BY timestamp DESC LIMIT 20", conn)
        conn.close()
        if not logs_df.empty:
            st.dataframe(logs_df)
        else:
            st.info("No usage logs yet.")

st.caption("Laboratory Reagent Inventory • Built with Streamlit • Data may reset on reboots")
