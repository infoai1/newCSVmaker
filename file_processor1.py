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
    if para_props.get('max_fsize-chapter heading? (i.e., did `is_sch` become true for `para34`'s full text?)
*   What was the `subch_context` assigned to `para34.s0`, `para34.s1`, etc.?

**It is highly likely that no change to the `chunker.py` you currently have (the 6-tuple input version) is needed.** The problem lies in the interaction between `file_processor.py`'s paragraph-level heading detection and NLTK's sentence tokenization.

**Please provide the `file_processor.py` DEBUG logs for the paragraph that contains "Some Sayings of the Prophet".** This will show us:
1.  If the paragraph itself was flagged as a heading.
2.  The exact NLTK sentences generated from it.
3.  The exact `ch_context` and `sub_pt', 0.0) < criteria['min_font_size']:
        rejection_reason = f"Font size {para_props.get('max_fsize_pt', 0.0):.1f}pt < min {criteria['min_font_size']:.1f}pt"
        passes_all_enabled_checks = False
    if passes_all_enabled_checks and para_props.get('alignment') != WD_ALIGN_PARAGRAPH.CENTER:
        align_val = para_props.get('alignment')
        align_str = str(align_val)
        if align_val ==ch_context` assigned to each of those NLTK sentences.

With that log, we can determine if `file_processor.py` needs a more aggressive internal splitting of NLTK sentences, or if the issue is simpler (e.g., `para34` isn't being flagged as a sub-chapter heading itself, leading to incorrect context inheritance for WD_ALIGN_PARAGRAPH.LEFT: align_str = "LEFT"
        elif align_val == WD_ALIGN_PARAGRAPH.RIGHT: align_str = "RIGHT"
        elif align_val == WD_ALIGN_PARAGRAPH.JUSTIFY: align_str = "JUSTIFY"
         its initial NLTK sentences).

For now, the files you should be using are:
*   **`app.pyelif align_val is None: align_str = "NOT SET"
        rejection_reason = f"Alignment: Not Centered (Actual: {align_str})"
        passes_all_enabled_checks = False`**: The version from your last message (from `sm_chunks (8).csv` / `sm_chunks (1
    return (True, f"Matches MinFont ({criteria['min_font_size']:.1f}pt) & Centered") if passes_all_enabled_checks else (False, rejection_reason)

def2).csv`).
*   **`file_processor.py`**: The version from my message just before you _extract_docx(data: bytes, heading_criteria: Dict[str, Dict[str, Any]]) -> uploaded `sm_chunks (8).csv` (the one titled "--- START OF FILE newCSVmaker-main/ List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]]:
    chfile_processor.py --- (Font Size & Centered Mandatory)" - this is the one that produces the 6-_criteria = heading_criteria.get("chapter", {})
    sch_criteria = heading_criteria.get("tuple `(sentence, marker, is_para_ch_hd, is_para_subch_hd, ch_contextsub_chapter", {})
    try: doc = docx.Document(io.BytesIO(data))
    except Exception as e: logger.error(f"Failed to open DOCX stream: {e}", exc_, subch_context)`).
*   **`chunker.py`**: The version from your last message (frominfo=True); return []

    res: List[Tuple[str, str, bool, bool, Optional[ `sm_chunks (8).csv` / `sm_chunks (12).csv` - this is the one that consumesstr], Optional[str]]] = []
    
    # These track the context ESTABLISHED BY THE PREVIOUS PARAGRAPH that was a heading
    active_ch_context_from_prev_paras = DEFAULT_CHAPTER the 6-tuple and has the refined logic to split on paragraph heading flags).

Run with these and get the_TITLE_FALLBACK
    active_subch_context_from_prev_paras = DEFAULT_SUBCHAPTER `file_processor.py` DEBUG logs.
