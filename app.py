import streamlit as st
import pandas as pd
import io
import re
import logging

# Import custom modules - Ensure these files exist and are importable
try:
    from utils import ensure_nltk_punkt, load_tokenizer
    from file_processor import extract_sentences_with_structure
    from chunker import chunk_structured_sentences, chunk_by_chapter
except ImportError as ie:
    st.error(f"Failed to import necessary modules. Check file structure and names. Error: {ie}")
    st.stop()


# --- Page Config ---
try:
    st.set_page_config(page_title="Book Processor", layout="wide")
    st.title("📖 Book Text Processor for AI Tasks")
    st.markdown("Upload a PDF or DOCX book file (e.g., by Maulana Wahiduddin Khan) to extract, structure, and chunk its content.")
except Exception as page_setup_err:
     # Less likely, but catch errors during initial page setup
     logging.error(f"Streamlit page setup failed: {page_setup_err}", exc_info=True)
     st.error(f"Error initializing Streamlit page: {page_setup_err}")
     st.stop()


# --- Initialize Session State ---
# Best practice: initialize all expected keys at the start
if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None
if 'processed_filename' not in st.session_state:
    st.session_state.processed_filename = None
if 'uploaded_file_info' not in st.session_state: # Store file info slightly differently
    st.session_state.uploaded_file_info = None

# --- Setup Logging and Helpers ---
# Configure logging (moved here, ensure it runs only once)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Run initializers
try:
    ensure_nltk_punkt()
    tokenizer = load_tokenizer() # Load tokenizer globally for reuse
except Exception as e:
    st.error(f"Initialization failed (NLTK/Tokenizer): {e}")
    logging.error(f"Initialization failed: {e}", exc_info=True)
    st.stop()

# --- Constants ---
TARGET_TOKENS = 200 # Default target size
OVERLAP_SENTENCES = 2 # Default overlap
DEFAULT_REGEX = r"^(CHAPTER|SECTION|PART)\s+[IVXLCDM\d]+"

