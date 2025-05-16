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
    # This function checks if a paragraph matches based on min_font_size and centered alignment.
    if not criteria or criteria.get('min_font_size') is None or criteria.get('alignment_centered') is not True:
        return False, "Core criteria (min_font_size / alignment_centered) missing or not True"

    rejection_reason = "Matches criteria" # Assume it passes initially
    passes_all_enabled_checks = True
    
    # logger.debug(f"    [{type_label}] Checking text: '{text[:40]}...' with MinFontSize={criteria['min_font_size']:.1f}pt & Centered={criteria['alignment_centered']} against ParaMaxFontSize={para_props.get('max_fsize_pt', 0.0):.1f}pt, ParaAlign={para_props.get('alignment')}")

    if para_props.get('max_fsize_pt', 0.0) < criteria['min_font_size']:
        rejection_reason = f"Font size {para_props.get('max_fsize_pt', 0.0):.1f}pt < min {criteria['min_font_size']:.1f}pt"
        passes_all_enabled_checks = False
    
    if passes_all_enabled_checks and para_props.get('alignment') != WD_ALIGN_PARAGRAPH.CENTER:
        align_val = para_props.get('alignment')
        align_str = str(align_val) 
        if align_val == WD_ALIGN_PARAGRAPH.LEFT: align_str = "LEFT"
        elif align_val == WD_ALIGN_PARAGRAPH.RIGHT: align_str = "RIGHT"
        elif align_val == WD_ALIGN_PARAGRAPH.JUSTIFY: align_str = "JUSTIFY"
        elif align_val is None: align_str = "NOT SET (effectively left)" 
        rejection_reason = f"Alignment: Not Centered (Actual: {align_str})"
        passes_all_enabled_checks = False
        
    return (True, f"Matches MinFont ({criteria['min_font_size']:.1f}pt) & Centered") if passes_all_enabled_checks else (False, rejection_reason)


def _extract_docx(data: bytes, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]]:
    # OUTPUT: (sentence_text, marker, is_paragraph_a_chapter_heading_flag, 
    #          is_paragraph_a_subchapter_heading_flag, chapter_context_for_sentence, subchapter_context_for_sentence)

    ch_criteria = heading_criteria.get("chapter", {})
    sch_criteria = heading_criteria.get("sub_chapter", {})

    try: 
        doc = docx.Document(io.BytesIO(data))
    except Exception as e: 
        logger.error(f"Failed to open DOCX stream: {e}", exc_info=True)
        return []

    res: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]] = []
    
    active_chapter_context = DEFAULT_CHAPTER_TITLE_FALLBACK
    active_subchapter_context = DEFAULT_SUBCHAPTER_TITLE_FALLBACK 

    logger.info(f"--- Starting DOCX Extraction (Font Size & Centered Criteria - preparing 6-tuple for chunker) ---")

    for i, para in enumerate(doc.paragraphs, 1):
        para_full_text_cleaned = _clean(para.text) 
        paragraph_marker_base = f"para{i}"
        if not para_full_text_cleaned: 
            continue

        para_max_font_size_pt = 0.0
        para_alignment_value = para.alignment 
        
        if para.runs:
            for run in para.runs:
                if run.text.strip(): 
                    if run.font.size:
                        try: 
                            para_max_font_size_pt = max(para_max_font_size_pt, run.font.size.pt)
                        except AttributeError: 
                            pass 
        
        current_para_props = {
            'max_fsize_pt': para_max_font_size_pt,
            'alignment': para_alignment_value,
        }
        
        # These flags are about whether THIS paragraph ITSELF is a heading
        this_paragraph_is_chapter_heading_flag = False
        this_paragraph_is_subchapter_heading_flag = False
        
        # Determine current context for sentences that will come from THIS paragraph
        # Start by inheriting, then update if this paragraph is a heading itself
        ch_context_for_sents_in_this_para = active_chapter_context
        subch_context_for_sents_in_this_para = active_subchapter_context

        is_ch_match, ch_match_reason = False, "Ch criteria not fully met or not defined"
        if ch_criteria and ch_criteria.get('min_font_size') is not None and ch_criteria.get('alignment_centered') is True:
             is_ch_match, ch_match_reason = _matches_criteria_docx_font_size_and_centered(
                 para_full_text_cleaned, current_para_props, ch_criteria, "Chapter"
             )
        
        if is_ch_match:
            this_paragraph_is_chapter_heading_flag = True
            active_chapter_context = para_full_text_cleaned # This paragraph's text IS the new active chapter context
            active_subchapter_context = DEFAULT_SUBCHAPTER_TITLE_FALLBACK # Reset sub-chapter on new chapter
            
            ch_context_for_sents_in_this_para = active_chapter_context
            subch_context_for_sents_in_this_para = active_subchapter_context # will be default
            logger.info(f"  ==> Para {i} IS CHAPTER: '{para_full_text_cleaned[:50]}' (Reason: {ch_match_reason})")
        else:
            is_sch_match, sch_match_reason = False, "SubCh criteria not met, disabled, or not distinct"
            if sch_criteria and sch_criteria.get('min_font_size') is not None and sch_criteria.get('alignment_centered') is True:
                if ch_criteria.get('min_font_size') is None or \
                   sch_criteria.get('min_font_size',0) < ch_criteria.get('min_font_size', float('inf')):
                    is_sch_match, sch_match_reason = _matches_criteria_docx_font_size_and_centered(
                        para_full_text_cleaned, current_para_props, sch_criteria, "Sub-Chapter"
                    )
            
            if is_sch_match:
                this_paragraph_is_subchapter_heading_flag = True
                active_subchapter_context = para_full_text_cleaned # This paragraph's text IS the new active sub-chapter context
                
                # Chapter context remains the inherited active_chapter_context
                ch_context_for_sents_in_this_para = active_chapter_context 
                subch_context_for_sents_in_this_para = active_subchapter_context
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
                    this_paragraph_is_chapter_heading_flag, # True if this sentence's original para was a CH
                    this_paragraph_is_subchapter_heading_flag, # True if this sentence's original para was a SCH
                    ch_context_for_sents_in_this_para,       
                    subch_context_for_sents_in_this_para     
                ))

    logger.info(f"--- DOCX Extraction Finished. Total 6-tuple segments generated: {len(res)} ---")
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
