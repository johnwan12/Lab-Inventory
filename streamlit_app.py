# streamlit_app.py - Laboratory Reagent Inventory System (Google Sheets version)
# Updated: workaround for "Spreadsheet must be specified" error

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

from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System (Google Sheets)")

#def get_gsheet_conn():
    #return st.connection(
       # "lab_gsheets",
        #type=GSheetsConnection,
        #spreadsheet="https://docs.google.com/spreadsheets/d/1xorAPoWd81bUE2yeJN4QsEhpEoUZ5yvdGIm2h9MHbkQ/edit",
        #worksheet="template"
    #)

def get_gsheet_conn():
    from google.oauth2 import service_account
    import json

    # Paste your FULL service account JSON here (copy from downloaded .json file)
    # IMPORTANT: Use triple quotes and preserve ALL newlines in private_key!
    creds_dict = {
        "type": "service_account",
        "project_id": "YOUR_PROJECT_ID_HERE",
        "private_key_id": "YOUR_PRIVATE_KEY_ID_HERE",
        "private_key": """-----BEGIN PRIVATE KEY-----
YOUR_FULL_PRIVATE_KEY_HERE_WITH_NEWLINES_PRESERVED
-----END PRIVATE KEY-----
""",
        "client_email": "YOUR_SERVICE_ACCOUNT_EMAIL@project.iam.gserviceaccount.com",
        "client_id": "YOUR_CLIENT_ID_HERE",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/YOUR_SERVICE_ACCOUNT_EMAIL%40project.iam.gserviceaccount.com",
        "universe_domain": "googleapis.com"
    }

    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )

    return st.connection(
        "lab_gsheets",
        type=GSheetsConnection,
        credentials=creds,
        spreadsheet="https://docs.google.com/spreadsheets/d/1xorAPoWd81bUE2yeJN4QsEhpEoUZ5yvdGIm2h9MHbkQ/edit",
        worksheet="template"
    )

# ── Authentication (hardcoded for now) ──────────────────────────────────────
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
            hashed = hashlib.sha256(password.encode()).hexdigest()
            if username == "admin" and hashed == hashlib.sha256("admin123".encode()).hexdigest():
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.role = "admin"
            elif username == "user" and hashed == hashlib.sha256("user123".encode()).hexdigest():
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.role = "user"
            
            if st.session_state.authenticated:
                st.success(f"Welcome, {username}! ({st.session_state.role.capitalize()})")
                st.rerun()
            else:
                st.error("Invalid username or password")
    st.stop()

if st.sidebar.button("🚪 Logout"):
    for key in ["authenticated", "username", "role"]:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

st.sidebar.success(f"Logged in as **{st.session_state.username}** ({st.session_state.role})")

# ── Load Reagents ───────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_reagents():
    conn = get_gsheet_conn()
    try:
        df = conn.read(
            usecols=[
                "id", "name", "cas_number", "supplier", "location",
                "quantity", "unit", "expiration_date", "low_stock_threshold"
            ],
            dtype={
                "id": "Int64",
                "quantity": float,
                "low_stock_threshold": float
            }
        )
        if not df.empty:
            df['expiration_date'] = pd.to_datetime(df['expiration_date'], errors='coerce').dt.date
            df = df.sort_values("name")
        if "low_stock_threshold" not in df.columns:
            df["low_stock_threshold"] = 1.0
        return df
    except Exception as e:
        st.error(f"Could not load data from Google Sheet: {str(e)}")
        return pd.DataFrame(columns=[
            'id','name','cas_number','supplier','location',
            'quantity','unit','expiration_date','low_stock_threshold'
        ])

reagents_df = load_reagents()