# --- Sidebar Definition ---
with st.sidebar:
    st.header("⚙️ Processing Options")

    # Use a variable to hold the uploaded file object from the widget
    # This widget reruns every time, so we need to check session state too
    uploaded_file_widget = st.file_uploader(
        "1. Upload Book File",
        type=['pdf', 'docx'],
        accept_multiple_files=False,
        key="file_uploader_widget" # Assign a key
    )

    # Store file info in session state IF a new file is uploaded
    if uploaded_file_widget is not None:
        # Check if it's different from the one potentially already processed
        if st.session_state.uploaded_file_info is None or \
           st.session_state.uploaded_file_info['name'] != uploaded_file_widget.name or \
           st.session_state.uploaded_file_info['size'] != uploaded_file_widget.size:
             st.session_state.uploaded_file_info = {
                 "name": uploaded_file_widget.name,
                 "size": uploaded_file_widget.size,
                 "type": uploaded_file_widget.type,
                 "getvalue": uploaded_file_widget.getvalue() # Read bytes here once
             }
             # Clear previous results when a new file is uploaded
             st.session_state.processed_data = None
             st.session_state.processed_filename = None
             st.success(f"File selected: {st.session_state.uploaded_file_info['name']} ({st.session_state.uploaded_file_info['size'] / 1024:.1f} KB)")


    # --- Display options only if a file has been selected (check session state) ---
    if st.session_state.uploaded_file_info:
        # Display file name from session state
        st.info(f"Processing target: {st.session_state.uploaded_file_info['name']}")

        # --- PDF Specific Options ---
        st.subheader("PDF Specific Options", help="These settings only apply when processing PDF files.")
        pdf_skip_start = st.number_input("Pages to Skip at START", min_value=0, value=0, step=1, key="pdf_skip_start")
        pdf_skip_end = st.number_input("Pages to Skip at END", min_value=0, value=0, step=1, key="pdf_skip_end")
        pdf_first_page_offset = st.number_input("Actual Page # of FIRST Processed Page", min_value=1, value=1, step=1, help="Set this to the real page number shown on the first page you want to process (e.g., if skipping front matter).", key="pdf_first_page")

        # --- Heading Style Definition ---
        st.subheader("Define Chapter Heading Style", help="Configure how chapter titles are identified.")
        with st.expander("Heading Style Criteria", expanded=False):
            # Master Toggles
            col1, col2 = st.columns(2)
            with col1:
                check_style = st.checkbox("Enable Font Style Checks?", value=False, key="check_style")
                check_case = st.checkbox("Enable Text Case Checks?", value=True, key="check_case") # Often useful
                check_layout = st.checkbox("Enable Layout Checks?", value=False, key="check_layout") # Layout can be unreliable
            with col2:
                check_word_count = st.checkbox("Enable Word Count Checks?", value=True, key="check_word_count") # Often useful
                check_pattern = st.checkbox("Enable Keyword/Pattern Check?", value=True, key="check_pattern") # Often useful

            # --- Specific Criteria (disabled based on master toggle) ---
            st.markdown("---")
            # Use columns for better layout if needed, or just stack them
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Font Style**")
                style_bold = st.checkbox("Must be Bold?", value=True, disabled=not check_style, key="style_bold")
                style_italic = st.checkbox("Must be Italic?", value=False, disabled=not check_style, key="style_italic")
            with c2:
                 st.markdown("**Layout**")
                 layout_centered = st.checkbox("Centered (Approx)?", value=True, disabled=not check_layout, key="layout_centered")
                 layout_alone = st.checkbox("Alone in Block (PDF)?", value=True, disabled=not check_layout, key="layout_alone")

            st.markdown("---")
            c3, c4 = st.columns(2)
            with c3:
                st.markdown("**Text Case**")
                case_title = st.checkbox("Title Case?", value=False, disabled=not check_case, key="case_title")
                case_upper = st.checkbox("ALL CAPS?", value=True, disabled=not check_case, key="case_upper")
            with c4:
                st.markdown("**Word Count**")
                word_count_min = st.number_input("Min Words", min_value=1, value=1, step=1, disabled=not check_word_count, key="wc_min")
                word_count_max = st.number_input("Max Words", min_value=1, value=10, step=1, disabled=not check_word_count, key="wc_max") # Low default, adjust as needed

            st.markdown("---")
            st.markdown("**Keyword/Pattern**")
            pattern_regex_str = st.text_input("Regex Pattern (Case Insensitive)", value=DEFAULT_REGEX, disabled=not check_pattern, help="Python regex pattern to match the start of the heading text.", key="pattern_str")
            # Validate Regex immediately for feedback
            pattern_regex = None
            is_regex_valid = False
            if check_pattern and pattern_regex_str:
                try:
                    pattern_regex = re.compile(pattern_regex_str, re.IGNORECASE)
                    st.caption("✅ Regex pattern is valid.")
                    is_regex_valid = True
                except re.error as e:
                    st.caption(f"⚠️ Invalid Regex: {e}")
                    is_regex_valid = False
            elif check_pattern and not pattern_regex_str:
                 st.caption("⚠️ Pattern check enabled, but pattern is empty.")
                 is_regex_valid = False # Treat empty pattern as invalid if check is enabled
            else:
                 is_regex_valid = True # Valid if check is disabled


        # --- Chunking Method ---
        st.subheader("Chunking Strategy")
        chunk_mode = st.radio(
            "Choose how to chunk the text:",
            (f"Chunk by ~{TARGET_TOKENS} Tokens (with {OVERLAP_SENTENCES} sentence overlap)", "Chunk by Detected Chapter Title"),
            index=0, # Default to token-based chunking
            key="chunk_mode"
        )

        # --- Output Options ---
        st.subheader("Output Options")
        include_marker = st.checkbox("Include Page/Para Marker in Output?", value=True, key="include_marker")

        # --- Process Button ---
        st.markdown("---")
        # Disable button if regex is required but invalid
        process_button_disabled = (check_pattern and not is_regex_valid)
        if process_button_disabled:
             st.warning("Cannot process: Fix the invalid or empty Regex pattern first.")

        process_button = st.button(
            "🚀 Process File",
            type="primary",
            disabled=process_button_disabled,
            key="process_button"
            )

    else: # No file selected in session state
        st.info("Please upload a PDF or DOCX file to begin.")
        process_button = False # Ensure button state is false


# --- Main Area Logic ---

