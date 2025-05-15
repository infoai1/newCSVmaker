import docx
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io
import re
import nltk
import logging
from typing import List, Tuple, Optional, Dict, Any

# Ensure this logger uses the config from app.py or sets its own if run standalone
# If app.py's basicConfig with force=True runs first, this module's logger will inherit that.
logger = logging.getLogger(__name__) # Use a named logger for this module
# logger.setLevel(logging.DEBUG) # This would be needed if not inheriting from root or if app.py didn't force DEBUG

DEFAULT_CHAPTER_TITLE_FALLBACK = "Introduction"
DEFAULT_SUBCHAPTER_TITLE_FALLBACK = None

RE_WS = re.compile(r"\s+")

def _clean(raw: str) -> str:
    txt = raw.replace("\n", " ")
    return RE_WS.sub(" ", txt).strip()

def _matches_criteria_docx(text: str, para_props: Dict[str, Any], criteria: Dict[str, Any], type_label: str) -> Tuple[bool, str]:
    if not criteria:
        logger.debug(f"    [{type_label}] Criteria not provided/empty. Skipping check for: '{text[:30]}...'")
        return False, "No criteria provided (detection likely disabled for this type)"

    rejection_reason = "Matches all enabled criteria"
    passes_all_enabled_checks = True

    logger.debug(f"    [{type_label}] Checking text: '{text[:40]}...' against criteria: {criteria} with props: {para_props}")

    if criteria.get('check_font_props'):
        if criteria.get('min_font_size', 0.0) > 0.0:
            if para_props.get('max_fsize_pt', 0.0) < criteria['min_font_size']:
                rejection_reason = f"Font size {para_props.get('max_fsize_pt', 0.0):.1f}pt < min {criteria['min_font_size']:.1f}pt"
                passes_all_enabled_checks = False
        if passes_all_enabled_checks and criteria.get('font_names'):
            if not any(fn in para_props.get('font_names_in_para', set()) for fn in criteria['font_names']):
                 rejection_reason = f"Para fonts {para_props.get('font_names_in_para', set())} not in required {criteria['font_names']}"
                 passes_all_enabled_checks = False
        if passes_all_enabled_checks and criteria.get('style_bold') and not para_props.get('is_bold_present', False):
            rejection_reason = "Style: Not Bold"
            passes_all_enabled_checks = False
        if passes_all_enabled_checks and criteria.get('style_italic') and not para_props.get('is_italic_present', False):
            rejection_reason = "Style: Not Italic"
            passes_all_enabled_checks = False
    else:
        logger.debug(f"    [{type_label}] Font property checks disabled by criteria for '{text[:30]}...'.")

    if passes_all_enabled_checks and criteria.get('check_case'):
        non_space_text = "".join(text.split())
        actual_is_all_caps = non_space_text.isupper() if non_space_text else False
        is_simple_title = text.istitle()

        if criteria.get('case_upper') and not actual_is_all_caps:
            rejection_reason = f"Case: Not ALL CAPS (Text: '{text[:30]}...')"
            passes_all_enabled_checks = False
        elif passes_all_enabled_checks and criteria.get('case_title') and not is_simple_title:
            rejection_reason = "Case: Not Title Case"
            passes_all_enabled_checks = False
    else:
        if criteria.get('check_case'): # Log only if check_case was true but previous checks failed
             logger.debug(f"    [{type_label}] Text case checks not performed due to prior failure or disabled by criteria for '{text[:30]}...'.")


    if passes_all_enabled_checks and criteria.get('check_word_count'):
        word_count = len(text.split())
        min_w, max_w = criteria.get('word_count_min', 1), criteria.get('word_count_max', 999)
        if not (min_w <= word_count <= max_w):
            rejection_reason = f"Word Count: {word_count} not in [{min_w}-{max_w}]"
            passes_all_enabled_checks = False
    else:
        if criteria.get('check_word_count'):
            logger.debug(f"    [{type_label}] Word count checks not performed due to prior failure or disabled by criteria for '{text[:30]}...'.")

    if passes_all_enabled_checks and criteria.get('check_alignment'):
        if criteria.get('alignment_centered') and para_props.get('alignment') != WD_ALIGN_PARAGRAPH.CENTER:
            align_val = para_props.get('alignment')
            align_str = str(align_val)
            if align_val == WD_ALIGN_PARAGRAPH.LEFT: align_str = "LEFT"
            elif align_val == WD_ALIGN_PARAGRAPH.RIGHT: align_str = "RIGHT"
            elif align_val == WD_ALIGN_PARAGRAPH.JUSTIFY: align_str = "JUSTIFY"
            elif align_val is None: align_str = "NOT SET (likely LEFT by default)"
            rejection_reason = f"Alignment: Not Centered (Actual: {align_str})"
            passes_all_enabled_checks = False
    else:
        if criteria.get('check_alignment'):
            logger.debug(f"    [{type_label}] Alignment checks not performed due to prior failure or disabled by criteria for '{text[:30]}...'.")

    if passes_all_enabled_checks:
        logger.debug(f"    [{type_label}] PASS: '{text[:30]}...' matches all enabled criteria.")
    else:
        logger.debug(f"    [{type_label}] FAIL for '{text[:30]}...': {rejection_reason}")
        
    return (True, "Matches all enabled criteria") if passes_all_enabled_checks else (False, rejection_reason)


