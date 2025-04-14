import fitz  # PyMuPDF
import docx
import re
import nltk
import io
import logging
from typing import List, Tuple, Dict, Any, Optional

# Configure logging (use the same configuration as utils or configure separately)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Cleaning Rules ---
def is_likely_metadata_or_footer(text: str, block_bbox: Optional[Tuple[float, float, float, float]] = None, page_height: Optional[float] = None) -> bool:
    """
    Identifies text likely to be headers, footers, or page numbers.
    Simple rules for now, can be expanded.
    """
    text = text.strip()
    if not text:
        return True

    # Check for common page number patterns
    if re.fullmatch(r"-?\s*\d+\s*-?", text):
        if block_bbox and page_height and block_bbox[3] > page_height * 0.90:
             return True
        # If position unavailable, still consider it potential metadata if just numbers
        elif not block_bbox:
             return True

    # Check for very short lines potentially at top/bottom
    if len(text.split()) < 5:
        if block_bbox and page_height:
            if block_bbox[1] < page_height * 0.10 or block_bbox[3] > page_height * 0.90:
                return True

    # Check for common footers
    if "www.cpsglobal.org" in text or "www.goodwordbooks.com" in text:
        return True
    if "Maulana Wahiduddin Khan" in text and block_bbox and page_height and block_bbox[3] > page_height * 0.90:
        return True # Name often appears in footer area

    return False

# --- Heading Detection ---
def check_heading_user_defined(
    text: str,
    style_info: Dict[str, Any], # e.g., {'bold': True, 'italic': False, 'size': 14.0, 'font': 'Times'}
    layout_info: Dict[str, Any], # e.g., {'centered': True, 'alone': True}
    criteria: Dict[str, Any]
) -> bool:
    """
    Checks if a text segment matches user-defined heading criteria.
    """
    text = text.strip()
    if not text:
        return False

    # --- Font Style Checks ---
    if criteria.get('check_style'):
        if criteria.get('style_bold') and not style_info.get('bold', False): return False
        if criteria.get('style_italic') and not style_info.get('italic', False): return False

    # --- Text Case Checks ---
    if criteria.get('check_case'):
        if criteria.get('case_title') and not text.istitle(): return False
        is_all_caps = all(c.isupper() or not c.isalpha() for c in text if c.isprintable() and not c.isspace())
        if criteria.get('case_upper') and not (is_all_caps and any(c.isalpha() for c in text)): return False

    # --- Layout Checks ---
    if criteria.get('check_layout'):
        if criteria.get('layout_centered') and not layout_info.get('centered', False): return False
        if criteria.get('layout_alone') and not layout_info.get('alone', False): return False

    # --- Word Count Checks ---
    if criteria.get('check_word_count'):
        word_count = len(text.split())
        if word_count < criteria.get('word_count_min', 0): return False
        if word_count > criteria.get('word_count_max', float('inf')): return False

    # --- Keywords/Pattern Check ---
    if criteria.get('check_pattern') and criteria.get('pattern_regex'):
        try:
            # Using search for flexibility unless user adds ^ start anchor
            if not criteria['pattern_regex'].search(text):
                return False
        except re.error as e:
            logging.warning(f"Regex error in heading check: {e}. Pattern: '{criteria.get('pattern_regex')}'")
            # Treat regex error as non-match
            return False

    # If all enabled checks passed
    return True


