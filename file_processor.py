# --- file_processor.py ---
# [Keep imports, constants, helpers as before]
import fitz, docx, io, re, statistics, nltk, logging
from typing import List, Tuple, Optional, Dict, Any

# Ensure DEBUG level is set for detailed logs
logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s | %(levelname)s | %(module)s:%(lineno)d | %(message)s")

# ... (Keep FLAG_BOLD, FLAG_ITALIC, CENTERING_TOLERANCE, _clean, _basic_heading_check) ...

# ─────────────────────────────────────────────
# 3. PDF extractor (Refactored with Block Type)
# ─────────────────────────────────────────────
def _extract_pdf(data: bytes,
                 skip_start: int, skip_end: int, offset: int,
                 heading_criteria: Dict[str, Any],
                 header_footer_margin: float = 0.15
                 ) -> List[Tuple[str, str, str, Optional[str]]]: # OUTPUT CHANGED: (sentence, marker, block_type, heading_text)

    doc = fitz.open(stream=data, filetype="pdf")
    # --- Page range calculation ---
    pdf_page_count = doc.page_count
    start_page = max(0, min(skip_start, pdf_page_count)) # Ensure start is not negative or beyond total pages
    end_page = max(start_page, min(pdf_page_count - skip_end, pdf_page_count)) # Ensure end is valid and not before start
    pages = range(start_page, end_page)
    logging.info(f"PDF has {pdf_page_count} pages. Processing pages {start_page} to {end_page - 1} (indices).")

    if not pages:
        logging.warning("Page range is empty after applying skip settings. No pages to process.")
        doc.close()
        return []
    # --- End Page Range ---

    # --- Font Size Threshold Calculation (Keep as before) ---
    # ... (Calculate font_size_threshold) ...
    sizes = []
    try:
        for p_idx in pages:
             # No need for boundary check here as 'pages' range is already validated
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
    check_style = heading_criteria.get('check_style', False); style_bold = heading_criteria.get('style_bold', False); style_italic = heading_criteria.get('style_italic', False)
    check_case = heading_criteria.get('check_case', False); case_upper = heading_criteria.get('case_upper', False); case_title = heading_criteria.get('case_title', False)
    check_layout = heading_criteria.get('check_layout', False); layout_centered = heading_criteria.get('layout_centered', False)
    check_word_count = heading_criteria.get('check_word_count', False); wc_min = heading_criteria.get('word_count_min', 1); wc_max = heading_criteria.get('word_count_max', 999)
    check_pattern = heading_criteria.get('check_pattern', False); pattern_regex = heading_criteria.get('pattern_regex', None)

    # --- Main Processing Loop ---
    # OUTPUT STRUCTURE: List of (sentence_text, marker, block_type, assigned_heading_text)
    # block_type can be 'header', 'footer', 'heading', 'body'
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

                bbox = blk["bbox"]
                # Extract block properties (same as before)
                # ... (extract block_text_lines, block_max_fsize, block_is_bold, block_is_italic) ...
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
                is_potential_heading = True # Assume could be heading unless disqualified

                # 1. Positional Check (Header/Footer)
                block_center_y = (bbox[1] + bbox[3]) / 2 if bbox else 0
                if block_center_y < header_zone_end_y:
                    block_type = "header"
                    is_potential_heading = False # Headers/footers are not headings
                    logging.debug(f"    -> Classified as HEADER (Center Y: {block_center_y:.1f})")
                elif block_center_y > footer_zone_start_y:
                    block_type = "footer"
                    is_potential_heading = False
                    logging.debug(f"    -> Classified as FOOTER (Center Y: {block_center_y:.1f})")

                # 2. Heading Check (Only if block_type is still 'body')
                if is_potential_heading:
                    rejection_reason = "Did not meet positive criteria"
                    passes_heading_checks = True # Assume passes until proven otherwise

                    # Check font size first
                    if block_max_fsize < font_size_threshold:
                        passes_heading_checks = False; rejection_reason = f"Font size {block_max_fsize:.1f} < threshold {font_size_threshold:.1f}"
                    else:
                        # Apply other enabled criteria (Style, Case, Layout, WC, Pattern)
                        # ... (Use the same sequential checks as the previous version) ...
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

                    # Final decision on heading status
                    if passes_heading_checks:
                        block_type = "heading"
                        block_heading_text = cleaned_text
                        last_confirmed_heading = cleaned_text # Update tracker
                        logging.info(f"    -> Classified as HEADING: '{cleaned_text}'")
                    else:
                        # It remains 'body'
                        logging.debug(f"    -> Classified as BODY (Rejected as heading: {rejection_reason})")

                # --- Determine heading text to assign to sentences ---
                # Assign the last known good heading, unless the current block *is* the heading
                assigned_heading = last_confirmed_heading
                if block_type == "heading":
                    assigned_heading = block_heading_text # Use its own text

                # --- SENTENCE EXTRACTION ---
                try:
                    sentences = nltk.sent_tokenize(cleaned_text)
                    if not sentences:
                         logging.debug(f"    -> NLTK tokenization resulted in 0 sentences for: '{cleaned_text[:50]}...'")
                         if cleaned_text: sentences = [cleaned_text] # Fallback if tokenization fails but text exists
                except Exception as e:
                    logging.error(f"NLTK sentence tokenization failed for block {blk_idx} on page {p + offset}: {e}. Using block as single sentence.")
                    sentences = [cleaned_text] if cleaned_text else []

                # Append sentences with the new structure
                for sent in sentences:
                    clean_sent = sent.strip()
                    if clean_sent:
                         # Append: (sentence, marker, block_type, assigned_heading)
                         out.append((clean_sent, marker, block_type, assigned_heading))

        except Exception as page_err:
             logging.error(f"FATAL: Failed processing page {p} (Index): {page_err}", exc_info=True)
             # Optionally continue to next page, or re-raise

    doc.close()
    logging.info(f"Extraction finished. Total sentence items generated: {len(out)}")
    if not out:
        logging.warning("The extraction process resulted in zero output items.")
    return out


# --- Wrapper Function (`extract_sentences_with_structure`) ---
# Needs to be updated slightly if the return type annotation changes,
# but the core logic of preparing and passing `heading_criteria` remains the same.
# The previous version of the wrapper should still work.

# --- DOCX Extractor (`_extract_docx`) ---
# Should ideally be updated to also return the 4-tuple format (block_type will likely always be 'body' or 'heading')
# For brevity, this is omitted here, but apply similar logic if DOCX processing is important.