def _extract_docx(data: bytes, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    ch_criteria = heading_criteria.get("chapter", {})
    sch_criteria = heading_criteria.get("sub_chapter", {})

    try: doc = docx.Document(io.BytesIO(data))
    except Exception as e:
        logger.error(f"Failed to open DOCX stream: {e}", exc_info=True)
        return []

    res: List[Tuple[str, str, Optional[str], Optional[str]]] = []
    current_chapter_title = DEFAULT_CHAPTER_TITLE_FALLBACK
    current_sub_chapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK

    logger.info(f"--- Starting DOCX Extraction ---")
    logger.debug(f"Chapter Criteria Enabled: {bool(ch_criteria)}. Details: {ch_criteria}")
    logger.debug(f"Sub-Chapter Criteria Enabled: {bool(sch_criteria)}. Details: {sch_criteria}")


    for i, para in enumerate(doc.paragraphs, 1):
        cleaned_text = _clean(para.text)
        marker = f"para{i}"
        if not cleaned_text: continue

        logger.debug(f"--- Para {i} [{marker}] Text: '{cleaned_text[:60]}...' ---")

        para_is_bold, para_is_italic, para_max_fsize_pt = False, False, 0.0
        para_fonts = set()
        para_align = para.alignment

        if para.runs:
            for run in para.runs:
                if run.text.strip():
                    if run.bold: para_is_bold = True
                    if run.italic: para_is_italic = True
                    if run.font.size:
                        try: para_max_fsize_pt = max(para_max_fsize_pt, run.font.size.pt)
                        except AttributeError: pass
                    if run.font.name: para_fonts.add(run.font.name)
        
        para_props = {
            'is_bold_present': para_is_bold, 'is_italic_present': para_is_italic,
            'max_fsize_pt': para_max_fsize_pt, 'font_names_in_para': para_fonts,
            'alignment': para_align,
        }
        logger.debug(f"  Para {i} Props: Bold={para_is_bold}, Italic={para_is_italic}, SizePt={para_max_fsize_pt:.1f}, Fonts={para_fonts}, Align={para_align}")

        is_chapter, ch_reason = False, "Chapter criteria not provided or not met"
        if ch_criteria :
             logger.debug(f"  Para {i} Checking for CHAPTER...")
             is_chapter, ch_reason = _matches_criteria_docx(cleaned_text, para_props, ch_criteria, "Chapter")
             # logger.debug(f"  Para {i} Chapter Check Result: {is_chapter}, Reason: {ch_reason}") # Covered by _matches_criteria_docx log
        
        if is_chapter:
            current_chapter_title = cleaned_text
            current_sub_chapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK
            logger.info(f"  ==> Para {i} Classified as CHAPTER: '{cleaned_text[:50]}'")
        else:
            is_sub_chapter, sch_reason = False, "Sub-chapter criteria not provided or not met"
            if sch_criteria: 
                logger.debug(f"  Para {i} Checking for SUB-CHAPTER (since not chapter)...")
                is_sub_chapter, sch_reason = _matches_criteria_docx(cleaned_text, para_props, sch_criteria, "Sub-Chapter")
                # logger.debug(f"  Para {i} Sub-Chapter Check Result: {is_sub_chapter}, Reason: {sch_reason}") # Covered by _matches_criteria_docx log
            
            if is_sub_chapter:
                current_sub_chapter_title = cleaned_text
                logger.info(f"  ==> Para {i} Classified as SUB-CHAPTER: '{cleaned_text[:50]}'")
            else:
                logger.debug(f"  Para {i} Classified as BODY. (Ch fail: {ch_reason if not is_chapter else 'N/A'}, SubCh fail: {sch_reason if not is_sub_chapter else 'N/A'})")


        try:
            sentences = nltk.sent_tokenize(cleaned_text)
            if not sentences and cleaned_text: sentences = [cleaned_text]
        except Exception as e:
            logger.error(f"NLTK tokenization failed P{i}: {e}", exc_info=True)
            sentences = [cleaned_text] if cleaned_text else []

        for sent_idx, sent_text in enumerate(sentences):
             clean_sent = sent_text.strip()
             if clean_sent:
                res.append((clean_sent, f"{marker}.s{sent_idx}", current_chapter_title, current_sub_chapter_title))

    logger.info(f"--- DOCX Extraction Finished. Items generated: {len(res)} ---")
    return res

def extract_sentences_with_structure(*, file_content: bytes, filename: str, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    file_ext = filename.lower().rsplit(".", 1)[-1] if isinstance(filename, str) and '.' in filename else ""
    if not file_ext: raise ValueError("Invalid or extensionless filename")
    if file_ext != "docx": raise ValueError(f"Unsupported file type: {file_ext}. Expected DOCX.")
            
    output_data = _extract_docx(data=file_content, heading_criteria=heading_criteria)
    return output_data
