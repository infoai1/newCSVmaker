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
        return False, "Core criteria (min_font_size / alignment_centered) missing or not True"
    rejection_reason = "Matches criteria"
    passes_all_enabled_checks = True
    if para_props.get('max_fsize_pt', 0.0) < criteria['min_font_size']:
        rejection_reason = f"Font size {para_props.get('max_fsize_pt', 0.0):.1f}pt < min {criteria['min_font_size']:.1f}pt"
        passes_all_enabled_checks = False
    if passes_all_enabled_checks and para_props.get('alignment') != WD_ALIGN_PARAGRAPH.CENTER:
        align_val = para_props.get('alignment')
        align_str = str(align_val)
        if align_val == WD_ALIGN_PARAGRAPH.LEFT: align_str = "LEFT"
        elif align_val == WD_ALIGN_PARAGRAPH.RIGHT: align_str = "RIGHT"
        elif align_val == WD_ALIGN_PARAGRAPH.JUSTIFY: align_str = "JUSTIFY"
        elif align_val is None: align_str = "NOT SET"
        rejection_reason = f"Alignment: Not Centered (Actual: {align_str})"
        passes_all_enabled_checks = False
    return (True, f"Matches MinFont ({criteria['min_font_size']:.1f}pt) & Centered") if passes_all_enabled_checks else (False, rejection_reason)

def _extract_docx(data: bytes, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]]:
    ch_criteria = heading_criteria.get("chapter", {})
    sch_criteria = heading_criteria.get("sub_chapter", {})
    try: doc = docx.Document(io.BytesIO(data))
    except Exception as e: logger.error(f"Failed to open DOCX stream: {e}", exc_info=True); return []

    res: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]] = []
    active_chapter_context_text = DEFAULT_CHAPTER_TITLE_FALLBACK
    active_subchapter_context_text = DEFAULT_SUBCHAPTER_TITLE_FALLBACK 

    logger.info(f"--- Starting DOCX Extraction (Font Size & Centered Criteria) ---") # Updated log message slightly for clarity

    for i, para in enumerate(doc.paragraphs, 1):
        para_full_text_cleaned = _clean(para.text) 
        paragraph_marker_base = f"para{i}"
        if not para_full_text_cleaned: 
            continue

        # Initialize paragraph properties before the loop
        para_max_font_size_pt = 0.0  # Initialize here
        para_alignment_value = para.alignment 
        para_font_names_set = set()  # Initialize here
        para_is_bold_flag = False    # Initialize here
        para_is_italic_flag = False  # Initialize here

        if para.runs:
            for run in para.runs:
                if run.text.strip(): 
                    if run.font.size:
                        try: 
                            para_max_font_size_pt = max(para_max_font_size_pt, run.font.size.pt)
                        except AttributeError: 
                            pass 
                    if run.font.name: para_font_names_set.add(run.font.name)
                    if run.bold: para_is_bold_flag = True
                    if run.italic: para_is_italic_flag = True
        
        current_para_props = {
            'max_fsize_pt': para_max_font_size_pt,
            'alignment': para_alignment_value,
            'font_names_in_para': para_font_names_set, 
            'is_bold_present': para_is_bold_flag,   
            'is_italic_present': para_is_italic_flag 
        }
        # logger.debug(f"  Para {i} Props: MaxFontSizePt={para_max_font_size_pt:.1f}, AlignmentValue={para_alignment_value}") # Redundant if logged in _matches_criteria
        
        this_paragraph_is_chapter_heading = False
        this_paragraph_is_subchapter_heading = False
        
        ch_context_for_this_para_sents = active_chapter_context_text
        subch_context_for_this_para_sents = active_subchapter_context_text

        is_ch_match, ch_match_reason = False, "Ch criteria not fully met or not defined"
        if ch_criteria and ch_criteria.get('min_font_size') is not None and ch_criteria.get('alignment_centered') is True:
             logger.debug(f"  Para {i} Checking for CHAPTER. Text: '{para_full_text_cleaned[:30]}...' Props: SizePt={current_para_props['max_fsize_pt']:.1f}, Align={current_para_props['alignment']}")
             is_ch_match, ch_match_reason = _matches_criteria_docx_font_size_and_centered(
                 para_full_text_cleaned, current_para_props, ch_criteria, "Chapter"
             )
        
        if is_ch_match:
            this_paragraph_is_chapter_heading = True
            active_chapter_context_text = para_full_text_cleaned 
            active_subchapter_context_text = DEFAULT_SUBCHAPTER_TITLE_FALLBACK 
            
            ch_context_for_this_para_sents = active_chapter_context_text
            subch_context_for_this_para_sents = active_subchapter_context_text
            logger.info(f"  ==> Para {i} IS CHAPTER: '{para_full_text_cleaned[:50]}' (Reason: {ch_match_reason})")
        else:
            is_sch_match, sch_match_reason = False, "SubCh criteria not met, disabled, or not distinct"
            if sch_criteria and sch_criteria.get('min_font_size') is not None and sch_criteria.get('alignment_centered') is True:
                if ch_criteria.get('min_font_size') is None or \
                   sch_criteria.get('min_font_size',0) < ch_criteria.get('min_font_size', float('inf')):
                    logger.debug(f"  Para {i} Checking for SUB-CHAPTER. Text: '{para_full_text_cleaned[:30]}...' Props: SizePt={current_para_props['max_fsize_pt']:.1f}, Align={current_para_props['alignment']}")
                    is_sch_match, sch_match_reason = _matches_criteria_docx_font_size_and_centered(
                        para_full_text_cleaned, current_para_props, sch_criteria, "Sub-Chapter"
                    )
            
            if is_sch_match:
                this_paragraph_is_subchapter_heading = True
                active_subchapter_context_text = para_full_text_cleaned 
                
                ch_context_for_this_para_sents = active_chapter_context_text 
                subch_context_for_this_para_sents = active_subchapter_context_text
                logger.info(f"  ==> Para {i} IS SUB-CHAPTER: '{para_full_text_cleaned[:50]}' (Reason: {sch_match_reason})")

        try:
            nltk_sentences = nltk.sent_tokenize(para_full_text_cleaned)
            if not nltk_sentences and para_full_text_cleaned: 
                nltk_sentences = [para_full_text_cleaned] 
        except Exception as e:
            logger.error(f"NLTK tokenization fail P{i}: {e}",exc_info=True)
            nltk_sentences=[para_full_text_cleaned] if para_full_text_cleaned else []

        for sent_idx, individual_sent_text in enumerate(nltk_sentences):
             clean_individual_sent = individual_sent_text.strip()
             if clean_individual_sent:
                res.append((
                    clean_individual_sent, 
                    f"{paragraph_marker_base}.s{sent_idx}", 
                    this_paragraph_is_chapter_heading,      
                    this_paragraph_is_subchapter_heading, 
                    ch_context_for_this_para_sents,       
                    subch_context_for_this_para_sents     
                ))

    logger.info(f"--- DOCX Extraction Finished. Total items generated: {len(res)} ---")
    return res

