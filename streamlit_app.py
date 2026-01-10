# 在 tab2 中添加/替换为这个增强版“Quick Entry via Photo”部分

with tab2:
    st.header("Add New Reagent")
    
    # ... 保持原有的手动表单部分不变 ...
    
    # 动态表单key（保持自动清空功能）
    if "add_form_key" not in st.session_state:
        st.session_state.add_form_key = 0
    
    # 同时也保存OCR解析出来的建议值（session state）
    if "ocr_suggestions" not in st.session_state:
        st.session_state.ocr_suggestions = {
            "name": "",
            "cas_number": "",
            "supplier": "",
            "catalog_number": ""  # 额外字段，可选
        }
    
    st.subheader("📸 Quick Entry via Photo (OCR)")
    st.info("拍试剂标签照片或上传图片 → 系统自动尝试提取名称、CAS号、货号、供应商等信息")

    # 拍照或上传
    uploaded_photo = (
        st.camera_input("直接用摄像头拍照") or
        st.file_uploader("或上传已拍好的照片", type=["jpg", "png", "jpeg"])
    )
    
    if uploaded_photo:
        st.image(uploaded_photo, caption="试剂标签照片", width=400)
        
        with st.spinner("正在OCR识别文本... (首次可能稍慢)"):
            try:
                # 初始化EasyOCR（只加载一次比较好，但Streamlit每次rerun都会重载，可优化）
                reader = easyocr.Reader(['en'], gpu=False)  # 'en'英文为主，必要时加'ch_sim'
                
                img = Image.open(uploaded_photo)
                img_array = np.array(img)
                
                results = reader.readtext(img_array, detail=0)  # 只取文本
                extracted_text = " ".join(results).upper()  # 统一大写方便匹配
                
                st.text_area("原始提取文本（可参考）", extracted_text, height=120)
                
                # 简单规则解析（可根据实际标签格式不断优化）
                suggestions = {"name": "", "cas_number": "", "supplier": "", "catalog_number": ""}
                
                # 尝试提取常见字段（关键词匹配，可扩展正则或更智能方法）
                words = extracted_text.split()
                for i, word in enumerate(words):
                    # CAS号通常是 数字-数字-数字 格式
                    if '-' in word and len(word.split('-')) == 3 and all(part.isdigit() for part in word.split('-')):
                        suggestions["cas_number"] = word
                    
                    # 常见供应商关键词
                    if any(kw in word for kw in ["SIGMA", "ALDRICH", "MERCK", "THERMO", "FISHER", "ACROS", "TCI"]):
                        suggestions["supplier"] = word
                    
                    # Catalog / Cat.No. / Product No. 后面往往是货号
                    if any(kw in word for kw in ["CAT", "CAT.", "CATALOG", "CATALOGUE", "PRODUCT", "P/N", "REF"]):
                        if i+1 < len(words):
                            suggestions["catalog_number"] = words[i+1]
                            # 试剂名称往往在货号前面几行，可尝试取前几个词
                            if i > 2:
                                suggestions["name"] = " ".join(words[max(0,i-4):i])
                
                # 如果没提取到名称，用前几行文本作为fallback
                if not suggestions["name"] and len(words) > 3:
                    suggestions["name"] = " ".join(words[:5])
                
                # 保存建议值到session
                st.session_state.ocr_suggestions = suggestions
                
                st.success("OCR提取完成！建议值已自动填充到下方表单，可直接修改后添加")
                
            except Exception as e:
                st.error(f"OCR处理失败：{str(e)}\n请确保图片清晰、文字可辨识。")

    # 显示并自动填充表单（使用session中的OCR建议值）
    st.markdown("### 使用OCR建议值（可编辑）")
    
    with st.form(key=f"add_form_{st.session_state.add_form_key}"):
        col1, col2 = st.columns(2)
        
        # 预填OCR建议值（如果有）
        name_default = st.session_state.ocr_suggestions.get("name", "")
        cas_default = st.session_state.ocr_suggestions.get("cas_number", "")
        supplier_default = st.session_state.ocr_suggestions.get("supplier", "")
        
        name = col1.text_input("Name*", value=name_default, help="Required")
        cas = col1.text_input("CAS Number", value=cas_default)
        supplier = col2.text_input("Supplier", value=supplier_default)
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
                # ... 原有的插入数据库代码保持不变 ...
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                c.execute("""INSERT INTO reagents 
                            (name, cas_number, supplier, location, quantity, unit, expiration_date, low_stock_threshold)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                          (name, cas or None, supplier or None, location, quantity, unit,
                           str(exp_date) if exp_date else None, threshold))
                conn.commit()
                conn.close()
                
                st.success(f"成功添加 '{name}'！")
                
                # 清空OCR建议值，准备下一次拍照
                st.session_state.ocr_suggestions = {"name": "", "cas_number": "", "supplier": "", "catalog_number": ""}
                
                # 表单重置
                st.session_state.add_form_key += 1
                st.cache_data.clear()
                st.rerun()
