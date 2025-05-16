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
    # These track the context established by the LAST heading paragraph encountered
    active_chapter_heading_text = DEFAULT_CHAPTER_TITLE_FALLBACK
    active_subchapter_heading_text = DEFAULT_SUBCHAPTER_TITLE_FALLBACK 

    logger.info(f"--- Starting DOCX Extraction (Experimental Sub-Sentence Split) ---")

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
        # These flags and texts are specific TO THIS PARAGRAPH if it's a heading.
        current_para_is_chapter_heading = False
        current_para_is_subchapter_heading = False
        # If this paragraph is a heading, its text is stored here. Otherwise, these are None.
        this_para_ch_heading_text_if_any: Optional[str] = None
        this_para_subch_heading_text_if_any: Optional[str] = None

        is_ch, _ = _matches_criteria_docx_font_size_and_centered(para_text_cleaned, para_props, ch_criteria, "Chapter")
        if is_ch:
            current_para_is_chapter_heading = True
            this_para_ch_heading_text_if_any = para_text_cleaned
            active_chapter_heading_text = para_text_cleaned # Update active context
            active_subchapter_heading_text = DEFAULT_SUBCHAPTER_TITLE_FALLBACK # Reset sub-chapter on new chapter
            logger.info(f"  Para {i} IS CHAPTER: '{para_text_cleaned[:50]}'")
        else:
            is_sch, _ = _matches_criteria_docx_font_size_and_centered(para_text_cleaned, para_props, sch_criteria, "Sub-Chapter")
            # A paragraph is a sub-chapter only if it's not a chapter and meets sub-chapter criteria
            if is_sch and (ch_criteria.get('min_font_size') is None or sch_criteria.get('min_font_size',0) < ch_criteria.get('min_font_size', float('inf'))):
                current_para_is_subchapter_heading = True
                this_para_subch_heading_text_if_any = para_text_cleaned
                active_subchapter_heading_text = para_text_cleaned # Update active context
                logger.info(f"  Para {i} IS SUB-CHAPTER: '{para_text_cleaned[:50]}'")
            # If not a chapter and not a sub-chapter, it's body text. It inherits active_chapter_heading_text and active_subchapter_heading_text.

        try:
            nltk_sentences = nltk.sent_tokenize(para_text_cleaned)
            if not nltk_sentences and para_text_cleaned: nltk_sentences = [para_text_cleaned]
        except Exception as e:
            logger.error(f"NLTK tokenization fail P{i}: {e}",exc_info=True); nltk_sentences=[para_text_cleaned] if para_text_cleaned else []

        sent_idx_counter = 0
        for orig_sent_idx, sent_text in enumerate(nltk_sentences):
            clean_sent = sent_text.strip()
            if not clean_sent: continue

            sentences_to_add = [] # List to hold potentially split sentences

            # --- Experimental Sub-Sentence Splitting Logic ---
            # If this paragraph was identified as a sub-chapter heading,
            # AND the current NLTK sentence contains that sub-chapter heading's text,
            # AND that heading text is not at the very beginning of the NLTK sentence,
            # then we attempt to split it.
            if current_para_is_subchapter_heading and this_para_subch_heading_text_if_any:
                try:
                    # Find the start of the sub-chapter heading text within the NLTK sentence
                    # Use regex to find the exact phrase, case-insensitively for robustness,
                    # but the split should use the original casing.
                    # The heading text itself might have punctuation, so escape it for regex.
                    heading_pattern = re.escape(this_para_subch_heading_text_if_any)
                    match = re.search(heading_pattern, clean_sent, re.IGNORECASE)

                    if match:
                        start_index = match.start()
                        if start_index > 0: # Heading found, but not at the start of the NLTK sentence
                            pre_heading_text = clean_sent[:start_index].strip()
                            actual_heading_and_post_text = clean_sent[start_index:].strip()
                            
                            if pre_heading_text:
                                logger.debug(f"    Sub-splitting P{i}.s{orig_sent_idx}: PRE-TEXT='{pre_heading_text[:30]}...'")
                                # This pre-text belongs to the context *before* this sub-chapter was introduced.
                                # If this sub-chapter started a new chapter, then sub-ch context is default.
                                # If this sub-chapter is under the current chapter, then its pre-text inherits previous_subchapter_context
                                sentences_to_add.append({
                                    "text": pre_heading_text, "marker_suffix": f"{sent_idx_counter}_pre",
                                    "is_ch_hd_para": False, "is_subch_hd_para": False, # This part is not a heading itself
                                    "ch_ctx": active_chapter_heading_text, 
                                    "subch_ctx": DEFAULT_SUBCHAPTER_TITLE_FALLBACK if current_para_is_chapter_heading else previous_subchapter_context_before_this_subch_para_was_defined
                                })
                                sent_idx_counter +=1
                            
                            if actual_heading_and_post_text:
                                sentences_to_add.append({
                                    "text": actual_heading_and_post_text, "marker_suffix": f"{sent_idx_counter}",
                                    "is_ch_hd_para": current_para_is_chapter_heading, # Could be True if a CH is also a SCH
                                    "is_subch_hd_para": True, # This part contains/is the sub_ch heading
                                    "ch_ctx": active_chapter_heading_text,
                                    "subch_ctx": this_para_subch_heading_text_if_any 
                                })
                                sent_idx_counter +=1
                        else: # Heading is at the start of the NLTK sentence, no pre-text to split
                            sentences_to_add.append({
                                "text": clean_sent, "marker_suffix": f"{sent_idx_counter}",
                                "is_ch_hd_para": current_para_is_chapter_heading,
                                "is_subch_hd_para": current_para_is_subchapter_heading,
                                "ch_ctx": active_chapter_heading_text,
                                "subch_ctx": active_subchapter_heading_text 
                            })
                            sent_idx_counter +=1
                    else: # Heading text not found in this NLTK sentence (shouldn't happen if para IS heading)
                        sentences_to_add.append({
                            "text": clean_sent, "marker_suffix": f"{sent_idx_counter}",
                            "is_ch_hd_para": current_para_is_chapter_heading,
                            "is_subch_hd_para": current_para_is_subchapter_heading,
                            "ch_ctx": active_chapter_heading_text,
                            "subch_ctx": active_subchapter_heading_text
                        })
                        sent_idx_counter +=1
                except Exception as e_split:
                    logger.error(f"Error during experimental sub-sentence split for P{i}: {e_split}", exc_info=True)
                    # Fallback to adding the original sentence if split fails
                    sentences_to_add.append({
                        "text": clean_sent, "marker_suffix": f"{sent_idx_counter}",
                        "is_ch_hd_para": current_para_is_chapter_heading,
                        "is_subch_hd_para": current_para_is_subchapter_heading,
                        "ch_ctx": active_chapter_heading_text,
                        "subch_ctx": active_subchapter_heading_text
                    })
                    sent_idx_counter +=1
            else: # Not a sub-chapter paragraph, or no sub-chapter heading text to split by
                 sentences_to_add.append({
                    "text": clean_sent, "marker_suffix": f"{sent_idx_counter}",
                    "is_ch_hd_para": current_para_is_chapter_heading, # True if the whole para was a CH
                    "is_subch_hd_para": current_para_is_subchapter_heading, # True if the whole para was a SCH
                    "ch_ctx": active_chapter_heading_text, # Context from last CH heading
                    "subch_ctx": active_subchapter_heading_text # Context from last SCH heading (or default if reset by new CH)
                })
                 sent_idx_counter += 1

            for s_data in sentences_to_add:
                res.append((
                    s_data["text"], 
                    f"{marker_base}.{s_data['marker_suffix']}", 
                    s_data["is_ch_hd_para"],
                    s_data["is_subch_hd_para"],
                    s_data["ch_ctx"], 
                    s_data["subch_ctx"]
                ))
        
        # Update `previous_subchapter_context_before_this_subch_para_was_defined` for the next paragraph
        # This needs to be the context that was active *before* this paragraph might have defined a new one.
        # This is complex because `active_subchapter_heading_text` gets updated if para IS subch.
        # Let's simplify: the "previous" context is simply what `active_subchapter_heading_text` was at the start of this para loop.
        # However, `active_subchapter_heading_text` is updated mid-loop.
        # The state `active_subchapter_heading_text` already carries the correct "previous" or "current" context for body text.
        # The experimental split logic needs to be careful with `previous_subchapter_context_before_this_subch_para_was_defined`.
        # For now, the split logic is simplified and might not perfectly handle all inherited contexts for pre-text.
        # The most important part is splitting the sentence. The chunker will then sort out contexts.
        # The `active_chapter_heading_text` and `active_subchapter_heading_text` are updated correctly
        # if the paragraph itself was a heading.

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
