import docx # For DOCX
from docx.shared import Pt # For font size in points
import io
import re
import nltk
import logging
from typing import List, Tuple, Optional, Dict, Any

logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s | %(levelname)s | %(module)s:%(lineno)d | %(message)s")

# --- Constants ---
DEFAULT_CHAPTER_TITLE_FALLBACK = "Introduction"
DEFAULT_SUBCHAPTER_TITLE_FALLBACK = None

# ─────────────────────────────────────────────
# 1. Whitespace cleaner
# ─────────────────────────────────────────────
RE_WS = re.compile(r"\s+")

def _clean(raw: str) -> str:
    txt = raw.replace("\n", " ")
    return RE_WS.sub(" ", txt).strip()

# ─────────────────────────────────────────────
# Helper: Check if a paragraph matches heading criteria (DOCX focused)
# ─────────────────────────────────────────────
def _matches_criteria_docx(text: str, para_props: Dict[str, Any], criteria: Dict[str, Any]) -> Tuple[bool, str]:
    """Checks if text/paragraph properties match given criteria for DOCX."""
    if not criteria: return False, "No criteria provided"
    rejection_reason = "Did not meet positive criteria" # Default
    passes_all_enabled_checks = True

    # Font Properties
    if criteria.get('check_font_props'):
        if criteria.get('min_font_size', 0.0) > 0.0:
            if para_props.get('max_fsize_pt', 0.0) < criteria['min_font_size']:
                rejection_reason = f"Font size {para_props.get('max_fsize_pt', 0.0):.1f}pt < min {criteria['min_font_size']:.1f}pt"
                passes_all_enabled_checks = False
        if passes_all_enabled_checks and criteria.get('font_names'):
            para_font_names_set = para_props.get('font_names_in_para', set())
            if not any(fn in para_font_names_set for fn in criteria['font_names']):
                 rejection_reason = f"Para fonts {para_font_names_set} not in required {criteria['font_names']}"
                 passes_all_enabled_checks = False
        if passes_all_enabled_checks and criteria.get('style_bold') and not para_props.get('is_bold_present', False):
            rejection_reason = "Style: Not Bold"
            passes_all_enabled_checks = False
        if passes_all_enabled_checks and criteria.get('style_italic') and not para_props.get('is_italic_present', False):
            rejection_reason = "Style: Not Italic"
            passes_all_enabled_checks = False
    
    # Text Case
    if passes_all_enabled_checks and criteria.get('check_case'):
        text_len = len(text.replace(" ","")); upper_count = sum(1 for c in text if c.isupper())
        is_mostly_upper = upper_count / text_len > 0.6 if text_len else False
        is_simple_title = text.istitle()
        if criteria.get('case_upper') and not is_mostly_upper:
            rejection_reason = f"Case: Not mostly UPPER ({upper_count}/{text_len})"
            passes_all_enabled_checks = False
        elif passes_all_enabled_checks and criteria.get('case_title') and not is_simple_title: # elif, so it doesn't override previous case reason
            rejection_reason = "Case: Not Title Case"
            passes_all_enabled_checks = False

    # Word Count
    if passes_all_enabled_checks and criteria.get('check_word_count'):
        word_count = len(text.split())
        min_w = criteria.get('word_count_min', 1)
        max_w = criteria.get('word_count_max', 999)
        if not (min_w <= word_count <= max_w):
            rejection_reason = f"Word Count: {word_count} not in [{min_w}-{max_w}]"
            passes_all_enabled_checks = False

    # Regex Pattern (Only if 'check_pattern' is true and a regex object exists)
    if passes_all_enabled_checks and criteria.get('check_pattern') and criteria.get('pattern_regex'):
        if not criteria['pattern_regex'].search(text):
            rejection_reason = f"Pattern: Regex '{criteria['pattern_regex'].pattern}' not found"
            passes_all_enabled_checks = False
    elif criteria.get('check_pattern') and not criteria.get('pattern_regex'): # Checked but no valid regex
        rejection_reason = "Pattern: Check enabled but no valid regex provided"
        passes_all_enabled_checks = False


    if passes_all_enabled_checks:
        return True, "Matches DOCX criteria"
    else:
        return False, rejection_reason


