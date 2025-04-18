import streamlit as st
import pandas as pd
import re
import logging

from utils import ensure_nltk_punkt, load_tokenizer  # unchanged helpers
from file_processor import extract_sentences_with_structure
from chunker import chunk_structured_sentences, chunk_by_chapter

# --------------------------------------------------
# Streamlit Page Config
# --------------------------------------------------
st.set_page_config(page_title="Book Processor", layout="wide")
st.title("📖 Book Text Processor for AI Tasks")

# --------------------------------------------------
# Session‐state init
# --------------------------------------------------
for key, default in {
    'processed_data': None,
    'processed_filename': None,
    'uploaded_file_info': None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# --------------------------------------------------
# Sidebar – Upload + options (subtitle removed)
# --------------------------------------------------
with st.sidebar:
    st.header("⚙️ Processing Options")
    uploaded = st.file_uploader("Upload PDF or DOCX", type=['pdf', 'docx'])

    if uploaded:
        st.session_state.uploaded_file_info = {
            'name': uploaded.name,
            'size': uploaded.size,
            'type': uploaded.type,
            'getvalue': uploaded.getvalue(),
        }
        st.success(f"Selected: {uploaded.name} ({uploaded.size/1024:.1f} KB)")

    # PDF‐specific skip / offset
    pdf_skip_start = st.number_input("Pages to Skip at START", 0, 999, 0)
    pdf_skip_end = st.number_input("Pages to Skip at END", 0, 999, 0)
    pdf_first_page = st.number_input("Actual Page # of FIRST Processed Page", 1, 9999, 1)

    # -------- Heading style criteria --------
    st.subheader("Define Chapter Heading Style")
    with st.expander("Heading Style Criteria"):
        check_case = st.checkbox("Enable Text Case Checks?", True)
        case_title = st.checkbox("Title Case?", True, disabled=not check_case)
        case_upper = st.checkbox("ALL CAPS?", False, disabled=not check_case)
        check_pattern = st.checkbox("Enable Keyword/Pattern Check?", False)
        pattern_str = st.text_input("Regex Pattern", r"^(CHAPTER|SECTION|PART)\s+[IVXLCDM\d]+", disabled=not check_pattern)
        pattern_regex = None
        if check_pattern and pattern_str:
            try:
                pattern_regex = re.compile(pattern_str, re.IGNORECASE)
                st.caption("✅ Regex OK")
            except re.error as e:
                st.caption(f"❌ Invalid regex: {e}")
                pattern_regex = None

    # -------- Chunking strategy --------
    st.subheader("Chunking Strategy")
    chunk_mode = st.radio("Choose how to chunk the text:",
                         ("Chunk by ~200 Tokens (2‑sentence overlap)", "Chunk by Detected Chapter Title"))

    include_marker = st.checkbox("Include Page/Para Marker in Output?", True)

    process = st.button("🚀 Process File", disabled=uploaded is None or (check_pattern and pattern_regex is None))

# --------------------------------------------------
# Main process logic
# --------------------------------------------------
if process and st.session_state.uploaded_file_info:
    info = st.session_state.uploaded_file_info
    file_bytes = info['getvalue']
    filename = info['name']
    file_type = filename.split('.')[-1].lower()

    heading_criteria = {
        'check_case': check_case,
        'case_title': case_title,
        'case_upper': case_upper,
        'check_pattern': check_pattern,
        'pattern_regex': pattern_regex,
        'check_word_count': True,
        'word_count_min': 1,
        'word_count_max': 12,
        'check_font_size': False,
    }

    with st.spinner("Extracting & chunking …"):
        sents = extract_sentences_with_structure(
            file_content=file_bytes,
            filename=filename,
            pdf_skip_start=pdf_skip_start if file_type == 'pdf' else 0,
            pdf_skip_end=pdf_skip_end if file_type == 'pdf' else 0,
            pdf_first_page_offset=pdf_first_page,
            heading_criteria=heading_criteria,
        )

        if chunk_mode.startswith("Chunk by ~"):
            tokenizer = load_tokenizer()
            chunks = chunk_structured_sentences(sents, tokenizer)
        else:
            chunks = chunk_by_chapter(sents)

        df = pd.DataFrame(chunks, columns=["Text Chunk", "Source Marker", "Detected Title"])
        if not include_marker:
            df.drop(columns=["Source Marker"], inplace=True)

        st.session_state.processed_data = df
        st.session_state.processed_filename = filename.rsplit('.', 1)[0]
        st.success("Done!")

# --------------------------------------------------
# Display & download
# --------------------------------------------------
if st.session_state.processed_data is not None:
    st.header("📊 Processed Chunks")
    st.dataframe(st.session_state.processed_data, use_container_width=True)
    csv = st.session_state.processed_data.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download CSV", data=csv,
                       file_name=f"{st.session_state.processed_filename}_chunks.csv", mime='text/csv')
