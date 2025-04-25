# --- START OF newCSVmaker-main/file_processor.py ---
import fitz                     # PyMuPDF
import docx, io
import re, statistics, nltk, logging
from typing import List, Tuple, Optional, Dict, Any

# Ensure DEBUG level is set for detailed logs during development/testing
# Change back to logging.INFO for normal use if desired
logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s | %(levelname)s | %(module)s:%(lineno)d | %(message)s")

# --- Constants ---
FLAG_BOLD = 1
FLAG_ITALIC = 2
CENTERING_TOLERANCE = 0.10

# ─────────────────────────────────────────────
# 1. Glyph fixes and whitespace cleaner
# ─────────────────────────────────────────────
GLYPH_MAP: Dict[str, str] = {
    "ﬂ": "fl", "ﬁ": "fi", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    "Te ": "The ", "te ": "the ", "!nd": "find", "!rst": "first", "!n": "fin",
}
RE_WS        = re.compile(r"\s+")
RE_ONLY_DIG  = re.compile(r"^\d{1,4}$")
RE_PNO_LEAD  = re.compile(r"^\d+\s+")
RE_MID_FI    = re.compile(r"([A-Za-z])!([A-Za-z])")

def _clean(raw: str) -> str:
    txt = raw.replace("\n", " ")
    txt = RE_PNO_LEAD.sub("", txt)
    txt = RE_MID_FI.sub(r"\1fi\2", txt)
    for bad, good in GLYPH_MAP.items():
        txt = txt.replace(bad, good)
    return RE_WS.sub(" ", txt).strip()

# ─────────────────────────────────────────────
# 2. Heading detector HELPER (Basic - for DOCX mainly)
# ─────────────────────────────────────────────
def _basic_heading_check(text: str,
                         regex: Optional[re.Pattern],
                         min_words: int,
                         max_words: int) -> bool:
    """Basic check based on regex and word count."""
    wc = len(text.split())
    if not (min_words <= wc <= max_words):
        return False
    return True if regex is None else bool(regex.search(text))

