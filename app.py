import streamlit as st
import pandas as pd
import io
import re # Still needed for general use, even if not for headings
import logging

# Import custom modules
try:
    from utils import ensure_nltk_punkt, load_tokenizer
    from file_processor import extract_sentences_with_structure
    from chunker import chunk_structured_sentences, chunk_by_chapter
except ImportError as ie:
    st.error(f"Failed to import necessary modules. Check file structure and names. Error: {ie}")
    st.stop()

# --- Page Config ---
try:
    st.set_page_config(page_title="DOCX Processor", layout="wide")
    st.title("📖 DOCX Text Processor for AI Tasks")
    st.markdown("Upload a DOCX book file to extract, structure, and chunk its content.")
except Exception as page_setup_err:
     logging.error(f"Streamlit page setup failed: {page_setup_err}", exc_info=True)
     st.error(f"Error initializing Streamlit page: {page_setup_err}")
     st.stop()

# --- Initialize Session State ---
if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None
if 'processed_filename' not in st.session_state:
    st.session_state.processed_filename = None
if 'uploaded_file_info' not in st.session_state:
    st.session_state.uploaded_file_info = None

# --- Setup Logging and Helpers ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    ensure_nltk_punkt()
    tokenizer = load_tokenizer()
except Exception as e:
    st.error(f"Initialization failed (NLTK/Tokenizer): {e}")
    logging.error(f"Initialization failed: {e}", exc_info=True)
    st.stop()

# --- Constants ---
TARGET_TOKENS = 200
OVERLAP_SENTENCES = 2
# DEFAULT_CHAPTER_REGEX - Removed
# DEFAULT_SUBCHAPTER_REGEX - Removed
COMMON_FONTS = ["Arial", "Calibri", "Times New Roman", "Courier New", "Verdana", "Georgia", "Helvetica", "Tahoma", "Garamond", "Bookman", "Perpetua"]


