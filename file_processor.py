import docx
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io
import re 
import nltk
import logging
from typing import List, Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

DEFAULT_CHAPTER_TITLE_FALLBACK = "Introduction" # Used if no chapter context is ever found
DEFAULT_SUBCHAPTER_TITLE_FALLBACK = None    # Used to signify no active sub-chapter

RE_WS = re.compile(r"\s+")

def _clean(raw: str) -> str:
    txt = raw.replace("\n", " ")
    return RE_WS.sub(" ", txt).strip()

def _matches_criteria_docx_font_size_and_centered(
    text: str, 
    para_props: Dict[str, Any], 
    criteria: Dict[str, Any], 
    type_label: str
) -> Tuple[bool, str]:
    """
    Checks if a paragraph's text and properties match the given criteria,
    which must include 'min_font_size' and 'alignment_centered': True.
    """
    # Ensure essential criteria keys are present and valid
    if not criteria or criteria.get('min_font_size') is None or criteria.get('alignment_centered') is not True:
        # logger.debug(f"    [{type_label}] Criteria insufficient for check. Text: '{text[:30]}...' Criteria: {criteria}")
        return False, "Core criteria (min_font_size / alignment_centered) missing or not set to True"

    rejection_reason = "Matches criteria" # Initial assumption
    passes_all_checks = True
    
    # Log the check being performed
    # logger.debug(f"    [{type_label}] Checking Text: '{text[:40]}...' "
    #              f"Criteria(MinFont={criteria['min_font_size']:.1f}pt, Centered={criteria['alignment_centered']}) "
    #              f"Against ParaProps(MaxFont={para_props.get('max_fsize_pt', 0.0):.1f}pt, Align={para_props.get('alignment')})")

    # 1. Minimum Font Size Check
    if para_props.get('max_fsize_pt', 0.0) < criteria['min_font_size']:
        rejection_reason = f"Font size {para_props.get('max_fsize_pt', 0.0):.1f}pt < min {criteria['min_font_size']:.1f}pt"
        passes_all_checks = False
    
    # 2. Centered Alignment Check (only if font size passed)
    if passes_all_checks and para_props.get('alignment') != WD_ALIGN_PARAGRAPH.CENTER:
        align_val = para_props.get('alignment')
        align_str = str(align_val) 
        if align_val == WD_ALIGN_PARAGRAPH.LEFT: align_str = "LEFT"
        elif align_val == WD_ALIGN_PARAGRAPH.RIGHT: align_str = "RIGHT"
        elif align_val == WD_ALIGN_PARAGRAPH.JUSTIFY: align_str = "JUSTIFY"
        elif align_val is None: align_str = "NOT_SET (likely LEFT)" # None alignment usually defaults to left
        rejection_reason = f"Alignment: Not Centered (Actual: {align_str})"
        passes_all_checks = False
        
    # if passes_all_checks:
    #     logger.debug(f"    [{type_label}] PASS: '{text[:30]}...'")
    # else:
    #     logger.debug(f"    [{type_label}] FAIL for '{text[:30]}...': {rejection_reason}")
        
    return (passes_all_checks, rejection_reason if not passes_all_checks else f"Matches MinFont ({criteria['min_font_size']:.1f}pt) & Centered")

