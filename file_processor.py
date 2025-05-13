# --- START OF newCSVmaker-main/file_processor.py ---
import fitz                     # PyMuPDF
import docx, io
import re, statistics, nltk, logging
from typing import List, Tuple, Optional, Dict, Any

logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s | %(levelname)s | %(module)s:%(lineno)d | %(message)s")

# --- Constants ---
FLAG_BOLD = 1
FLAG_ITALIC = 2
CENTERING_TOLERANCE = 0.10
DEFAULT_CHAPTER_TITLE_FALLBACK = "Introduction"
DEFAULT_SUBCHAPTER_TITLE_FALLBACK = None # Or "General Text"

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
# Helper: Check if a block matches heading criteria
# ─────────────────────────────────────────────
def _matches_criteria(text: str, block_props: Dict[str, Any], criteria: Dict[str, Any], page_width: float) -> Tuple[bool, str]:
    """Checks if text/block properties match given criteria."""
    if not criteria: return False, "No criteria provided"

    # Font Size (Primary for PDF)
    if criteria.get('check_font_props') and criteria.get('min_font_size', 0.0) > 0.0:
        if block_props.get('max_fsize', 0.0) < criteria['min_font_size']:
            return False, f"Font size {block_props.get('max_fsize', 0.0):.1f} < min {criteria['min_font_size']:.1f}"

    # Font Names (Primary for PDF)
    if criteria.get('check_font_props') and criteria.get('font_names'):
        block_fonts = block_props.get('fonts', set())
        # Check if any of the block's fonts are in the criteria's list of allowed fonts
        # Or, if the criteria list specifies fonts that *must* be present.
        # Simple check: if any required font is found. More complex logic (all must match, etc.) could be added.
        if not any(f_name in block_fonts for f_name in criteria['font_names']):
             return False, f"Font names {block_fonts} not in {criteria['font_names']}"


    # Style (Bold/Italic)
    if criteria.get('check_style'):
        if criteria.get('style_bold') and not block_props.get('is_bold', False):
            return False, "Style: Not Bold"
        if criteria.get('style_italic') and not block_props.get('is_italic', False):
            return False, "Style: Not Italic"

    # Text Case
    if criteria.get('check_case'):
        text_len = len(text.replace(" ","")); upper_count = sum(1 for c in text if c.isupper())
        is_mostly_upper = upper_count / text_len > 0.6 if text_len else False
        is_simple_title = text.istitle()
        if criteria.get('case_upper') and not is_mostly_upper:
            return False, f"Case: Not mostly UPPER ({upper_count}/{text_len})"
        if criteria.get('case_title') and not is_simple_title: # only check if not already failed by case_upper
            return False, "Case: Not Title Case"

    # Layout (Centered, Alone - PDF specific)
    if criteria.get('check_layout'):
        if criteria.get('layout_centered'):
            page_center_x = page_width / 2
            block_center_x = (block_props.get('bbox', [0,0,0,0])[0] + block_props.get('bbox', [0,0,0,0])[2]) / 2
            allowed_delta = page_width * CENTERING_TOLERANCE
            if abs(block_center_x - page_center_x) > allowed_delta:
                return False, f"Layout: Not Centered (Delta: {abs(block_center_x - page_center_x):.1f})"
        # 'layout_alone' check is tricky here as it depends on context (e.g. number of lines in block for PDF)
        # For PDF, it means the block usually has few lines.
        # For DOCX, it means the paragraph is standalone.
        # This check is better handled within the specific extractor.

    # Word Count
    if criteria.get('check_word_count'):
        word_count = len(text.split())
        min_w = criteria.get('word_count_min', 1)
        max_w = criteria.get('word_count_max', 999)
        if not (min_w <= word_count <= max_w):
            return False, f"Word Count: {word_count} not in [{min_w}-{max_w}]"

    # Regex Pattern
    if criteria.get('check_pattern') and criteria.get('pattern_regex'):
        if not criteria['pattern_regex'].search(text):
            return False, f"Pattern: Regex '{criteria['pattern_regex'].pattern}' not found"

    return True, "Matches criteria"


