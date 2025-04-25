# --- file_processor.py ---
# [Keep imports, constants, helper functions like _clean as before]
import fitz, docx, io, re, statistics, nltk, logging
from typing import List, Tuple, Optional, Dict, Any

logging.basicConfig(level=logging.DEBUG, # <<< CHANGE TO DEBUG for more output
                    format="%(asctime)s | %(levelname)s | %(module)s:%(lineno)d | %(message)s")

# ... (Keep FLAG_BOLD, FLAG_ITALIC, CENTERING_TOLERANCE, _clean, _basic_heading_check) ...

# ─────────────────────────────────────────────
# 3. PDF extractor (REVISED AGAIN)
# ─────────────────────────────────────────────
def _extract_pdf(data: bytes,
                 skip_start: int, skip_end: int, offset: int,
                 heading_criteria: Dict[str, Any],
                 header_footer_margin: float = 0.15
                 ) -> List[Tuple[str, str, Optional[str]]]:

    doc = fitz.open(stream=data, filetype="pdf")
    start_page = max(0, skip_start)
    end_page = max(start_page, doc.page_count - skip_end)
    pages = range(start_page, end_page)

    if not pages:
        logging.warning("No pages selected for processing.")
        doc.close()
        return []

    # --- Font Size Threshold Calculation (Keep as before) ---
    # ... (Calculate font_size_threshold) ...
    sizes = []
    try:
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


    # --- Extract heading criteria (Keep as before) ---
    check_style = heading_criteria.get('check_style', False)
    style_bold = heading_criteria.get('style_bold', False)
    style_italic = heading_criteria.get('style_italic', False)
    check_case = heading_criteria.get('check_case', False)
    case_upper = heading_criteria.get('case_upper', False)
    case_title = heading_criteria.get('case_title', False)
    check_layout = heading_criteria.get('check_layout', False)
    layout_centered = heading_criteria.get('layout_centered', False)
    check_word_count = heading_criteria.get('check_word_count', False)
    wc_min = heading_criteria.get('word_count_min', 1)
    wc_max = heading_criteria.get('word_count_max', 999)
    check_pattern = heading_criteria.get('check_pattern', False)
    pattern_regex = heading_criteria.get('pattern_regex', None)

    out: List[Tuple[str, str, Optional[str]]] = []
    # *** CHANGE: Let's track the *last confirmed heading text* separate from block processing ***
    last_confirmed_heading = None

    logging.debug(f"Processing pages {start_page} to {end_page-1}. Criteria: {heading_criteria}")

    for p in pages:
        if p >= doc.page_count: continue
        try:
            page = doc.load_page(p)
            page_rect = page.rect
            page_height = page_rect.height
            page_width = page_rect.width
            header_zone_end_y = page_height * header_footer_margin
            footer_zone_start_y = page_height * (1.0 - header_footer_margin)

            logging.debug(f"--- Processing Page {p + offset} (Height: {page_height:.1f}, Width: {page_width:.1f}) ---")
            logging.debug(f"Header zone y < {header_zone_end_y:.1f}, Footer zone y > {footer_zone_start_y:.1f}")

            page_blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT | fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE)["blocks"] # Try adding flags

            for blk_idx, blk in enumerate(page_blocks):
                if blk.get("type") != 0 or "lines" not in blk: continue

                bbox = blk["bbox"]
                block_text_lines = []
                block_max_fsize = 0
                block_is_bold = False
                block_is_italic = False

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
                    if line_text.strip():
                        block_text_lines.append(line_text)

                if not block_text_lines: continue

                raw_text = " ".join(block_text_lines)
                cleaned_text = _clean(raw_text)

                # Calculate block vertical center more robustly
                block_center_y = (bbox[1] + bbox[3]) / 2 if bbox else 0

                logging.debug(f"  Block {blk_idx}: BBox={bbox}, CenterY={block_center_y:.1f}, MaxSize={block_max_fsize:.1f}, Bold={block_is_bold}, Italic={block_is_italic}, Text='{cleaned_text[:80]}...'")

                if not cleaned_text or RE_ONLY_DIG.match(cleaned_text):
                    logging.debug(f"    -> Skipping block (empty or only digits).")
                    continue

                # --- HEADING CHECK - START WITH FALSE, REQUIRE POSITIVE MATCH ---
                is_this_block_a_heading = False
                rejection_reason = "Did not meet positive criteria" # Default reason

                # 1. PRE-FILTER: Check if definitely NOT a heading (e.g., in margin, too small)
                if block_center_y < header_zone_end_y or block_center_y > footer_zone_start_y:
                    rejection_reason = f"In margin zone (Center Y: {block_center_y:.1f})"
                    logging.debug(f"    -> REJECTED ({rejection_reason})")
                     # Don't check further criteria if in margin
                elif block_max_fsize < font_size_threshold:
                     rejection_reason = f"Font size {block_max_fsize:.1f} < threshold {font_size_threshold:.1f}"
                     logging.debug(f"    -> REJECTED ({rejection_reason})")
                     # Don't check further criteria if too small
                else:
                    # 2. POSITIVE CHECKS: If not pre-filtered, check if it meets *enabled* criteria
                    passes_positive_checks = True # Assume passes until a required check fails

                    if check_style:
                        if style_bold and not block_is_bold: passes_positive_checks = False; rejection_reason = "Style: Not Bold"
                        if passes_positive_checks and style_italic and not block_is_italic: passes_positive_checks = False; rejection_reason = "Style: Not Italic"

                    if passes_positive_checks and check_case:
                        # Using more lenient checks
                        text_len = len(cleaned_text.replace(" ","")) # Length without spaces
                        upper_count = sum(1 for c in cleaned_text if c.isupper())
                        is_mostly_upper = upper_count / text_len > 0.6 if text_len else False # Need > 60% upper
                        is_simple_title = cleaned_text.istitle() # Basic title check

                        if case_upper and not is_mostly_upper: passes_positive_checks = False; rejection_reason = f"Case: Not mostly UPPER ({upper_count}/{text_len})"
                        elif passes_positive_checks and case_title and not is_simple_title: passes_positive_checks = False; rejection_reason = "Case: Not Title Case"

                    if passes_positive_checks and check_layout:
                        if layout_centered:
                            page_center_x = page_width / 2
                            block_center_x = (bbox[0] + bbox[2]) / 2
                            allowed_delta = page_width * CENTERING_TOLERANCE
                            if abs(block_center_x - page_center_x) > allowed_delta:
                                passes_positive_checks = False; rejection_reason = f"Layout: Not Centered (Delta: {abs(block_center_x - page_center_x):.1f} > {allowed_delta:.1f})"

                    if passes_positive_checks and check_word_count:
                        word_count = len(cleaned_text.split())
                        if not (wc_min <= word_count <= wc_max):
                            passes_positive_checks = False; rejection_reason = f"Word Count: {word_count} not in [{wc_min}-{wc_max}]"

                    if passes_positive_checks and check_pattern and pattern_regex:
                        if not pattern_regex.search(cleaned_text):
                            passes_positive_checks = False; rejection_reason = f"Pattern: Regex '{pattern_regex.pattern}' not found"

                    # FINAL DECISION FOR THIS BLOCK
                    if passes_positive_checks:
                        is_this_block_a_heading = True
                        logging.info(f"    -> CONFIRMED HEADING: '{cleaned_text}'")
                    else:
                        # Log why it failed the positive checks if it wasn't rejected earlier
                        logging.debug(f"    -> REJECTED ({rejection_reason})")

                # --- Update the ongoing heading tracker ---
                block_heading_to_assign = None
                if is_this_block_a_heading:
                    block_heading_to_assign = cleaned_text
                    last_confirmed_heading = cleaned_text # Update the tracker
                # *** CRITICAL: Decide if non-heading text should inherit last heading ***
                # Option A: Only associate heading if block IS a heading (stricter)
                # sentence_heading = block_heading_to_assign
                # Option B: Associate with the last known confirmed heading (better for chapter chunking)
                sentence_heading = last_confirmed_heading


                # --- SENTENCE EXTRACTION ---
                try:
                    # Use the raw text for sentence tokenization before cleaning? Maybe not. Use cleaned.
                    sentences = nltk.sent_tokenize(cleaned_text)
                except Exception as e:
                    logging.error(f"NLTK sentence tokenization failed for block {blk_idx} on page {p + offset}: {e}. Using block as single sentence.")
                    sentences = [cleaned_text]

                for sent in sentences:
                    clean_sent = sent.strip()
                    if clean_sent:
                        # Append sentence with the chosen heading (Option B used here)
                        out.append((clean_sent, f"p{p + offset}.{blk_idx}", sentence_heading)) # Added block index to marker

        except Exception as page_err:
             logging.error(f"Failed processing page {p}: {page_err}", exc_info=True)

    doc.close()
    logging.debug(f"Extraction finished. Total items: {len(out)}")
    return out