# --- PDF Processing ---
def _process_pdf(
    file_bytes: io.BytesIO,
    skip_start: int,
    skip_end: int,
    first_page_offset: int,
    heading_criteria: Dict[str, Any]
) -> List[Tuple[str, str, Optional[str]]]:
    """Extracts structured sentences from a PDF file."""
    extracted_data = []
    current_chapter_title = None
    doc = None # Initialize doc to None for finally block

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        num_pages = len(doc)
        start_page_idx = skip_start
        end_page_idx = num_pages - skip_end

        if start_page_idx >= end_page_idx:
            logging.warning("PDF processing skipped: Invalid page range after skipping.")
            return []

        for page_num_idx in range(start_page_idx, end_page_idx):
            page = doc.load_page(page_num_idx)
            page_height = page.rect.height
            page_width = page.rect.width
            actual_page_num = page_num_idx + first_page_offset
            page_marker = f"Page {actual_page_num}"

            page_dict = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)
            potential_headings = []
            non_heading_blocks = []

            for block in page_dict.get("blocks", []):
                if block.get("type") == 0: # Text block
                    block_text = ""
                    span_details = []
                    block_bbox = block.get("bbox")
                    for line in block.get("lines", []):
                        line_text_parts = []
                        for span in line.get("spans", []):
                            line_text_parts.append(span.get("text", ""))
                            if not span_details: # Store first span's details
                                span_details.append({
                                    'size': span.get('size'), 'font': span.get('font'),
                                    'flags': span.get('flags'),
                                    'bold': bool(span.get('flags', 0) & (1<<4)), # Bold flag often 16
                                    'italic': bool(span.get('flags', 0) & (1<<1)), # Italic flag often 2
                                })
                        if block_text and line_text_parts: block_text += "\n"
                        block_text += "".join(line_text_parts)

                    block_text = block_text.strip()
                    if not block_text or is_likely_metadata_or_footer(block_text, block_bbox, page_height):
                        continue

                    style_info = span_details[0] if span_details else {}
                    is_alone = len(block.get("lines", [])) == 1
                    is_centered = False
                    if block_bbox:
                        block_center_x = (block_bbox[0] + block_bbox[2]) / 2
                        page_center_x = page_width / 2
                        tolerance = page_width * 0.15
                        is_centered = abs(block_center_x - page_center_x) < tolerance
                    layout_info = {'centered': is_centered, 'alone': is_alone}

                    if check_heading_user_defined(block_text, style_info, layout_info, heading_criteria):
                        potential_headings.append((block_text, page_marker))
                        logging.info(f"Detected potential heading on {page_marker}: '{block_text[:80]}...'") # Log truncated heading
                    else:
                        non_heading_blocks.append(block_text)

            # Process collected blocks for the page
            if potential_headings:
                current_chapter_title = potential_headings[0][0] # Use first detected heading on page

            full_page_text = "\n".join(non_heading_blocks)

            # Tokenize non-heading text into sentences
            try:
                sentences = nltk.sent_tokenize(full_page_text)
            except LookupError:
                logging.error("NLTK 'punkt' model not found during sentence tokenization. Aborting processing.")
                raise RuntimeError("NLTK 'punkt' tokenizer data not found. Processing cannot continue.") from None

            for sentence in sentences:
                sentence = sentence.replace('\n', ' ').strip()
                if sentence and not is_likely_metadata_or_footer(sentence): # Final check
                    extracted_data.append((sentence, page_marker, current_chapter_title))

        logging.info(f"Finished processing PDF. Extracted {len(extracted_data)} sentence segments.")

    except fitz.FitzError as e: # Corrected exception type
        logging.error(f"PyMuPDF (fitz) error processing PDF: {e}")
        raise ValueError(f"Error processing PDF file: {e}") from e
    except Exception as e:
        logging.error(f"Unexpected error during PDF processing: {e}", exc_info=True)
        if "NLTK 'punkt' tokenizer data not found" in str(e):
             raise # Re-raise the specific NLTK error
        else:
             raise RuntimeError(f"An unexpected error occurred during PDF processing: {e}") from e
    finally:
        if doc:
            doc.close() # Ensure PDF document is closed

    return extracted_data