# ─────────────────────────────────────────────
# 3. PDF extractor
# ─────────────────────────────────────────────
def _extract_pdf(data: bytes,
                 skip_start: int, skip_end: int, offset: int,
                 heading_criteria: Dict[str, Dict[str, Any]], # Contains 'chapter' and 'sub_chapter' criteria
                 header_footer_margin: float = 0.15
                 ) -> List[Tuple[str, str, str, Optional[str], Optional[str]]]:
    # OUTPUT: (sentence, marker, block_type, chapter_title, sub_chapter_title)

    doc = None
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        logging.error(f"Failed to open PDF stream: {e}", exc_info=True)
        return []

    pdf_page_count = doc.page_count
    start_page = max(0, min(skip_start, pdf_page_count))
    end_page = max(start_page, min(pdf_page_count - skip_end, pdf_page_count))
    pages = range(start_page, end_page)
    logging.info(f"PDF has {pdf_page_count} pages. Processing pages {start_page} to {end_page - 1} (indices).")

    if not pages:
        logging.warning("Page range is empty. No pages to process.")
        if doc: doc.close()
        return []

    # Automatic font size threshold (can be a fallback or supplementary info)
    # sizes = []
    # for p_idx in pages:
    #     page_blocks = doc.load_page(p_idx).get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]
    #     for blk in page_blocks:
    #         if blk.get("type") == 0 and "lines" in blk:
    #             for ln in blk["lines"]:
    #                 if "spans" in ln:
    #                     for sp in ln["spans"]: sizes.append(sp["size"])
    # font_size_threshold_auto = statistics.mean(sizes) + statistics.pstdev(sizes) * 0.5 if sizes else 12
    # logging.info(f"Auto font size threshold: {font_size_threshold_auto:.2f} (used as fallback if specific criteria not met)")

    ch_criteria = heading_criteria.get("chapter", {})
    sch_criteria = heading_criteria.get("sub_chapter", {})

    out: List[Tuple[str, str, str, Optional[str], Optional[str]]] = []
    current_chapter_title = DEFAULT_CHAPTER_TITLE_FALLBACK
    current_sub_chapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK

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
                 logging.debug(f"Page {p + offset}: No text blocks found.")
                 continue

            for blk_idx, blk in enumerate(page_blocks):
                if blk.get("type") != 0 or "lines" not in blk: continue

                bbox = blk.get("bbox")
                if not bbox:
                     logging.warning(f"Block {blk_idx} on page {p+offset} missing bbox.")
                     continue

                block_text_lines = []
                block_max_fsize = 0.0
                block_is_bold = False
                block_is_italic = False
                block_font_names = set() # Store all font names in the block

                for ln in blk["lines"]:
                    line_text_parts = []
                    if "spans" in ln:
                        for sp in ln["spans"]:
                            line_text_parts.append(sp["text"])
                            block_max_fsize = max(block_max_fsize, sp["size"])
                            if sp["flags"] & FLAG_BOLD: block_is_bold = True
                            if sp["flags"] & FLAG_ITALIC: block_is_italic = True
                            block_font_names.add(sp["font"]) # Add font name
                    line_text = "".join(line_text_parts)
                    if line_text.strip(): block_text_lines.append(line_text)

                if not block_text_lines: continue

                raw_text = " ".join(block_text_lines)
                cleaned_text = _clean(raw_text)
                marker = f"p{p + offset}.{blk_idx}"

                logging.debug(f"  Block {blk_idx} [{marker}]: BBox={bbox}, MaxSize={block_max_fsize:.1f}, Fonts={block_font_names}, Bold={block_is_bold}, Italic={block_is_italic}, Text='{cleaned_text[:60]}...'")

                if not cleaned_text or RE_ONLY_DIG.match(cleaned_text):
                    logging.debug(f"    -> Skipping block (empty/digits).")
                    continue

                block_props = {
                    'max_fsize': block_max_fsize,
                    'is_bold': block_is_bold,
                    'is_italic': block_is_italic,
                    'fonts': block_font_names,
                    'bbox': bbox,
                    'num_lines': len(block_text_lines)
                }

                block_type = "body" # Default
                assigned_chapter_for_block = current_chapter_title
                assigned_sub_chapter_for_block = current_sub_chapter_title

                # 1. Positional Check (Header/Footer)
                block_center_y = (bbox[1] + bbox[3]) / 2
                if block_center_y < header_zone_end_y:
                    block_type = "header"
                    logging.debug(f"    -> Classified as HEADER (Y: {block_center_y:.1f})")
                elif block_center_y > footer_zone_start_y:
                    block_type = "footer"
                    logging.debug(f"    -> Classified as FOOTER (Y: {block_center_y:.1f})")
                else:
                    # 2. Heading Checks (if not header/footer)
                    is_chapter, ch_reason = _matches_criteria(cleaned_text, block_props, ch_criteria, page_width)
                    if ch_criteria.get('check_layout') and ch_criteria.get('layout_alone') and block_props['num_lines'] > 3: # Example for 'alone'
                        is_chapter = False; ch_reason += "; Not alone (many lines)"


                    if is_chapter:
                        block_type = "chapter_heading"
                        current_chapter_title = cleaned_text
                        current_sub_chapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK # Reset sub-chapter on new chapter
                        assigned_chapter_for_block = current_chapter_title
                        assigned_sub_chapter_for_block = current_sub_chapter_title
                        logging.info(f"    -> Classified as CHAPTER HEADING: '{cleaned_text}' (Reason: {ch_reason})")
                    else: # Not a chapter, check for sub-chapter
                        logging.debug(f"    -> Not chapter (Reason: {ch_reason}). Checking sub-chapter...")
                        is_sub_chapter, sch_reason = _matches_criteria(cleaned_text, block_props, sch_criteria, page_width)
                        if sch_criteria.get('check_layout') and sch_criteria.get('layout_alone') and block_props['num_lines'] > 5:
                             is_sub_chapter = False; sch_reason += "; Not alone (sub, many lines)"


                        if is_sub_chapter:
                            block_type = "sub_chapter_heading"
                            current_sub_chapter_title = cleaned_text
                            # Chapter title remains the current one
                            assigned_sub_chapter_for_block = current_sub_chapter_title
                            logging.info(f"    -> Classified as SUB-CHAPTER HEADING: '{cleaned_text}' (Reason: {sch_reason})")
                        else:
                            block_type = "body" # Confirmed body
                            logging.debug(f"    -> Classified as BODY (Reason: {sch_reason})")


                # Sentence Extraction from the block
                try:
                    sentences = nltk.sent_tokenize(cleaned_text)
                    if not sentences and cleaned_text: sentences = [cleaned_text]
                except Exception as e:
                    logging.error(f"NLTK sentence tokenization failed for block {blk_idx} pg {p + offset}: {e}", exc_info=True)
                    sentences = [cleaned_text] if cleaned_text else []

                for sent_idx, sent_text in enumerate(sentences):
                    clean_sent = sent_text.strip()
                    if clean_sent:
                        # For heading blocks, all sentences within them get marked with that heading.
                        # For body blocks, they inherit the last known headings.
                        final_sent_marker = f"{marker}.s{sent_idx}"
                        out.append((clean_sent, final_sent_marker, block_type,
                                    assigned_chapter_for_block, # The chapter active for this block
                                    assigned_sub_chapter_for_block # The sub-chapter active for this block
                                   ))
        except Exception as page_err:
             logging.error(f"FATAL: Failed processing page {p} (Index): {page_err}", exc_info=True)

    if doc: doc.close()
    logging.info(f"PDF Extraction finished. Total 5-tuple items: {len(out)}")
    return out


