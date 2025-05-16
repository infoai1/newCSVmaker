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
    # It's called for both chapter and sub-chapter detection.
    if not criteria or criteria.get('min_font_size') is None or criteria.get('alignment_centered') is not True:
        # logger.debug(f"    [{type_label}] Criteria insufficient (min_font_size missing or alignment_centered not True). Text: '{text[:30]}...' Criteria: {criteria}")
        return False, "Core criteria (min_font_size / alignment_centered) missing or not True"

    rejection_reason = "Matches criteria" # Assume it passes initially
    passes_all_enabled_checks = True
    
    # logger.debug(f"    [{type_label}] Checking text: '{text[:40]}...' with MinFontSize={criteria['min_font_size']:.1f}pt & Centered={criteria['alignment_centered']} against ParaMaxFontSize={para_props.get('max_fsize_pt', 0.0):.1f}pt, ParaAlign={para_props.get('alignment')}")

    # Criterion 1: Minimum Font Size
    if para_props.get('max_fsize_pt', 0.0) < criteria['min_font_size']:
        rejection_reason = f"Font size {para_props.get('max_fsize_pt', 0.0):.1f}pt < min {criteria['min_font_size']:.1f}pt"
        passes_all_enabled_checks = False
    
    # Criterion 2: Centered Alignment (only checked if font size passed)
    if passes_all_enabled_checks and para_props.get('alignment') != WD_ALIGN_PARAGRAPH.CENTER:
        align_val = para_props.get('alignment')
        align_str = str(align_val) # Default to raw value if not a known enum member
        if align_val == WD_ALIGN_PARAGRAPH.LEFT: align_str = "LEFT"
        elif align_val == WD_ALIGN_PARAGRAPH.RIGHT: align_str = "RIGHT"
        elif align_val == WD_ALIGN_PARAGRAPH.JUSTIFY: align_str = "JUSTIFY"
        elif align_val is None: align_str = "NOT SET (effectively left)" # None often defaults to left
        rejection_reason = f"Alignment: Not Centered (Actual: {align_str})"
        passes_all_enabled_checks = False
        
    # if passes_all_enabled_checks:
    #     logger.debug(f"    [{type_label}] PASS: '{text[:30]}...' matches Font Size & Centered criteria.")
    # else:
    #     logger.debug(f"    [{type_label}] FAIL for '{text[:30]}...': {rejection_reason}")
        
    return (True, f"Matches MinFont ({criteria['min_font_size']:.1f}pt) & Centered") if passes_all_enabled_checks else (False, rejection_reason)