# --- DOCX Processing ---
def _process_docx(
    file_bytes: io.BytesIO,
    heading_criteria: Dict[str, Any]
) -> List[Tuple[str, str, Optional[str]]]:
    """Extracts structured sentences from a DOCX file."""
    extracted_data = []
    current_chapter_title = None

    try:
        document = docx.Document(file_bytes)
        para_count = 0

        for i, para in enumerate(document.paragraphs):
            para_count += 1
            para_marker = f"Para {para_count}"
            text = para.text.strip()

            if not text or is_likely_metadata_or_footer(text):
                continue

            # Style and Layout Info (Limited for DOCX)
            style_info = {'bold': False, 'italic': False}
            if para.runs:
                first_run = para.runs[0]
                style_info['bold'] = bool(first_run.bold)
                style_info['italic'] = bool(first_run.italic)

            layout_info = {'centered': False, 'alone': True} # Assume alone
            # Check alignment for centered text
            try:
                # Accessing alignment can sometimes fail depending on docx structure/library version nuances
                if para.alignment and hasattr(para.alignment, 'name') and 'CENTER' in para.alignment.name:
                    layout_info['centered'] = True
            except Exception as align_err:
                 logging.warning(f"Could not determine paragraph alignment for '{text[:30]}...': {align_err}")


            # Check if paragraph is a heading
            if check_heading_user_defined(text, style_info, layout_info, heading_criteria):
                current_chapter_title = text
                logging.info(f"Detected potential heading at {para_marker}: '{text[:80]}...'") # Log truncated heading
                continue # Skip tokenizing heading itself

            # Tokenize non-heading paragraph text
            try:
                sentences = nltk.sent_tokenize(text)
            except LookupError:
                logging.error("NLTK 'punkt' model not found during sentence tokenization. Aborting processing.")
                raise RuntimeError("NLTK 'punkt' tokenizer data not found. Processing cannot continue.") from None

            for sentence in sentences:
                sentence = sentence.replace('\n', ' ').strip()
                if sentence and not is_likely_metadata_or_footer(sentence): # Final check
                    extracted_data.append((sentence, para_marker, current_chapter_title))

        logging.info(f"Finished processing DOCX. Extracted {len(extracted_data)} sentence segments.")

    except docx.opc.exceptions.PackageNotFoundError:
        logging.error("Invalid DOCX file provided.")
        raise ValueError("The uploaded file is not a valid DOCX document.")
    except Exception as e:
        logging.error(f"Unexpected error during DOCX processing: {e}", exc_info=True)
        if "NLTK 'punkt' tokenizer data not found" in str(e):
             raise # Re-raise the specific NLTK error
        else:
             raise RuntimeError(f"An unexpected error occurred during DOCX processing: {e}") from e

    return extracted_data


# --- Main Extraction Function ---
def extract_sentences_with_structure(
    file_content: bytes,
    filename: str,
    pdf_skip_start: int = 0,
    pdf_skip_end: int = 0,
    pdf_first_page_offset: int = 1,
    heading_criteria: Dict[str, Any] = None
) -> List[Tuple[str, str, Optional[str]]]:
    """
    Reads PDF or DOCX file content, extracts text, detects headings based on criteria,
    and returns a list of (sentence, page/para_marker, detected_chapter_title).
    """
    file_extension = ""
    try:
        file_extension = filename.split('.')[-1].lower()
    except IndexError:
        raise ValueError("Could not determine file extension from filename.")

    file_bytes = io.BytesIO(file_content)
    # Ensure heading_criteria is always a dict, even if None is passed
    heading_criteria = heading_criteria if heading_criteria is not None else {}

    if file_extension == 'pdf':
        logging.info(f"Processing PDF: {filename}")
        return _process_pdf(
            file_bytes,
            pdf_skip_start,
            pdf_skip_end,
            pdf_first_page_offset,
            heading_criteria
        )
    elif file_extension == 'docx':
        logging.info(f"Processing DOCX: {filename}")
        # DOCX doesn't use page skipping/offset
        return _process_docx(file_bytes, heading_criteria)
    else:
        raise ValueError(f"Unsupported file type: '{file_extension}'. Please upload PDF or DOCX.")