# This block executes *only* when the process button is clicked AND it was not disabled
if process_button:
    # Get file info from session state
    file_info = st.session_state.uploaded_file_info
    if not file_info:
        st.error("Error: No file information found in session state. Please re-upload.")
        st.stop()

    filename = file_info['name']
    file_content = file_info['getvalue'] # Get bytes stored earlier
    file_type = filename.split('.')[-1].lower() # Recalculate or store in session state

    # Get options from sidebar widgets (using their keys)
    # We need to re-read widget values here as they might have changed
    # PDF Options
    current_pdf_skip_start = st.session_state.pdf_skip_start
    current_pdf_skip_end = st.session_state.pdf_skip_end
    current_pdf_first_page = st.session_state.pdf_first_page
    # Heading Criteria
    current_check_style = st.session_state.check_style
    current_style_bold = st.session_state.style_bold
    current_style_italic = st.session_state.style_italic
    current_check_case = st.session_state.check_case
    current_case_title = st.session_state.case_title
    current_case_upper = st.session_state.case_upper
    current_check_layout = st.session_state.check_layout
    current_layout_centered = st.session_state.layout_centered
    current_layout_alone = st.session_state.layout_alone
    current_check_word_count = st.session_state.check_word_count
    current_wc_min = st.session_state.wc_min
    current_wc_max = st.session_state.wc_max
    current_check_pattern = st.session_state.check_pattern
    current_pattern_str = st.session_state.pattern_str
    # Re-compile regex based on current string value if needed
    current_pattern_regex = None
    if current_check_pattern and current_pattern_str:
         try:
              current_pattern_regex = re.compile(current_pattern_str, re.IGNORECASE)
         except re.error:
              # This check should have disabled the button, but double-check
              st.error("Processing stopped due to invalid regex pattern.")
              st.stop()

    # Chunking and Output Options
    current_chunk_mode = st.session_state.chunk_mode
    current_include_marker = st.session_state.include_marker


    # 2. Compile Heading Criteria Dictionary for processing
    heading_criteria = {
        'check_style': current_check_style,
        'style_bold': current_style_bold,
        'style_italic': current_style_italic,
        'check_case': current_check_case,
        'case_title': current_case_title,
        'case_upper': current_case_upper,
        'check_layout': current_check_layout,
        'layout_centered': current_layout_centered,
        'layout_alone': current_layout_alone,
        'check_word_count': current_check_word_count,
        'word_count_min': current_wc_min if current_check_word_count else 1, # Use defaults if unchecked
        'word_count_max': current_wc_max if current_check_word_count else 999,
        'check_pattern': current_check_pattern,
        'pattern_regex': current_pattern_regex # Pass the compiled regex object
    }


    with st.spinner(f"Processing '{filename}'... This may take a moment."):
        try:
            # 3. Call Extraction Function
            logging.info("Starting text extraction...")
            structured_sentences = extract_sentences_with_structure(
                file_content=file_content,
                filename=filename,
                pdf_skip_start=current_pdf_skip_start if file_type == 'pdf' else 0,
                pdf_skip_end=current_pdf_skip_end if file_type == 'pdf' else 0,
                pdf_first_page_offset=current_pdf_first_page if file_type == 'pdf' else 1,
                heading_criteria=heading_criteria
            )
            logging.info(f"Extraction complete. Found {len(structured_sentences)} sentence segments.")

            if not structured_sentences:
                st.warning("No text segments were extracted. Check file content or PDF skip/heading settings.")
                # Don't stop, allow showing zero results
                chunks = [] # Ensure chunks is an empty list
            else:
                 # 4. Call Chunking Function
                logging.info(f"Starting chunking using mode: {current_chunk_mode}...")
                if current_chunk_mode.startswith("Chunk by ~"):
                    chunks = chunk_structured_sentences(
                        structured_data=structured_sentences,
                        tokenizer=tokenizer, # Use the globally loaded tokenizer
                        target_tokens=TARGET_TOKENS,
                        overlap_sentences=OVERLAP_SENTENCES
                    )
                else: # Chunk by Chapter Title
                    chunks = chunk_by_chapter(
                        structured_data=structured_sentences
                    )
                logging.info(f"Chunking complete. Created {len(chunks)} chunks.")


            # 5. Format Output (even if chunks list is empty)
            if chunks:
                df = pd.DataFrame(chunks, columns=['chunk_text', 'marker', 'title'])
                # Clean up titles
                df['title'] = df['title'].fillna("Unknown Title")
                # Rename columns for clarity
                final_columns = {'chunk_text': 'Text Chunk', 'marker': 'Source Marker', 'title': 'Detected Title'}
                df.rename(columns=final_columns, inplace=True)
            else:
                 # Create empty DataFrame with expected columns if no chunks
                 df = pd.DataFrame(columns=['Text Chunk', 'Source Marker', 'Detected Title'])
                 if not structured_sentences:
                      st.warning("No text segments extracted.")
                 else:
                      st.warning("Text extracted but chunking resulted in zero chunks.")


            # Select final columns based on user choice
            display_columns = ['Text Chunk', 'Detected Title']
            if current_include_marker:
                # Ensure 'Source Marker' column exists before inserting
                if 'Source Marker' in df.columns:
                     display_columns.insert(1, 'Source Marker')

            # Ensure all selected columns exist in the DataFrame
            final_df = df[[col for col in display_columns if col in df.columns]]


            # Store results in session state
            st.session_state.processed_data = final_df
            st.session_state.processed_filename = filename.split('.')[0] # Base name for download
            st.success(f"✅ Processing complete for '{filename}'!")

        except (ValueError, RuntimeError, FileNotFoundError, Exception) as e:
            logging.error(f"Processing failed for {filename}: {e}", exc_info=True)
            st.error(f"An error occurred during processing: {e}")
            # Clear results on error
            st.session_state.processed_data = None
            st.session_state.processed_filename = None


# --- Display Results Area ---
# This part runs on every interaction if processed_data exists

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
        st.info("Processing resulted in 0 chunks.") # Display message if dataframe is empty

elif st.session_state.uploaded_file_info is None: # Only show if no file ever uploaded
     st.markdown("---")
     st.markdown("Upload a file and configure options in the sidebar to start processing.")
