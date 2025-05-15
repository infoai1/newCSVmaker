import streamlit as st
import pandas as pd
import io
import re
import logging

# --- Setup Logging and Helpers ---
# This needs to be configured before other modules that use logging are imported,
# if those modules also try to configure basicConfig.
# Using force=True to try and override any default Streamlit logging config.
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)-12s | %(module)s:%(lineno)d | %(message)s",
    force=True
)
# Test log to confirm DEBUG level
logging.debug("app.py: Logging configured at DEBUG level.")


# Import custom modules AFTER basicConfig is set up if they also use logging.
try:
    from utils import ensure_nltk_punkt, load_tokenizer
    from file_processor import extract_sentences_with_structure
    from chunker import chunk_structured_sentences, chunk_by_chapter
except ImportError as ie:
    logging.error(f"app.py: Failed to import necessary modules. Error: {ie}", exc_info=True)
    st.error(f"Failed to import necessary modules. Check file structure and names. Error: {ie}")
    st.stop()

# --- Page Config ---
try:
    st.set_page_config(page_title="DOCX Processor", layout="wide")
    st.title("📖 DOCX Text Processor for AI Tasks")
    st.markdown("Upload a DOCX book file to extract, structure, and chunk its content.")
    logging.debug("app.py: Page config set.")
except Exception as page_setup_err:
     logging.error(f"app.py: Streamlit page setup failed: {page_setup_err}", exc_info=True)
     st.error(f"Error initializing Streamlit page: {page_setup_err}")
     st.stop()

# --- Initialize Session State ---
if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None
    logging.debug("app.py: Initialized session_state.processed_data")
if 'processed_filename' not in st.session_state:
    st.session_state.processed_filename = None
    logging.debug("app.py: Initialized session_state.processed_filename")
if 'uploaded_file_info' not in st.session_state:
    st.session_state.uploaded_file_info = None
    logging.debug("app.py: Initialized session_state.uploaded_file_info")


try:
    ensure_nltk_punkt()
    tokenizer = load_tokenizer()
    logging.debug("app.py: NLTK and Tokenizer initialized.")
except Exception as e:
    logging.error(f"app.py: Initialization failed (NLTK/Tokenizer): {e}", exc_info=True)
    st.error(f"Initialization failed (NLTK/Tokenizer): {e}")
    st.stop()

# --- Constants ---
TARGET_TOKENS = 200
OVERLAP_SENTENCES = 2
COMMON_FONTS = ["Arial", "Calibri", "Times New Roman", "Courier New", "Verdana", "Georgia", "Helvetica", "Tahoma", "Garamond", "Bookman", "Perpetua"]
logging.debug("app.py: Constants defined.")

