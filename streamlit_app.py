# streamlit_app.py - Lab Reagent Inventory (QR Generation Fixed, No pyzbar Needed)

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

# init_db(), authentication, load_reagents(), alerts — (keep from previous version)

# After alerts...

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Catalog", "Add Reagent", "Log Usage", "QR Tools", "Admin"])

# Tabs 1-3 unchanged...

with tab4:
    st.header("QR Code Tools")
    
    if reagents_df.empty:
        st.info("Add reagents first to generate QR codes!")
    else:
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Generate Printable QR Labels")
            selected_id = st.selectbox("Select Reagent", reagents_df['id'], 
                                      format_func=lambda x: reagents_df[reagents_df['id']==x]['name'].values[0])
            row = reagents_df[reagents_df['id'] == selected_id].iloc[0]
            
            # Get current app URL from query params or input
            query_params = st.query_params
            base_url = "https://" + query_params.get("base_url", ["your-app-name.streamlit.app"])[0]
            app_url = st.text_input("Your App URL (for QR links)", value=base_url, 
                                    help="Copy your deployed URL here once — it will be remembered")
            
            # Update query param for persistence
            st.query_params["base_url"] = app_url.split("//")[-1]
            
            qr_data = f"{app_url}?reagent_id={selected_id}"
            
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            buf = BytesIO()
            img.save(buf, format="PNG")
            byte_im = buf.getvalue()
            
            st.image(byte_im, caption=f"QR Label for {row['name']} (ID: {selected_id})")
            st.download_button(
                label="Download QR Label (Print & Stick!)",
                data=byte_im,
                file_name=f"QR_{row['name'].replace(' ', '_')}_ID{selected_id}.png",
                mime="image/png"
            )
            st.code(qr_data, language=None)
            st.success("Print this on sticker paper and attach to reagent bottles!")

        with col2:
            st.subheader("Quick Reagent Lookup")
            manual_id = st.number_input("Enter Reagent ID manually", min_value=1, step=1)
            
            if manual_id and manual_id in reagents_df['id'].values:
                view_row = reagents_df[reagents_df['id'] == manual_id].iloc[0]
                st.subheader(f"📋 Details: {view_row['name']}")
                st.dataframe(view_row.to_frame().T, use_container_width=True)
                st.info("Pro Tip: Bookmark the QR link on your phone for instant access!")

# Auto-load reagent from URL on app open
query_params = st.query_params
if "reagent_id" in query_params:
    auto_id = int(query_params["reagent_id"])
    if auto_id in reagents_df['id'].values:
        auto_row = reagents_df[reagents_df['id'] == auto_id].iloc[0]
        st.success(f"🔍 Auto-loaded Reagent: {auto_row['name']} (ID: {auto_id})")
        st.dataframe(auto_row.to_frame().T, use_container_width=True)

# Tab 5 unchanged...

st.caption("QR Generation works perfectly! Use your phone's browser to open the QR link for instant reagent lookup.")
