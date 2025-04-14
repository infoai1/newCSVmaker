import streamlit as st
import pandas as pd
import io
import re
import logging

# Import custom modules
from utils import ensure_nltk_punkt, load_tokenizer
from file_processor import extract_sentences_with_structure
from chunker import chunk_structured_sentences, chunk_by_chapter

# --- Page Config ---
st.set_page_config(page_title="Book Processor", layout="wide")
st.title("📖 Book Text Processor for AI Tasks")
st.markdown("Upload a PDF or DOCX book file (e.g., by Maulana Wahiduddin Khan) to extract, structure, and chunk its content.")

# --- Initialize Session State ---
if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None
if 'processed_filename' not in st.session_state:
    st.session_state.processed_filename = None

# --- Setup Logging and Helpers ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
try:
    ensure_nltk_punkt()
    tokenizer = load_tokenizer()
except Exception as e:
    st.error(f"Initialization failed: {e}")
    st.stop()

# --- Sidebar for Upload and Options ---
with st.sidebar:
    st.header("⚙️ Processing Options")

    uploaded_file = st.file_uploader("1. Upload Book File", type=['pdf', 'docx'], accept_multiple_files=False)

    if uploaded_file:
        st.success(f"Uploaded: {uploaded_file.name} ({uploaded_file.size / 1024:.1f} KB)")

        # --- PDF Specific Options ---
        st.subheader("PDF Specific Options", help="These settings only apply when processing PDF files.")
        pdf_skip_start = st.number_input("Pages to Skip at START", min_value=0, value=0, step=1)
        pdf_skip_end = st.number_input("Pages to Skip at END", min_value=0, value=0, step=1)
        pdf_first_page_offset = st.number_input("Actual Page # of FIRST Processed Page", min_value=1, value=1, step=1, help="Set this to the real page number shown on the first page you want to process (e.g., if skipping front matter).")

        # --- Heading Style Definition ---
        st.subheader("Define Chapter Heading Style", help="Configure how chapter titles are identified.")
        with st.expander("Heading Style Criteria", expanded=False):
            # Master Toggles
            col1, col2 = st.columns(2)
            with col1:
                check_style = st.checkbox("Enable Font Style Checks?", value=False)
                check_case = st.checkbox("Enable Text Case Checks?", value=True) # Often useful
                check_layout = st.checkbox("Enable Layout Checks?", value=False) # Layout can be unreliable
            with col2:
                check_word_count = st.checkbox("Enable Word Count Checks?", value=True) # Often useful
                check_pattern = st.checkbox("Enable Keyword/Pattern Check?", value=True) # Often useful

            # --- Specific Criteria (disabled based on master toggle) ---
            st.markdown("---")
            if check_style:
                st.markdown("**Font Style Requirements**")
                style_bold = st.checkbox("Must be Bold?", value=True, disabled=not check_style)
                style_italic = st.checkbox("Must be Italic?", value=False, disabled=not check_style)
                # Add Font Name/Size later if needed - requires more complex PDF parsing
            else:
                style_bold = False
                style_italic = False

            st.markdown("---")
            if check_case:
                st.markdown("**Text Case Requirements**")
                case_title = st.checkbox("Must be Title Case?", value=False, disabled=not check_case)
                case_upper = st.checkbox("Must be ALL CAPS?", value=True, disabled=not check_case)
            else:
                case_title = False
                case_upper = False

            st.markdown("---")
            if check_layout:
                 st.markdown("**Layout Requirements**")
                 layout_centered = st.checkbox("Must be Centered (Approx)?", value=True, disabled=not check_layout)
                 layout_alone = st.checkbox("Must be Alone in Block (PDF)?", value=True, disabled=not check_layout)
                 # 'Alone' is harder for DOCX, may need refinement
            else:
                 layout_centered = False
                 layout_alone = False


            st.markdown("---")
            if check_word_count:
                st.markdown("**Word Count Requirements**")
                word_count_min = st.number_input("Min Words", min_value=1, value=1, step=1, disabled=not check_word_count)
                word_count_max = st.number_input("Max Words", min_value=1, value=10, step=1, disabled=not check_word_count) # Low default, adjust as needed
            else:
                word_count_min = 1
                word_count_max = 999 # Effectively infinity if check disabled

            st.markdown("---")
            if check_pattern:
                st.markdown("**Keyword/Pattern Requirement**")
                # Default regex for CHAPTER/SECTION/PART followed by Roman or Arabic numerals
                default_regex = r"^(CHAPTER|SECTION|PART)\s+[IVXLCDM\d]+"
                pattern_regex_str = st.text_input("Regex Pattern (Case Insensitive)", value=default_regex, disabled=not check_pattern, help="Python regex pattern to match the start of the heading text.")
                # Validate Regex on input change? Or just before processing.
                pattern_regex = None
                if check_pattern and pattern_regex_str:
                    try:
                        # Compile with IgnoreCase flag
                        pattern_regex = re.compile(pattern_regex_str, re.IGNORECASE)
                        st.success("Regex pattern is valid.")
                    except re.error as e:
                        st.error(f"Invalid Regex: {e}")
                        pattern_regex = None # Ensure it's None if invalid
            else:
                pattern_regex_str = ""
                pattern_regex = None

        # --- Chunking Method ---
        st.subheader("Chunking Strategy")
        TARGET_TOKENS = 200 # Default target size
        OVERLAP_SENTENCES = 2 # Default overlap
        chunk_mode = st.radio(
            "Choose how to chunk the text:",
            (f"Chunk by ~{TARGET_TOKENS} Tokens (with {OVERLAP_SENTENCES} sentence overlap)", "Chunk by Detected Chapter Title"),
            index=0, # Default to token-based chunking
            key="chunk_mode"
        )

        # --- Output Options ---
        st.subheader("Output Options")
        include_marker = st.checkbox("Include Page/Para Marker in Output?", value=True)

        # --- Process Button ---
        st.markdown("---")
        process_button = st.button("🚀 Process File", type="primary")

    else:
        st.info("Please upload a PDF or DOCX file to begin.")
        process_button = False # Disable processing if no file


