import streamlit as st
import pandas as pd
from datetime import date

from config import EXPECTED_COLS
from auth import ensure_login
from gsheets_client import get_sheets_service, get_spreadsheet_id
from inventory_repo import load_inventory, update_row_cells, append_row
from locks_repo import try_lock_row
from audit_repo import audit
from ui_widgets import location_widget
from alerts import build_alerts
from notify import send_slack, send_email

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")
st.caption("Streamlit + Google Sheets API v4 • Hardened multi-user CRUD")

ensure_login()

svc = get_sheets_service()
SPREADSHEET_ID = get_spreadsheet_id()

@st.cache_data(ttl=120, show_spinner="Loading inventory...")
def cached_load():
    return load_inventory(svc, SPREADSHEET_ID)

reagents_df, HEADER_MAP, RAW_HEADERS = cached_load()

# Alerts (UI)
alerts = build_alerts(reagents_df)
if alerts["low_stock"] or alerts["expired"]:
    msg = []
    if alerts["low_stock"]:
        msg.append("⚠️ **Low stock:**\n" + "\n".join([f"- {x}" for x in alerts["low_stock"]]))
    if alerts["expired"]:
        msg.append("❌ **Expired:**\n" + "\n".join([f"- {x}" for x in alerts["expired"]]))
    st.warning("\n\n".join(msg), icon="🚨")

tab_catalog, tab_add, tab_admin = st.tabs(["📋 Catalog", "➕ Add", "🛠 Admin"])

# ─────────────────────────────────────────────────────────────────────────────
# Catalog
# ─────────────────────────────────────────────────────────────────────────────
with tab_catalog:
    st.subheader("Reagent Catalog")
    search = st.text_input("Search", "")
    df_view = reagents_df.copy()

    if search and not df_view.empty:
        search_df = df_view.drop(columns=["_row"], errors="ignore").astype(str)
        mask = search_df.apply(lambda x: x.str.contains(search, case=False, na=False)).any(axis=1)
        df_view = df_view[mask].reset_index(drop=True)

    st.dataframe(df_view.drop(columns=["_row"], errors="ignore"), use_container_width=True, hide_index=True)

    st.markdown("### Row actions (Edit / Delete)")

    for _, r in df_view.iterrows():
        rownum = int(r.get("_row", 0))
        name = str(r.get("name", "") or "(no name)")

        with st.expander(f"{name} • sheet row {rownum}", expanded=False):
            cols = st.columns([3, 1])

            # EDIT
            with cols[0]:
                with st.form(f"edit_{rownum}"):
                    name2 = st.text_input("Name", value=str(r.get("name", "")))
                    cas2 = st.text_input("CAS Number", value=str(r.get("cas_number", "")))
                    sup2 = st.text_input("Supplier", value=str(r.get("supplier", "")))

                    loc2 = location_widget("Location", value=str(r.get("location", "")), key=f"loc_{rownum}")

                    qty2 = st.number_input("Quantity", min_value=0.0, value=float(r.get("quantity", 0.0) or 0.0), step=0.1)
                    unit2 = st.text_input("Unit", value=str(r.get("unit", "")))

                    exp_val = r.get("expiration_date")
                    has_exp = st.checkbox("Has expiration date", value=pd.notnull(exp_val), key=f"hasexp_{rownum}")
                    exp2 = st.date_input("Expiration date", value=exp_val if pd.notnull(exp_val) else date.today(), key=f"exp_{rownum}") if has_exp else None

                    low2 = st.number_input("Low stock threshold", min_value=0.0, value=float(r.get("low_stock_threshold", 10.0) or 10.0), step=1.0)

                    if st.form_submit_button("💾 Save row", type="primary"):
                        # Lock first
                        if not try_lock_row(svc, SPREADSHEET_ID, rownum, st.session_state.username, "edit"):
                            st.error("This row is being edited by someone else. Try again in ~1 minute.")
                            st.stop()

                        updates = {
                            "name": name2.strip(),
                            "cas_number": cas2.strip(),
                            "supplier": sup2.strip(),
                            "location": loc2.strip(),
                            "quantity": str(qty2),
                            "unit": unit2.strip(),
                            "expiration_date": exp2.isoformat() if exp2 else "",
                            "low_stock_threshold": str(low2),
                        }
                        update_row_cells(svc, SPREADSHEET_ID, HEADER_MAP, rownum, updates)
                        audit(svc, SPREADSHEET_ID, st.session_state.username, st.session_state.role, "UPDATE", rownum, name2, str(updates))

                        st.success("Row updated.")
                        cached_load.clear()
                        st.rerun()

            # DELETE (admin only)
            with cols[1]:
                if st.session_state.role != "admin":
                    st.info("Delete: admin only")
                else:
                    confirm = st.checkbox("Confirm delete", key=f"confirm_del_{rownum}")
                    if st.button("🗑️ Delete row", key=f"del_{rownum}", disabled=not confirm):
                        if not try_lock_row(svc, SPREADSHEET_ID, rownum, st.session_state.username, "delete"):
                            st.error("This row is being edited by someone else. Try again in ~1 minute.")
                            st.stop()

                        # Delete via batchUpdate
                        meta = svc.get(spreadsheetId=SPREADSHEET_ID).execute()
                        sheet_id = None
                        for s in meta.get("sheets", []):
                            if s["properties"]["title"] == "template":
                                sheet_id = s["properties"]["sheetId"]
                                break
                        if sheet_id is None:
                            st.error("Cannot find sheet tab 'template'")
                            st.stop()

                        svc.batchUpdate(
                            spreadsheetId=SPREADSHEET_ID,
                            body={"requests": [{"deleteDimension": {"range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": rownum - 1,
                                "endIndex": rownum
                            }}}]}
                        ).execute()

                        audit(svc, SPREADSHEET_ID, st.session_state.username, st.session_state.role, "DELETE", rownum, name, "deleted row")
                        st.success("Row deleted.")
                        cached_load.clear()
                        st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# Add
