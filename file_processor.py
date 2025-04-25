# --- file_processor.py ---
import fitz                     # PyMuPDF
import docx, io
import re, statistics, nltk, logging
from typing import List, Tuple, Optional, Dict, Any # Added Any

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")

# --- Constants for PDF processing ---
# Flags from PyMuPDF documentation for font properties
FLAG_BOLD = 1
FLAG_ITALIC = 2
# Define a tolerance for centering check (e.g., block center within +/- 10% of page center)
CENTERING_TOLERANCE = 0.10

# ─────────────────────────────────────────────
# 1. Glyph fixes and whitespace cleaner (Keep As Is)
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
# 2. Heading detector HELPER (Simplified - main logic moved to extractors)
# ─────────────────────────────────────────────
# This is now mostly for DOCX or as a fallback
def _basic_heading_check(text: str,
                         regex: Optional[re.Pattern],
                         min_words: int,
                         max_words: int) -> bool:
    """Basic check based on regex and word count."""
    wc = len(text.split())
    if not (min_words <= wc <= max_words):
        return False
    # If regex is enabled, it must match. If not enabled, skip regex check.
    return True if regex is None else bool(regex.search(text))

# ─────────────────────────────────────────────
# 3. PDF extractor (SIGNIFICANTLY REVISED)
# ─────────────────────────────────────────────
def _extract_pdf(data: bytes,
                 skip_start: int, skip_end: int, offset: int,
                 # Pass the full criteria dictionary
                 heading_criteria: Dict[str, Any],
                 header_footer_margin: float = 0.15
                 ) -> List[Tuple[str, str, Optional[str]]]:

    doc = fitz.open(stream=data, filetype="pdf")
    start_page = max(0, skip_start)
    end_page = max(start_page, doc.page_count - skip_end)
    pages = range(start_page, end_page)

    if not pages:
        logging.warning("No pages selected for processing after skipping.")
        doc.close()
        return []

    # --- Font Size Threshold Calculation (Keep similar logic) ---
    sizes = []
    # ... (rest of the threshold calculation logic remains the same as previous version)
    try:
        # ... (code to collect sizes) ...
        for p_idx in pages:
             if p_idx >= doc.page_count: continue
             page_blocks = doc.load_page(p_idx).get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]
             for blk in page_blocks:
                  if blk.get("type") == 0 and "lines" in blk:
                      for ln in blk["lines"]:
                          if "spans" in ln:
                              for sp in ln["spans"]:
                                  if "size" in sp: sizes.append(sp["size"])
    except Exception as e:
        logging.error(f"Error calculating font sizes: {e}")
        font_size_threshold = 12 # Default threshold
    else:
        font_size_threshold = statistics.mean(sizes) + statistics.pstdev(sizes) * 0.5 if sizes else 12
    logging.info(f"Using font size threshold: {font_size_threshold:.2f}")
    # --- End Threshold Calculation ---


    # --- Extract heading criteria from the dictionary for easier access ---
    check_style = heading_criteria.get('check_style', False)
    style_bold = heading_criteria.get('style_bold', False)
    style_italic = heading_criteria.get('style_italic', False)
    check_case = heading_criteria.get('check_case', False)
    case_upper = heading_criteria.get('case_upper', False)
    case_title = heading_criteria.get('case_title', False) # Note: Title case detection is basic
    check_layout = heading_criteria.get('check_layout', False)
    layout_centered = heading_criteria.get('layout_centered', False)
    # layout_alone = heading_criteria.get('layout_alone', False) # Check if block has only one line?
    check_word_count = heading_criteria.get('check_word_count', False)
    wc_min = heading_criteria.get('word_count_min', 1)
    wc_max = heading_criteria.get('word_count_max', 999)
    check_pattern = heading_criteria.get('check_pattern', False)
    pattern_regex = heading_criteria.get('pattern_regex', None) # Expect compiled regex


    out: List[Tuple[str, str, Optional[str]]] = []
    current_heading_text = None # Track last *valid* heading seen

    for p in pages:
        if p >= doc.page_count: continue
        try:
            page = doc.load_page(p)
            page_rect = page.rect
            page_height = page_rect.height
            page_width = page_rect.width
            header_zone_end_y = page_height * header_footer_margin
            footer_zone_start_y = page_height * (1.0 - header_footer_margin)

            page_blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]
            for blk in page_blocks:
                if blk.get("type") != 0 or "lines" not in blk: continue

                # --- Extract block properties ---
                block_text_lines = []
                block_max_fsize = 0
                block_is_bold = False # Check if *any* span is bold
                block_is_italic = False # Check if *any* span is italic
                span_count = 0
                for ln in blk["lines"]:
                    line_text_parts = []
                    if "spans" in ln:
                        for sp in ln["spans"]:
                            span_count += 1
                            if "text" in sp: line_text_parts.append(sp["text"])
                            if "size" in sp: block_max_fsize = max(block_max_fsize, sp["size"])
                            if "flags" in sp:
                                if sp["flags"] & FLAG_BOLD: block_is_bold = True
                                if sp["flags"] & FLAG_ITALIC: block_is_italic = True
                    line_text = "".join(line_text_parts)
                    if line_text.strip():
                        block_text_lines.append(line_text)

                if not block_text_lines: continue # Skip empty blocks

                raw_text = " ".join(block_text_lines)
                cleaned_text = _clean(raw_text)
                if not cleaned_text or RE_ONLY_DIG.match(cleaned_text):
                    continue

                # --- HEADING DETECTION LOGIC ---
                is_heading = True # Start assuming it IS a heading, then invalidate
                block_heading_text = None # Reset for this block

                # 1. Positional Check (Header/Footer Zone) - Always apply this check first
                bbox = blk["bbox"]
                # Use vertical center of the block for check
                block_center_y = (bbox[1] + bbox[3]) / 2
                is_in_margin = block_center_y < header_zone_end_y or block_center_y > footer_zone_start_y
                if is_in_margin:
                    logging.debug(f"Ignoring block in margin (Page {p + offset}, Center Y:{block_center_y:.1f}): '{cleaned_text[:50]}...'")
                    is_heading = False # Definitely not a heading if in margin

                # 2. Font Size Check (Apply only if not already disqualified)
                # Use a relative check: must be >= threshold AND larger than typical body text (e.g. > 10)
                # This prevents tiny text that's relatively large for its page from being a heading
                if is_heading and block_max_fsize < font_size_threshold:
                    # Optional: Add check block_max_fsize < MIN_REASONABLE_HEADING_SIZE (e.g. 10)?
                    # logging.debug(f"Block failed font size check ({block_max_fsize:.1f} < {font_size_threshold:.1f}): {cleaned_text[:30]}")
                    is_heading = False

                # 3. Style Checks (Apply only if check_style is enabled and not disqualified)
                if is_heading and check_style:
                    if style_bold and not block_is_bold:
                         is_heading = False
                         # logging.debug(f"Block failed Bold check: {cleaned_text[:30]}")
                    if is_heading and style_italic and not block_is_italic:
                         is_heading = False
                         # logging.debug(f"Block failed Italic check: {cleaned_text[:30]}")

                # 4. Case Checks (Apply only if check_case is enabled and not disqualified)
                if is_heading and check_case:
                    # Basic check: requires more than half the letters to be uppercase
                    is_likely_upper = sum(1 for c in cleaned_text if c.isupper()) > len(cleaned_text) / 2
                    # Basic check: first letter of most words is upper, others lower
                    is_likely_title = cleaned_text.istitle() # This is often too strict

                    if case_upper and not is_likely_upper:
                         is_heading = False
                         # logging.debug(f"Block failed ALL CAPS check: {cleaned_text[:30]}")
                    # Use 'elif' because it usually can't be both Title and Upper
                    elif is_heading and case_title and not is_likely_title:
                         is_heading = False
                         # logging.debug(f"Block failed Title Case check: {cleaned_text[:30]}")

                # 5. Layout Checks (Apply only if check_layout is enabled and not disqualified)
                if is_heading and check_layout:
                    if layout_centered:
                        page_center_x = page_width / 2
                        block_center_x = (bbox[0] + bbox[2]) / 2
                        allowed_delta = page_width * CENTERING_TOLERANCE
                        if abs(block_center_x - page_center_x) > allowed_delta:
                            is_heading = False
                            # logging.debug(f"Block failed Centered check: {cleaned_text[:30]}")
                    # Check for 'alone in block' might mean len(blk["lines"]) == 1?
                    # if is_heading and layout_alone and len(blk["lines"]) > 1:
                    #      is_heading = False

                # 6. Word Count Check (Apply only if check_word_count is enabled and not disqualified)
                if is_heading and check_word_count:
                    word_count = len(cleaned_text.split())
                    if not (wc_min <= word_count <= wc_max):
                        is_heading = False
                        # logging.debug(f"Block failed Word Count check ({word_count}): {cleaned_text[:30]}")

                # 7. Regex Pattern Check (Apply only if check_pattern is enabled and not disqualified)
                if is_heading and check_pattern and pattern_regex:
                    if not pattern_regex.search(cleaned_text):
                        is_heading = False
                        # logging.debug(f"Block failed Regex check: {cleaned_text[:30]}")


                # --- Final Decision for this block ---
                if is_heading:
                    block_heading_text = cleaned_text # Assign the text as heading
                    current_heading_text = cleaned_text # Update the ongoing chapter title tracker
                    logging.info(f"Detected HEADING (Page {p + offset}): '{cleaned_text}'") # Use INFO for confirmed headings
                # --- End Heading Detection ---


                # --- SENTENCE EXTRACTION ---
                try:
                    sentences = nltk.sent_tokenize(cleaned_text)
                except Exception as e:
                    logging.error(f"NLTK sentence tokenization failed for block on page {p + offset}: {e}. Using block as single sentence.")
                    sentences = [cleaned_text]

                for sent in sentences:
                    clean_sent = sent.strip()
                    if clean_sent:
                         # Associate sentence with the heading status OF THIS BLOCK.
                         # Or, use current_heading_text if you want subsequent paragraphs
                         # under a heading to inherit it. Let's stick with block association for now.
                         # Pass block_heading_text (which is None if block wasn't a heading)
                         out.append((clean_sent, f"p{p + offset}", block_heading_text))

        except Exception as page_err:
             logging.error(f"Failed processing page {p}: {page_err}", exc_info=True)

    doc.close()
    return out