# --- Sidebar Definition ---
with st.sidebar:
    st.header("⚙️ Processing Options")
    logging.debug("app.py: Sidebar rendering.")

    uploaded_file_widget = st.file_uploader(
        "1. Upload DOCX File",
        type=['docx'],
        accept_multiple_files=False,
        key="file_uploader_widget"
    )

    if uploaded_file_widget is not None:
        logging.debug(f"app.py: File uploaded: {uploaded_file_widget.name}")
        if st.session_state.uploaded_file_info is None or \
           st.session_state.uploaded_file_info['name'] != uploaded_file_widget.name or \
           st.session_state.uploaded_file_info['size'] != uploaded_file_widget.size:
             st.session_state.uploaded_file_info = {
                 "name": uploaded_file_widget.name,
                 "size": uploaded_file_widget.size,
                 "type": uploaded_file_widget.type,
                 "getvalue": uploaded_file_widget.getvalue()
             }
             st.session_state.processed_data = None
             st.session_state.processed_filename = None
             logging.info(f"app.py: New file selected and session state updated: {st.session_state.uploaded_file_info['name']}")
             st.success(f"File selected: {st.session_state.uploaded_file_info['name']} ({st.session_state.uploaded_file_info['size'] / 1024:.1f} KB)")
    # else:
        # logging.debug("app.py: No file uploaded yet via widget.")


    if st.session_state.uploaded_file_info:
        logging.debug(f"app.py: Processing options for file: {st.session_state.uploaded_file_info['name']}")
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
                ch_check_alignment = st.checkbox("Enable Alignment Check?", value=True, key="ch_check_alignment")

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
                 ch_case_title = st.checkbox("Title Case (Chapter)?", value=False, disabled=not ch_check_case, key="ch_case_title_ch")
                 ch_case_upper = st.checkbox("ALL CAPS (Chapter)?", value=True, disabled=not ch_check_case, key="ch_case_upper")
                 st.markdown("**Word Count**")
                 ch_word_count_min = st.number_input("Min Words (Chapter)", min_value=1, value=1, step=1, disabled=not ch_check_word_count, key="ch_wc_min")
                 ch_word_count_max = st.number_input("Max Words (Chapter)", min_value=1, value=10, step=1, disabled=not ch_check_word_count, key="ch_wc_max")
                 st.markdown("**Alignment (DOCX)**")
                 ch_alignment_centered = st.checkbox("Must be Centered (Chapter)?", value=True, disabled=not ch_check_alignment, key="ch_align_center")

        # --- Sub-Chapter Heading Style Definition ---
        st.subheader("Define Sub-Chapter Heading Style", help="Configure how sub-chapter titles are identified in DOCX. Default: ALL CAPS & Centered.")
        with st.expander("Sub-Chapter Heading Criteria", expanded=False):
            sch_enable_all_criteria = st.checkbox("Enable Sub-Chapter Detection?", value=True, key="sch_enable_all", help="Uncheck to disable all sub-chapter detection.")

            col_sch_1, col_sch_2, col_sch_3 = st.columns(3)
            with col_sch_1:
                sch_check_font_props = st.checkbox("Font Checks (Sub)?", value=False, key="sch_check_font_props", disabled=not sch_enable_all_criteria)
                sch_check_case = st.checkbox("Case Checks (Sub)?", value=True, key="sch_check_case", disabled=not sch_enable_all_criteria)
            with col_sch_2:
                sch_check_word_count = st.checkbox("Word Count (Sub)?", value=True, key="sch_check_word_count", disabled=not sch_enable_all_criteria)
            with col_sch_3:
                sch_check_alignment = st.checkbox("Alignment (Sub)?", value=True, key="sch_check_alignment", disabled=not sch_enable_all_criteria)

            st.markdown("---")
            c_sch_1, c_sch_2, c_sch_3 = st.columns(3)
            with c_sch_1:
                st.markdown("**Font Props (Sub)**")
                sch_style_bold = st.checkbox("Bold (Sub)?", value=False, disabled=not sch_check_font_props or not sch_enable_all_criteria, key="sch_style_bold")
                sch_style_italic = st.checkbox("Italic (Sub)?", value=False, disabled=not sch_check_font_props or not sch_enable_all_criteria, key="sch_style_italic")
                sch_min_font_size = st.number_input("Min Font (Sub, pts)", min_value=0.0, value=12.0, step=0.5, disabled=not sch_check_font_props or not sch_enable_all_criteria, key="sch_min_font_size")
                sch_font_names = st.multiselect("Fonts (Sub)", options=COMMON_FONTS, default=[], disabled=not sch_check_font_props or not sch_enable_all_criteria, key="sch_font_names")

            with c_sch_2:
                 st.markdown("**Text Case (Sub)**")
                 sch_case_title = st.checkbox("Title Case (Sub)?", value=False, disabled=not sch_check_case or not sch_enable_all_criteria, key="sch_case_title_sch")
                 sch_case_upper = st.checkbox("ALL CAPS (Sub)?", value=True, disabled=not sch_check_case or not sch_enable_all_criteria, key="sch_case_upper_sch")
                 st.markdown("**Word Count (Sub)**")
                 sch_word_count_min = st.number_input("Min Words (Sub)", min_value=1, value=1, step=1, disabled=not sch_check_word_count or not sch_enable_all_criteria, key="sch_wc_min_sch")
                 sch_word_count_max = st.number_input("Max Words (Sub)", min_value=1, value=10, step=1, disabled=not sch_check_word_count or not sch_enable_all_criteria, key="sch_wc_max_sch")

            with c_sch_3:
                 st.markdown("**Alignment (Sub)**")
                 sch_alignment_centered = st.checkbox("Centered (Sub)?", value=True, disabled=not sch_check_alignment or not sch_enable_all_criteria, key="sch_align_center_sch")

        st.subheader("Chunking Strategy")
        chunk_mode = st.radio(
            "Choose how to chunk the text:",
            (f"Chunk by ~{TARGET_TOKENS} Tokens (with {OVERLAP_SENTENCES} sentence overlap)", "Chunk by Detected Chapter Title"),
            index=0, key="chunk_mode"
        )

        st.subheader("Output Options")
        include_marker = st.checkbox("Include Paragraph Marker in Output?", value=True, key="include_marker")

        st.markdown("---")
        process_button = st.button(
            "🚀 Process File", type="primary", key="process_button"
            )
    else:
        logging.debug("app.py: No file in session state, showing upload prompt.")
        st.info("Please upload a DOCX file to begin.")
        process_button = False