# ── Alerts ──────────────────────────────────────────────────────────────────
alerts = []
today = date.today()
for _, row in reagents_df.iterrows():
    threshold = row.get('low_stock_threshold', 1.0)
    if pd.notna(row['quantity']) and row['quantity'] <= threshold:
        alerts.append(f"⚠️ **Low Stock**: {row['name']} — {row['quantity']:.2f} {row['unit']} (threshold: {threshold})")
    if pd.notnull(row['expiration_date']) and row['expiration_date'] < today:
        alerts.append(f"❌ **Expired**: {row['name']} ({row['expiration_date']})")

if alerts:
    st.warning("\n\n".join(alerts))

# ── Tabs ────────────────────────────────────────────────────────────────────
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Catalog"

tab_names = ["Catalog", "Add Reagent", "Log Usage", "QR Tools", "Admin"]
tab1, tab2, tab3, tab4, tab5 = st.tabs(tab_names)

# ── Catalog ────────────────────────────────────────────────────────────────
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
            editable_df["Edit"] = False

            edited_df = st.data_editor(
                editable_df,
                column_config={
                    "Edit": st.column_config.CheckboxColumn("Edit", default=False),
                    "Delete": st.column_config.CheckboxColumn("Delete", default=False),
                    "id": "ID",
                    "name": "Name",
                    "cas_number": "CAS Number",
                    "supplier": "Supplier",
                    "location": "Location",
                    "quantity": st.column_config.NumberColumn("Quantity", format="%.2f"),
                    "unit": "Unit",
                    "expiration_date": "Expiration Date",
                    "low_stock_threshold": st.column_config.NumberColumn("Low Stock Threshold", format="%.1f"),
                },
                hide_index=True,
                use_container_width=True,
                key="catalog_editor"
            )

            to_edit = edited_df[edited_df["Edit"] == True]["id"].dropna().astype(int).tolist()
            if to_edit:
                edit_id = to_edit[0]
                reagent = reagents_df[reagents_df['id'] == edit_id].iloc[0]

                with st.expander(f"✏️ Edit: {reagent['name']} (ID: {edit_id})", expanded=True):
                    e_name = st.text_input("Name", value=str(reagent['name']))
                    e_cas = st.text_input("CAS Number", value=str(reagent.get('cas_number', '')))
                    e_supplier = st.text_input("Supplier", value=str(reagent.get('supplier', '')))
                    e_location = st.text_input("Location", value=str(reagent['location']))
                    e_quantity = st.number_input("Quantity", value=float(reagent['quantity']), step=0.1, min_value=0.0)
                    unit_options = ["g","mg","ml","L","bottles","vials","kg"]
                    e_unit_idx = unit_options.index(reagent['unit']) if reagent['unit'] in unit_options else 0
                    e_unit = st.selectbox("Unit", unit_options, index=e_unit_idx)
                    e_exp = st.date_input("Expiration Date", value=reagent['expiration_date'] if pd.notnull(reagent['expiration_date']) else None)
                    e_threshold = st.number_input("Low Stock Threshold", value=float(reagent.get('low_stock_threshold', 1.0)), min_value=0.0, step=0.1)

                    if st.button("Save Changes", type="primary"):
                        if e_exp and e_exp < date.today():
                            st.error("Cannot save: Expiration date is in the past.")
                        else:
                            conn = get_gsheet_conn()
                            df = conn.read()
                            mask = df['id'] == edit_id
                            if not mask.any():
                                st.error("Reagent not found in sheet.")
                            else:
                                row_idx = df.index[mask][0] + 2
                                updates = {
                                    "name": e_name,
                                    "cas_number": e_cas,
                                    "supplier": e_supplier,
                                    "location": e_location,
                                    "quantity": e_quantity,
                                    "unit": e_unit,
                                    "expiration_date": str(e_exp) if e_exp else "",
                                    "low_stock_threshold": e_threshold
                                }
                                for col_name, value in updates.items():
                                    col_idx = df.columns.get_loc(col_name) + 1
                                    conn.update(
                                        range=f"{chr(64 + col_idx)}{row_idx}",
                                        values=[[value]]
                                    )
                                st.success("Changes saved!")
                                st.cache_data.clear()
                                st.rerun()

            to_delete = edited_df[edited_df["Delete"] == True]["id"].dropna().astype(int).tolist()
            if to_delete:
                st.warning(f"Selected {len(to_delete)} reagent(s) for deletion.")
                if st.button("🗑️ Confirm Delete Selected", type="primary"):
                    conn = get_gsheet_conn()
                    df = conn.read()
                    updated_df = df[~df['id'].isin(to_delete)]
                    conn.update(data=updated_df.to_dict('records'))
                    st.success(f"Deleted {len(to_delete)} reagent(s)!")
                    st.cache_data.clear()
                    st.rerun()
        else:
            st.dataframe(display_df.style.format({"quantity": "{:.2f}"}), use_container_width=True)
            st.info("Only admin users can edit or delete reagents.")

