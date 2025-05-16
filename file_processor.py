import docx
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import io
import re 
import nltk # Still needed for body text
import logging
from typing import List, Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

DEFAULT_CHAPTER_TITLE_FALLBACK = "Introduction"
DEFAULT_SUBCHAPTER_TITLE_FALLBACK = None # Represent no active sub-chapter
RE_WS = re.compile(r"\s+")

def _clean(raw: str) -> str:
    txt = raw.replace("\n", " ") # Consolidate newlines from paragraph text
    return RE_WS.sub(" ", txt).strip()

def _get_paragraph_properties(para: docx.text.paragraph.Paragraph) -> Dict[str, Any]:
    """Extracts relevant properties (max font size, alignment) from a paragraph."""
    max_fsize_pt = 0.0
    # Note: paragraph.alignment can be None if not explicitly set (inherits). 
    # WD_ALIGN_PARAGRAPH.LEFT is 0, which is often the default if None.
    alignment = para.alignment if para.alignment is not None else WD_ALIGN_PARAGRAPH.LEFT 

    # Extract font size from runs - consider only runs with text
    has_text_in_runs = False
    if para.runs:
        for run in para.runs:
            if run.text.strip(): # Only consider runs that contribute visible text
                has_text_in_runs = True
                if run.font.size:
                    try:
                        max_fsize_pt = max(max_fsize_pt, run.font.size.pt)
                    except AttributeError: # run.font.size might be None
                        pass
    
    # If no runs with text, or no font size found, max_fsize_pt remains 0.0
    # If paragraph text exists but no runs with text (e.g. empty runs, fields), this might be an issue.
    # However, for typical text, this should work.
    if not has_text_in_runs and para.text.strip(): # Paragraph has text but not in discernible runs with size
        logger.debug(f"Paragraph has text '{para.text[:30]}...' but no runs with font size found. Max font size defaults to 0.")


    return {'max_fsize_pt': max_fsize_pt, 'alignment': alignment}

def _check_heading_criteria_line_by_line(
    line_text: str, 
    line_props: Dict[str, Any], 
    criteria: Dict[str, Any]
) -> bool:
    """Checks if a line (paragraph) meets font size and centered criteria."""
    if not criteria or criteria.get('min_font_size') is None or criteria.get('alignment_centered') is not True:
        return False # Essential criteria missing

    # Check Font Size
    if line_props.get('max_fsize_pt', 0.0) < criteria['min_font_size']:
        return False
    
    # Check Alignment
    if line_props.get('alignment') != WD_ALIGN_PARAGRAPH.CENTER:
        return False
        
    return True

