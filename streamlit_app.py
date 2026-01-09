# streamlit_app.py - Laboratory Reagent Inventory Web App (QR Tools Fixed!)

import streamlit as st
import pandas as pd
from datetime import date, datetime
import qrcode
from io import BytesIO
import hashlib
from PIL import Image
import cv2
import numpy as np
from pyzbar.pyzbar import decode  # For QR decoding

# --- SQLite Fix for Streamlit Cloud ---
try:
    import pysqlite3 as sqlite3
except ImportError:
    import sqlite3
# --------------------------------------

st.set_page_config(page_title="Lab Reagent Inventory", layout="wide")
st.title("🧪 Laboratory Reagent Inventory System")

DB_FILE = "reagents.db"

# ... (init_db(), authentication, load_reagents(), load_logs(), alerts — keep unchanged from previous version)

# After login and alerts...

tab1, tab2, tab3, tab4, tab5 = st.tabs(["Catalog", "Add Reagent", "Log Usage", "QR Tools", "Admin"])

# ... (tab1, tab2, tab3 unchanged)

with tab4:
    st.header("QR Code Tools")
    
    if reagents_df.empty:
        st.info("Add some reagents first to generate QR codes!")
    else:
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Generate & Print QR Label")
            selected_id = st.selectbox("Select Reagent", reagents_df['id'], format_func=lambda x: reagents_df[reagents_df['id']==x]['name'].values[0])
            row = reagents_df[reagents_df['id'] == selected_id].iloc[0]
            
            # Auto-detect current app URL (works on deployed Streamlit Cloud!)
            current_url = st.text_input("Your App URL (auto-filled if possible)", value="https://" + st.secrets.get("app_url", "your-app.streamlit.app"), help="Usually your deployed URL")
            
            qr_data = f"{current_url}?reagent_id={selected_id}"
            
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            buf = BytesIO()
            img.save(buf, format="PNG")
            byte_im = buf.getvalue()
            
            st.image(byte_im, caption=f"QR for {row['name']} (ID: {selected_id})")
            st.download_button(
                label="Download QR Label (Print & Stick on Bottle)",
                data=byte_im,
                file_name=f"QR_{row['name'].replace(' ', '_')}_ID{selected_id}.png",
                mime="image/png"
            )
            st.code(qr_data, language=None)  # Show the link for verification
        
        with col2:
            st.subheader("Scan QR Code with Camera")
            camera_img = st.camera_input("Point your camera at the QR label")
            
            scanned_id = None
            if camera_img:
                # Process image for decoding
                bytes_data = camera_img.getvalue()
                img = Image.open(BytesIO(bytes_data))
                img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                
                decoded_objects = decode(img_cv)
                if decoded_objects:
                    for obj in decoded_objects:
                        data = obj.data.decode('utf-8')
                        st.success(f"QR Detected! Link: {data}")
                        # Extract reagent_id from URL
                        if "reagent_id=" in data:
                            scanned_id = int(data.split("reagent_id=")[-1].split("&")[0])
                            break
                    if scanned_id:
                        st.info(f"Loading Reagent ID {scanned_id}...")
                else:
                    st.warning("No QR code detected in image. Try again with better lighting/angle.")
                st.image(camera_img, caption="Captured Image")
            
            # Fallback manual entry
            manual_id = st.number_input("Or manually enter Reagent ID", min_value=1, step=1)
            view_id = scanned_id or manual_id
            
            if view_id and view_id in reagents_df['id'].values:
                view_row = reagents_df[reagents_df['id'] == view_id].iloc[0]
                st.subheader(f"Reagent Details: {view_row['name']}")
                st.write(view_row.T)

# ... (tab5 Admin unchanged)

st.caption("QR Tools Fixed! Generate labels, print, stick on bottles, and scan with phone/tablet camera for instant lookup.")