# ─────────────────────────────────────────────
# 4. DOCX extractor (Keep previous version or apply similar debug logging if needed)
# ─────────────────────────────────────────────
# ... (_extract_docx function - can add similar DEBUG logging if DOCX also fails) ...
def _extract_docx(data: bytes, heading_criteria: Dict[str, Any]) -> List[Tuple[str, str, Optional[str]]]:
    # ... (Add logging.debug messages inside the loop similar to _extract_pdf) ...
    # --- Extract criteria ---
    check_case = heading_criteria.get('check_case', False)
    case_upper = heading_criteria.get('case_upper', False)
    case_title = heading_criteria.get('case_title', False)
    check_word_count = heading_criteria.get('check_word_count', False)
    wc_min = heading_criteria.get('word_count_min', 1)
    wc_max = heading_criteria.get('word_count_max', 999)
    check_pattern = heading_criteria.get('check_pattern', False)
    pattern_regex = heading_criteria.get('pattern_regex', None)

    doc = docx.Document(io.BytesIO(data))
    res = []
    last_confirmed_heading = None # Use same logic as PDF

    logging.debug(f"Processing DOCX. Criteria: {heading_criteria}")

    for i, para in enumerate(doc.paragraphs, 1):
        cleaned_text = _clean(para.text)
        logging.debug(f"  Para {i}: Text='{cleaned_text[:80]}...'")
        if not cleaned_text:
            logging.debug("    -> Skipping empty paragraph.")
            continue

        is_this_para_a_heading = False
        rejection_reason = "Did not meet positive criteria"
        passes_positive_checks = True

        # Apply checks similar to PDF (excluding style/layout)
        if check_case:
             text_len = len(cleaned_text.replace(" ",""))
             upper_count = sum(1 for c in cleaned_text if c.isupper())
             is_mostly_upper = upper_count / text_len > 0.6 if text_len else False
             is_simple_title = cleaned_text.istitle()
             if case_upper and not is_mostly_upper: passes_positive_checks = False; rejection_reason = f"Case: Not mostly UPPER ({upper_count}/{text_len})"
             elif passes_positive_checks and case_title and not is_simple_title: passes_positive_checks = False; rejection_reason = "Case: Not Title Case"

        if passes_positive_checks and check_word_count:
            word_count = len(cleaned_text.split())
            if not (wc_min <= word_count <= wc_max):
                passes_positive_checks = False; rejection_reason = f"Word Count: {word_count} not in [{wc_min}-{wc_max}]"

        if passes_positive_checks and check_pattern and pattern_regex:
            if not pattern_regex.search(cleaned_text):
                passes_positive_checks = False; rejection_reason = f"Pattern: Regex '{pattern_regex.pattern}' not found"

        if passes_positive_checks:
            is_this_para_a_heading = True
            logging.info(f"    -> CONFIRMED HEADING (DOCX): '{cleaned_text}'")
        else:
            logging.debug(f"    -> REJECTED ({rejection_reason})")

        # Determine heading to assign to sentences
        sentence_heading = last_confirmed_heading # Default to last known
        if is_this_para_a_heading:
             last_confirmed_heading = cleaned_text # Update tracker
             sentence_heading = cleaned_text # Assign current heading to its own sentences

        try:
            sentences = nltk.sent_tokenize(cleaned_text)
        except Exception as e:
            logging.error(f"NLTK sentence tokenization failed for para {i}: {e}. Using para as single sentence.")
            sentences = [cleaned_text]

        for sent in sentences:
             clean_sent = sent.strip()
             if clean_sent:
                res.append((clean_sent, f"para{i}", sentence_heading)) # Assign determined heading

    logging.debug(f"DOCX Extraction finished. Total items: {len(res)}")
    return res

