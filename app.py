import streamlit as st
import pandas as pd
import re
import logging

from utils import ensure_nltk_punkt, load_tokenizer
from file_processor import extract_sentences_with_structure
from chunker import chunk_structured_sentences, chunk_by_chapter

# --------------------------------------------------
# Page setup
# --------------------------------------------------
st.set_page_config(page_title="Book Processor", layout="wide")
st.title("📖 Book Text Processor")

# --------------------------------------------------
# Session‐state init
# --------------------------------------------------
for k in ("processed_data", "processed_filename", "uploaded_file_info"):
    st.session_state.setdefault(k, None)

# --------------------------------------------------
# Constants
# --------------------------------------------------
TARGET_TOKENS = 200
OVERLAP_SENTENCES = 2

# --------------------------------------------------
# Sidebar – Upload & options
# --------------------------------------------------
with st.sidebar:
    st.header("⚙️ Options")

    uploaded = st.file_uploader("Upload PDF or DOCX", type=["pdf", "docx"])
    if uploaded:
        st.session_state.uploaded_file_info = {
            "name": uploaded.name,
            "size": uploaded.size,
            "getvalue": uploaded.getvalue(),
        }
        st.success(f"Selected {uploaded.name}")

    pdf_skip_start = st.number_input("Skip pages at START", 0, 999, 0)
    pdf_skip_end   = st.number_input("Skip pages at END",   0, 999, 0)
    pdf_first_off  = st.number_input("Real page # of first processed", 1, 9999, 1)

    st.subheader("Heading detection (defaults suited for your book)")
    check_case  = st.checkbox("Enable Text‑Case check", True)
    case_title  = st.checkbox("Title‑Case?", True, disabled=not check_case)
    case_upper  = st.checkbox("ALL‑CAPS?", False, disabled=not check_case)

    check_pattern = st.checkbox("Keyword / pattern?", False)
    pattern_str   = st.text_input("Regex", r"^(CHAPTER|SECTION|PART)\s+[IVXLCDM\d]+", disabled=not check_pattern)
    pattern_rx    = None
    if check_pattern and pattern_str:
        try:
            pattern_rx = re.compile(pattern_str, re.IGNORECASE)
            st.caption("✅ Regex OK")
        except re.error as e:
            st.caption(f"❌ {e}")
            pattern_rx = None

    chunk_mode = st.radio("Chunk by…", ("~200 tokens", "Detected chapter title"))
    include_marker = st.checkbox("Include page / para marker", True)

    run = st.button("🚀 Process", disabled=uploaded is None or (check_pattern and pattern_rx is None))

# --------------------------------------------------
# Prepare helpers
# --------------------------------------------------
ensure_nltk_punkt()
tokenizer = load_tokenizer()

heading_criteria_template = {
    'check_pattern': check_pattern,
    'pattern_regex': pattern_rx,
    'check_word_count': True,
    'word_count_min': 1,
    'word_count_max': 12,
    'check_case': check_case,
    'case_title': case_title,
    'case_upper': case_upper,
    'check_font_size': False,  # font‑size disabled by default
}

# --------------------------------------------------
# Main process
# --------------------------------------------------
if run and st.session_state.uploaded_file_info:
    info = st.session_state.uploaded_file_info
    fname = info["name"]
    fbytes = info["getvalue"]
    ftype  = fname.rsplit('.', 1)[-1].lower()

    with st.spinner("Extracting …"):
        sents = extract_sentences_with_structure(
            file_content=fbytes,
            filename=fname,
            pdf_skip_start=pdf_skip_start if ftype == "pdf" else 0,
            pdf_skip_end=pdf_skip_end   if ftype == "pdf" else 0,
            pdf_first_page_offset=pdf_first_off,
            heading_criteria=heading_criteria_template,
        )

        if chunk_mode.startswith("~200"):
            chunks = chunk_structured_sentences(sents, tokenizer,
                                               target_tokens=TARGET_TOKENS,
                                               overlap_sentences=OVERLAP_SENTENCES)
        else:
            chunks = chunk_by_chapter(sents)

    df = pd.DataFrame(chunks, columns=["Text Chunk", "Source Marker", "Detected Title"])
    if not include_marker:
        df.drop(columns=["Source Marker"], inplace=True)

    st.session_state.processed_data = df
    st.session_state.processed_filename = fname.rsplit('.', 1)[0]
    st.success("Done")

# --------------------------------------------------
# Display + download
# --------------------------------------------------
if st.session_state.processed_data is not None:
    st.dataframe(st.session_state.processed_data, use_container_width=True)
    csv = st.session_state.processed_data.to_csv(index=False).encode('utf‑8')
    st.download_button("📥 Download CSV", csv,
                       file_name=f"{st.session_state.processed_filename}_chunks.csv",
                       mime="text/csv")