# ─────────────────────────────────────────────
# 4. DOCX extractor (REVISED to use more criteria)
# ─────────────────────────────────────────────
def _extract_docx(data: bytes,
                  # Pass the full criteria dictionary
                  heading_criteria: Dict[str, Any]
                  ) -> List[Tuple[str, str, Optional[str]]]:

    # --- Extract criteria (similar to PDF part) ---
    check_case = heading_criteria.get('check_case', False)
    case_upper = heading_criteria.get('case_upper', False)
    case_title = heading_criteria.get('case_title', False)
    check_word_count = heading_criteria.get('check_word_count', False)
    wc_min = heading_criteria.get('word_count_min', 1)
    wc_max = heading_criteria.get('word_count_max', 999)
    check_pattern = heading_criteria.get('check_pattern', False)
    pattern_regex = heading_criteria.get('pattern_regex', None)
    # Note: Style (bold/italic) and layout (centered) checks are less reliable/easy with python-docx paragraph runs

    doc = docx.Document(io.BytesIO(data))
    res = []
    current_heading_text = None # Track last valid heading

    for i, para in enumerate(doc.paragraphs, 1):
        cleaned_text = _clean(para.text)
        if not cleaned_text:
            continue

        # --- Basic Heading Check using available criteria ---
        is_heading = True
        block_heading_text = None

        # 1. Case Checks
        if is_heading and check_case:
             is_likely_upper = sum(1 for c in cleaned_text if c.isupper()) > len(cleaned_text) / 2
             is_likely_title = cleaned_text.istitle()
             if case_upper and not is_likely_upper: is_heading = False
             elif is_heading and case_title and not is_likely_title: is_heading = False

        # 2. Word Count Check
        if is_heading and check_word_count:
            word_count = len(cleaned_text.split())
            if not (wc_min <= word_count <= wc_max): is_heading = False

        # 3. Regex Pattern Check
        if is_heading and check_pattern and pattern_regex:
            if not pattern_regex.search(cleaned_text): is_heading = False

        # --- Final Decision ---
        if is_heading:
             # We assume if it passes filters, it's a heading in DOCX context
             # (Lacks font size/positional info readily available in PDF)
             block_heading_text = cleaned_text
             current_heading_text = cleaned_text
             logging.info(f"Detected HEADING (Para {i}): '{cleaned_text}'")
        # --- End DOCX Heading Check ---

        try:
            sentences = nltk.sent_tokenize(cleaned_text)
        except Exception as e:
            logging.error(f"NLTK sentence tokenization failed for para {i}: {e}. Using para as single sentence.")
            sentences = [cleaned_text]

        for sent in sentences:
             clean_sent = sent.strip()
             if clean_sent:
                # Associate with block's heading status
                res.append((clean_sent, f"para{i}", block_heading_text))

    return res