# ─────────────────────────────────────────────
# 4. DOCX extractor
# ─────────────────────────────────────────────
def _extract_docx(data: bytes,
                  heading_criteria: Dict[str, Dict[str, Any]] # {"chapter": {...}, "sub_chapter": {...}}
                  ) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    # OUTPUT: (sentence, marker, chapter_title, sub_chapter_title)

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
        
        if not cleaned_text:
            logging.debug(f"  Para {i} [{marker}]: Skipping empty paragraph.")
            continue
        
        logging.debug(f"  Para {i} [{marker}]: Text='{cleaned_text[:60]}...'")

        para_is_bold_present = False
        para_is_italic_present = False
        para_max_font_size_pt = 0.0
        para_font_names_in_para = set()

        if para.runs:
            for run in para.runs:
                if run.text.strip():
                    if run.bold: para_is_bold_present = True
                    if run.italic: para_is_italic_present = True
                    if run.font.size:
                        try: para_max_font_size_pt = max(para_max_font_size_pt, run.font.size.pt)
                        except AttributeError: pass
                    if run.font.name: para_font_names_in_para.add(run.font.name)
        
        # logging.debug(f"    Para {i} Props: Bold={para_is_bold_present}, Italic={para_is_italic_present}, MaxSizePt={para_max_font_size_pt:.1f}, Fonts={para_font_names_in_para}")

        para_props_for_check = {
            'is_bold_present': para_is_bold_present,
            'is_italic_present': para_is_italic_present,
            'max_fsize_pt': para_max_font_size_pt,
            'font_names_in_para': para_font_names_in_para,
        }

        is_chapter, ch_reason = _matches_criteria_docx(cleaned_text, para_props_for_check, ch_criteria)
        if is_chapter:
            current_chapter_title = cleaned_text
            current_sub_chapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK
            logging.info(f"    -> DOCX Classified as CHAPTER HEADING: '{cleaned_text}' (Reason: {ch_reason})")
        else:
            # logging.debug(f"    -> DOCX Not chapter (Reason: {ch_reason}). Checking sub-chapter...")
            is_sub_chapter, sch_reason = _matches_criteria_docx(cleaned_text, para_props_for_check, sch_criteria)
            if is_sub_chapter:
                current_sub_chapter_title = cleaned_text
                logging.info(f"    -> DOCX Classified as SUB-CHAPTER HEADING: '{cleaned_text}' (Reason: {sch_reason})")
            # else:
                # logging.debug(f"    -> DOCX Classified as BODY (Not Chapter: '{ch_reason}', Not Sub-Chapter: '{sch_reason}')")


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

    logging.info(f"DOCX Extraction finished. Total items: {len(res)}")
    return res


# ─────────────────────────────────────────────
# 6. Main extraction wrapper (called by app.py) - DOCX only now
# ─────────────────────────────────────────────
def extract_sentences_with_structure(*,
                                     file_content: bytes,
                                     filename: str,
                                     heading_criteria: Dict[str, Dict[str, Any]]
                                     ) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    file_ext = ""
    if isinstance(filename, str) and '.' in filename:
         file_ext = filename.lower().rsplit(".", 1)[-1]
    else:
         logging.error(f"Invalid or extensionless filename: {filename}")
         raise ValueError("Invalid or extensionless filename")

    if file_ext != "docx":
        logging.error(f"Unsupported file type: {filename}. This processor is for DOCX only.")
        raise ValueError(f"Unsupported file type: {file_ext}. Expected DOCX.")

    # Compile regex for sub-chapter if provided and enabled
    sch_crit = heading_criteria.get("sub_chapter", {})
    if sch_crit.get('check_pattern') and isinstance(sch_crit.get('pattern_regex_str'), str) and sch_crit.get('pattern_regex_str'):
        try:
            sch_crit['pattern_regex'] = re.compile(sch_crit['pattern_regex_str'], re.IGNORECASE)
            logging.debug(f"Compiled sub-chapter regex: {sch_crit['pattern_regex_str']}")
        except re.error as e:
            logging.error(f"Invalid sub-chapter regex string: {sch_crit['pattern_regex_str']} - Error: {e}")
            sch_crit['pattern_regex'] = None
            sch_crit['check_pattern'] = False
    elif 'pattern_regex_str' in sch_crit: # Ensure it's None if string is empty or check_pattern is false
         sch_crit['pattern_regex'] = None
    heading_criteria["sub_chapter"] = sch_crit # Update main dict

    # Chapter criteria does not use regex anymore
    ch_crit = heading_criteria.get("chapter", {})
    ch_crit['pattern_regex'] = None
    ch_crit['check_pattern'] = False
    heading_criteria["chapter"] = ch_crit


    output_data = _extract_docx(data=file_content, heading_criteria=heading_criteria)

    logging.info(f"Wrapper returning {len(output_data)} items from DOCX.")
    return output_data

# --- END OF newCSVmaker-main/file_processor.py ---