# --- Sidebar Definition ---
with st.sidebar:
    st.header("⚙️ Processing Options")

    uploaded_file_widget = st.file_uploader(
        "1. Upload DOCX File",
        type=['docx'], # Only DOCX
        accept_multiple_files=False,
        key="file_uploader_widget"
    )

    if uploaded_file_widget is not None:
        # Check if file is different from the one potentially already processed
        if st.session_state.uploaded_file_info is None or \
           st.session_state.uploaded_file_info['name'] != uploaded_file_widget.name or \
           st.session_state.uploaded_file_info['size'] != uploaded_file_widget.size:
             st.session_state.uploaded_file_info = {
                 "name": uploaded_file_widget.name,
                 "size": uploaded_file_widget.size,
                 "type": uploaded_file_widget.type,
                 "getvalue": uploaded_file_widget.getvalue()
             }
             # Clear previous results when a new file is uploaded
             st.session_state.processed_data = None
             st.session_state.processed_filename = None
             st.success(f"File selected: {st.session_state.uploaded_file_info['name']} ({st.session_state.uploaded_file_info['size'] / 1024:.1f} KB)")


    # --- Display options only if a file has been selected ---
    if st.session_state.uploaded_file_info:
        st.info(f"Processing target: {st.session_state.uploaded_file_info['name']}")

        # --- Chapter Heading Style Definition ---
        st.subheader("Define Chapter Heading Style", help="Configure how chapter titles are identified in DOCX.")
        with st.expander("Chapter Heading Criteria", expanded=True):
            col_ch_1, col_ch_2 = st.columns(2)
            with col_ch_1:
                ch_check_font_props = st.checkbox("Enable Font Property Checks?", value=True, key="ch_check_font_props")
                ch_check_case = st.checkbox("Enable Text Case Checks?", value=True, key="ch_check_case")
            with col_ch_2:
                ch_check_word_count = st.checkbox("Enable Word Count Checks?", value=True, key="ch_check_word_count")
                ch_check_alignment = st.checkbox("Enable Alignment Check?", value=True, key="ch_check_alignment") # New Alignment Check

            st.markdown("---")
            c_ch_1, c_ch_2 = st.columns(2)
            with c_ch_1:
                st.markdown("**Font Properties (DOCX)**")
                ch_style_bold = st.checkbox("Must be Bold?", value=True, disabled=not ch_check_font_props, key="ch_style_bold")
                ch_style_italic = st.checkbox("Must be Italic?", value=False, disabled=not ch_check_font_props, key="ch_style_italic")
                ch_min_font_size = st.number_input("Min Font Size (Chapter, pts)", min_value=0.0, value=16.0, step=0.5, disabled=not ch_check_font_props, key="ch_min_font_size")
                ch_font_names = st.multiselect("Font Names (Chapter)", options=COMMON_FONTS, default=[], disabled=not ch_check_font_props, key="ch_font_names")

            with c_ch_2:
                 st.markdown("**Text Case**")
                 ch_case_title = st.checkbox("Title Case?", value=False, disabled=not ch_check_case, key="ch_case_title")
                 ch_case_upper = st.checkbox("ALL CAPS?", value=True, disabled=not ch_check_case, key="ch_case_upper")
                 st.markdown("**Word Count**")
                 ch_word_count_min = st.number_input("Min Words", min_value=1, value=1, step=1, disabled=not ch_check_word_count, key="ch_wc_min")
                 ch_word_count_max = st.number_input("Max Words", min_value=1, value=10, step=1, disabled=not ch_check_word_count, key="ch_wc_max")
                 st.markdown("**Alignment (DOCX)**") # New Alignment section
                 ch_alignment_centered = st.checkbox("Must be Centered?", value=True, disabled=not ch_check_alignment, key="ch_align_center")


        # --- Sub-Chapter Heading Style Definition ---
        st.subheader("Define Sub-Chapter Heading Style", help="Configure how sub-chapter titles are identified in DOCX.")
        with st.expander("Sub-Chapter Heading Criteria", expanded=False):
            col_sch_1, col_sch_2 = st.columns(2)
            with col_sch_1:
                sch_check_font_props = st.checkbox("Enable Font Property Checks (Sub)?", value=False, key="sch_check_font_props")
                sch_check_case = st.checkbox("Enable Text Case Checks (Sub)?", value=False, key="sch_check_case")
            with col_sch_2:
                sch_check_word_count = st.checkbox("Enable Word Count Checks (Sub)?", value=True, key="sch_check_word_count")
                # Pattern check removed for sub-chapters
                # sch_check_pattern = st.checkbox("Enable Keyword/Pattern Check (Sub)?", value=False, key="sch_check_pattern")

            st.markdown("---")
            c_sch_1, c_sch_2 = st.columns(2)
            with c_sch_1:
                st.markdown("**Font Properties (DOCX - Sub)**")
                sch_style_bold = st.checkbox("Must be Bold (Sub)?", value=True, disabled=not sch_check_font_props, key="sch_style_bold")
                sch_style_italic = st.checkbox("Must be Italic (Sub)?", value=False, disabled=not sch_check_font_props, key="sch_style_italic")
                sch_min_font_size = st.number_input("Min Font Size (Sub-Chapter, pts)", min_value=0.0, value=13.0, step=0.5, disabled=not sch_check_font_props, key="sch_min_font_size")
                sch_font_names = st.multiselect("Font Names (Sub-Chapter)", options=COMMON_FONTS, default=[], disabled=not sch_check_font_props, key="sch_font_names")

            with c_sch_2:
                 st.markdown("**Text Case (Sub)**")
                 sch_case_title = st.checkbox("Title Case (Sub)?", value=True, disabled=not sch_check_case, key="sch_case_title")
                 sch_case_upper = st.checkbox("ALL CAPS (Sub)?", value=False, disabled=not sch_check_case, key="sch_case_upper")
                 st.markdown("**Word Count (Sub)**")
                 sch_word_count_min = st.number_input("Min Words (Sub)", min_value=1, value=1, step=1, disabled=not sch_check_word_count, key="sch_wc_min")
                 sch_word_count_max = st.number_input("Max Words (Sub)", min_value=1, value=15, step=1, disabled=not sch_check_word_count, key="sch_wc_max")

            # Keyword/Pattern section removed for sub-chapters
            # st.markdown("**Keyword/Pattern (Sub-Chapter)**")
            # sch_pattern_regex_str = st.text_input("Regex (Sub-Chapter)", value=DEFAULT_SUBCHAPTER_REGEX, disabled=not sch_check_pattern, key="sch_pattern_str")
            # is_sch_regex_valid = True # Default to true as pattern is removed

        st.subheader("Chunking Strategy")
        chunk_mode = st.radio(
            "Choose how to chunk the text:",
            (f"Chunk by ~{TARGET_TOKENS} Tokens (with {OVERLAP_SENTENCES} sentence overlap)", "Chunk by Detected Chapter Title"),
            index=0, key="chunk_mode"
        )

        st.subheader("Output Options")
        include_marker = st.checkbox("Include Paragraph Marker in Output?", value=True, key="include_marker")

        st.markdown("---")
        # No more regex checks needed to disable button
        process_button_disabled = False

        # Removed warning about Regex patterns
        # if process_button_disabled:
        #      st.warning("Cannot process: Fix invalid or empty Regex pattern(s) first.")

        process_button = st.button(
            "🚀 Process File",
            type="primary",
            disabled=process_button_disabled, # Should always be enabled now unless other logic added
            key="process_button"
            )
    else: # No file selected in session state
        st.info("Please upload a DOCX file to begin.")
        process_button = False # Ensure button state is false