# ── Add Reagent ─────────────────────────────────────────────────────────────
with tab2:
    st.header("Add Reagent")

    # Bulk import (simplified)
    st.subheader("Bulk Add from Excel")
    uploaded = st.file_uploader("Upload Excel (.xlsx/.xls)", type=["xlsx", "xls"])

    if uploaded:
        try:
            df_excel = pd.read_excel(uploaded)
            df_excel.columns = df_excel.columns.str.strip().str.lower()
            df_excel = df_excel.rename(columns={'item': 'name', 'supplier item identifier': 'cas_number'})

            if 'name' not in df_excel.columns:
                st.error("Excel must contain a 'name' or 'Item' column.")
            else:
                if st.button("Confirm Import", type="primary"):
                    conn = get_gsheet_conn()
                    current = conn.read()
                    max_id = current['id'].max() if not current.empty else 0

                    new_rows = []
                    for _, r in df_excel.iterrows():
                        name = str(r.get('name', '')).strip()
                        if not name: continue
                        max_id += 1
                        new_rows.append({
                            "id": max_id,
                            "name": name,
                            "cas_number": str(r.get('cas_number', '')).strip() or "",
                            "supplier": str(r.get('supplier', '')).strip() or "",
                            "location": "Default Location",
                            "quantity": 1.0,
                            "unit": "bottles",
                            "expiration_date": "",
                            "low_stock_threshold": 1.0
                        })

                    if new_rows:
                        new_df = pd.DataFrame(new_rows)
                        final_df = pd.concat([current, new_df], ignore_index=True)
                        conn.update(data=final_df.to_dict('records'))
                        st.success(f"Imported {len(new_rows)} reagents.")
                        st.cache_data.clear()
                        st.rerun()
        except Exception as e:
            st.error(f"Import failed: {str(e)}")

    st.markdown("---")

    # Single entry form
    with st.form("add_reagent_form"):
        col1, col2 = st.columns(2)
        name = col1.text_input("Name*", help="Required")
        cas = col1.text_input("CAS Number")
        supplier = col2.text_input("Supplier")
        loc_preset = col2.selectbox("Location*", ["Scrappy-Doo", "Daphne", "Tom", "Jerry", "Scooby-Doo", "Velma", "Custom input"])
        custom_loc = col2.text_input("Custom location") if loc_preset == "Custom input" else ""
        location = custom_loc.strip() if loc_preset == "Custom input" else loc_preset
        quantity = col1.number_input("Initial Quantity*", min_value=0.0, step=0.1)
        unit = col1.selectbox("Unit", ["g","mg","ml","L","bottles","vials","kg"])
        exp_date = col2.date_input("Expiration Date", value=None)
        threshold = col2.number_input("Low Stock Threshold", value=1.0, min_value=0.0, step=0.1)

        submitted = st.form_submit_button("Add Reagent", type="primary")

        if submitted:
            if not name.strip():
                st.error("Name is required.")
            elif not location:
                st.error("Location is required.")
            else:
                conn = get_gsheet_conn()
                df = conn.read()
                max_id = df['id'].max() if not df.empty else 0
                new_id = max_id + 1

                new_row = {
                    "id": new_id,
                    "name": name.strip(),
                    "cas_number": cas or "",
                    "supplier": supplier or "",
                    "location": location,
                    "quantity": quantity,
                    "unit": unit,
                    "expiration_date": str(exp_date) if exp_date else "",
                    "low_stock_threshold": threshold
                }

                updated = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                conn.update(data=updated.to_dict('records'))
                st.success(f"Added **{name.strip()}** (ID: {new_id})")
                st.cache_data.clear()
                st.rerun()

    # OCR Section
    st.subheader("Quick Entry via Photo (OCR)")
    photo = st.camera_input("Take photo of reagent label") or st.file_uploader("Or upload photo", type=["jpg", "png", "jpeg"])

    if photo:
        st.image(photo, width=400)
        
        if not pytesseract:
            st.error("pytesseract package not installed – check requirements.txt")
        else:
            with st.spinner("Extracting text with Tesseract OCR..."):
                try:
                    img = Image.open(photo)
                    text = pytesseract.image_to_string(img).strip()
                    
                    if text:
                        st.success("Text extracted!")
                        st.text_area("Extracted Text – copy to form fields above", text, height=150)
                    else:
                        st.warning("No text detected. Try better lighting or angle.")
                except Exception as e:
                    st.error(f"OCR processing failed: {str(e)}")

