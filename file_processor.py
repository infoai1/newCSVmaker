import docx
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io
import re
import nltk
import logging
from typing import List, Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

DEFAULT_CHAPTER_TITLE_FALLBACK = "Introduction"
DEFAULT_SUBCHAPTER_TITLE_FALLBACK = None
RE_WS = re.compile(r"\s+")

def _clean(raw: str) -> str:
    txt = raw.replace("\n", " ")
    return RE_WS.sub(" ", txt).strip()

def _matches_criteria_docx(text: str, para_props: Dict[str, Any], criteria: Dict[str, Any], type_label: str) -> Tuple[bool, str]:
    if not criteria:
        logger.debug(f"    [{type_label}] No criteria provided (detection likely disabled). Text: '{text[:30]}...'")
        return False, "No criteria defined for this type"

    rejection_reason = "Matches all enabled criteria"
    passes_all_enabled_checks = True
    
    # Always log the check attempt if criteria are present
    logger.debug(f"    [{type_label}] Checking text: '{text[:40]}...' against criteria: {criteria} with props: {para_props}")

    # Font Properties (Primary) - check_font_props is now implicitly True if criteria are font-focused
    if criteria.get('font_names') is None or criteria.get('min_font_size') is None : # Should not happen if UI logic is correct
        logger.warning(f"    [{type_label}] Font name or min_font_size missing in criteria. Criteria: {criteria}")
        # Fallback or assume check_font_props was meant to be false if these are missing
        # For now, let's assume it's a misconfiguration and potentially fail.
        # Or, you could have a master 'check_font_props' from app.py if you want to disable font checks entirely.
        # Based on the simplified UI, font_names and min_font_size are always primary.

    # Min Font Size (Mandatory if font checks are on)
    if criteria.get('min_font_size', 0.0) > 0.0: # min_font_size check is always active
        if para_props.get('max_fsize_pt', 0.0) < criteria['min_font_size']:
            rejection_reason = f"Font size {para_props.get('max_fsize_pt', 0.0):.1f}pt < min {criteria['min_font_size']:.1f}pt"
            passes_all_enabled_checks = False
    
    # Font Names (Mandatory if font checks are on and list is not empty)
    if passes_all_enabled_checks and criteria.get('font_names'): # if list is not empty
        if not any(fn in para_props.get('font_names_in_para', set()) for fn in criteria['font_names']):
             rejection_reason = f"Para fonts {para_props.get('font_names_in_para', set())} not in required {criteria['font_names']}"
             passes_all_enabled_checks = False
    
    # Optional additional checks (ALL CAPS, Centered)
    # These are only checked if their respective master toggles (ch_check_case_val, ch_check_alignment_val) were True in app.py
    if passes_all_enabled_checks and criteria.get('check_case') and criteria.get('case_upper'):
        non_space_text = "".join(text.split())
        actual_is_all_caps = non_space_text.isupper() if non_space_text else False
        if not actual_is_all_caps:
            rejection_reason = f"Case: Not ALL CAPS (Text: '{text[:30]}...')"
            passes_all_enabled_checks = False
            
    if passes_all_enabled_checks and criteria.get('check_alignment') and criteria.get('alignment_centered'):
        if para_props.get('alignment') != WD_ALIGN_PARAGRAPH.CENTER:
            align_val = para_props.get('alignment')
            align_str = str(align_val)
            if align_val == WD_ALIGN_PARAGRAPH.LEFT: align_str = "LEFT"
            elif align_val == WD_ALIGN_PARAGRAPH.RIGHT: align_str = "RIGHT"
            elif align_val == WD_ALIGN_PARAGRAPH.JUSTIFY: align_str = "JUSTIFY"
            elif align_val is None: align_str = "NOT SET (likely LEFT by default)"
            rejection_reason = f"Alignment: Not Centered (Actual: {align_str})"
            passes_all_enabled_checks = False

    # Optional Max Word Count (Mainly for sub-chapters from UI)
    if passes_all_enabled_checks and criteria.get('check_word_count'): # Only if explicitly enabled for this type
        word_count = len(text.split())
        # Max words is the primary concern here for this simplified model
        max_w = criteria.get('word_count_max', 999) 
        if word_count > max_w : # only checking max
            rejection_reason = f"Word Count: {word_count} > max {max_w}"
            passes_all_enabled_checks = False


    if passes_all_enabled_checks:
        logger.debug(f"    [{type_label}] PASS: '{text[:30]}...' matches criteria.")
    else:
        logger.debug(f"    [{type_label}] FAIL for '{text[:30]}...': {rejection_reason}")
        
    return (True, "Matches criteria") if passes_all_enabled_checks else (False, rejection_reason)


