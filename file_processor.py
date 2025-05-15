import docx
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io
import re # Keep for _clean, even if not for heading patterns
import nltk
import logging
from typing import List, Tuple, Optional, Dict, Any

logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s | %(levelname)s | %(module)s:%(lineno)d | %(message)s")

DEFAULT_CHAPTER_TITLE_FALLBACK = "Introduction"
DEFAULT_SUBCHAPTER_TITLE_FALLBACK = None

RE_WS = re.compile(r"\s+")

def _clean(raw: str) -> str:
    txt = raw.replace("\n", " ")
    return RE_WS.sub(" ", txt).strip()

def _matches_criteria_docx(text: str, para_props: Dict[str, Any], criteria: Dict[str, Any]) -> Tuple[bool, str]:
    if not criteria: # If criteria dict is empty (e.g., sub-chapter detection disabled)
        return False, "No criteria provided (detection likely disabled for this type)"
    
    rejection_reason = "Did not meet positive criteria"
    passes_all_enabled_checks = True

    # Font Properties
    if criteria.get('check_font_props'):
        if criteria.get('min_font_size', 0.0) > 0.0 and para_props.get('max_fsize_pt', 0.0) < criteria['min_font_size']:
            rejection_reason = f"Font size {para_props.get('max_fsize_pt', 0.0):.1f}pt < min {criteria['min_font_size']:.1f}pt"
            passes_all_enabled_checks = False
        if passes_all_enabled_checks and criteria.get('font_names'): # List of font names
            if not any(fn in para_props.get('font_names_in_para', set()) for fn in criteria['font_names']):
                 rejection_reason = f"Para fonts {para_props.get('font_names_in_para', set())} not in required {criteria['font_names']}"
                 passes_all_enabled_checks = False
        if passes_all_enabled_checks and criteria.get('style_bold') and not para_props.get('is_bold_present', False):
            rejection_reason = "Style: Not Bold"
            passes_all_enabled_checks = False
        if passes_all_enabled_checks and criteria.get('style_italic') and not para_props.get('is_italic_present', False):
            rejection_reason = "Style: Not Italic"
            passes_all_enabled_checks = False

    # Text Case
    if passes_all_enabled_checks and criteria.get('check_case'):
        non_space_text = "".join(text.split())
        actual_is_all_caps = non_space_text.isupper() if non_space_text else False
        is_simple_title = text.istitle() # Original text for istitle()

        if criteria.get('case_upper') and not actual_is_all_caps:
            rejection_reason = f"Case: Not ALL CAPS (Text: '{text[:30]}...')"
            passes_all_enabled_checks = False
        # Check Title Case only if ALL CAPS wasn't required or if it passed ALL CAPS (e.g. "CHAPTER ONE" is both)
        # This 'elif' means Title Case is only a failing reason if ALL CAPS wasn't the primary required case that failed.
        elif passes_all_enabled_checks and criteria.get('case_title') and not is_simple_title:
            rejection_reason = "Case: Not Title Case"
            passes_all_enabled_checks = False

    # Word Count
    if passes_all_enabled_checks and criteria.get('check_word_count'):
        word_count = len(text.split())
        min_w, max_w = criteria.get('word_count_min', 1), criteria.get('word_count_max', 999)
        if not (min_w <= word_count <= max_w):
            rejection_reason = f"Word Count: {word_count} not in [{min_w}-{max_w}]"
            passes_all_enabled_checks = False

    # Alignment Check
    if passes_all_enabled_checks and criteria.get('check_alignment'):
        if criteria.get('alignment_centered') and para_props.get('alignment') != WD_ALIGN_PARAGRAPH.CENTER:
            # Provide more context for alignment failure
            align_val = para_props.get('alignment')
            align_str = str(align_val) # Default to string value
            if align_val == WD_ALIGN_PARAGRAPH.LEFT: align_str = "LEFT"
            elif align_val == WD_ALIGN_PARAGRAPH.RIGHT: align_str = "RIGHT"
            elif align_val == WD_ALIGN_PARAGRAPH.JUSTIFY: align_str = "JUSTIFY"
            elif align_val is None: align_str = "NOT SET (likely LEFT)"
            rejection_reason = f"Alignment: Not Centered (Actual: {align_str})"
            passes_all_enabled_checks = False

    return (True, "Matches DOCX criteria") if passes_all_enabled_checks else (False, rejection_reason)