if process_button:
    logging.info("app.py: Process button clicked.")
    file_info = st.session_state.uploaded_file_info
    if not file_info:
        logging.error("app.py: Process button clicked but no file_info in session state.")
        st.error("Error: No file information found. Please re-upload.")
        st.stop()

    filename = file_info['name']
    file_content = file_info['getvalue']
    logging.debug(f"app.py: Processing file: {filename}")

    ch_heading_criteria = {
        'check_font_props': st.session_state.ch_check_font_props,
        'style_bold': st.session_state.ch_style_bold,
        'style_italic': st.session_state.ch_style_italic,
        'min_font_size': st.session_state.ch_min_font_size if st.session_state.ch_check_font_props else 0.0,
        'font_names': st.session_state.ch_font_names if st.session_state.ch_check_font_props else [],
        'check_case': st.session_state.ch_check_case,
        'case_title': st.session_state.ch_case_title_ch,
        'case_upper': st.session_state.ch_case_upper,
        'check_word_count': st.session_state.ch_check_word_count,
        'word_count_min': st.session_state.ch_wc_min if st.session_state.ch_check_word_count else 1,
        'word_count_max': st.session_state.ch_wc_max if st.session_state.ch_check_word_count else 999,
        'check_alignment': st.session_state.ch_check_alignment,
        'alignment_centered': st.session_state.ch_align_center if st.session_state.ch_check_alignment else False,
        'check_pattern': False, 'pattern_regex': None,
    }
    logging.debug(f"app.py: Chapter criteria collected: {ch_heading_criteria}")

    sch_heading_criteria = {}
    if st.session_state.get("sch_enable_all", False): # Use .get for safety if key might not exist
        sch_heading_criteria = {
            'check_font_props': st.session_state.sch_check_font_props,
            'style_bold': st.session_state.sch_style_bold,
            'style_italic': st.session_state.sch_style_italic,
            'min_font_size': st.session_state.sch_min_font_size if st.session_state.sch_check_font_props else 0.0,
            'font_names': st.session_state.sch_font_names if st.session_state.sch_check_font_props else [],
            'check_case': st.session_state.sch_check_case,
            'case_title': st.session_state.sch_case_title_sch,
            'case_upper': st.session_state.sch_case_upper_sch,
            'check_word_count': st.session_state.sch_check_word_count,
            'word_count_min': st.session_state.sch_wc_min_sch if st.session_state.sch_check_word_count else 1,
            'word_count_max': st.session_state.sch_wc_max_sch if st.session_state.sch_check_word_count else 999,
            'check_alignment': st.session_state.sch_check_alignment,
            'alignment_centered': st.session_state.sch_align_center_sch if st.session_state.sch_check_alignment else False,
            'check_pattern': False, 'pattern_regex': None,
        }
    logging.debug(f"app.py: Sub-chapter criteria collected (enabled: {st.session_state.get('sch_enable_all', False)}): {sch_heading_criteria}")


    combined_heading_criteria = {
        "chapter": ch_heading_criteria,
        "sub_chapter": sch_heading_criteria
    }

    with st.spinner(f"Processing '{filename}'... This may take a moment."):
        try:
            logging.info(f"app.py: Calling extract_sentences_with_structure for {filename}")
            structured_sentences = extract_sentences_with_structure(
                file_content=file_content,
                filename=filename,
                heading_criteria=combined_heading_criteria
            )
            logging.info(f"app.py: Extraction complete. Found {len(structured_sentences)} sentence segments.")

            if not structured_sentences:
                st.warning("No text segments were extracted. Check DOCX content or heading criteria.")
                chunks = []
            else:
                logging.info(f"app.py: Starting chunking using mode: {st.session_state.chunk_mode}...")
                if st.session_state.chunk_mode.startswith("Chunk by ~"):
                    chunks = chunk_structured_sentences(
                        structured_data=structured_sentences, tokenizer=tokenizer,
                        target_tokens=TARGET_TOKENS, overlap_sentences=OVERLAP_SENTENCES
                    )
                else:
                    chunks = chunk_by_chapter(structured_data=structured_sentences)
                logging.info(f"app.py: Chunking complete. Created {len(chunks)} chunks.")

            if chunks:
                df = pd.DataFrame(chunks, columns=['chunk_text', 'marker', 'title', 'sub_title'])
                df['title'] = df['title'].fillna("Unknown Chapter")
                df['sub_title'] = df['sub_title'].fillna("")
                final_columns = {
                    'chunk_text': 'Text Chunk', 'marker': 'Source Marker',
                    'title': 'Detected Chapter', 'sub_title': 'Detected Sub-Chapter'
                }
                df.rename(columns=final_columns, inplace=True)
            else:
                 df = pd.DataFrame(columns=['Text Chunk', 'Source Marker', 'Detected Chapter', 'Detected Sub-Chapter'])
                 if not structured_sentences: st.warning("No text segments extracted.")
                 else: st.warning("Text extracted but chunking resulted in zero chunks.")
            logging.debug(f"app.py: DataFrame created/updated. Shape: {df.shape}")

            display_columns = ['Text Chunk', 'Detected Chapter', 'Detected Sub-Chapter']
            if st.session_state.include_marker and 'Source Marker' in df.columns:
                display_columns.insert(1, 'Source Marker')
            final_df = df[[col for col in display_columns if col in df.columns]]

            st.session_state.processed_data = final_df
            st.session_state.processed_filename = filename.split('.')[0]
            st.success(f"✅ Processing complete for '{filename}'!")
            logging.info(f"app.py: Processing complete for '{filename}'.")


        except (ValueError, RuntimeError, FileNotFoundError, Exception) as e:
            logging.error(f"app.py: Processing failed for {filename}: {e}", exc_info=True)
            st.error(f"An error occurred during processing: {e}")
            st.session_state.processed_data = None
            st.session_state.processed_filename = None
