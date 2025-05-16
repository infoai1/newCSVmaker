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
    active_chapter_context = DEFAULT_CHAPTER_TITLE_FALLBACK
    active_subchapter_context = DEFAULT_SUBCHAPTER_TITLE_FALLBACK 

    logger.info(f"--- Starting DOCX Extraction (Attempting sub-sentence split for embedded headings) ---")

    for i, para in enumerate(doc.paragraphs, 1):
        para_text_cleaned = _clean(para.text) 
        marker_base = f"para{i}"
        if not para_text_cleaned: continue

        para_max_fsize_pt, para_align = 0.0, para.alignment
        if para.runs:
            for run in para.runs:
                if run.text.strip() and run.font.size:
                    try: para_max_fsize_pt = max(para_max_fsize_pt, run.font.size.pt)
                    except AttributeError: pass
        
        para_props = {'max_fsize_pt': para_max_fsize_pt, 'alignment': para_align}
        
        # Determine if this paragraph AS A WHOLE is a chapter or sub-chapter heading
        para_is_chapter_heading_flag = False
        para_is_subchapter_heading_flag = False
        
        # These store the text of the heading IF this paragraph itself IS that heading
        text_if_para_is_chapter_heading: Optional[str] = None
        text_if_para_is_subchapter_heading: Optional[str] = None

        is_ch, _ = _matches_criteria_docx_font_size_and_centered(para_text_cleaned, para_props, ch_criteria, "Chapter")
        if is_ch:
            para_is_chapter_heading_flag = True
            text_if_para_is_chapter_heading = para_text_cleaned
            active_chapter_context = para_text_cleaned 
            active_subchapter_context = DEFAULT_SUBCHAPTER_TITLE_FALLBACK 
            logger.info(f"  Para {i} IS CHAPTER: '{para_text_cleaned[:50]}'")
        else: # Only check for sub-chapter if it's not a chapter
            is_sch, _ = _matches_criteria_docx_font_size_and_centered(para_text_cleaned, para_props, sch_criteria, "Sub-Chapter")
            if is_sch and (ch_criteria.get('min_font_size') is None or sch_criteria.get('min_font_size',0) < ch_criteria.get('min_font_size', float('inf'))):
                para_is_subchapter_heading_flag = True
                text_if_para_is_subchapter_heading = para_text_cleaned
                active_subchapter_context = para_text_cleaned 
                logger.info(f"  Para {i} IS SUB-CHAPTER: '{para_text_cleaned[:50]}'")
            # If not chapter and not sub-chapter, it's body text; it inherits active_chapter_context and active_subchapter_context

        try:
            nltk_sentences = nltk.sent_tokenize(para_text_cleaned)
            if not nltk_sentences and para_text_cleaned: nltk_sentences = [para_text_cleaned]
        except Exception as e:
            logger.error(f"NLTK tokenization fail P{i}: {e}",exc_info=True); nltk_sentences=[para_text_cleaned] if para_text_cleaned else []

        sent_idx_counter = 0
        for orig_sent_idx, sent_text_from_nltk in enumerate(nltk_sentences):
            current_segment = sent_text_from_nltk.strip()
            if not current_segment: continue

            # Determine the context for this NLTK sentence before any potential split
            # If the paragraph itself was a heading, that's the primary context.
            # Otherwise, it inherits from the active contexts.
            current_sent_ch_context = text_if_para_is_chapter_heading if para_is_chapter_heading_flag else active_chapter_context
            current_sent_subch_context = text_if_para_is_subchapter_heading if para_is_subchapter_heading_flag else active_subchapter_context


            # --- Experimental Sub-Sentence Split Logic ---
            # If this paragraph ITSELF was identified as a sub-chapter heading (e.g., para_text_cleaned IS "Some Sayings of the Prophet")
            # AND the NLTK sentence `current_segment` contains this heading text but not at the start.
            # This means NLTK combined pre-heading text with the heading text within this sub-chapter paragraph.
            if para_is_subchapter_heading_flag and text_if_para_is_subchapter_heading:
                # `text_if_para_is_subchapter_heading` is the actual heading text of this paragraph.
                heading_text_to_find = text_if_para_is_subchapter_heading
                
                try:
                    # Find where the actual heading text starts within the current NLTK sentence
                    # Using a simple find; regex might be more robust if heading text has special chars
                    # For this to work, heading_text_to_find must be a simple string without regex metacharacters
                    # or they should be escaped if using re.search.
                    # We assume clean_sent is the NLTK sentence.
                    
                    # Ensure we are looking for the exact heading text associated with THIS paragraph
                    # if it was identified as a sub_chapter_heading
                    
                    # If the current segment (NLTK sentence) contains the specific sub-chapter heading text of its parent paragraph
                    # AND that sub-chapter heading text is not at the beginning of the segment:
                    idx = current_segment.find(heading_text_to_find)

                    if idx > 0: # Heading found, but not at the start of this NLTK sentence
                        pre_text = current_segment[:idx].strip()
                        heading_onward_text = current_segment[idx:].strip()
                        
                        if pre_text:
                            logger.debug(f"    Sub-splitting P{i}.s{orig_sent_idx}: PRE-TEXT='{pre_text[:30]}...' for sub_ch '{heading_text_to_find}'")
                            # This pre-text is still part of the same sub-chapter paragraph.
                            # Its context is the sub-chapter itself.
                            res.append((
                                pre_text, 
                                f"{marker_base}.s{sent_idx_counter}_pre",
                                False, # This fragment is not a heading paragraph itself
                                True,  # Belongs to a sub-chapter paragraph
                                current_sent_ch_context, 
                                current_sent_subch_context # which is heading_text_to_find
                            ))
                            sent_idx_counter +=1
                        
                        if heading_onward_text:
                            res.append((
                                heading_onward_text,
                                f"{marker_base}.s{sent_idx_counter}",
                                False, 
                                True, # This part IS the sub-chapter heading text (or starts with it)
                                current_sent_ch_context,
                                current_sent_subch_context # which is heading_text_to_find
                            ))
                            sent_idx_counter +=1
                        continue # Skip adding the original unsplit NLTK sentence
                except Exception as e_split_sub:
                    logger.error(f"Error during sub-sentence split for sub_ch P{i}: {e_split_sub}", exc_info=True)
                    # Fallback to original sentence if split fails
            
            # If no split occurred, add the sentence as is
            res.append((
                current_segment, 
                f"{marker_base}.s{sent_idx_counter}", 
                para_is_chapter_heading_flag,    # True if the original paragraph was a chapter heading
                para_is_subchapter_heading_flag, # True if the original paragraph was a sub-chapter heading
                current_sent_ch_context,         # Chapter context for this sentence
                current_sent_subch_context       # Sub-chapter context for this sentence
            ))
            sent_idx_counter += 1
            
        # After processing all sentences of a paragraph, the active_chapter/subchapter_context
        # will have been updated if this paragraph was a heading.

    logger.info(f"--- DOCX Extraction Finished. Items: {len(res)} ---")
    return res

def extract_sentences_with_structure(*, file_content: bytes, filename: str, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]]:
    file_ext = filename.lower().rsplit(".", 1)[-1] if isinstance(filename, str) and '.' in filename else ""
    if not file_ext: raise ValueError("Invalid/extensionless filename")
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
            
    final_criteria = {"chapter": clean_ch_criteria, "sub_chapter": clean_sch_criteria}
    
    output_data = _extract_docx(data=file_content, heading_criteria=final_criteria)
    return output_data