# ─────────────────────────────────────────────
# 4. DOCX extractor
# ─────────────────────────────────────────────
def _extract_docx(data: bytes,
                  heading_criteria: Dict[str, Dict[str, Any]]
                  ) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    # OUTPUT: (sentence, marker, chapter_title, sub_chapter_title)
    # Note: DOCX font property detection is less direct. We'll primarily use patterns.

    ch_criteria = heading_criteria.get("chapter", {})
    sch_criteria = heading_criteria.get("sub_chapter", {})

    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as e:
        logging.error(f"Failed to open DOCX stream: {e}", exc_info=True)
        return []

    res: List[Tuple[str, str, Optional[str], Optional[str]]] = []
    current_chapter_title = DEFAULT_CHAPTER_TITLE_FALLBACK
    current_sub_chapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK

    logging.debug(f"Processing DOCX. Chapter Criteria: {ch_criteria}, Sub-Chapter Criteria: {sch_criteria}")

    for i, para in enumerate(doc.paragraphs, 1):
        cleaned_text = _clean(para.text)
        marker = f"para{i}"
        logging.debug(f"  Para {i} [{marker}]: Text='{cleaned_text[:60]}...'")
        if not cleaned_text:
            logging.debug("    -> Skipping empty paragraph.")
            continue

        # DOCX block properties (simplified for now)
        # Font size/name for DOCX is complex (run-level).
        # For now, rely more on patterns and word counts for DOCX.
        # A more advanced DOCX parser would inspect paragraph styles or dominant run properties.
        para_props = {} # Placeholder for future DOCX style analysis
        page_width_docx_mock = 600 # Mock value, as page width isn't directly used for DOCX criteria here

        is_chapter, ch_reason = _matches_criteria(cleaned_text, para_props, ch_criteria, page_width_docx_mock)
        if is_chapter:
            current_chapter_title = cleaned_text
            current_sub_chapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK # Reset
            logging.info(f"    -> DOCX Classified as CHAPTER HEADING: '{cleaned_text}' (Reason: {ch_reason})")
        else:
            logging.debug(f"    -> DOCX Not chapter (Reason: {ch_reason}). Checking sub-chapter...")
            is_sub_chapter, sch_reason = _matches_criteria(cleaned_text, para_props, sch_criteria, page_width_docx_mock)
            if is_sub_chapter:
                current_sub_chapter_title = cleaned_text
                logging.info(f"    -> DOCX Classified as SUB-CHAPTER HEADING: '{cleaned_text}' (Reason: {sch_reason})")
            else:
                 logging.debug(f"    -> DOCX Classified as BODY (Reason: {sch_reason})")


        try:
            sentences = nltk.sent_tokenize(cleaned_text)
            if not sentences and cleaned_text: sentences = [cleaned_text]
        except Exception as e:
            logging.error(f"NLTK sentence tokenization failed for para {i}: {e}", exc_info=True)
            sentences = [cleaned_text] if cleaned_text else []

        for sent_idx, sent_text in enumerate(sentences):
             clean_sent = sent_text.strip()
             if clean_sent:
                final_sent_marker = f"{marker}.s{sent_idx}"
                res.append((clean_sent, final_sent_marker, current_chapter_title, current_sub_chapter_title))

    logging.info(f"DOCX Extraction finished. Total 4-tuple items: {len(res)}")
    return res