# else:
    # logging.debug("app.py: Process button not clicked.")


if st.session_state.processed_data is not None:
    logging.debug("app.py: Displaying processed data.")
    st.header("📊 Processed Chunks")
    st.dataframe(st.session_state.processed_data, use_container_width=True)
    if not st.session_state.processed_data.empty:
        st.info(f"Total Chunks Created: {len(st.session_state.processed_data)}")
        try:
            csv_data = st.session_state.processed_data.to_csv(index=False).encode('utf-8')
            download_filename = f"{st.session_state.processed_filename}_chunks.csv"
            st.download_button(
                label="📥 Download Chunks as CSV", data=csv_data,
                file_name=download_filename, mime='text/csv', key="download_button"
            )
        except Exception as download_err:
            logging.error(f"app.py: Failed to prepare download file: {download_err}", exc_info=True)
            st.error(f"Failed to prepare download file: {download_err}")
    else:
        st.info("Processing resulted in 0 chunks.")
# else:
    # logging.debug("app.py: No processed data to display.")


if st.session_state.uploaded_file_info is None and st.session_state.processed_data is None :
     # This condition might need adjustment depending on when you want to show this message.
     # Show if no file has ever been uploaded AND no processing has happened.
     logging.debug("app.py: No file uploaded and no data processed, showing initial prompt.")
     st.markdown("---")
     st.markdown("Upload a DOCX file and configure options in the sidebar to start processing.")

logging.debug("app.py: Reached end of script execution for this run.")