# ─────────────────────────────────────────────
# 3. PDF extractor (Refactored with Block Type - Returns 4 Tuples)
# ─────────────────────────────────────────────
def _extract_pdf(data: bytes,
                 skip_start: int, skip_end: int, offset: int,
                 heading_criteria: Dict[str, Any],
                 header_footer_margin: float = 0.15
                 ) -> List[Tuple[str, str, str, Optional[str]]]: # OUTPUT: (sentence, marker, block_type, heading_text)

    doc = None # Initialize doc to None
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        logging.error(f"Failed to open PDF stream: {e}", exc_info=True)
        return [] # Cannot proceed if PDF doesn't open

    # --- Page range calculation ---
    pdf_page_count = doc.page_count
    start_page = max(0, min(skip_start, pdf_page_count))
    end_page = max(start_page, min(pdf_page_count - skip_end, pdf_page_count))
    pages = range(start_page, end_page)
    logging.info(f"PDF has {pdf_page_count} pages. Processing pages {start_page} to {end_page - 1} (indices).")

    if not pages:
        logging.warning("Page range is empty after applying skip settings. No pages to process.")
        if doc: doc.close()
        return []
    # --- End Page Range ---

    # --- Font Size Threshold Calculation ---
    sizes = []
    try:
        for p_idx in pages:
             page = doc.load_page(p_idx) # Load page once
             page_blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]
             for blk in page_blocks:
                  if blk.get("type") == 0 and "lines" in blk:
                      for ln in blk["lines"]:
                          if "spans" in ln:
                              for sp in ln["spans"]:
                                  if "size" in sp: sizes.append(sp["size"])
    except Exception as e:
        logging.error(f"Error calculating font sizes: {e}", exc_info=True)
        font_size_threshold = 12 # Default threshold
    else:
        font_size_threshold = statistics.mean(sizes) + statistics.pstdev(sizes) * 0.5 if sizes else 12
    logging.info(f"Using font size threshold: {font_size_threshold:.2f}")
    # --- End Threshold Calculation ---

    # --- Extract heading criteria ---
    check_style = heading_criteria.get('check_style', False); style_bold = heading_criteria.get('style_bold', False); style_italic = heading_criteria.get('style_italic', False)
    check_case = heading_criteria.get('check_case', False); case_upper = heading_criteria.get('case_upper', False); case_title = heading_criteria.get('case_title', False)
    check_layout = heading_criteria.get('check_layout', False); layout_centered = heading_criteria.get('layout_centered', False)
    check_word_count = heading_criteria.get('check_word_count', False); wc_min = heading_criteria.get('word_count_min', 1); wc_max = heading_criteria.get('word_count_max', 999)
    check_pattern = heading_criteria.get('check_pattern', False); pattern_regex = heading_criteria.get('pattern_regex', None)

    # --- Main Processing Loop ---
    out: List[Tuple[str, str, str, Optional[str]]] = []
    last_confirmed_heading = None

    for p in pages:
        try:
            page = doc.load_page(p)
            page_rect = page.rect
            page_height = page_rect.height
            page_width = page_rect.width
            header_zone_end_y = page_height * header_footer_margin
            footer_zone_start_y = page_height * (1.0 - header_footer_margin)

            logging.debug(f"--- Processing Page {p + offset} (Index {p}) ---")

            page_blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT | fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

            if not page_blocks:
                 logging.debug(f"Page {p + offset}: No text blocks found by get_text.")
                 continue

            for blk_idx, blk in enumerate(page_blocks):
                if blk.get("type") != 0 or "lines" not in blk: continue

                bbox = blk.get("bbox") # Use .get for safety
                if not bbox:
                     logging.warning(f"Block {blk_idx} on page {p+offset} missing bounding box.")
                     continue # Cannot process without bbox

                # Extract block properties
                block_text_lines = []; block_max_fsize = 0; block_is_bold = False; block_is_italic = False
                for ln in blk["lines"]:
                    line_text_parts = []
                    if "spans" in ln:
                        for sp in ln["spans"]:
                            if "text" in sp: line_text_parts.append(sp["text"])
                            if "size" in sp: block_max_fsize = max(block_max_fsize, sp["size"])
                            if "flags" in sp:
                                if sp["flags"] & FLAG_BOLD: block_is_bold = True
                                if sp["flags"] & FLAG_ITALIC: block_is_italic = True
                    line_text = "".join(line_text_parts)
                    if line_text.strip(): block_text_lines.append(line_text)

                if not block_text_lines: continue

                raw_text = " ".join(block_text_lines)
                cleaned_text = _clean(raw_text)
                marker = f"p{p + offset}.{blk_idx}" # Page number uses offset

                logging.debug(f"  Block {blk_idx} [{marker}]: BBox={bbox}, MaxSize={block_max_fsize:.1f}, Text='{cleaned_text[:80]}...'")

                if not cleaned_text or RE_ONLY_DIG.match(cleaned_text):
                    logging.debug(f"    -> Skipping block (empty/digits).")
                    continue

                # --- BLOCK TYPE CLASSIFICATION ---
                block_type = "body" # Default
                block_heading_text = None # Text if block_type becomes 'heading'
                is_potential_heading = True

                # 1. Positional Check (Header/Footer)
                block_center_y = (bbox[1] + bbox[3]) / 2
                if block_center_y < header_zone_end_y:
                    block_type = "header"; is_potential_heading = False
                    logging.debug(f"    -> Classified as HEADER (Center Y: {block_center_y:.1f})")
                elif block_center_y > footer_zone_start_y:
                    block_type = "footer"; is_potential_heading = False
                    logging.debug(f"    -> Classified as FOOTER (Center Y: {block_center_y:.1f})")

                # 2. Heading Check (Only if block_type is still 'body')
                if is_potential_heading:
                    rejection_reason = "Did not meet positive criteria"
                    passes_heading_checks = True

                    if block_max_fsize < font_size_threshold:
                        passes_heading_checks = False; rejection_reason = f"Font size {block_max_fsize:.1f} < threshold {font_size_threshold:.1f}"
                    else:
                        # Apply other enabled criteria
                        if check_style:
                             if style_bold and not block_is_bold: passes_heading_checks = False; rejection_reason = "Style: Not Bold"
                             if passes_heading_checks and style_italic and not block_is_italic: passes_heading_checks = False; rejection_reason = "Style: Not Italic"
                        if passes_heading_checks and check_case:
                             text_len = len(cleaned_text.replace(" ","")); upper_count = sum(1 for c in cleaned_text if c.isupper())
                             is_mostly_upper = upper_count / text_len > 0.6 if text_len else False; is_simple_title = cleaned_text.istitle()
                             if case_upper and not is_mostly_upper: passes_heading_checks = False; rejection_reason = f"Case: Not mostly UPPER ({upper_count}/{text_len})"
                             elif passes_heading_checks and case_title and not is_simple_title: passes_heading_checks = False; rejection_reason = "Case: Not Title Case"
                        if passes_heading_checks and check_layout:
                             if layout_centered:
                                  page_center_x = page_width / 2; block_center_x = (bbox[0] + bbox[2]) / 2
                                  allowed_delta = page_width * CENTERING_TOLERANCE
                                  if abs(block_center_x - page_center_x) > allowed_delta: passes_heading_checks = False; rejection_reason = f"Layout: Not Centered (Delta: {abs(block_center_x - page_center_x):.1f})"
                        if passes_heading_checks and check_word_count:
                             word_count = len(cleaned_text.split())
                             if not (wc_min <= word_count <= wc_max): passes_heading_checks = False; rejection_reason = f"Word Count: {word_count} not in [{wc_min}-{wc_max}]"
                        if passes_heading_checks and check_pattern and pattern_regex:
                             if not pattern_regex.search(cleaned_text): passes_heading_checks = False; rejection_reason = f"Pattern: Regex '{pattern_regex.pattern}' not found"

                    if passes_heading_checks:
                        block_type = "heading"
                        block_heading_text = cleaned_text
                        last_confirmed_heading = cleaned_text
                        logging.info(f"    -> Classified as HEADING: '{cleaned_text}'")
                    else:
                        logging.debug(f"    -> Classified as BODY (Rejected as heading: {rejection_reason})")

                # --- Determine heading text to assign ---
                assigned_heading = last_confirmed_heading
                if block_type == "heading":
                    assigned_heading = block_heading_text

                # --- SENTENCE EXTRACTION ---
                try:
                    sentences = nltk.sent_tokenize(cleaned_text)
                    if not sentences and cleaned_text: sentences = [cleaned_text]
                except Exception as e:
                    logging.error(f"NLTK sentence tokenization failed block {blk_idx} pg {p + offset}: {e}", exc_info=True)
                    sentences = [cleaned_text] if cleaned_text else []

                # Append sentences with the new structure
                for sent in sentences:
                    clean_sent = sent.strip()
                    if clean_sent:
                         out.append((clean_sent, marker, block_type, assigned_heading))

        except Exception as page_err:
             logging.error(f"FATAL: Failed processing page {p} (Index): {page_err}", exc_info=True)

    if doc: doc.close()
    logging.info(f"Extraction finished. Total 4-tuple items generated: {len(out)}")
    if not out:
        logging.warning("The PDF extraction process resulted in zero output items.")
    return out