# --- Main Area Logic ---
if process_button:
    file_info = st.session_state.uploaded_file_info
    if not file_info:
        st.error("Error: No file information found. Please re-upload.")
        st.stop()

    filename = file_info['name']
    file_content = file_info['getvalue']

    # --- Retrieve Chapter Heading Criteria ---
    ch_heading_criteria = {
        'check_font_props': st.session_state.ch_check_font_props,
        'style_bold': st.session_state.ch_style_bold,
        'style_italic': st.session_state.ch_style_italic,
        'min_font_size': st.session_state.ch_min_font_size if st.session_state.ch_check_font_props else 0.0,
        'font_names': st.session_state.ch_font_names if st.session_state.ch_check_font_props else [],
        'check_case': st.session_state.ch_check_case,
        'case_title': st.session_state.ch_case_title,
        'case_upper': st.session_state.ch_case_upper,
        'check_word_count': st.session_state.ch_check_word_count,
        'word_count_min': st.session_state.ch_wc_min if st.session_state.ch_check_word_count else 1,
        'word_count_max': st.session_state.ch_wc_max if st.session_state.ch_check_word_count else 999,
        'check_alignment': st.session_state.ch_check_alignment, # New alignment check flag
        'alignment_centered': st.session_state.ch_align_center if st.session_state.ch_check_alignment else False, # New alignment value flag
        'check_pattern': False,
        'pattern_regex': None,
    }

    # --- Retrieve Sub-Chapter Heading Criteria ---
    sch_heading_criteria = {
        'check_font_props': st.session_state.sch_check_font_props,
        'style_bold': st.session_state.sch_style_bold,
        'style_italic': st.session_state.sch_style_italic,
        'min_font_size': st.session_state.sch_min_font_size if st.session_state.sch_check_font_props else 0.0,
        'font_names': st.session_state.sch_font_names if st.session_state.sch_check_font_props else [],
        'check_case': st.session_state.sch_check_case,
        'case_title': st.session_state.sch_case_title,
        'case_upper': st.session_state.sch_case_upper,
        'check_word_count': st.session_state.sch_check_word_count,
        'word_count_min': st.session_state.sch_wc_min if st.session_state.sch_check_word_count else 1,
        'word_count_max': st.session_state.sch_wc_max if st.session_state.sch_check_word_count else 999,
        'check_alignment': False, # Alignment check not added for sub-chapters here
        'alignment_centered': False,
        'check_pattern': False, # Pattern check explicitly disabled for sub-chapters
        'pattern_regex': None,   # No compiled regex for sub-chapters
    }

    combined_heading_criteria = {
        "chapter": ch_heading_criteria,
        "sub_chapter": sch_heading_criteria
    }

    with st.spinner(f"Processing '{filename}'... This may take a moment."):
        try:
            logging.info("Starting text extraction from DOCX...")
            structured_sentences = extract_sentences_with_structure(
                file_content=file_content,
                filename=filename,
                heading_criteria=combined_heading_criteria
            )
            logging.info(f"Extraction complete. Found {len(structured_sentences)} sentence segments.")

            if not structured_sentences:
                st.warning("No text segments were extracted. Check DOCX content or heading criteria.")
                chunks = []
            else:
                logging.info(f"Starting chunking using mode: {st.session_state.chunk_mode}...")
                if st.session_state.chunk_mode.startswith("Chunk by ~"):
                    chunks = chunk_structured_sentences(
                        structured_data=structured_sentences,
                        tokenizer=tokenizer,
                        target_tokens=TARGET_TOKENS,
                        overlap_sentences=OVERLAP_SENTENCES
                    )
                else: # Chunk by Chapter Title
                    chunks = chunk_by_chapter(
                        structured_data=structured_sentences
                    )
                logging.info(f"Chunking complete. Created {len(chunks)} chunks.")

            if chunks:
                # Expecting 4 elements: chunk_text, marker, chapter_title, sub_chapter_title
                df = pd.DataFrame(chunks, columns=['chunk_text', 'marker', 'title', 'sub_title'])
                df['title'] = df['title'].fillna("Unknown Chapter")
                df['sub_title'] = df['sub_title'].fillna("")
                final_columns = {
                    'chunk_text': 'Text Chunk',
                    'marker': 'Source Marker',
                    'title': 'Detected Chapter',
                    'sub_title': 'Detected Sub-Chapter'
                }
                df.rename(columns=final_columns, inplace=True)
            else:
                 # Create empty DataFrame with expected columns if no chunks
                 df = pd.DataFrame(columns=['Text Chunk', 'Source Marker', 'Detected Chapter', 'Detected Sub-Chapter'])
                 if not structured_sentences:
                      st.warning("No text segments extracted.")
                 else:
                      st.warning("Text extracted but chunking resulted in zero chunks.")

            # Select final columns based on user choice
            display_columns = ['Text Chunk', 'Detected Chapter', 'Detected Sub-Chapter']
            if st.session_state.include_marker:
                # Ensure 'Source Marker' column exists before inserting
                if 'Source Marker' in df.columns:
                     display_columns.insert(1, 'Source Marker')

            # Ensure all selected columns exist in the DataFrame
            final_df = df[[col for col in display_columns if col in df.columns]]

            # Store results in session state
            st.session_state.processed_data = final_df
            st.session_state.processed_filename = filename.split('.')[0]
            st.success(f"✅ Processing complete for '{filename}'!")

        except (ValueError, RuntimeError, FileNotFoundError, Exception) as e:
            logging.error(f"Processing failed for {filename}: {e}", exc_info=True)
            st.error(f"An error occurred during processing: {e}")
            # Clear results on error
            st.session_state.processed_data = None
            st.session_state.processed_filename = None


# --- Display Results Area ---
if st.session_state.processed_data is not None:
    st.header("📊 Processed Chunks")
    st.dataframe(st.session_state.processed_data, use_container_width=True)

    if not st.session_state.processed_data.empty:
        st.info(f"Total Chunks Created: {len(st.session_state.processed_data)}")
        # --- Download Button ---
        try:
            csv_data = st.session_state.processed_data.to_csv(index=False).encode('utf-8')
            download_filename = f"{st.session_state.processed_filename}_chunks.csv"
            st.download_button(
                label="📥 Download Chunks as CSV",
                data=csv_data,
                file_name=download_filename,
                mime='text/csv',
                key="download_button"
            )
        except Exception as download_err:
            st.error(f"Failed to prepare download file: {download_err}")
            logging.error(f"CSV conversion/download error: {download_err}", exc_info=True)
    else:
        st.info("Processing resulted in 0 chunks.")

elif st.session_state.uploaded_file_info is None: # Only show if no file ever uploaded
     st.markdown("---")
     st.markdown("Upload a DOCX file and configure options in the sidebar to start processing.")
