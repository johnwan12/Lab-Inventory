# streamlit_app.py - Laboratory Reagent Inventory System (2026 - Google Sheets version)
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

WORKSHEET_NAME = "template"  # Your tab name – change if different

def get_gsheet_conn():
    return st.connection("lab_gsheets", type=GSheetsConnection)

# ── Authentication (still hardcoded for simplicity) ─────────────────────────
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
            # Hardcoded check – move to sheet later if needed
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

# ── Load Reagents from Google Sheet ─────────────────────────────────────────
@st.cache_data(ttl=300)
def load_reagents():
    conn = get_gsheet_conn()
    try:
        df = conn.read(
            worksheet=WORKSHEET_NAME,
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
        # Ensure low_stock_threshold default
        if "low_stock_threshold" not in df.columns:
            df["low_stock_threshold"] = 1.0
        return df
    except Exception as e:
        st.error(f"Error loading data from sheet: {e}")
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

# ── Tab navigation ──────────────────────────────────────────────────────────
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Catalog"

tab_names = ["Catalog", "Add Reagent", "Log Usage", "QR Tools", "Admin"]
active_index = tab_names.index(st.session_state.active_tab) if st.session_state.active_tab in tab_names else 0
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
                    "Edit": st.column_config.CheckboxColumn("Edit", help="Check to edit", default=False),
                    "Delete": st.column_config.CheckboxColumn("Delete", help="Check to delete", default=False),
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

            to_edit = edited_df[edited_df["Edit"] == True]["id"].tolist()
            if to_edit:
                edit_id = to_edit[0]
                reagent = reagents_df[reagents_df['id'] == edit_id].iloc[0]

                with st.expander(f"✏️ Edit: {reagent['name']} (ID: {edit_id})", expanded=True):
                    e_name = st.text_input("Name", value=reagent['name'])
                    e_cas = st.text_input("CAS Number", value=reagent['cas_number'] or "")
                    e_supplier = st.text_input("Supplier", value=reagent['supplier'] or "")
                    e_location = st.text_input("Location", value=reagent['location'])
                    e_quantity = st.number_input("Quantity", value=float(reagent['quantity']), step=0.1, min_value=0.0)
                    e_unit = st.selectbox("Unit", ["g","mg","ml","L","bottles","vials","kg"], index=["g","mg","ml","L","bottles","vials","kg"].index(reagent['unit']))
                    e_exp = st.date_input("Expiration Date", value=reagent['expiration_date'] if pd.notnull(reagent['expiration_date']) else None)
                    e_threshold = st.number_input("Low Stock Threshold", value=float(reagent.get('low_stock_threshold', 1.0)), min_value=0.0, step=0.1)

                    if st.button("Save Changes", type="primary"):
                        today_date = date.today()
                        if e_exp and e_exp < today_date:
                            st.error(f"Cannot save: Expiration date is in the past (today: {today_date}).")
                        else:
                            conn = get_gsheet_conn()
                            df = conn.read(worksheet=WORKSHEET_NAME)
                            row_idx = df[df['id'] == edit_id].index[0] + 2  # +2: header + 0-index

                            updates = {
                                "name": e_name,
                                "cas_number": e_cas or "",
                                "supplier": e_supplier or "",
                                "location": e_location,
                                "quantity": e_quantity,
                                "unit": e_unit,
                                "expiration_date": str(e_exp) if e_exp else "",
                                "low_stock_threshold": e_threshold
                            }

                            for col, val in updates.items():
                                col_idx = df.columns.get_loc(col) + 1  # 1-based for gsheets
                                conn.update(
                                    worksheet=WORKSHEET_NAME,
                                    range=f"{chr(64 + col_idx)}{row_idx}",
                                    values=[[val]]
                                )
                            st.success("Reagent updated!")
                            st.cache_data.clear()
                            st.rerun()

            to_delete = edited_df[edited_df["Delete"] == True]["id"].tolist()
            if to_delete:
                st.warning(f"Selected {len(to_delete)} reagent(s) for deletion.")
                if st.button("🗑️ Confirm Delete Selected", type="primary"):
                    conn = get_gsheet_conn()
                    df = conn.read(worksheet=WORKSHEET_NAME)
                    rows_to_keep = df[~df['id'].isin(to_delete)]
                    conn.update(worksheet=WORKSHEET_NAME, data=rows_to_keep)
                    st.success(f"Deleted {len(to_delete)} reagent(s)!")
                    st.cache_data.clear()
                    st.rerun()
        else:
            st.dataframe(display_df.style.format({"quantity": "{:.2f}"}), use_container_width=True)
            st.info("Only admin users can edit or delete reagents.")

# ── Add Reagent ─────────────────────────────────────────────────────────────
with tab2:
    st.header("Add Reagent")

    # Bulk Excel import (adapted – still processes to df then writes)
    st.subheader("Bulk Add from Excel")
    uploaded_excel = st.file_uploader("Upload Excel (.xlsx/.xls)", type=["xlsx", "xls"])

    if uploaded_excel is not None:
        try:
            df_excel = pd.read_excel(uploaded_excel)
            df_excel.columns = df_excel.columns.str.strip().str.lower()
            rename_map = {'item': 'name', 'supplier item identifier': 'cas_number'}
            df_excel = df_excel.rename(columns=rename_map)

            if 'name' not in df_excel.columns:
                st.error("Excel must contain a 'name' or 'Item' column.")
            else:
                if st.button("Confirm Import All Valid Rows", type="primary"):
                    conn = get_gsheet_conn()
                    current_df = conn.read(worksheet=WORKSHEET_NAME)
                    max_id = current_df['id'].max() if not current_df.empty else 0

                    imported = 0
                    new_rows = []
                    for _, row in df_excel.iterrows():
                        name = str(row.get('name', '')).strip()
                        if not name:
                            continue
                        max_id += 1
                        new_row = {
                            "id": max_id,
                            "name": name,
                            "cas_number": str(row.get('cas_number', '')).strip() or "",
                            "supplier": str(row.get('supplier', '')).strip() or "",
                            "location": "Default Location",
                            "quantity": 1.0,
                            "unit": "bottles",
                            "expiration_date": "",
                            "low_stock_threshold": 1.0,
                            "Delete": "false",
                            "Edit": "false"
                        }
                        new_rows.append(new_row)
                        imported += 1

                    if new_rows:
                        new_df = pd.DataFrame(new_rows)
                        updated_df = pd.concat([current_df, new_df], ignore_index=True)
                        conn.update(worksheet=WORKSHEET_NAME, data=updated_df)
                        st.success(f"Imported {imported} reagents!")
                        st.cache_data.clear()
                        st.rerun()
        except Exception as e:
            st.error(f"Error: {str(e)}")

    st.markdown("---")

    # Single entry form
    with st.form(key="add_form"):
        col1, col2 = st.columns(2)
        name = col1.text_input("Name*", help="Required")
        cas = col1.text_input("CAS Number")
        supplier = col2.text_input("Supplier")
        location_preset = col2.selectbox("Location*", options=["Scrappy-Doo", "Daphne", "Tom", "Jerry", "Scooby-Doo", "Velma", "Custom input"])
        custom_location = ""
        if location_preset == "Custom input":
            custom_location = col2.text_input("Custom location*", placeholder="e.g., Cabinet B - Shelf 4")
        final_location = custom_location.strip() if location_preset == "Custom input" else location_preset
        quantity = col1.number_input("Initial Quantity*", min_value=0.0, step=0.1)
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
                conn = get_gsheet_conn()
                df = conn.read(worksheet=WORKSHEET_NAME)
                max_id = df['id'].max() if not df.empty else 0
                new_id = max_id + 1

                new_row = {
                    "id": new_id,
                    "name": name.strip(),
                    "cas_number": cas or "",
                    "supplier": supplier or "",
                    "location": final_location,
                    "quantity": quantity,
                    "unit": unit,
                    "expiration_date": str(exp_date) if exp_date else "",
                    "low_stock_threshold": threshold,
                    "Delete": "false",
                    "Edit": "false"
                }

                updated_df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                conn.update(worksheet=WORKSHEET_NAME, data=updated_df)
                st.success(f"Added **{name.strip()}** (ID: {new_id})!")
                st.cache_data.clear()
                st.rerun()

    # OCR section (unchanged)
    st.subheader("Quick Entry via Photo (OCR)")
    photo = st.camera_input("Take photo of reagent label") or st.file_uploader("Or upload photo", type=["jpg", "png", "jpeg"])
    if photo:
        st.image(photo, width=400)
        if not pytesseract:
            st.error("pytesseract not installed.")
        else:
            with st.spinner("Extracting text..."):
                try:
                    img = Image.open(photo)
                    text = pytesseract.image_to_string(img).strip()
                    if text
