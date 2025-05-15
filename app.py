import streamlit as st
import pandas as pd
import io
import re
import logging

# --- Setup Logging and Helpers ---
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(module)s:%(lineno)d | %(message)s",
    force=True
)
logger_app = logging.getLogger(__name__)
logger_app.debug("app.py: Logging configured at DEBUG level.")

try:
    from utils import ensure_nltk_punkt, load_tokenizer
    from file_processor import extract_sentences_with_structure
    from chunker import chunk_structured_sentences, chunk_by_chapter
    
    fp_logger = logging.getLogger('file_processor')
    fp_logger.setLevel(logging.DEBUG) # Explicitly set for file_processor
    logger_app.debug(f"app.py: Logger '{fp_logger.name}' forced to DEBUG. Effective level: {logging.getLevelName(fp_logger.getEffectiveLevel())}")

except ImportError as ie:
    logger_app.error(f"app.py: Failed to import necessary modules. Error: {ie}", exc_info=True)
    st.error(f"Failed to import necessary modules. Check file structure and names. Error: {ie}")
    st.stop()

# --- Page Config ---
try:
    st.set_page_config(page_title="DOCX Processor", layout="wide")
    st.title("📖 DOCX Text Processor for AI Tasks")
    st.markdown("Upload a DOCX book file to extract, structure, and chunk its content.")
except Exception as page_setup_err:
     logger_app.error(f"app.py: Streamlit page setup failed: {page_setup_err}", exc_info=True)
     st.error(f"Error initializing Streamlit page: {page_setup_err}")
     st.stop()

# --- Initialize Session State ---
if 'processed_data' not in st.session_state: st.session_state.processed_data = None
if 'processed_filename' not in st.session_state: st.session_state.processed_filename = None
if 'uploaded_file_info' not in st.session_state: st.session_state.uploaded_file_info = None

try:
    ensure_nltk_punkt()
    tokenizer = load_tokenizer()
except Exception as e:
    logger_app.error(f"app.py: Initialization failed (NLTK/Tokenizer): {e}", exc_info=True)
    st.error(f"Initialization failed (NLTK/Tokenizer): {e}")
    st.stop()

# --- Constants ---
TARGET_TOKENS = 200
OVERLAP_SENTENCES = 2
COMMON_FONTS = sorted(["Arial", "Calibri", "Times New Roman", "Courier New", "Verdana", "Georgia", "Helvetica", "Tahoma", "Garamond", "Bookman", "Perpetua", "Cambria", "Century", "Franklin Gothic Book"]) # Added more and sorted
# Allow users to add custom fonts
if 'custom_fonts' not in st.session_state:
    st.session_state.custom_fonts = []


