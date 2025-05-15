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
        logger.debug(f"    [{type_label}] Criteria insufficient (min_font_size missing or alignment_centered not True). Text: '{text[:30]}...' Criteria: {criteria}")
        return False, "Core criteria (min_font_size / alignment_centered) missing or not True"

    rejection_reason = "Matches all criteria"
    passes_all_enabled_checks = True
    
    # logger.debug(f"    [{type_label}] Checking text: '{text[:40]}...' with MinFontSize={criteria['min_font_size']:.1f}pt & Centered={criteria['alignment_centered']} against ParaMaxFontSize={para_props.get('max_fsize_pt', 0.0):.1f}pt, ParaAlign={para_props.get('alignment')}")

    if para_props.get('max_fsize_pt', 0.0) < criteria['min_font_size']:
        rejection_reason = f"Font size {para_props.get('max_fsize_pt', 0.0):.1f}pt < min {criteria['min_font_size']:.1f}pt"
        passes_all_enabled_checks = False
    
    if passes_all_enabled_checks: 
        if para_props.get('alignment') != WD_ALIGN_PARAGRAPH.CENTER:
            align_val = para_props.get('alignment')
            align_str = str(align_val)
            if align_val == WD_ALIGN_PARAGRAPH.LEFT: align_str = "LEFT"
            elif align_val == WD_ALIGN_PARAGRAPH.RIGHT: align_str = "RIGHT"
            elif align_val == WD_ALIGN_PARAGRAPH.JUSTIFY: align_str = "JUSTIFY"
            elif align_val is None: align_str = "NOT SET (likely LEFT)"
            rejection_reason = f"Alignment: Not Centered (Actual: {align_str})"
            passes_all_enabled_checks = False

    # if passes_all_enabled_checks:
    #     logger.debug(f"    [{type_label}] PASS: '{text[:30]}...' matches Font Size & Centered criteria.")
    # else:
    #     logger.debug(f"    [{type_label}] FAIL for '{text[:30]}...': {rejection_reason}")
        
    return (True, f"Matches Font Size ({criteria['min_font_size']:.1f}pt) & Centered") if passes_all_enabled_checks else (False, rejection_reason)