def _extract_docx(data: bytes, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    ch_criteria = heading_criteria.get("chapter", {})
    sch_criteria = heading_criteria.get("sub_chapter", {})

    try: doc = docx.Document(io.BytesIO(data))
    except Exception as e:
        logger.error(f"Failed to open DOCX stream: {e}", exc_info=True); return []

    res: List[Tuple[str, str, Optional[str], Optional[str]]] = []
    current_chapter_title = DEFAULT_CHAPTER_TITLE_FALLBACK
    current_sub_chapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK

    logger.info(f"--- Starting DOCX Extraction (Simplified Font/Size Focus) ---")
    logger.debug(f"Chapter Criteria: {ch_criteria}")
    logger.debug(f"Sub-Chapter Criteria: {sch_criteria if sch_criteria else 'Disabled'}")

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
                    if run.bold: para_is_bold = True # Still useful to log, even if not primary criteria
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
        logger.debug(f"  Para {i} Props: SizePt={para_max_fsize_pt:.1f}, Fonts={para_fonts}, Align={para_align}, Bold={para_is_bold}, Italic={para_is_italic}")

        is_chapter, ch_reason = False, "Chapter criteria not met or not defined"
        if ch_criteria.get('font_names') and ch_criteria.get('min_font_size'): # Basic check if criteria are usable
             is_chapter, ch_reason = _matches_criteria_docx(cleaned_text, para_props, ch_criteria, "Chapter")
        
        if is_chapter:
            current_chapter_title = cleaned_text
            current_sub_chapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK
            logger.info(f"  ==> Para {i} Classified as CHAPTER: '{cleaned_text[:50]}'")
        else:
            is_sub_chapter, sch_reason = False, "Sub-chapter criteria not met, not defined, or disabled"
            if sch_criteria.get('font_names') and sch_criteria.get('min_font_size'): # Basic check for sub-chapter criteria
                is_sub_chapter, sch_reason = _matches_criteria_docx(cleaned_text, para_props, sch_criteria, "Sub-Chapter")
            
            if is_sub_chapter:
                current_sub_chapter_title = cleaned_text
                logger.info(f"  ==> Para {i} Classified as SUB-CHAPTER: '{cleaned_text[:50]}'")
            else:
                logger.debug(f"  Para {i} Classified as BODY. (Ch fail: '{ch_reason}', SubCh fail: '{sch_reason}')")

        try:
            sentences = nltk.sent_tokenize(cleaned_text)
            if not sentences and cleaned_text: sentences = [cleaned_text]
        except Exception as e:
            logger.error(f"NLTK tokenization fail P{i}: {e}",exc_info=True); sentences=[cleaned_text] if cleaned_text else []

        for sent_idx, sent_text in enumerate(sentences):
             if sent_text.strip():
                res.append((sent_text.strip(),f"{marker}.s{sent_idx}",current_chapter_title,current_sub_chapter_title))

    logger.info(f"--- DOCX Extraction Finished. Items: {len(res)} ---")
    return res

def extract_sentences_with_structure(*, file_content: bytes, filename: str, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    file_ext = filename.lower().rsplit(".", 1)[-1] if isinstance(filename, str) and '.' in filename else ""
    if not file_ext: raise ValueError("Invalid/extensionless filename")
    if file_ext != "docx": raise ValueError(f"Unsupported file type: {file_ext}. Expected DOCX.")
            
    output_data = _extract_docx(data=file_content, heading_criteria=heading_criteria)
    return output_data
