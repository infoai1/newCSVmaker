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

def _matches_criteria_docx_font_size_and_centered(text: str, para_props: Dict[str, Any], criteria: Dict[str, Any], type_label: str) -> Tuple[bool, str]:
    if not criteria or criteria.get('min_font_size') is None or criteria.get('alignment_centered') is not True:
        # alignment_centered must be explicitly True in criteria now
        logger.debug(f"    [{type_label}] Criteria insufficient (min_font_size missing or alignment_centered not True). Text: '{text[:30]}...' Criteria: {criteria}")
        return False, "Core criteria (min_font_size / alignment_centered) missing or not True"

    rejection_reason = "Matches all criteria"
    passes_all_enabled_checks = True
    
    logger.debug(f"    [{type_label}] Checking text: '{text[:40]}...' with MinFontSize={criteria['min_font_size']:.1f}pt & Centered={criteria['alignment_centered']} against ParaMaxFontSize={para_props.get('max_fsize_pt', 0.0):.1f}pt, ParaAlign={para_props.get('alignment')}")

    # 1. Min Font Size (Mandatory)
    if para_props.get('max_fsize_pt', 0.0) < criteria['min_font_size']:
        rejection_reason = f"Font size {para_props.get('max_fsize_pt', 0.0):.1f}pt < min {criteria['min_font_size']:.1f}pt"
        passes_all_enabled_checks = False
    
    # 2. Centered Alignment (Mandatory, as 'alignment_centered' is True in criteria)
    if passes_all_enabled_checks: # Only check if font size passed
        if para_props.get('alignment') != WD_ALIGN_PARAGRAPH.CENTER:
            align_val = para_props.get('alignment')
            align_str = str(align_val)
            if align_val == WD_ALIGN_PARAGRAPH.LEFT: align_str = "LEFT"
            elif align_val == WD_ALIGN_PARAGRAPH.RIGHT: align_str = "RIGHT"
            elif align_val == WD_ALIGN_PARAGRAPH.JUSTIFY: align_str = "JUSTIFY"
            elif align_val is None: align_str = "NOT SET (likely LEFT)"
            rejection_reason = f"Alignment: Not Centered (Actual: {align_str})"
            passes_all_enabled_checks = False

    if passes_all_enabled_checks:
        logger.debug(f"    [{type_label}] PASS: '{text[:30]}...' matches Font Size & Centered criteria.")
    else:
        logger.debug(f"    [{type_label}] FAIL for '{text[:30]}...': {rejection_reason}")
        
    return (True, f"Matches Font Size ({criteria['min_font_size']:.1f}pt) & Centered") if passes_all_enabled_checks else (False, rejection_reason)