def _extract_docx(data: bytes, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]]:
    # This function processes the DOCX file paragraph by paragraph.
    # It determines if each paragraph is a chapter or sub-chapter heading.
    # Then, it splits each paragraph into sentences using NLTK.
    # For each sentence, it outputs a 6-tuple:
    # (sentence_text, marker, is_paragraph_a_chapter_heading_flag, 
    #  is_paragraph_a_subchapter_heading_flag, chapter_context, subchapter_context)

    ch_criteria = heading_criteria.get("chapter", {})
    sch_criteria = heading_criteria.get("sub_chapter", {})

    try: 
        doc = docx.Document(io.BytesIO(data))
    except Exception as e: 
        logger.error(f"Failed to open DOCX stream: {e}", exc_info=True)
        return []

    res: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]] = []
    
    # These track the text of the most recently identified chapter/sub-chapter heading paragraph
    active_chapter_context_text = DEFAULT_CHAPTER_TITLE_FALLBACK
    active_subchapter_context_text = DEFAULT_SUBCHAPTER_TITLE_FALLBACK 

    logger.info(f"--- Starting DOCX Extraction (Font Size & Centered Criteria) ---")
    # logger.debug(f"Chapter Criteria being used: {ch_criteria}")
    # logger.debug(f"Sub-Chapter Criteria being used: {sch_criteria if sch_criteria else 'Sub-chapter detection disabled'}")

    for i, para in enumerate(doc.paragraphs, 1):
        para_full_text_cleaned = _clean(para.text) 
        paragraph_marker_base = f"para{i}"
        if not para_full_text_cleaned: 
            # logger.debug(f"  Para {i} is empty, skipping.")
            continue

        # logger.debug(f"--- Para {i} [{paragraph_marker_base}] Full Text: '{para_full_text_cleaned[:70]}...' ---")

        # Get properties of the current paragraph
        para_max_font_size_pt = 0.0
        para_alignment_value = para.alignment 
        # These are collected for potential logging/debugging, not active criteria in this version
        # para_font_names_set = set()
        # para_is_bold_flag = False
        # para_is_italic_flag = False

        if para.runs:
            for run in para.runs:
                if run.text.strip(): # Consider runs with text content
                    if run.font.size:
                        try: 
                            para_max_font_size_pt = max(para_max_font_size_pt, run.font.size.pt)
                        except AttributeError: # Handles if run.font.size is None
                            pass 
                    # if run.font.name: para_font_names_set.add(run.font.name)
                    # if run.bold: para_is_bold_flag = True
                    # if run.italic: para_is_italic_flag = True
        
        current_para_props = {
            'max_fsize_pt': para_max_fsize_pt,
            'alignment': para_alignment_value,
            # 'font_names_in_para': para_font_names_set, 
            # 'is_bold_present': para_is_bold_flag,   
            # 'is_italic_present': para_is_italic_flag 
        }
        # logger.debug(f"  Para {i} Properties: MaxFontSizePt={para_max_fsize_pt:.1f}, AlignmentValue={para_alignment_value}")
        
        # Flags indicating if THIS paragraph ITSELF is a heading
        this_paragraph_is_chapter_heading = False
        this_paragraph_is_subchapter_heading = False
        
        # Determine context for sentences that will come from THIS paragraph
        # Default to inheriting from previous active contexts
        ch_context_for_this_para_sents = active_chapter_context_text
        subch_context_for_this_para_sents = active_subchapter_context_text

        # Check if this paragraph is a CHAPTER heading
        is_ch_match, ch_match_reason = False, "Ch criteria not fully met or not defined"
        if ch_criteria and ch_criteria.get('min_font_size') is not None and ch_criteria.get('alignment_centered') is True:
             is_ch_match, ch_match_reason = _matches_criteria_docx_font_size_and_centered(
                 para_full_text_cleaned, current_para_props, ch_criteria, "Chapter"
             )
        
        if is_ch_match:
            this_paragraph_is_chapter_heading = True
            active_chapter_context_text = para_full_text_cleaned # Update active context
            active_subchapter_context_text = DEFAULT_SUBCHAPTER_TITLE_FALLBACK # Reset sub-chapter on new chapter
            
            ch_context_for_this_para_sents = active_chapter_context_text
            subch_context_for_this_para_sents = active_subchapter_context_text # Will be default/None
            logger.info(f"  ==> Para {i} IS CHAPTER: '{para_full_text_cleaned[:50]}' (Reason: {ch_match_reason})")
        else:
            # If not a chapter, check if it's a SUB-CHAPTER heading
            is_sch_match, sch_match_reason = False, "SubCh criteria not met, disabled, or not distinct"
            if sch_criteria and sch_criteria.get('min_font_size') is not None and sch_criteria.get('alignment_centered') is True:
                # Ensure sub-chapter font size is distinct from chapter font size if both use same criteria otherwise
                if ch_criteria.get('min_font_size') is None or \
                   sch_criteria['min_font_size'] < ch_criteria.get('min_font_size', float('inf')):
                    is_sch_match, sch_match_reason = _matches_criteria_docx_font_size_and_centered(
                        para_full_text_cleaned, current_para_props, sch_criteria, "Sub-Chapter"
                    )
                # else: 
                    # sch_match_reason = "Sub-ch min_font_size not < ch_min_font_size."
                    # logger.debug(f"  Para {i} Sub-ch check skipped: {sch_match_reason} for '{para_full_text_cleaned[:30]}...'")
            
            if is_sch_match:
                this_paragraph_is_subchapter_heading = True
                active_subchapter_context_text = para_full_text_cleaned # Update active context
                
                # Sentences from this paragraph will get this new sub-chapter context
                # Chapter context remains the inherited active_chapter_context_text
                ch_context_for_this_para_sents = active_chapter_context_text 
                subch_context_for_this_para_sents = active_subchapter_context_text
                logger.info(f"  ==> Para {i} IS SUB-CHAPTER: '{para_full_text_cleaned[:50]}' (Reason: {sch_match_reason})")
            # else: # Paragraph is body text
                # logger.debug(f"  Para {i} IS BODY. (Ch fail: '{ch_match_reason}', SubCh fail: '{sch_match_reason}')")


        # Split the full paragraph text into NLTK sentences
        try:
            nltk_sentences = nltk.sent_tokenize(para_full_text_cleaned)
            if not nltk_sentences and para_full_text_cleaned: # If para has text but NLTK returns no sentences
                nltk_sentences = [para_full_text_cleaned] 
        except Exception as e:
            logger.error(f"NLTK tokenization fail P{i}: {e}",exc_info=True)
            nltk_sentences=[para_full_text_cleaned] if para_full_text_cleaned else []

        # Assign context and heading flags to each NLTK-derived sentence from this paragraph
        for sent_idx, individual_sent_text in enumerate(nltk_sentences):
             clean_individual_sent = individual_sent_text.strip()
             if clean_individual_sent:
                res.append((
                    clean_individual_sent, 
                    f"{paragraph_marker_base}.s{sent_idx}", # Use simple sentence index
                    this_paragraph_is_chapter_heading,    # Flag if original para was CH  
                    this_paragraph_is_subchapter_heading, # Flag if original para was SCH
                    ch_context_for_this_para_sents,       # Chapter context for this sentence
                    subch_context_for_this_para_sents     # Sub-chapter context for this sentence
                ))

    logger.info(f"--- DOCX Extraction Finished. Total items generated: {len(res)} ---")
    return res