def _extract_docx(data: bytes, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    ch_criteria = heading_criteria.get("chapter", {})
    sch_criteria = heading_criteria.get("sub_chapter", {}) # This will be {} if sub-chapter detection is disabled via app.py

    try: doc = docx.Document(io.BytesIO(data))
    except Exception as e:
        logging.error(f"Failed to open DOCX stream: {e}", exc_info=True)
        return []

    res: List[Tuple[str, str, Optional[str], Optional[str]]] = []
    current_chapter_title = DEFAULT_CHAPTER_TITLE_FALLBACK
    current_sub_chapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK

    logging.debug(f"DOCX Processing: ChCrit Enabled={bool(ch_criteria)}, SubChCrit Enabled={bool(sch_criteria)}")
    if ch_criteria: logging.debug(f"Chapter Criteria: {ch_criteria}")
    if sch_criteria: logging.debug(f"Sub-Chapter Criteria: {sch_criteria}")


    for i, para in enumerate(doc.paragraphs, 1):
        cleaned_text = _clean(para.text)
        marker = f"para{i}"
        if not cleaned_text: continue

        para_is_bold, para_is_italic, para_max_fsize_pt = False, False, 0.0
        para_fonts = set()
        para_align = para.alignment # Get paragraph alignment, can be None

        if para.runs:
            for run in para.runs:
                if run.text.strip(): # Consider runs with actual text
                    if run.bold: para_is_bold = True
                    if run.italic: para_is_italic = True
                    if run.font.size:
                        try: para_max_fsize_pt = max(para_max_fsize_pt, run.font.size.pt)
                        except AttributeError: pass # run.font.size might be None
                    if run.font.name: para_fonts.add(run.font.name)
        
        para_props = {
            'is_bold_present': para_is_bold, 'is_italic_present': para_is_italic,
            'max_fsize_pt': para_max_fsize_pt, 'font_names_in_para': para_fonts,
            'alignment': para_align,
        }

        # Check for Chapter Heading
        is_chapter, ch_reason = False, "Chapter criteria not checked or not met"
        if ch_criteria : # Only check if chapter criteria are provided
             is_chapter, ch_reason = _matches_criteria_docx(cleaned_text, para_props, ch_criteria)
        
        if is_chapter:
            current_chapter_title = cleaned_text
            current_sub_chapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK # Reset sub-chapter
            logging.info(f"  P{i} [{marker}]: CHAPTER: '{cleaned_text[:50]}' (Criteria: {ch_reason})")
        else:
            # Check for Sub-Chapter Heading only if it's not a chapter AND sub-chapter criteria are enabled
            is_sub_chapter, sch_reason = False, "Sub-chapter criteria not checked or not met"
            if sch_criteria: # Only check if sub_chapter criteria are provided/enabled
                is_sub_chapter, sch_reason = _matches_criteria_docx(cleaned_text, para_props, sch_criteria)
            
            if is_sub_chapter:
                current_sub_chapter_title = cleaned_text
                logging.info(f"  P{i} [{marker}]: SUB-CHAPTER: '{cleaned_text[:50]}' (Criteria: {sch_reason})")
            # else: # Paragraph is body text
                # logging.debug(f"  P{i} [{marker}]: BODY (NotCh: '{ch_reason}', NotSubCh: '{sch_reason}') Text: '{cleaned_text[:30]}...'")


        try:
            sentences = nltk.sent_tokenize(cleaned_text)
            if not sentences and cleaned_text: sentences = [cleaned_text]
        except Exception as e:
            logging.error(f"NLTK tokenization failed P{i}: {e}", exc_info=True)
            sentences = [cleaned_text] if cleaned_text else []

        for sent_idx, sent_text in enumerate(sentences):
             clean_sent = sent_text.strip()
             if clean_sent:
                res.append((clean_sent, f"{marker}.s{sent_idx}", current_chapter_title, current_sub_chapter_title))

    logging.info(f"DOCX Extraction finished. Items: {len(res)}")
    return res

def extract_sentences_with_structure(*, file_content: bytes, filename: str, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    file_ext = filename.lower().rsplit(".", 1)[-1] if isinstance(filename, str) and '.' in filename else ""
    if not file_ext: raise ValueError("Invalid or extensionless filename")
    if file_ext != "docx": raise ValueError(f"Unsupported file type: {file_ext}. Expected DOCX.")
            
    output_data = _extract_docx(data=file_content, heading_criteria=heading_criteria)
    logging.info(f"Wrapper returning {len(output_data)} items from DOCX.")
    return output_data