# ─────────────────────────────────────────────────────────────────────────────
with tab_add:
    st.subheader("Add New Reagent")
    with st.form("add_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            new_id = st.text_input("ID", "")
            new_name = st.text_input("Name", "")
            new_cas = st.text_input("CAS Number", "")
        with c2:
            new_supplier = st.text_input("Supplier", "")
            new_location = location_widget("Location", value="", key="add_loc")
            new_unit = st.text_input("Unit", "mL")
        with c3:
            new_qty = st.number_input("Quantity", min_value=0.0, value=0.0, step=0.1)
            new_low = st.number_input("Low stock threshold", min_value=0.0, value=10.0, step=1.0)
            has_exp = st.checkbox("Has expiration date?", value=False)
            new_exp = st.date_input("Expiration date", value=date.today()) if has_exp else None

        if st.form_submit_button("➕ Add reagent", type="primary", use_container_width=True):
            if not new_name.strip():
                st.error("Name is required.")
                st.stop()

            payload = {
                "id": new_id.strip(),
                "name": new_name.strip(),
                "cas_number": new_cas.strip(),
                "supplier": new_supplier.strip(),
                "location": new_location.strip(),
                "quantity": str(new_qty),
                "unit": new_unit.strip(),
                "expiration_date": new_exp.isoformat() if new_exp else "",
                "low_stock_threshold": str(new_low),
            }
            append_row(svc, SPREADSHEET_ID, RAW_HEADERS, payload)
            audit(svc, SPREADSHEET_ID, st.session_state.username, st.session_state.role, "CREATE", 0, new_name, str(payload))
            st.success("Reagent added.")
            cached_load.clear()
            st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# Admin: notify now
# ─────────────────────────────────────────────────────────────────────────────
with tab_admin:
    st.subheader("Notifications")
    if st.session_state.role != "admin":
        st.info("Admin only")
    else:
        if st.button("Send Slack + Email alerts now"):
            txt = []
            if alerts["low_stock"]:
                txt.append("LOW STOCK:\n" + "\n".join(alerts["low_stock"]))
            if alerts["expired"]:
                txt.append("EXPIRED:\n" + "\n".join(alerts["expired"]))
            msg = "\n\n".join(txt) if txt else "No alerts."

            send_slack(msg)
            send_email("Lab Inventory Alerts", msg)
            st.success("Sent (if configured).")

st.caption("Laboratory Reagent Inventory • January 2026")