# --- Sidebar Definition ---
with st.sidebar:
    st.header("⚙️ Processing Options")

    # Custom Font Input
    st.subheader("Custom Fonts")
    custom_font_input = st.text_input("Add custom font name (then press Enter)", key="custom_font_text_input")
    if st.button("Add Font", key="add_custom_font_button"):
        if custom_font_input and custom_font_input not in st.session_state.custom_fonts and custom_font_input not in COMMON_FONTS:
            st.session_state.custom_fonts.append(custom_font_input)
            st.rerun() # Rerun to update multiselect options
        elif not custom_font_input:
            st.caption("Please enter a font name.")
        else:
            st.caption(f"'{custom_font_input}' is already in the list or common fonts.")

    # Combine common and custom fonts for selection
    all_available_fonts = sorted(list(set(COMMON_FONTS + st.session_state.custom_fonts)))


    uploaded_file_widget = st.file_uploader(
        "1. Upload DOCX File", type=['docx'], accept_multiple_files=False, key="file_uploader_widget"
    )

    if uploaded_file_widget is not None:
        if st.session_state.uploaded_file_info is None or \
           st.session_state.uploaded_file_info['name'] != uploaded_file_widget.name or \
           st.session_state.uploaded_file_info['size'] != uploaded_file_widget.size:
             st.session_state.uploaded_file_info = {
                 "name": uploaded_file_widget.name, "size": uploaded_file_widget.size,
                 "type": uploaded_file_widget.type, "getvalue": uploaded_file_widget.getvalue()
             }
             st.session_state.processed_data = None
             st.session_state.processed_filename = None
             logger_app.info(f"app.py: New file: {st.session_state.uploaded_file_info['name']}")
             st.success(f"File selected: {st.session_state.uploaded_file_info['name']} ({st.session_state.uploaded_file_info['size'] / 1024:.1f} KB)")

    if st.session_state.uploaded_file_info:
        st.info(f"Processing target: {st.session_state.uploaded_file_info['name']}")

        # --- Chapter Heading Style Definition ---
        st.subheader("Define Chapter Heading Style")
        with st.expander("Chapter Heading Criteria", expanded=True):
            ch_font_names = st.multiselect("Font Names (Chapter)", options=all_available_fonts, default=["Perpetua"], key="ch_font_names_sel", help="Select one or more font names for chapters.")
            ch_min_font_size = st.number_input("Min Font Size (Chapter, pts)", min_value=6.0, value=16.0, step=0.5, key="ch_min_font_size_val", help="Minimum point size for chapter headings.")
            
            st.markdown("<hr style='margin:0.5rem 0;'>", unsafe_allow_html=True)
            ch_opt_col1, ch_opt_col2 = st.columns(2)
            with ch_opt_col1:
                ch_check_case = st.checkbox("Also Check ALL CAPS (Chapter)?", value=True, key="ch_check_case_val")
            with ch_opt_col2:
                ch_check_alignment = st.checkbox("Also Check Centered (Chapter)?", value=True, key="ch_check_alignment_val")


        # --- Sub-Chapter Heading Style Definition ---
        st.subheader("Define Sub-Chapter Heading Style")
        sch_enable_all_criteria = st.checkbox("Enable Sub-Chapter Detection?", value=True, key="sch_enable_all_val", help="Uncheck to disable all sub-chapter detection.")
        
        with st.expander("Sub-Chapter Heading Criteria", expanded=False):
            sch_font_names = st.multiselect("Font Names (Sub-Chapter)", options=all_available_fonts, default=["Perpetua"], key="sch_font_names_sel", help="Select font names for sub-chapters.", disabled=not sch_enable_all_criteria)
            sch_min_font_size = st.number_input("Min Font Size (Sub, pts)", min_value=6.0, value=12.0, step=0.5, key="sch_min_font_size_val", help="Minimum point size for sub-chapters.", disabled=not sch_enable_all_criteria)
            
            st.markdown("<hr style='margin:0.5rem 0;'>", unsafe_allow_html=True)
            sch_opt_col1, sch_opt_col2 = st.columns(2)
            with sch_opt_col1:
                sch_check_case = st.checkbox("Also Check ALL CAPS (Sub)?", value=True, key="sch_check_case_val", help="Additionally check if sub-chapter is ALL CAPS.", disabled=not sch_enable_all_criteria)
            with sch_opt_col2:
                sch_check_alignment = st.checkbox("Also Check Centered (Sub)?", value=True, key="sch_check_alignment_val", help="Additionally check if sub-chapter is centered.", disabled=not sch_enable_all_criteria)
            
            sch_word_count_max = st.number_input("Max Words (Sub-Chapter)", min_value=1, value=10, step=1, key="sch_wc_max_val", help="Optional: Maximum words for a sub-chapter title.", disabled=not sch_enable_all_criteria)


        st.subheader("Chunking Strategy")
        chunk_mode = st.radio("Chunk by:", ("~200 Tokens", "Chapter Title"), index=0, key="chunk_mode_sel")

        st.subheader("Output Options")
        include_marker = st.checkbox("Include Source Marker?", value=True, key="include_marker_val")

        st.markdown("---")
        process_button = st.button("🚀 Process File", type="primary", key="process_button_val")
    else:
        st.info("Please upload a DOCX file to begin.")
        process_button = False


