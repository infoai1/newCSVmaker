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

    # Check for common page number patterns (optional: make stricter)
    if re.fullmatch(r"-?\s*\d+\s*-?", text):
         # Check position if available (e.g., bottom 10% of page for PDF)
        if block_bbox and page_height and block_bbox[3] > page_height * 0.90:
             return True
        # If position unavailable, still consider it potential metadata if just numbers
        elif not block_bbox:
             return True


    # Check for very short lines (e.g., less than 5 words) potentially at top/bottom
    if len(text.split()) < 5:
        # Check position if available (e.g., top 10% or bottom 10%)
        if block_bbox and page_height:
            if block_bbox[1] < page_height * 0.10 or block_bbox[3] > page_height * 0.90:
                return True
        # Heuristic: short lines are often suspect without position info
        # return True # Be careful with this, might remove valid short sentences

    # Add more rules based on observed patterns (e.g., repeated headers/footers)
    # For Maulana Wahiduddin Khan books, common footers might include website URLs
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
        # Add font name/size checks here if needed and criteria provided

    # --- Text Case Checks ---
    if criteria.get('check_case'):
        if criteria.get('case_title') and not text.istitle(): return False
        # Simple ALL CAPS check (consider refining for punctuation/numbers)
        is_all_caps = all(c.isupper() or not c.isalpha() for c in text if c.isprintable() and not c.isspace())
        if criteria.get('case_upper') and not (is_all_caps and any(c.isalpha() for c in text)): return False # Ensure it has letters

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
            if not re.match(criteria['pattern_regex'], text):
                return False
        except re.error as e:
            logging.warning(f"Regex error in heading check: {e}. Pattern: '{criteria['pattern_regex']}'")
            # Optionally: Decide whether to treat regex error as a non-match
            # return False
            pass # Or ignore the check if regex is invalid

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

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        num_pages = len(doc)
        start_page_idx = skip_start
        end_page_idx = num_pages - skip_end

        if start_page_idx >= end_page_idx:
            logging.warning("PDF processing skipped: Invalid page range after skipping.")
            return [] # Or raise error

        for page_num_idx in range(start_page_idx, end_page_idx):
            page = doc.load_page(page_num_idx)
            page_height = page.rect.height
            page_width = page.rect.width
            actual_page_num = page_num_idx + first_page_offset # Adjust page number based on offset
            page_marker = f"Page {actual_page_num}"

            page_dict = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT) # Get detailed text info

            potential_headings = []
            non_heading_blocks = []

            for block in page_dict.get("blocks", []):
                if block.get("type") == 0: # Text block
                    block_text = ""
                    span_details = [] # Collect details of spans in the block
                    block_bbox = block.get("bbox")

                    for line in block.get("lines", []):
                        line_text_parts = []
                        for span in line.get("spans", []):
                             line_text_parts.append(span.get("text", ""))
                             # Store first span's details as representative for the line/block
                             if not span_details:
                                 span_details.append({
                                     'size': span.get('size'),
                                     'font': span.get('font'),
                                     'flags': span.get('flags'), # Flags contain bold/italic info
                                     'bold': bool(span.get('flags', 0) & (1<<4)), # Bold flag often 16
                                     'italic': bool(span.get('flags', 0) & (1<<1)), # Italic flag often 2
                                 })

                        # Add space between lines if reconstructing block text
                        if block_text and line_text_parts:
                             block_text += "\n" # Or space, depending on desired structure
                        block_text += "".join(line_text_parts)

                    block_text = block_text.strip()
                    if not block_text: continue

                    # Preliminary cleaning (e.g., footers based on position)
                    if is_likely_metadata_or_footer(block_text, block_bbox, page_height):
                         logging.debug(f"Skipping likely metadata/footer on {page_marker}: '{block_text[:50]}...'")
                         continue

                    # --- Prepare info for heading check ---
                    # Use first span's style as representative
                    style_info = span_details[0] if span_details else {}

                    # Layout approximations
                    is_alone = len(block.get("lines", [])) == 1 # Simplistic: block has only one line
                    # Centered check (approximate): Check if block's horizontal center is near page center
                    is_centered = False
                    if block_bbox:
                         block_center_x = (block_bbox[0] + block_bbox[2]) / 2
                         page_center_x = page_width / 2
                         # Allow some tolerance (e.g., within 15% of page width from center)
                         tolerance = page_width * 0.15
                         is_centered = abs(block_center_x - page_center_x) < tolerance

                    layout_info = {'centered': is_centered, 'alone': is_alone}

                    # --- Check if this block is a heading ---
                    if check_heading_user_defined(block_text, style_info, layout_info, heading_criteria):
                        potential_headings.append((block_text, page_marker))
                        logging.info(f"Detected potential heading on {page_marker}: '{block_text}'")
                    else:
                         # It's regular text, add block text for sentence tokenization later
                         non_heading_blocks.append(block_text)


            # --- Process collected blocks for the page ---
            # If headings were found on this page, assume the first one is the primary chapter start for this page
            if potential_headings:
                # Use the text of the first detected heading on this page
                current_chapter_title = potential_headings[0][0]
                # Optional: Add heading text itself as a segment?
                # extracted_data.append((current_chapter_title, page_marker, current_chapter_title))


            # Tokenize the non-heading text from this page into sentences
            full_page_text = "\n".join(non_heading_blocks) # Join blocks with newline
            sentences = nltk.sent_tokenize(full_page_text)

            for sentence in sentences:
                 sentence = sentence.replace('\n', ' ').strip() # Clean up spaces/newlines within sentence
                 if sentence and not is_likely_metadata_or_footer(sentence): # Final check on sentence level
                     extracted_data.append((sentence, page_marker, current_chapter_title))

        logging.info(f"Finished processing PDF. Extracted {len(extracted_data)} sentence segments.")
        doc.close()

    except fitz.fitz.FitzError as e:
        logging.error(f"PyMuPDF (fitz) error processing PDF: {e}")
        raise ValueError(f"Error processing PDF file: {e}") from e
    except nltk.downloader.DownloadError as e:
         logging.error(f"NLTK 'punkt' model not available: {e}")
         raise RuntimeError("NLTK 'punkt' model needed for sentence tokenization is missing.") from e
    except Exception as e:
        logging.error(f"Unexpected error during PDF processing: {e}", exc_info=True)
        raise RuntimeError(f"An unexpected error occurred during PDF processing: {e}") from e

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

            if not text:
                continue

             # Simple cleaning (can be expanded)
            if is_likely_metadata_or_footer(text):
                 logging.debug(f"Skipping likely metadata/footer at {para_marker}: '{text[:50]}...'")
                 continue

            # --- Style and Layout Info (Limited for DOCX) ---
            style_info = {'bold': False, 'italic': False}
            # Check style of the first run (simplification)
            if para.runs:
                first_run = para.runs[0]
                style_info['bold'] = bool(first_run.bold)
                style_info['italic'] = bool(first_run.italic)
                # Could add font name/size if needed: first_run.font.name, first_run.font.size

            # Layout info is harder in docx without deeper inspection
            layout_info = {'centered': False, 'alone': True} # Assume alone, cannot easily tell centered
            # Crude check for centered using paragraph format alignment
            if para.alignment and hasattr(para.alignment, 'name') and 'CENTER' in para.alignment.name:
                 layout_info['centered'] = True


            # --- Check if paragraph is a heading ---
            if check_heading_user_defined(text, style_info, layout_info, heading_criteria):
                current_chapter_title = text
                logging.info(f"Detected potential heading at {para_marker}: '{text}'")
                 # Optional: Add heading text itself as a segment?
                 # extracted_data.append((current_chapter_title, para_marker, current_chapter_title))
                 # Don't tokenize the heading itself, just update the title
                continue # Move to next paragraph after identifying a heading

            # --- Tokenize non-heading paragraph text ---
            sentences = nltk.sent_tokenize(text)
            for sentence in sentences:
                 sentence = sentence.replace('\n', ' ').strip()
                 if sentence and not is_likely_metadata_or_footer(sentence): # Final check
                     extracted_data.append((sentence, para_marker, current_chapter_title))

        logging.info(f"Finished processing DOCX. Extracted {len(extracted_data)} sentence segments.")

    except docx.opc.exceptions.PackageNotFoundError:
        logging.error("Invalid DOCX file provided.")
        raise ValueError("The uploaded file is not a valid DOCX document.")
    except nltk.downloader.DownloadError as e:
         logging.error(f"NLTK 'punkt' model not available: {e}")
         raise RuntimeError("NLTK 'punkt' model needed for sentence tokenization is missing.") from e
    except Exception as e:
        logging.error(f"Unexpected error during DOCX processing: {e}", exc_info=True)
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
    file_extension = filename.split('.')[-1].lower()
    file_bytes = io.BytesIO(file_content)

    if heading_criteria is None:
        heading_criteria = {} # Default to no criteria if none provided

    if file_extension == 'pdf':
        logging.info(f"Processing PDF: {filename}")
        return _process_pdf(file_bytes, pdf_skip_start, pdf_skip_end, pdf_first_page_offset, heading_criteria)
    elif file_extension == 'docx':
        logging.info(f"Processing DOCX: {filename}")
        # DOCX doesn't use page skipping/offset from PDF options
        return _process_docx(file_bytes, heading_criteria)
    else:
        raise ValueError(f"Unsupported file type: '{file_extension}'. Please upload PDF or DOCX.")