# ── Log Usage ───────────────────────────────────────────────────────────────
with tab3:
    st.header("Log Reagent Usage")
    if reagents_df.empty:
        st.warning("No reagents in inventory yet.")
    else:
        usable = reagents_df[reagents_df['quantity'] > 0].copy()
        if usable.empty:
            st.info("No reagents with positive stock.")
        else:
            options = usable['id'].tolist()
            labels = [f"{r['name']} (ID: {r['id']}) – {r['quantity']:.2f} {r['unit']} left" for _, r in usable.iterrows()]
            selected_id = st.selectbox("Select Reagent", options=options, format_func=lambda x: next((l for i,l in zip(options,labels) if i==x), str(x)))

            if selected_id:
                row = usable[usable['id'] == selected_id].iloc[0]
                avail = float(row['quantity'])
                thresh = row.get('low_stock_threshold', 1.0)
                if 0 < avail <= thresh:
                    st.warning(f"Low stock: only {avail:.2f} {row['unit']} left")

                col1, col2 = st.columns(2)
                qty_used = col1.number_input("Quantity Used", min_value=0.01, max_value=avail, value=min(0.01, avail), step=0.1, format="%.2f")
                notes = col2.text_area("Notes (optional)", height=80)

                if st.button("Record Usage", type="primary"):
                    if qty_used > avail:
                        st.error("Cannot use more than available.")
                    else:
                        conn = get_gsheet_conn()
                        df = conn.read()
                        idx = df[df['id'] == selected_id].index[0]
                        new_qty = avail - qty_used
                        col_idx = df.columns.get_loc("quantity") + 1
                        conn.update(
                            range=f"{chr(64 + col_idx)}{idx+2}",
                            values=[[new_qty]]
                        )
                        st.success(f"Usage logged. New quantity: {new_qty:.2f} {row['unit']}")
                        st.cache_data.clear()
                        st.rerun()

# ── Remaining tabs ──────────────────────────────────────────────────────────
with tab4:
    st.header("QR Code Tools")
    st.info("Coming soon...")

with tab5:
    if st.session_state.role != "admin":
        st.error("Admin access only")
    else:
        st.header("Admin Dashboard")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Reagents", len(reagents_df))
        col2.metric("Low Stock", sum(1 for a in alerts if "Low" in a))
        col3.metric("Expired", sum(1 for a in alerts if "Expired" in a))

st.caption("Laboratory Reagent Inventory • Streamlit + Google Sheets • January 2026")

