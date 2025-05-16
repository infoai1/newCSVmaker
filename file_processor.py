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
    current_chapter_context = DEFAULT_CHAPTER_TITLE_FALLBACK
    previous_subchapter_context = DEFAULT_SUBCHAPTER_TITLE_FALLBACK # Track context before this paragraph

    logger.info(f"--- Starting DOCX Extraction (Attempting intra-sentence heading split) ---")

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
        
        # Determine paragraph's own heading status and text if it IS a heading
        para_is_chapter_heading, para_is_subchapter_heading = False, False
        para_chapter_heading_text, para_subchapter_heading_text = None, None

        is_ch, ch_reason = _matches_criteria_docx_font_size_and_centered(para_text_cleaned, para_props, ch_criteria, "Chapter")
        if is_ch:
            para_is_chapter_heading = True
            para_chapter_heading_text = para_text_cleaned
            current_chapter_context = para_text_cleaned
            previous_subchapter_context = DEFAULT_SUBCHAPTER_TITLE_FALLBACK # Reset sub-chapter on new chapter
            logger.info(f"  ==> Para {i} IS CHAPTER: '{para_text_cleaned[:50]}'")
        else:
            is_sch, sch_reason = _matches_criteria_docx_font_size_and_centered(para_text_cleaned, para_props, sch_criteria, "Sub-Chapter")
            if is_sch and (ch_criteria.get('min_font_size') is None or sch_criteria.get('min_font_size',0) < ch_criteria.get('min_font_size', float('inf'))):
                para_is_subchapter_heading = True
                para_subchapter_heading_text = para_text_cleaned
                # The context for sentences FROM this paragraph will be this new sub-chapter.
                # The `previous_subchapter_context` is what was active BEFORE this paragraph.
                # We update `current_subchapter_context` later when assigning to sentences.
                logger.info(f"  ==> Para {i} IS SUB-CHAPTER: '{para_text_cleaned[:50]}'")


        # Tokenize paragraph into NLTK sentences
        try:
            nltk_sentences = nltk.sent_tokenize(para_text_cleaned)
            if not nltk_sentences and para_text_cleaned: nltk_sentences = [para_text_cleaned]
        except Exception as e:
            logger.error(f"NLTK tokenization fail P{i}: {e}",exc_info=True); nltk_sentences=[para_text_cleaned] if para_text_cleaned else []

        sent_idx_counter = 0 # For unique sentence markers after potential splits

        # The context to apply to sentences from this paragraph.
        # If this para IS a heading, its own text becomes the new context.
        # Otherwise, it inherits.
        para_ch_context_to_apply = para_chapter_heading_text if para_is_chapter_heading else current_chapter_context
        para_subch_context_to_apply = para_subchapter_heading_text if para_is_subchapter_heading else \
                                     (previous_subchapter_context if not para_is_chapter_heading else DEFAULT_SUBCHAPTER_TITLE_FALLBACK)


        for orig_sent_idx, sent_text in enumerate(nltk_sentences):
            clean_sent = sent_text.strip()
            if not clean_sent: continue

            # This is the crucial experimental part:
            # If this paragraph ITSELF was NOT a sub-chapter heading, 
            # BUT we find text within its NLTK-sentence that LOOKS like a known sub-chapter heading text
            # (this implies we need a list of all detected sub-chapter heading texts, or refine this logic)
            # For now, we'll simplify: if `para_subchapter_heading_text` (the text of *this* paragraph if it was a sub_ch heading)
            # is found within an NLTK sentence of this paragraph, and doesn't start it.
            
            # If the paragraph ITSELF was identified as a sub-chapter:
            if para_is_subchapter_heading and para_subchapter_heading_text:
                # The context for all its sentences is this sub-chapter title.
                # This means `para_subch_context_to_apply` is `para_subchapter_heading_text`.
                # If `sent_text` is just part of this heading paragraph, no internal split needed based on this rule.
                # The `chunker` should handle the transition correctly if the previous paragraph had a different context.
                pass # No internal split needed based on this rule alone. `chunker` handles context changes.
            
            # More general problem: what if an NLTK sentence contains a heading text that was identified
            # as the `current_subchapter_context` for this paragraph, but isn't at the start of the NLTK sentence?
            # This is what happens with "para19.s6".
            # `current_subchapter_context` for sentences in `para19` becomes "The Wisdom of Creation"
            # *because* `para19` itself was classified as that sub-chapter.

            # The core of the issue in the CSV for para19.s6 is that "The Wisdom of Creation" is the sub-chapter title
            # for the entire paragraph from which para19.s6 was derived. The text *before* "The Wisdom of Creation"
            # in that same paragraph is, by definition, part of that sub-chapter.
            # The chunker correctly identifies that para19.s6 (and thus its parent paragraph) starts a new sub-chapter context.

            # The only way to split "...Creator. The Wisdom of Creation..." is if "The Wisdom of Creation"
            # is considered a heading distinct from the paragraph it's in, which means `file_processor`
            # would need to look for heading patterns *inside* NLTK sentences.
            # This is beyond the current "paragraph-level heading detection" scope.

            # Sticking to the current model: paragraph-level heading detection.
            # The previous `chunker.py` correctly splits between different paragraph contexts.
            # The "issue" is an artifact of NLTK sentence splitting combined with how
            # a heading might be formatted within its own paragraph.

            # For clarity, the flags passed to chunker should reflect the original paragraph's status.
            # The contexts are what that sentence should "inherit" or "belong to".
            res.append((
                clean_sent, 
                f"{marker_base}.s{sent_idx_counter}", 
                para_is_chapter_heading,
                para_is_subchapter_heading,
                para_ch_context_to_apply, # Chapter context for this sentence
                para_subch_context_to_apply # Sub-chapter context for this sentence
            ))
            sent_idx_counter += 1
        
        # After processing all sentences in a paragraph, update the "previous" context trackers
        # if this paragraph established a new context.
        if para_is_chapter_heading:
            current_chapter_context = para_chapter_heading_text
            previous_subchapter_context = DEFAULT_SUBCHAPTER_TITLE_FALLBACK # Reset on new chapter
        elif para_is_subchapter_heading:
            previous_subchapter_context = para_subchapter_heading_text


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