def _extract_docx(data: bytes, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]]:
    # OUTPUT: (sentence, marker, is_para_chapter_heading, is_para_subchapter_heading, chapter_context, subchapter_context)
    ch_criteria = heading_criteria.get("chapter", {})
    sch_criteria = heading_criteria.get("sub_chapter", {})

    try: doc = docx.Document(io.BytesIO(data))
    except Exception as e:
        logger.error(f"Failed to open DOCX stream: {e}", exc_info=True); return []

    # Change res type hint
    res: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]] = []
    current_chapter_context = DEFAULT_CHAPTER_TITLE_FALLBACK
    current_subchapter_context = DEFAULT_SUBCHAPTER_TITLE_FALLBACK

    logger.info(f"--- Starting DOCX Extraction (FONT SIZE & CENTERED Mandatory Criteria) ---")
    # logger.debug(f"Chapter Criteria: {ch_criteria}")
    # logger.debug(f"Sub-Chapter Criteria: {sch_criteria if sch_criteria else 'Detection Disabled'}")

    for i, para in enumerate(doc.paragraphs, 1):
        para_text_cleaned = _clean(para.text) # This is the full paragraph text
        marker_base = f"para{i}"
        if not para_text_cleaned: continue

        # logger.debug(f"--- Para {i} [{marker_base}] Text: '{para_text_cleaned[:60]}...' ---")

        para_max_fsize_pt = 0.0
        para_align = para.alignment
        para_fonts = set() # For logging
        para_is_bold = False # For logging
        para_is_italic = False # For logging

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
            'font_names_in_para': para_fonts, 
            'is_bold_present': para_is_bold,   
            'is_italic_present': para_is_italic 
        }
        # logger.debug(f"  Para {i} Props: SizePt={para_max_fsize_pt:.1f}, Align={para_align}")
        
        # Determine if this paragraph AS A WHOLE is a chapter or sub-chapter heading
        para_is_chapter_heading = False
        para_is_subchapter_heading = False

        # Check for Chapter Heading
        is_ch, ch_reason = False, "Chapter criteria not met or disabled"
        if ch_criteria and ch_criteria.get('min_font_size') is not None and ch_criteria.get('alignment_centered') is True:
             is_ch, ch_reason = _matches_criteria_docx_font_size_and_centered(para_text_cleaned, para_props, ch_criteria, "Chapter")
        
        if is_ch:
            current_chapter_context = para_text_cleaned # The heading text becomes the context
            current_subchapter_context = DEFAULT_SUBCHAPTER_TITLE_FALLBACK # Reset
            para_is_chapter_heading = True
            logger.info(f"  ==> Para {i} Classified as CHAPTER: '{para_text_cleaned[:50]}' (Reason: {ch_reason})")
        else:
            # Check for Sub-Chapter Heading only if it's not a chapter
            is_sch, sch_reason = False, "Sub-chapter criteria not met, disabled, or already chapter"
            if sch_criteria and sch_criteria.get('min_font_size') is not None and sch_criteria.get('alignment_centered') is True:
                # Ensure sub-chapter font size is distinct if chapter detection is also active
                if ch_criteria.get('min_font_size') is None or sch_criteria['min_font_size'] < ch_criteria.get('min_font_size', float('inf')):
                    is_sch, sch_reason = _matches_criteria_docx_font_size_and_centered(para_text_cleaned, para_props, sch_criteria, "Sub-Chapter")
                # else: sch_reason = "Sub-ch min_font_size not distinct from ch min_font_size."
            
            if is_sch:
                current_subchapter_context = para_text_cleaned # The heading text becomes the context
                para_is_subchapter_heading = True
                logger.info(f"  ==> Para {i} Classified as SUB-CHAPTER: '{para_text_cleaned[:50]}' (Reason: {sch_reason})")
            # else:
                # logger.debug(f"  Para {i} Classified as BODY. (Ch fail: '{ch_reason}', SubCh fail: '{sch_reason}')")


        # NLTK Sentence Tokenization of the paragraph's cleaned text
        try:
            sentences = nltk.sent_tokenize(para_text_cleaned)
            if not sentences and para_text_cleaned: sentences = [para_text_cleaned]
        except Exception as e:
            logger.error(f"NLTK tokenization fail P{i}: {e}",exc_info=True); sentences=[para_text_cleaned] if para_text_cleaned else []

        for sent_idx, sent_text in enumerate(sentences):
             clean_sent = sent_text.strip()
             if clean_sent:
                # Pass the flags indicating if the original paragraph was a heading
                res.append((
                    clean_sent, 
                    f"{marker_base}.s{sent_idx}", 
                    para_is_chapter_heading,      # Was the original para a chapter heading?
                    para_is_subchapter_heading,   # Was the original para a subchapter heading?
                    current_chapter_context,      # The current chapter context
                    current_subchapter_context    # The current subchapter context
                ))

    logger.info(f"--- DOCX Extraction Finished. Items: {len(res)} ---")
    return res

def extract_sentences_with_structure(*, file_content: bytes, filename: str, heading_criteria: Dict[str, Dict[str, Any]]) -> List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]]:
    # Return type hint updated
    file_ext = filename.lower().rsplit(".", 1)[-1] if isinstance(filename, str) and '.' in filename else ""
    if not file_ext: raise ValueError("Invalid/extensionless filename")
    if file_ext != "docx": raise ValueError(f"Unsupported file type: {file_ext}. Expected DOCX.")
            
    clean_ch_criteria = {}
    if heading_criteria.get("chapter"):
        clean_ch_criteria['min_font_size'] = heading_criteria["chapter"].get('min_font_size')
        if heading_criteria["chapter"].get('alignment_centered') is True:
            clean_ch_criteria['alignment_centered'] = True
    
    clean_sch_criteria = {}
    if heading_criteria.get("sub_chapter"): 
        sch_min_fs = heading_criteria["sub_chapter"].get('min_font_size')
        if sch_min_fs is not None: clean_sch_criteria['min_font_size'] = sch_min_fs
        if heading_criteria["sub_chapter"].get('alignment_centered') is True:
            clean_sch_criteria['alignment_centered'] = True
            
    final_criteria = {"chapter": clean_ch_criteria, "sub_chapter": clean_sch_criteria}
    
    output_data = _extract_docx(data=file_content, heading_criteria=final_criteria)
    return output_data