if process_button:
    logger_app.info("app.py: Process button clicked.")
    file_info = st.session_state.uploaded_file_info
    if not file_info:
        st.error("Error: No file information found. Please re-upload.")
        st.stop()

    filename, file_content = file_info['name'], file_info['getvalue']

    ch_heading_criteria = {
        'check_font_props': True, # Always true now as it's the primary method
        'font_names': st.session_state.ch_font_names_sel,
        'min_font_size': st.session_state.ch_min_font_size_val,
        'check_case': st.session_state.ch_check_case_val,
        'case_upper': True if st.session_state.ch_check_case_val else False, # Only if master case check is on
        'case_title': False, # Not offering Title Case for simplicity now
        'check_alignment': st.session_state.ch_check_alignment_val,
        'alignment_centered': True if st.session_state.ch_check_alignment_val else False,
        # Disabled criteria
        'style_bold': False, 'style_italic': False, 
        'check_word_count': False, 'word_count_min': 1, 'word_count_max': 999,
        'check_pattern': False, 'pattern_regex': None,
    }
    logger_app.debug(f"app.py: Chapter criteria: {ch_heading_criteria}")

    sch_heading_criteria = {}
    if st.session_state.sch_enable_all_val:
        sch_heading_criteria = {
            'check_font_props': True,
            'font_names': st.session_state.sch_font_names_sel,
            'min_font_size': st.session_state.sch_min_font_size_val,
            'check_case': st.session_state.sch_check_case_val,
            'case_upper': True if st.session_state.sch_check_case_val else False,
            'case_title': False,
            'check_alignment': st.session_state.sch_check_alignment_val,
            'alignment_centered': True if st.session_state.sch_check_alignment_val else False,
            'check_word_count': True, # Max words is still useful for sub-chapters
            'word_count_min': 1, 
            'word_count_max': st.session_state.sch_wc_max_val,
            # Disabled criteria
            'style_bold': False, 'style_italic': False,
            'check_pattern': False, 'pattern_regex': None,
        }
    logger_app.debug(f"app.py: Sub-chapter criteria (enabled: {st.session_state.sch_enable_all_val}): {sch_heading_criteria}")

    combined_heading_criteria = {"chapter": ch_heading_criteria, "sub_chapter": sch_heading_criteria}

    with st.spinner(f"Processing '{filename}'..."):
        try:
            structured_sentences = extract_sentences_with_structure(
                file_content=file_content, filename=filename, heading_criteria=combined_heading_criteria
            )
            logger_app.info(f"Extraction: {len(structured_sentences)} segments.")

            if not structured_sentences:
                st.warning("No text segments extracted.")
                chunks = []
            else:
                if st.session_state.chunk_mode_sel == "~200 Tokens":
                    chunks = chunk_structured_sentences(
                        structured_data=structured_sentences, tokenizer=tokenizer,
                        target_tokens=TARGET_TOKENS, overlap_sentences=OVERLAP_SENTENCES
                    )
                else:
                    chunks = chunk_by_chapter(structured_data=structured_sentences)
                logger_app.info(f"Chunking: {len(chunks)} chunks.")

            if chunks:
                df = pd.DataFrame(chunks, columns=['chunk_text', 'marker', 'title', 'sub_title'])
                df.fillna({'title': "Unknown Chapter", 'sub_title': ""}, inplace=True)
                df.rename(columns={'chunk_text': 'Text Chunk', 'marker': 'Source Marker',
                                   'title': 'Detected Chapter', 'sub_title': 'Detected Sub-Chapter'}, inplace=True)
            else:
                 df = pd.DataFrame(columns=['Text Chunk', 'Source Marker', 'Detected Chapter', 'Detected Sub-Chapter'])
                 st.warning("No chunks created." if structured_sentences else "No text segments extracted.")
            
            display_cols = ['Text Chunk', 'Detected Chapter', 'Detected Sub-Chapter']
            if st.session_state.include_marker_val and 'Source Marker' in df.columns:
                display_cols.insert(1, 'Source Marker')
            final_df = df[[col for col in display_cols if col in df.columns]]

            st.session_state.processed_data = final_df
            st.session_state.processed_filename = filename.split('.')[0]
            st.success(f"✅ Processing complete for '{filename}'!")

        except Exception as e:
            logger_app.error(f"Processing error for {filename}: {e}", exc_info=True)
            st.error(f"An error during processing: {e}")
            st.session_state.processed_data = None

if st.session_state.processed_data is not None:
    st.header("📊 Processed Chunks")
    st.dataframe(st.session_state.processed_data, use_container_width=True)
    if not st.session_state.processed_data.empty:
        st.info(f"Total Chunks: {len(st.session_state.processed_data)}")
        try:
            csv_data = st.session_state.processed_data.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download CSV", csv_data, f"{st.session_state.processed_filename}_chunks.csv", 'text/csv')
        except Exception as e:
            logger_app.error(f"Download prep error: {e}", exc_info=True)
            st.error(f"Failed to prepare download: {e}")
    else: st.info("0 chunks produced.")
elif st.session_state.uploaded_file_info is None:
     st.markdown("---")
     st.markdown("Upload a DOCX file and configure options in the sidebar.")