def extract_sentences_with_structure(*, file_content: bytes, filename: str, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]]:
    """Wrapper for extraction, prepares criteria for _extract_docx."""
    file_ext = filename.lower().rsplit(".", 1)[-1] if isinstance(filename, str) and '.' in filename else ""
    if not file_ext: raise ValueError("Invalid or extensionless filename provided")
    if file_ext != "docx": raise ValueError(f"Unsupported file type: {file_ext}. Expected DOCX.")
            
    # Prepare clean criteria dictionary based on what app.py sends for "Font Size & Centered"
    # This ensures only 'min_font_size' and 'alignment_centered' are passed if they meet conditions.
    clean_ch_criteria = {}
    raw_ch_crit = heading_criteria.get("chapter", {}) # Get chapter criteria dict, or empty if not present
    # Check if essential keys are present and valid before adding to clean criteria
    if raw_ch_crit.get('min_font_size') is not None and raw_ch_crit.get('alignment_centered') is True:
        clean_ch_criteria['min_font_size'] = raw_ch_crit['min_font_size']
        clean_ch_criteria['alignment_centered'] = True # This is True because app.py sets it so
    
    clean_sch_criteria = {}
    raw_sch_crit = heading_criteria.get("sub_chapter", {}) # Get sub-chapter criteria dict
    if raw_sch_crit: # Process only if sub_chapter criteria dict is not empty (i.e., detection enabled)
        if raw_sch_crit.get('min_font_size') is not None and raw_sch_crit.get('alignment_centered') is True:
            clean_sch_criteria['min_font_size'] = raw_sch_crit['min_font_size']
            clean_sch_criteria['alignment_centered'] = True
            
    final_criteria_to_pass = {"chapter": clean_ch_criteria, "sub_chapter": clean_sch_criteria}
    
    output_data = _extract_docx(data=file_content, heading_criteria=final_criteria_to_pass)
    return output_data