# --- Main Area for Processing and Results ---
if process_button and uploaded_file:
    # 1. Read Input File
    filename = uploaded_file.name
    file_content = uploaded_file.getvalue()
    file_type = filename.split('.')[-1].lower()

    # 2. Compile Heading Criteria Dictionary
    heading_criteria = {
        'check_style': check_style,
        'style_bold': style_bold,
        'style_italic': style_italic,
        'check_case': check_case,
        'case_title': case_title,
        'case_upper': case_upper,
        'check_layout': check_layout,
        'layout_centered': layout_centered,
        'layout_alone': layout_alone, # Note limitations for DOCX
        'check_word_count': check_word_count,
        'word_count_min': word_count_min,
        'word_count_max': word_count_max,
        'check_pattern': check_pattern,
        'pattern_regex': pattern_regex # Pass the compiled regex object
    }
    # Add a check for invalid regex before proceeding
    if check_pattern and not pattern_regex and pattern_regex_str:
         st.error("Processing stopped: Heading pattern check is enabled but the Regex pattern is invalid.")
         st.stop()


    with st.spinner(f"Processing '{filename}'... This may take a moment."):
        try:
            # 3. Call Extraction Function
            logging.info("Starting text extraction...")
            structured_sentences = extract_sentences_with_structure(
                file_content=file_content,
                filename=filename,
                pdf_skip_start=pdf_skip_start if file_type == 'pdf' else 0,
                pdf_skip_end=pdf_skip_end if file_type == 'pdf' else 0,
                pdf_first_page_offset=pdf_first_page_offset if file_type == 'pdf' else 1,
                heading_criteria=heading_criteria
            )
            logging.info(f"Extraction complete. Found {len(structured_sentences)} sentence segments.")

            if not structured_sentences:
                st.warning("No text segments were extracted. Check PDF skip settings or file content.")
                st.stop()

            # 4. Call Chunking Function
            logging.info(f"Starting chunking using mode: {chunk_mode}...")
            if chunk_mode.startswith("Chunk by ~"):
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

            if not chunks:
                 st.warning("Chunking resulted in zero chunks. Check extraction results.")
                 st.stop()


            # 5. Format Output
            df = pd.DataFrame(chunks, columns=['chunk_text', 'marker', 'title'])

            # Clean up titles (fill NaN/None with a default, e.g., 'Introduction' or previous valid title propagation done in chunker)
            df['title'] = df['title'].fillna("Unknown Title") # Or use the default from chunker


            # Rename columns for clarity
            final_columns = {'chunk_text': 'Text Chunk', 'marker': 'Source Marker', 'title': 'Detected Title'}
            df.rename(columns=final_columns, inplace=True)

            # Select final columns based on user choice
            display_columns = ['Text Chunk', 'Detected Title']
            if include_marker:
                display_columns.insert(1, 'Source Marker') # Insert marker between chunk and title

            final_df = df[display_columns]

            # Store results in session state
            st.session_state.processed_data = final_df
            st.session_state.processed_filename = filename.split('.')[0] # Base name for download
            st.success(f"✅ Successfully processed '{filename}'!")

        except (ValueError, RuntimeError, FileNotFoundError, Exception) as e:
            logging.error(f"Processing failed for {filename}: {e}", exc_info=True)
            st.error(f"An error occurred during processing: {e}")
            st.session_state.processed_data = None # Clear previous results on error

# --- Display Results ---
if st.session_state.processed_data is not None:
    st.header("📊 Processed Chunks")
    st.dataframe(st.session_state.processed_data, use_container_width=True)

    st.info(f"Total Chunks Created: {len(st.session_state.processed_data)}")

    # --- Download Button ---
    csv_data = st.session_state.processed_data.to_csv(index=False).encode('utf-8')
    download_filename = f"{st.session_state.processed_filename}_chunks.csv"

    st.download_button(
        label="📥 Download Chunks as CSV",
        data=csv_data,
        file_name=download_filename,
        mime='text/csv',
    )

elif not uploaded_file:
     st.markdown("---")
     st.markdown("Upload a file and configure options in the sidebar to start processing.")