def _extract_docx(data: bytes, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    ch_criteria = heading_criteria.get("chapter", {})
    sch_criteria = heading_criteria.get("sub_chapter", {})

    try: doc = docx.Document(io.BytesIO(data))
    except Exception as e:
        logger.error(f"Failed to open DOCX stream: {e}", exc_info=True); return []

    res: List[Tuple[str, str, Optional[str], Optional[str]]] = []
    current_chapter_title = DEFAULT_CHAPTER_TITLE_FALLBACK
    current_sub_chapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK

    logger.info(f"--- Starting DOCX Extraction (FONT SIZE & CENTERED Mandatory Criteria) ---")
    logger.debug(f"Chapter Criteria: {ch_criteria}")
    logger.debug(f"Sub-Chapter Criteria: {sch_criteria if sch_criteria else 'Detection Disabled'}")

    for i, para in enumerate(doc.paragraphs, 1):
        cleaned_text = _clean(para.text)
        marker = f"para{i}"
        if not cleaned_text: continue

        para_max_fsize_pt = 0.0
        para_align = para.alignment
        # Other props for logging context
        para_fonts = set()
        para_is_bold = False
        para_is_italic = False


        if para.runs:
            for run in para.runs:
                if run.text.strip():
                    if run.font.size:
                        try: para_max_fsize_pt = max(para_max_fsize_pt, run.font.size.pt)
                        except AttributeError: pass
                    if run.font.name: para_fonts.add(run.font.name)
                    if run.bold: para_is_bold = True
                    if run.italic: para_is_italic = True
        
        para_props = {
            'max_fsize_pt': para_max_fsize_pt,
            'alignment': para_align,
            'font_names_in_para': para_fonts, # For logging
            'is_bold_present': para_is_bold,   # For logging
            'is_italic_present': para_is_italic # For logging
        }
        
        is_chapter, ch_reason = False, "Chapter criteria not met or disabled"
        # Check if ch_criteria is not empty and has the required keys
        if ch_criteria and ch_criteria.get('min_font_size') is not None and ch_criteria.get('alignment_centered') is True:
             logger.debug(f"  Para {i} Checking for CHAPTER. Text: '{cleaned_text[:30]}...' Props: SizePt={para_max_fsize_pt:.1f}, Align={para_align}")
             is_chapter, ch_reason = _matches_criteria_docx_font_size_and_centered(cleaned_text, para_props, ch_criteria, "Chapter")
        
        if is_chapter:
            current_chapter_title = cleaned_text
            current_sub_chapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK
            logger.info(f"  ==> Para {i} Classified as CHAPTER: '{cleaned_text[:50]}' (Reason: {ch_reason})")
        else:
            is_sub_chapter, sch_reason = False, "Sub-chapter criteria not met, disabled, or already chapter"
            # Check if sch_criteria is not empty and has the required keys
            if sch_criteria and sch_criteria.get('min_font_size') is not None and sch_criteria.get('alignment_centered') is True:
                # Ensure sub-chapter font size is distinct if chapter detection is also active
                if ch_criteria.get('min_font_size') is None or sch_criteria['min_font_size'] < ch_criteria.get('min_font_size', float('inf')):
                    logger.debug(f"  Para {i} Checking for SUB-CHAPTER. Text: '{cleaned_text[:30]}...' Props: SizePt={para_max_fsize_pt:.1f}, Align={para_align}")
                    is_sub_chapter, sch_reason = _matches_criteria_docx_font_size_and_centered(cleaned_text, para_props, sch_criteria, "Sub-Chapter")
                else:
                    sch_reason = "Sub-ch min_font_size not distinct from ch min_font_size."
                    logger.debug(f"  Para {i} Sub-ch check skipped: {sch_reason}. Text: '{cleaned_text[:30]}...'")
            
            if is_sub_chapter:
                current_sub_chapter_title = cleaned_text
                logger.info(f"  ==> Para {i} Classified as SUB-CHAPTER: '{cleaned_text[:50]}' (Reason: {sch_reason})")
            # else: # Log body only if it failed a specific check it was eligible for
                # if (ch_criteria and not is_chapter and ch_criteria.get('min_font_size') is not None) or \
                #    (sch_criteria and not is_sub_chapter and sch_criteria.get('min_font_size') is not None) :
                    # logger.debug(f"  Para {i} Classified as BODY. (Ch fail: '{ch_reason}', SubCh fail: '{sch_reason}') Text: '{cleaned_text[:30]}...'")

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
            
    # Ensure the criteria dicts passed to _extract_docx are clean and only contain what's intended
    clean_ch_criteria = {}
    if heading_criteria.get("chapter"):
        clean_ch_criteria['min_font_size'] = heading_criteria["chapter"].get('min_font_size')
        if heading_criteria["chapter"].get('alignment_centered') is True: # Check it's explicitly True
            clean_ch_criteria['alignment_centered'] = True
    
    clean_sch_criteria = {}
    if heading_criteria.get("sub_chapter"): 
        clean_sch_criteria['min_font_size'] = heading_criteria["sub_chapter"].get('min_font_size')
        if heading_criteria["sub_chapter"].get('alignment_centered') is True:
            clean_sch_criteria['alignment_centered'] = True
            
    final_criteria = {"chapter": clean_ch_criteria, "sub_chapter": clean_sch_criteria}
    
    output_data = _extract_docx(data=file_content, heading_criteria=final_criteria)
    return output_data
