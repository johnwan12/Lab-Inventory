# streamlit_app.py - Laboratory Reagent Inventory System (2026)
# Features: user registration, forgot password/reset, bulk Excel import, photo OCR (disabled note),
#           admin edit/delete, exp date warning, location dropdown+custom
import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
import hashlib
import uuid
try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")

DB_FILE = "reagents.db"

# ── Database Init ───────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
   
    # Users with email
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 username TEXT UNIQUE NOT NULL,
                 password_hash TEXT NOT NULL,
                 email TEXT UNIQUE NOT NULL,
                 role TEXT NOT NULL DEFAULT 'user')''')
   
    # Reset tokens
    c.execute('''CREATE TABLE IF NOT EXISTS reset_tokens (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER NOT NULL,
                 token TEXT UNIQUE NOT NULL,
                 expiry DATETIME NOT NULL,
                 used INTEGER DEFAULT 0,
                 FOREIGN KEY(user_id) REFERENCES users(id))''')
   
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
   
    # Default admin
    hashed = hashlib.sha256("admin123".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)",
              ("admin", hashed, "admin@example.com", "admin"))
   
    conn.commit()
    conn.close()

init_db()

# ── Session state ───────────────────────────────────────────────────────────
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.role = None
    st.session_state.page = "login"  # login, register, forgot, reset

# ── Helpers ─────────────────────────────────────────────────────────────────
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def username_exists(uname):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM users WHERE username = ?", (uname,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def email_to_user_id(email):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE email = ?", (email,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def create_reset_token(user_id):
    token = str(uuid.uuid4())
    expiry = (datetime.now() + timedelta(hours=1)).isoformat()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO reset_tokens (user_id, token, expiry) VALUES (?, ?, ?)",
              (user_id, token, expiry))
    conn.commit()
    conn.close()
    return token

def validate_reset_token(token):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id, expiry, used FROM reset_tokens WHERE token = ?", (token,))
    row = c.fetchone()
    conn.close()
    if row and row[2] == 0:  # not used
        if datetime.fromisoformat(row[1]) > datetime.now():
            return row[0]
    return None

def mark_token_used(token):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE reset_tokens SET used = 1 WHERE token = ?", (token,))
    conn.commit()
    conn.close()

def update_user_password(user_id, new_pw):
    hashed = hash_pw(new_pw)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hashed, user_id))
    conn.commit()
    conn.close()

# ── Pages ───────────────────────────────────────────────────────────────────
def login_page():
    st.subheader("Login")
    with st.form("login"):
        uname = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
        
        if submit:
            if not username_exists(uname):
                st.error("User not found. Please register first.")
            else:
                hashed = hash_pw(pw)
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("SELECT role FROM users WHERE username=? AND password_hash=?", (uname, hashed))
                res = c.fetchone()
                conn.close()
                if res:
                    st.session_state.authenticated = True
                    st.session_state.username = uname
                    st.session_state.role = res[0]
                    st.success(f"Welcome, {uname}!")
                    st.rerun()
                else:
                    st.error("Invalid password")

    cols = st.columns(2)
    if cols[0].button("Register"):
        st.session_state.page = "register"
        st.rerun()
    if cols[1].button("Forgot username / password"):
        st.session_state.page = "forgot"
        st.rerun()

def register_page():
    st.subheader("Register")
    with st.form("register"):
        uname = st.text_input("Username")
        email = st.text_input("Email")
        pw = st.text_input("Password", type="password")
        pw2 = st.text_input("Confirm password", type="password")
        submit = st.form_submit_button("Create account")
        
        if submit:
            if not all([uname, email, pw, pw2]):
                st.error("All fields required.")
            elif pw != pw2:
                st.error("Passwords do not match.")
            elif username_exists(uname):
                st.error("Username already taken.")
            elif email_to_user_id(email):
                st.error("Email already registered.")
            else:
                hashed = hash_pw(pw)
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("INSERT INTO users (username, password_hash, email, role) VALUES (?,?,?,?)",
                          (uname, hashed, email, "user"))
                conn.commit()
                conn.close()
                st.success("Account created! You can now log in.")
                st.session_state.page = "login"
                st.rerun()

    if st.button("Back to login"):
        st.session_state.page = "login"
        st.rerun()

def forgot_page():
    st.subheader("Forgot username or password?")
    email = st.text_input("Enter your registered email")
    
    if st.button("Send recovery link"):
        user_id = email_to_user_id(email)
        if user_id:
            token = create_reset_token(user_id)
            # In production: send real email
            reset_url = f"{st.secrets.get('app_url', 'http://localhost:8501')}?token={token}"
            st.info(f"**SIMULATED EMAIL** sent to {email}")
            st.info(f"Reset link: {reset_url} (valid 1 hour)")
            st.info("(Replace this with real email sending in production)")
        else:
            st.error("No account found with that email.")

    if st.button("Back"):
        st.session_state.page = "login"
        st.rerun()

def reset_page(token):
    user_id = validate_reset_token(token)
    if not user_id:
        st.error("Invalid or expired reset link.")
        return
    
    st.subheader("Reset your password")
    with st.form("reset"):
        new_pw = st.text_input("New password", type="password")
        confirm = st.text_input("Confirm new password", type="password")
        submit = st.form_submit_button("Change password")
        
        if submit:
            if new_pw != confirm:
                st.error("Passwords do not match.")
            elif len(new_pw) < 6:
                st.error("Password must be at least 6 characters.")
            else:
                update_user_password(user_id, new_pw)
                mark_token_used(token)
                st.success("Password updated! Please log in.")
                st.session_state.page = "login"
                st.rerun()

# ── Routing ─────────────────────────────────────────────────────────────────
if not st.session_state.authenticated:
    params = st.query_params
    token = params.get("token", [None])[0]
    
    if token:
        reset_page(token)
    elif st.session_state.page == "register":
        register_page()
    elif st.session_state.page == "forgot":
        forgot_page()
    else:
        login_page()
    st.stop()

# ── Authenticated content ───────────────────────────────────────────────────
st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})")

if st.sidebar.button("🚪 Logout"):
    for k in ["authenticated", "username", "role", "page"]:
        st.session_state.pop(k, None)
    st.rerun()

# ── Your existing tabs here (Catalog, Add Reagent, etc.) ────────────────────
# Paste your previous tab code below this line...
# For example:

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Catalog", "Add Reagent", "Log Usage", "QR Tools", "Admin"])

with tab1:
    st.header("Reagent Catalog")
    # ... your catalog code ...

with tab2:
    st.header("Add Reagent")
    # ... your add reagent code with custom location ...

# etc.

st.caption("Laboratory Reagent Inventory • Streamlit • January 2026")
