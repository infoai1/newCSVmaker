import streamlit as st
import pandas as pd
import io
import logging # re is no longer strictly needed here if not used elsewhere

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
    fp_logger.setLevel(logging.DEBUG) 
    logger_app.debug(f"app.py: Logger '{fp_logger.name}' forced to DEBUG. Effective level: {logging.getLevelName(fp_logger.getEffectiveLevel())}")

except ImportError as ie:
    logger_app.error(f"app.py: Failed to import necessary modules. Error: {ie}", exc_info=True)
    st.error(f"Failed to import necessary modules. Check file structure and names. Error: {ie}")
    st.stop()

# --- Page Config ---
try:
    st.set_page_config(page_title="DOCX Processor", layout="wide")
    st.title("📖 DOCX Text Processor (Font Name & Size)")
    st.markdown("Upload a DOCX file to extract, structure, and chunk its content based on Font Name and Size.")
except Exception as page_setup_err:
     logger_app.error(f"app.py: Streamlit page setup failed: {page_setup_err}", exc_info=True)
     st.error(f"Error initializing Streamlit page: {page_setup_err}")
     st.stop()

# --- Initialize Session State ---
if 'processed_data' not in st.session_state: st.session_state.processed_data = None
if 'processed_filename' not in st.session_state: st.session_state.processed_filename = None
if 'uploaded_file_info' not in st.session_state: st.session_state.uploaded_file_info = None
if 'custom_fonts' not in st.session_state: st.session_state.custom_fonts = []


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
COMMON_FONTS = sorted(["Arial", "Calibri", "Times New Roman", "Courier New", "Verdana", "Georgia", "Helvetica", "Tahoma", "Garamond", "Bookman", "Perpetua", "Cambria", "Century", "Franklin Gothic Book"])