# ─────────────────────────────────────────────
# 6. Back-compat wrapper (REVISED to pass dict)
# ─────────────────────────────────────────────
def extract_sentences_with_structure(*,
                                     file_content: bytes,
                                     filename: str,
                                     pdf_skip_start: int = 0,
                                     pdf_skip_end: int = 0,
                                     pdf_first_page_offset: int = 1,
                                     # Expect the full dictionary from app.py
                                     heading_criteria: Dict = None,
                                     # Keep old args for potential direct use, but prioritize dict
                                     regex: str = "", # Fallback if criteria dict not passed well
                                     max_heading_words: int = 12): # Fallback
    """
    Wrapper updated to pass the full heading_criteria dictionary
    to the underlying PDF or DOCX extractors.
    """
    effective_criteria = heading_criteria if heading_criteria is not None else {}

    # --- Ensure essential keys exist in criteria, potentially using fallbacks ---
    if 'pattern_regex' not in effective_criteria and regex:
         try:
             effective_criteria['pattern_regex'] = re.compile(regex, re.I)
         except re.error:
              effective_criteria['pattern_regex'] = None
    if 'word_count_max' not in effective_criteria:
         effective_criteria['word_count_max'] = max_heading_words
    # Ensure other keys have defaults if missing from dict
    effective_criteria.setdefault('check_style', False)
    effective_criteria.setdefault('style_bold', False)
    effective_criteria.setdefault('style_italic', False)
    effective_criteria.setdefault('check_case', False)
    effective_criteria.setdefault('case_upper', False)
    effective_criteria.setdefault('case_title', False)
    effective_criteria.setdefault('check_layout', False)
    effective_criteria.setdefault('layout_centered', False)
    effective_criteria.setdefault('check_word_count', False)
    effective_criteria.setdefault('word_count_min', 1)
    effective_criteria.setdefault('check_pattern', 'pattern_regex' in effective_criteria and effective_criteria['pattern_regex'] is not None)


    # --- Determine file type ---
    file_ext = filename.lower().rsplit(".", 1)[-1] if '.' in filename else ''

    # --- Call appropriate extractor with the full criteria ---
    if file_ext == "pdf":
        return _extract_pdf(data=file_content,
                            skip_start=pdf_skip_start,
                            skip_end=pdf_skip_end,
                            offset=pdf_first_page_offset,
                            heading_criteria=effective_criteria, # Pass the dict
                            header_footer_margin=0.15) # Keep margin hardcoded or make configurable
    elif file_ext == "docx":
        return _extract_docx(data=file_content,
                             heading_criteria=effective_criteria) # Pass the dict
    else:
        logging.error(f"Unsupported file type attempted: {filename}")
        raise ValueError(f"Unsupported file type: {filename}")