# ─────────────────────────────────────────────
# 4. DOCX extractor (Returns 3 Tuples - Sentence, Marker, Heading)
# ─────────────────────────────────────────────
def _extract_docx(data: bytes,
                  heading_criteria: Dict[str, Any]
                  ) -> List[Tuple[str, str, Optional[str]]]: # OUTPUT: (sentence, marker, heading_text)

    # --- Extract criteria ---
    check_case = heading_criteria.get('check_case', False); case_upper = heading_criteria.get('case_upper', False); case_title = heading_criteria.get('case_title', False)
    check_word_count = heading_criteria.get('check_word_count', False); wc_min = heading_criteria.get('word_count_min', 1); wc_max = heading_criteria.get('word_count_max', 999)
    check_pattern = heading_criteria.get('check_pattern', False); pattern_regex = heading_criteria.get('pattern_regex', None)

    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as e:
        logging.error(f"Failed to open DOCX stream: {e}", exc_info=True)
        return []

    res: List[Tuple[str, str, Optional[str]]] = []
    last_confirmed_heading = None

    logging.debug(f"Processing DOCX. Criteria: {heading_criteria}")

    for i, para in enumerate(doc.paragraphs, 1):
        cleaned_text = _clean(para.text)
        marker = f"para{i}"
        logging.debug(f"  Para {i} [{marker}]: Text='{cleaned_text[:80]}...'")
        if not cleaned_text:
            logging.debug("    -> Skipping empty paragraph.")
            continue

        is_this_para_a_heading = False
        rejection_reason = "Did not meet positive criteria"
        passes_positive_checks = True # Assume passes unless a check fails

        # Apply checks
        if check_case:
             text_len = len(cleaned_text.replace(" ","")); upper_count = sum(1 for c in cleaned_text if c.isupper())
             is_mostly_upper = upper_count / text_len > 0.6 if text_len else False; is_simple_title = cleaned_text.istitle()
             if case_upper and not is_mostly_upper: passes_positive_checks = False; rejection_reason = f"Case: Not mostly UPPER ({upper_count}/{text_len})"
             elif passes_positive_checks and case_title and not is_simple_title: passes_positive_checks = False; rejection_reason = "Case: Not Title Case"
        if passes_positive_checks and check_word_count:
            word_count = len(cleaned_text.split())
            if not (wc_min <= word_count <= wc_max): passes_positive_checks = False; rejection_reason = f"Word Count: {word_count} not in [{wc_min}-{wc_max}]"
        if passes_positive_checks and check_pattern and pattern_regex:
            if not pattern_regex.search(cleaned_text): passes_positive_checks = False; rejection_reason = f"Pattern: Regex '{pattern_regex.pattern}' not found"

        # Determine heading text to assign
        assigned_heading = last_confirmed_heading # Inherit by default
        if passes_positive_checks:
            is_this_para_a_heading = True
            last_confirmed_heading = cleaned_text # Update tracker
            assigned_heading = cleaned_text # Assign self as heading
            logging.info(f"    -> Classified as HEADING (DOCX): '{cleaned_text}'")
        else:
             logging.debug(f"    -> Classified as BODY (DOCX) (Rejected as heading: {rejection_reason})")

        try:
            sentences = nltk.sent_tokenize(cleaned_text)
            if not sentences and cleaned_text: sentences = [cleaned_text]
        except Exception as e:
            logging.error(f"NLTK sentence tokenization failed para {i}: {e}", exc_info=True)
            sentences = [cleaned_text] if cleaned_text else []

        for sent in sentences:
             clean_sent = sent.strip()
             if clean_sent:
                # Append 3-tuple: (sentence, marker, assigned_heading)
                res.append((clean_sent, marker, assigned_heading))

    logging.info(f"DOCX Extraction finished. Total 3-tuple items generated: {len(res)}")
    if not res:
        logging.warning("The DOCX extraction process resulted in zero output items.")
    return res