def _extract_docx(data: bytes, heading_criteria: Dict[str, Dict[str, Any]]) \
    -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    # OUTPUT: (text_segment, marker, chapter_context, subchapter_context)
    # text_segment is EITHER a full heading line OR an NLTK sentence from body text.

    ch_criteria = heading_criteria.get("chapter", {})
    sch_criteria = heading_criteria.get("sub_chapter", {})

    try: 
        doc = docx.Document(io.BytesIO(data))
    except Exception as e: 
        logger.error(f"Failed to open DOCX stream: {e}", exc_info=True)
        return []

    res: List[Tuple[str, str, Optional[str], Optional[str]]] = []
    
    # These track the most recently established chapter and sub-chapter TEXTS
    active_chapter_title = DEFAULT_CHAPTER_TITLE_FALLBACK
    active_subchapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK 

    logger.info(f"--- Starting DOCX Extraction (Line-by-Line Heading Check) ---")
    logger.debug(f"Chapter Criteria: {ch_criteria}")
    logger.debug(f"Sub-Chapter Criteria: {sch_criteria if sch_criteria else 'Sub-chapter detection disabled'}")

    for i, para in enumerate(doc.paragraphs, 1):
        para_text_cleaned = _clean(para.text) 
        para_marker_base = f"para{i}"

        if not para_text_cleaned:
            # logger.debug(f"  Para {i} is empty, skipping.")
            continue

        para_props = _get_paragraph_properties(para)
        logger.debug(f"  Para {i} Text: '{para_text_cleaned[:60]}...' Props: SizePt={para_props['max_fsize_pt']:.1f}, Align={para_props['alignment']}")

        is_chapter_line = _check_heading_criteria_line_by_line(para_text_cleaned, para_props, ch_criteria)
        
        if is_chapter_line:
            active_chapter_title = para_text_cleaned
            active_subchapter_title = DEFAULT_SUBCHAPTER_TITLE_FALLBACK # Reset sub-chapter
            res.append((para_text_cleaned, f"{para_marker_base}.s0", active_chapter_title, active_subchapter_title))
            logger.info(f"    ==> Para {i} IS CHAPTER: '{active_chapter_title[:50]}'")
        else:
            is_subchapter_line = False
            if sch_criteria: # Only check if sub-chapter detection is enabled
                 # Ensure sub-chapter font size is distinct from chapter's to avoid ambiguity if both are checked
                if ch_criteria.get('min_font_size') is None or \
                   sch_criteria.get('min_font_size',0) < ch_criteria.get('min_font_size', float('inf')):
                    is_subchapter_line = _check_heading_criteria_line_by_line(para_text_cleaned, para_props, sch_criteria)
                else:
                    logger.debug(f"    Para {i} Sub-chapter check skipped: min_font_size not distinct from chapter's for '{para_text_cleaned[:30]}...'")


            if is_subchapter_line:
                active_subchapter_title = para_text_cleaned
                # Chapter context remains the current active_chapter_title
                res.append((para_text_cleaned, f"{para_marker_base}.s0", active_chapter_title, active_subchapter_title))
                logger.info(f"    ==> Para {i} IS SUB-CHAPTER: '{active_subchapter_title[:50]}' (under Ch: '{active_chapter_title[:30]}...')")
            else:
                # This line is body text. Split it into NLTK sentences.
                # These sentences inherit the last known active_chapter_title and active_subchapter_title.
                logger.debug(f"    Para {i} is BODY TEXT. Applying NLTK sentence tokenization.")
                try:
                    nltk_sentences = nltk.sent_tokenize(para_text_cleaned)
                    if not nltk_sentences and para_text_cleaned: 
                        nltk_sentences = [para_text_cleaned] 
                except Exception as e_nltk:
                    logger.error(f"NLTK tokenization fail P{i}: {e_nltk}",exc_info=True)
                    nltk_sentences=[para_text_cleaned] if para_text_cleaned else []

                for sent_idx, individual_sent_text in enumerate(nltk_sentences):
                    clean_individual_sent = individual_sent_text.strip()
                    if clean_individual_sent:
                        res.append((
                            clean_individual_sent, 
                            f"{para_marker_base}.s{sent_idx}", 
                            active_chapter_title,       
                            active_subchapter_title    
                        ))
    
    logger.info(f"--- DOCX Line-by-Line Extraction Finished. Total segments: {len(res)} ---")
    return res

def extract_sentences_with_structure(*, file_content: bytes, filename: str, heading_criteria: Dict[str, Dict[str, Any]]) \
    -> List[Tuple[str, str, Optional[str], Optional[str]]]: # Return type hint updated
    """Wrapper for extraction, prepares criteria for _extract_docx."""
    # This function primarily just passes through, ensuring criteria dicts are somewhat valid.
    # The new _extract_docx handles the "line-by-line" logic.
    
    file_ext = filename.lower().rsplit(".", 1)[-1] if isinstance(filename, str) and '.' in filename else ""
    if not file_ext: raise ValueError("Invalid or extensionless filename provided")
    if file_ext != "docx": raise ValueError(f"Unsupported file type: {file_ext}. Expected DOCX.")
            
    # Criteria passed from app.py should already be clean (min_font_size, alignment_centered:True)
    # No further cleaning needed here if app.py sends the correct structure.
    
    output_data = _extract_docx(data=file_content, heading_criteria=heading_criteria)
    return output_data