# ─────────────────────────────────────────────
# 6. Main extraction wrapper (called by app.py)
# ─────────────────────────────────────────────
def extract_sentences_with_structure(*,
                                     file_content: bytes,
                                     filename: str,
                                     pdf_skip_start: int = 0,
                                     pdf_skip_end: int = 0,
                                     pdf_first_page_offset: int = 1,
                                     heading_criteria: Dict[str, Dict[str, Any]] # Expects {"chapter": {...}, "sub_chapter": {...}}
                                     ) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    """
    Wrapper to call appropriate extractor and normalize output.
    Returns: List of (sentence, marker, chapter_title, sub_chapter_title) tuples.
    """
    file_ext = ""
    if isinstance(filename, str) and '.' in filename:
         file_ext = filename.lower().rsplit(".", 1)[-1]
    else:
         logging.error(f"Invalid or extensionless filename: {filename}")
         raise ValueError("Invalid or extensionless filename")

    # Ensure criteria dictionaries exist and compile regex if provided as string
    for key_type in ["chapter", "sub_chapter"]:
        criteria_set = heading_criteria.get(key_type, {})
        if criteria_set.get('check_pattern') and isinstance(criteria_set.get('pattern_regex_str'), str) and criteria_set.get('pattern_regex_str'):
            try:
                criteria_set['pattern_regex'] = re.compile(criteria_set['pattern_regex_str'], re.IGNORECASE)
                logging.debug(f"Compiled {key_type} regex: {criteria_set['pattern_regex_str']}")
            except re.error as e:
                logging.error(f"Invalid {key_type} regex string: {criteria_set['pattern_regex_str']} - Error: {e}")
                criteria_set['pattern_regex'] = None
                criteria_set['check_pattern'] = False # Disable if regex invalid
        elif not criteria_set.get('pattern_regex_str'):
             criteria_set['pattern_regex'] = None # Ensure it's None if empty string

        heading_criteria[key_type] = criteria_set # Update main dict


    output_data: List[Tuple[str, str, Optional[str], Optional[str]]] = []

    if file_ext == "pdf":
        # _extract_pdf returns List[Tuple[str, str, str, Optional[str], Optional[str]]]
        # (sentence, marker, block_type, chapter_title, sub_chapter_title)
        extracted_raw_pdf = _extract_pdf(data=file_content,
                                         skip_start=pdf_skip_start,
                                         skip_end=pdf_skip_end,
                                         offset=pdf_first_page_offset,
                                         heading_criteria=heading_criteria,
                                         header_footer_margin=0.15)
        # Convert 5-tuples to 4-tuples by discarding block_type
        for item in extracted_raw_pdf:
            if len(item) == 5:
                # Discard block_type (item[2]), keep sentence, marker, chapter, sub_chapter
                # (item[0]=sentence, item[1]=marker, item[3]=chapter, item[4]=sub_chapter)
                if item[2] not in ["header", "footer"]: # Filter out headers/footers
                    output_data.append((item[0], item[1], item[3], item[4]))
            else:
                logging.warning(f"PDF extractor returned unexpected item: {item}")

    elif file_ext == "docx":
        # _extract_docx returns List[Tuple[str, str, Optional[str], Optional[str]]]
        output_data = _extract_docx(data=file_content,
                                    heading_criteria=heading_criteria)
    else:
        logging.error(f"Unsupported file type: {filename}")
        raise ValueError(f"Unsupported file type: {file_ext}")

    logging.info(f"Wrapper returning {len(output_data)} items (sentence, marker, chapter, sub_chapter).")
    return output_data

# --- END OF newCSVmaker-main/file_processor.py ---