# ─────────────────────────────────────────────
# 6. Back-compat wrapper (Keep previous version, it passes the dict)
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
    # This wrapper function implementation from the previous response is likely sufficient
    # as it focuses on preparing and passing the heading_criteria dictionary.
    # Make sure it populates 'pattern_regex' correctly if needed.
    effective_criteria = heading_criteria if heading_criteria is not None else {}
    # ... (rest of the wrapper code ensuring defaults and compiling regex if needed) ...
    if 'pattern_regex' not in effective_criteria and regex:
         try:
             # Ensure pattern_regex is stored if valid regex string provided via old param
             effective_criteria['pattern_regex'] = re.compile(regex, re.I)
             effective_criteria.setdefault('check_pattern', True) # Assume check if regex provided
         except re.error:
              logging.warning(f"Invalid fallback regex provided: {regex}")
              effective_criteria['pattern_regex'] = None
              effective_criteria.setdefault('check_pattern', False)
    elif 'pattern_regex' in effective_criteria and isinstance(effective_criteria['pattern_regex'], str):
         # Compile if the dict contains a string pattern instead of compiled
         try:
             pattern_str = effective_criteria['pattern_regex']
             effective_criteria['pattern_regex'] = re.compile(pattern_str, re.I)
             logging.debug(f"Compiled regex from criteria dict string: {pattern_str}")
         except re.error as e:
             logging.error(f"Invalid regex string in heading_criteria dict: {effective_criteria['pattern_regex']} - Error: {e}")
             effective_criteria['pattern_regex'] = None
             effective_criteria['check_pattern'] = False # Disable check if regex invalid

    effective_criteria.setdefault('check_style', False)
    # ... (set defaults for all other criteria keys) ...
    effective_criteria.setdefault('style_bold', False)
    effective_criteria.setdefault('style_italic', False)
    effective_criteria.setdefault('check_case', False)
    effective_criteria.setdefault('case_upper', False)
    effective_criteria.setdefault('case_title', False)
    effective_criteria.setdefault('check_layout', False)
    effective_criteria.setdefault('layout_centered', False)
    effective_criteria.setdefault('check_word_count', False)
    effective_criteria.setdefault('word_count_min', 1)
    effective_criteria.setdefault('word_count_max', heading_criteria.get('word_count_max', max_heading_words)) # Use dict value or fallback
    effective_criteria.setdefault('check_pattern', effective_criteria.get('pattern_regex') is not None)


    file_ext = filename.lower().rsplit(".", 1)[-1] if '.' in filename else ''

    if file_ext == "pdf":
        return _extract_pdf(data=file_content, skip_start=pdf_skip_start, skip_end=pdf_skip_end,
                            offset=pdf_first_page_offset, heading_criteria=effective_criteria,
                            header_footer_margin=0.15)
    elif file_ext == "docx":
        return _extract_docx(data=file_content, heading_criteria=effective_criteria)
    else:
        logging.error(f"Unsupported file type attempted: {filename}")
        raise ValueError(f"Unsupported file type: {filename}")