# --- Sidebar Definition ---
with st.sidebar:
    st.header("⚙️ Processing Options")

    st.subheader("Custom Fonts")
    custom_font_input = st.text_input("Add custom font name (then press Enter)", key="custom_font_text_input")
    if st.button("Add Font", key="add_custom_font_button"):
        if custom_font_input and custom_font_input not in st.session_state.custom_fonts and custom_font_input not in COMMON_FONTS:
            st.session_state.custom_fonts.append(custom_font_input)
            st.rerun() 
        elif not custom_font_input: st.caption("Please enter a font name.")
        else: st.caption(f"'{custom_font_input}' is already in a list.")
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
             st.session_state.processed_data = None; st.session_state.processed_filename = None
             st.success(f"File selected: {st.session_state.uploaded_file_info['name']} ({st.session_state.uploaded_file_info['size'] / 1024:.1f} KB)")

    if st.session_state.uploaded_file_info:
        st.info(f"Processing target: {st.session_state.uploaded_file_info['name']}")

        st.subheader("Define Chapter Heading Style")
        with st.expander("Chapter Criteria (Font Name & Size)", expanded=True):
            ch_font_names = st.multiselect("Font Names (Chapter)", options=all_available_fonts, default=["Perpetua"], key="ch_font_names_sel")
            ch_min_font_size = st.number_input("Min Font Size (Chapter, pts)", min_value=6.0, value=16.0, step=0.5, key="ch_min_font_size_val")
            # Optional: Centered and ALL CAPS can be added back as secondary discriminators if needed by un-commenting
            # ch_also_centered = st.checkbox("Also Must Be Centered (Chapter)?", value=False, key="ch_also_centered_val")
            # ch_also_all_caps = st.checkbox("Also Must Be ALL CAPS (Chapter)?", value=False, key="ch_also_all_caps_val")


        st.subheader("Define Sub-Chapter Heading Style")
        sch_enable_detection = st.checkbox("Enable Sub-Chapter Detection?", value=True, key="sch_enable_detection_val")
        
        with st.expander("Sub-Chapter Criteria (Font Name & Size)", expanded=False):
            sch_font_names = st.multiselect("Font Names (Sub-Chapter)", options=all_available_fonts, default=["Perpetua"], key="sch_font_names_sel", disabled=not sch_enable_detection)
            sch_min_font_size = st.number_input("Min Font Size (Sub, pts)", min_value=6.0, value=12.0, step=0.5, key="sch_min_font_size_val", disabled=not sch_enable_detection)
            # Optional: Centered and ALL CAPS can be added back as secondary discriminators if needed by un-commenting
            # sch_also_centered = st.checkbox("Also Must Be Centered (Sub-Chapter)?", value=False, key="sch_also_centered_val", disabled=not sch_enable_detection)
            # sch_also_all_caps = st.checkbox("Also Must Be ALL CAPS (Sub-Chapter)?", value=False, key="sch_also_all_caps_val", disabled=not sch_enable_detection)


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
    if not file_info: st.error("Error: No file information found."); st.stop()
    filename, file_content = file_info['name'], file_info['getvalue']

    ch_heading_criteria = {
        'font_names': st.session_state.ch_font_names_sel,
        'min_font_size': st.session_state.ch_min_font_size_val,
        # 'check_alignment': st.session_state.get('ch_also_centered_val', False), # get with default if checkbox doesn't exist
        # 'alignment_centered': st.session_state.get('ch_also_centered_val', False),
        # 'check_case': st.session_state.get('ch_also_all_caps_val', False),
        # 'case_upper': st.session_state.get('ch_also_all_caps_val', False),
        # All other criteria are implicitly False or not checked
    }
    logger_app.debug(f"app.py: Chapter criteria: {ch_heading_criteria}")

    sch_heading_criteria = {}
    if st.session_state.sch_enable_detection_val:
        sch_heading_criteria = {
            'font_names': st.session_state.sch_font_names_sel,
            'min_font_size': st.session_state.sch_min_font_size_val,
            # 'check_alignment': st.session_state.get('sch_also_centered_val', False),
            # 'alignment_centered': st.session_state.get('sch_also_centered_val', False),
            # 'check_case': st.session_state.get('sch_also_all_caps_val', False),
            # 'case_upper': st.session_state.get('sch_also_all_caps_val', False),
        }
    logger_app.debug(f"app.py: Sub-chapter criteria (enabled: {st.session_state.sch_enable_detection_val}): {sch_heading_criteria}")

    combined_heading_criteria = {"chapter": ch_heading_criteria, "sub_chapter": sch_heading_criteria}

    with st.spinner(f"Processing '{filename}'..."):
        try:
            structured_sentences = extract_sentences_with_structure(
                file_content=file_content, filename=filename, heading_criteria=combined_heading_criteria
            )
            logger_app.info(f"Extraction: {len(structured_sentences)} segments.")
            chunks = [] # Initialize chunks
            if not structured_sentences:
                st.warning("No text segments extracted.")
            else:
                if st.session_state.chunk_mode_sel == "~200 Tokens":
                    chunks = chunk_structured_sentences(
                        structured_data=structured_sentences, tokenizer=tokenizer,
                        target_tokens=TARGET_TOKENS, overlap_sentences=OVERLAP_SENTENCES
                    )
                else: # Chunk by Chapter Title
                    chunks = chunk_by_chapter(structured_data=structured_sentences)
                logger_app.info(f"Chunking: {len(chunks)} chunks.")

            df_columns = ['Text Chunk', 'Source Marker', 'Detected Chapter', 'Detected Sub-Chapter']
            if chunks:
                df = pd.DataFrame(chunks, columns=['chunk_text', 'marker', 'title', 'sub_title'])
                df.fillna({'title': "Unknown Chapter", 'sub_title': ""}, inplace=True)
                df.rename(columns={'chunk_text': 'Text Chunk', 'marker': 'Source Marker',
                                   'title': 'Detected Chapter', 'sub_title': 'Detected Sub-Chapter'}, inplace=True)
            else:
                 df = pd.DataFrame(columns=df_columns) # Use predefined columns for empty df
                 st.warning("No chunks created." if structured_sentences else "No text segments extracted.")
            
            display_cols = ['Text Chunk', 'Detected Chapter', 'Detected Sub-Chapter']
            if st.session_state.include_marker_val and 'Source Marker' in df.columns:
                display_cols.insert(1, 'Source Marker')
            
            # Ensure final_df has all display_cols, even if some are empty
            final_df = pd.DataFrame(columns=display_cols) 
            for col in display_cols:
                if col in df.columns:
                    final_df[col] = df[col]
                # else: # Column not in df, will remain as empty series in final_df from initialization
                #    final_df[col] = pd.Series(dtype='object') # Ensure column exists with object dtype

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