def extract_sentences_with_structure(*, file_content: bytes, filename: str, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]]:
    file_ext = filename.lower().rsplit(".", 1)[-1] if isinstance(filename, str) and '.' in filename else ""
    if not file_ext: raise ValueError("Invalid or extensionless filename provided")
    if file_ext != "docx": raise ValueError(f"Unsupported file type: {file_ext}. Expected DOCX.")
            
    clean_ch_criteria = {}
    raw_ch_crit = heading_criteria.get("chapter", {}) 
    if raw_ch_crit.get('min_font_size') is not None and raw_ch_crit.get('alignment_centered') is True:
        clean_ch_criteria['min_font_size'] = raw_ch_crit['min_font_size']
        clean_ch_criteria['alignment_centered'] = True 
    
    clean_sch_criteria = {}
    raw_sch_crit = heading_criteria.get("sub_chapter", {}) 
    if raw_sch_crit: 
        if raw_sch_crit.get('min_font_size') is not None and raw_sch_crit.get('alignment_centered') is True:
            clean_sch_criteria['min_font_size'] = raw_sch_crit['min_font_size']
            clean_sch_criteria['alignment_centered'] = True
            
    final_criteria_to_pass = {"chapter": clean_ch_criteria, "sub_chapter": clean_sch_criteria}
    
    output_data = _extract_docx(data=file_content, heading_criteria=final_criteria_to_pass)
    return output_data