# ─────────────────────────────────────────────
# 6. Back-compat wrapper (RESTORED and ADAPTED)
# ─────────────────────────────────────────────
def extract_sentences_with_structure(*,
                                     file_content: bytes,
                                     filename: str,
                                     pdf_skip_start: int = 0,
                                     pdf_skip_end: int = 0,
                                     pdf_first_page_offset: int = 1,
                                     heading_criteria: Dict = None,
                                     regex: str = "",
                                     max_heading_words: int = 12):
    """
    Wrapper called by app.py. It calls the internal extractors (_extract_pdf, _extract_docx)
    and ensures the output is consistently a list of 3-tuples: (sentence, marker, assigned_heading),
    which is the format expected by app.py and chunker.py.
    """
    effective_criteria = heading_criteria if heading_criteria is not None else {}

    # --- Prepare criteria (Compile regex, set defaults) ---
    # (This section remains the same as the previous good version)
    if 'pattern_regex' not in effective_criteria and regex:
         try:
             effective_criteria['pattern_regex'] = re.compile(regex, re.I)
             effective_criteria.setdefault('check_pattern', True)
         except re.error:
              logging.warning(f"Invalid fallback regex provided: {regex}")
              effective_criteria['pattern_regex'] = None
              effective_criteria.setdefault('check_pattern', False)
    elif 'pattern_regex' in effective_criteria and isinstance(effective_criteria['pattern_regex'], str):
         try:
             pattern_str = effective_criteria['pattern_regex']
             effective_criteria['pattern_regex'] = re.compile(pattern_str, re.I)
             logging.debug(f"Compiled regex from criteria dict string: {pattern_str}")
         except re.error as e:
             logging.error(f"Invalid regex string in heading_criteria dict: {effective_criteria['pattern_regex']} - Error: {e}")
             effective_criteria['pattern_regex'] = None
             effective_criteria['check_pattern'] = False

    # Ensure other keys have defaults
    effective_criteria.setdefault('check_style', False); effective_criteria.setdefault('style_bold', False); effective_criteria.setdefault('style_italic', False)
    effective_criteria.setdefault('check_case', False); effective_criteria.setdefault('case_upper', False); effective_criteria.setdefault('case_title', False)
    effective_criteria.setdefault('check_layout', False); effective_criteria.setdefault('layout_centered', False)
    effective_criteria.setdefault('check_word_count', False); effective_criteria.setdefault('word_count_min', 1)
    effective_criteria.setdefault('word_count_max', heading_criteria.get('word_count_max', max_heading_words))
    effective_criteria.setdefault('check_pattern', effective_criteria.get('pattern_regex') is not None)
    # --- End Criteria Preparation ---

    # --- Determine file type ---
    file_ext = ""
    if isinstance(filename, str) and '.' in filename:
         file_ext = filename.lower().rsplit(".", 1)[-1]
    elif isinstance(filename, str):
         logging.warning(f"Filename '{filename}' has no extension.")
    else:
         logging.error(f"Invalid filename provided: {filename}")
         raise ValueError("Invalid filename")


    # --- Call appropriate extractor and CONVERT to 3-tuple format ---
    structured_sentences_output = [] # This will always hold 3-tuples

    if file_ext == "pdf":
        # _extract_pdf returns List[Tuple[str, str, str, Optional[str]]]
        extracted_data_raw = _extract_pdf(data=file_content,
                                          skip_start=pdf_skip_start,
                                          skip_end=pdf_skip_end,
                                          offset=pdf_first_page_offset,
                                          heading_criteria=effective_criteria,
                                          header_footer_margin=0.15)
        # Convert 4-tuples to 3-tuples
        for item in extracted_data_raw:
             if len(item) == 4:
                  # Keep sentence, marker, assigned_heading (discard block_type)
                  structured_sentences_output.append((item[0], item[1], item[3]))
             else:
                  logging.warning(f"PDF extractor returned unexpected item structure: {item}")

    elif file_ext == "docx":
        # _extract_docx currently returns List[Tuple[str, str, Optional[str]]] (3-tuples)
        structured_sentences_output = _extract_docx(data=file_content,
                                                     heading_criteria=effective_criteria)
        # No conversion needed for DOCX as it already returns 3-tuples

    else:
        logging.error(f"Unsupported file type attempted: {filename}")
        raise ValueError(f"Unsupported file type: {filename}")

    # --- Return the consistent 3-tuple list ---
    logging.info(f"Wrapper returning {len(structured_sentences_output)} items in 3-tuple format.")
    return structured_sentences_output

# --- END OF newCSVmaker-main/file_processor.py ---
