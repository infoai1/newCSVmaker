import fitz  # PyMuPDF
import docx
import re
import nltk
import io
import logging
import statistics
from typing import List, Tuple, Dict, Optional, Any

import streamlit as st

# --------------------------------------------------
# Logging
# --------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --------------------------------------------------
# NLTK – ensure punkt
# --------------------------------------------------

def _ensure_punkt() -> None:
    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        nltk.download("punkt", quiet=True)

# --------------------------------------------------
# Glyph normalisation
# --------------------------------------------------
GLYPH_MAP_BASE: Dict[str, str] = {
    # broken small‑caps → normal
    "!e ": "The ", "!E ": "THE ", "#e ": "The ", "#E ": "THE ",
    # ligatures
    "ﬂ": "fl", "ﬁ": "fi", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
}


def normalise_glyphs(text: str, extra_map: Optional[Dict[str, str]] = None) -> str:
    """Return *text* after applying GLYPH_MAP_BASE plus *extra_map* overrides."""
    glyph_map = GLYPH_MAP_BASE.copy()
    if extra_map:
        glyph_map.update(extra_map)
    for bad, good in glyph_map.items():
        text = text.replace(bad, good)
    return text

# --------------------------------------------------
# Heading classifier helper
# --------------------------------------------------

def _qualifies(text: str, *, criteria: Dict[str, Any]) -> bool:
    """Check a line against the active heading criteria."""
    # regex / keyword
    if criteria.get("check_pattern") and criteria.get("pattern_regex"):
        if not criteria["pattern_regex"].search(text):
            return False

    # word‑count
    if criteria.get("check_word_count"):
        wc = len(text.split())
        if not (criteria["word_count_min"] <= wc <= criteria["word_count_max"]):
            return False

    # case
    if criteria.get("check_case"):
        if criteria.get("case_upper") and not text.isupper():
            return False
        if criteria.get("case_title") and not text.istitle():
            return False

    return True

# --------------------------------------------------
# PDF extraction helper
# --------------------------------------------------

def _extract_pdf(
    *,
    data: bytes,
    skip_start: int,
    skip_end: int,
    first_page_offset: int,
    heading_criteria: Dict[str, Any],
    extra_glyphs: Dict[str, str],
) -> List[Tuple[str, str, Optional[str]]]:

    doc = fitz.open(stream=data, filetype="pdf")

    # --- determine adaptive font threshold if font‑size check is ON ---
    adaptive_min_size = None
    if heading_criteria.get("check_font_size"):
        sizes: List[float] = []
        for pno in range(doc.page_count):
            for span in doc.load_page(pno).get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]:
                if span["type"] == 0:
                    for line in span["lines"]:
                        for sp in line["spans"]:
                            sizes.append(sp["size"])
        if sizes:
            avg = statistics.mean(sizes)
            sd = statistics.pstdev(sizes) or 1.0
            adaptive_min_size = avg + sd * 0.5  # ½ σ above average counts as heading
            logging.info("Adaptive font threshold ≈ %.1f pt", adaptive_min_size)

    def bigger_font(size: float) -> bool:
        if not heading_criteria.get("check_font_size"):
            return True
        return size >= (adaptive_min_size or heading_criteria["font_size_min"])

    results: List[Tuple[str, str, Optional[str]]] = []

    for page_no in range(skip_start, doc.page_count - skip_end):
        page = doc.load_page(page_no)
        text_dict = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)

        for blk in text_dict["blocks"]:
            if blk["type"] != 0:
                continue

            # join text of the block into one string (keeps headings intact)
            blk_text = "\n".join(sp["text"] for line in blk["lines"] for sp in line["spans"])
            blk_text = normalise_glyphs(blk_text, extra_map=extra_glyphs)

            # pick the *largest* span size in the block for quick heading guess
            max_span_size = max(sp["size"] for line in blk["lines"] for sp in line["spans"])

            sentences = nltk.sent_tokenize(blk_text)
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                marker = f"p{page_no + first_page_offset}"
                heading = sent if (bigger_font(max_span_size) and _qualifies(sent, criteria=heading_criteria)) else None
                results.append((sent, marker, heading))

    doc.close()
    return results

# --------------------------------------------------
# DOCX extraction helper
# --------------------------------------------------

def _extract_docx(
    *,
    data: bytes,
    heading_criteria: Dict[str, Any],
    extra_glyphs: Dict[str, str],
) -> List[Tuple[str, str, Optional[str]]]:
    doc = docx.Document(io.BytesIO(data))
    out: List[Tuple[str, str, Optional[str]]] = []

    for idx, para in enumerate(doc.paragraphs, 1):
        text = normalise_glyphs(para.text.strip(), extra_map=extra_glyphs)
        if not text:
            continue
        marker = f"para{idx}"
        heading = text if _qualifies(text, criteria=heading_criteria) else None
        out.append((text, marker, heading))
    return out

# --------------------------------------------------
# Public API function
# --------------------------------------------------

def extract_sentences_with_structure(
    *,
    file_content: bytes,
    filename: str,
    pdf_skip_start: int = 0,
    pdf_skip_end: int = 0,
    pdf_first_page_offset: int = 1,
    heading_criteria: Dict[str, Any],
    subtitle_criteria: Dict[str, Any] = None,
    extra_glyphs: Dict[str, str] = None,
) -> List[Tuple[str, str, Optional[str]]]:
    """Return (sentence, marker, heading_or_None) list for either PDF or DOCX."""

    _ensure_punkt()
    extra_glyphs = extra_glyphs or {}

    ext = filename.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        return _extract_pdf(
            data=file_content,
            skip_start=pdf_skip_start,
            skip_end=pdf_skip_end,
            first_page_offset=pdf_first_page_offset,
            heading_criteria=heading_criteria,
            extra_glyphs=extra_glyphs,
        )
    if ext == "docx":
        return _extract_docx(
            data=file_content,
            heading_criteria=heading_criteria,
            extra_glyphs=extra_glyphs,
        )
    raise ValueError("Unsupported file type: " + filename)