def _extract_docx(data: bytes, heading_criteria: Dict[str, Dict[str, Any]]) \
    -> List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]]:
    """
    Processes DOCX: identifies heading paragraphs, tokenizes to sentences, assigns context.
    Outputs 6-tuples: (sentence, marker, is_para_CH_flag, is_para_SCH_flag, ch_context, sch_context)
    """
    ch_criteria = heading_criteria.get("chapter", {})
    sch_criteria = heading_criteria.get("sub_chapter", {})

    try: 
        doc = docx.Document(io.BytesIO(data))
    except Exception as e: 
        logger.error(f"Failed to open DOCX stream: {e}", exc_info=True)
        return []

    res: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]] = []
    
    # These track the text of the most recently *confirmed* heading paragraph
    active_chapter_heading_text = DEFAULT_CHAPTER_TITLE_FALLBACK
    active_subchapter_heading_text = DEFAULT_SUBCHAPTER_TITLE_FALLBACK 

    logger.info(f"--- Starting DOCX Extraction (Font Size & Centered Mandatory) ---")
    # logger.debug(f"Chapter Criteria: {ch_criteria}")
    # logger.debug(f"Sub-Chapter Criteria: {sch_criteria if sch_criteria else 'Detection Disabled'}")

    for i, para in enumerate(doc.paragraphs, 1):
        para_full_text_cleaned = _clean(para.text) 
        paragraph_marker_base = f"para{i}"
        if not para_full_text_cleaned: 
            continue

        # --- Get Paragraph Properties ---
        para_max_font_size_pt = 0.0
        para_alignment_value = para.alignment 
        if para.runs:
            for run in para.runs:
                if run.text.strip() and run.font.size:
                    try: 
                        para_max_font_size_pt = max(para_max_font_size_pt, run.font.size.pt)
                    except AttributeError: pass 
        current_para_props = {
            'max_fsize_pt': para_max_font_size_pt,
            'alignment': para_alignment_value,
        }
        # logger.debug(f"  Para {i} Text: '{para_full_text_cleaned[:60]}...' Props: SizePt={para_max_font_size_pt:.1f}, Align={para_alignment_value}")
        
        # --- Determine if this paragraph IS a heading ---
        # These flags and text apply IF this paragraph itself is a heading
        this_para_is_chapter_heading_flag = False
        this_para_is_subchapter_heading_flag = False
        
        # Context that sentences from THIS paragraph will get. Start by inheriting.
        ch_context_for_sents_from_this_para = active_chapter_heading_text
        subch_context_for_sents_from_this_para = active_subchapter_heading_text

        # Check for CHAPTER heading
        is_ch_match, ch_match_reason = _matches_criteria_docx_font_size_and_centered(
            para_full_text_cleaned, current_para_props, ch_criteria, "Chapter"
        )
        
        if is_ch_match:
            this_paragraph_is_chapter_heading_flag = True
            active_chapter_heading_text = para_full_text_cleaned # Update active context
            active_subchapter_heading_text = DEFAULT_SUBCHAPTER_TITLE_FALLBACK # Reset sub-chapter
            
            ch_context_for_sents_from_this_para = active_chapter_heading_text
            subch_context_for_sents_from_this_para = active_subchapter_heading_text # Will be default
            logger.info(f"  ==> Para {i} IS CHAPTER: '{para_full_text_cleaned[:50]}' (Reason: {ch_match_reason})")
        else:
            # If not a chapter, check if it's a SUB-CHAPTER heading
            is_sch_match, sch_match_reason = False, "SubCh criteria not fully met or disabled" # Default if sch_criteria is empty
            if sch_criteria: # Only check if sub-chapter detection is enabled and criteria exist
                if ch_criteria.get('min_font_size') is None or \
                   sch_criteria.get('min_font_size',0) < ch_criteria.get('min_font_size', float('inf')): # Ensure distinct
                    is_sch_match, sch_match_reason = _matches_criteria_docx_font_size_and_centered(
                        para_full_text_cleaned, current_para_props, sch_criteria, "Sub-Chapter"
                    )
                # else: sch_match_reason = "Sub-ch min_font_size not < ch_min_font_size."
            
            if is_sch_match:
                this_paragraph_is_subchapter_heading_flag = True
                active_subchapter_heading_text = para_full_text_cleaned # Update active context
                
                # Chapter context for this sub-chapter paragraph is the currently active chapter
                ch_context_for_sents_from_this_para = active_chapter_heading_text 
                subch_context_for_sents_from_this_para = active_subchapter_heading_text
                logger.info(f"  ==> Para {i} IS SUB-CHAPTER: '{para_full_text_cleaned[:50]}' (Reason: {sch_match_reason})")
            # else: # Paragraph is body text, inherits contexts
                # logger.debug(f"  Para {i} IS BODY. Inherits Ch='{ch_context_for_sents_from_this_para}', SubCh='{subch_context_for_sents_from_this_para}'")


        # --- Tokenize paragraph into NLTK sentences ---
        try:
            nltk_sentences = nltk.sent_tokenize(para_full_text_cleaned)
            if not nltk_sentences and para_full_text_cleaned: 
                nltk_sentences = [para_full_text_cleaned] 
        except Exception as e:
            logger.error(f"NLTK tokenization fail P{i} ('{para_full_text_cleaned[:30]}...'): {e}",exc_info=True)
            nltk_sentences=[para_full_text_cleaned] if para_full_text_cleaned else []

        # Assign determined context and flags to each NLTK-derived sentence from this paragraph
        for sent_idx, individual_sent_text in enumerate(nltk_sentences):
             clean_individual_sent = individual_sent_text.strip()
             if clean_individual_sent:
                res.append((
                    clean_individual_sent, 
                    f"{paragraph_marker_base}.s{sent_idx}", 
                    this_paragraph_is_chapter_heading_flag,    # Was THIS para a CH?
                    this_paragraph_is_subchapter_heading_flag, # Was THIS para a SCH?
                    ch_context_for_sents_from_this_para,       # Effective Ch context for this sent
                    subch_context_for_sents_from_this_para     # Effective SubCh context for this sent
                ))

    logger.info(f"--- DOCX Extraction Finished. Total 6-tuple segments: {len(res)} ---")
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
