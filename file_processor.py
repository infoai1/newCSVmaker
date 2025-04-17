import fitz  # PyMuPDF
import docx
import re
import nltk
import io
import logging
import statistics
from typing import List, Tuple, Dict, Optional, Any

import streamlit as st

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

# --------------------------------------------------
# NLTK setup – ensure punkt models are present
# --------------------------------------------------

def _ensure_punkt() -> None:
    for res in ("punkt", "punkt_tab"):
        try:
            nltk.data.find(f"tokenizers/{res}")
        except LookupError:
            nltk.download(res, quiet=True)

# --------------------------------------------------
# Glyph normalisation map
# --------------------------------------------------
GLYPH_MAP: Dict[str, str] = {
    "!e ": "The ", "!E ": "THE ", "#e ": "The ", "#E ": "THE ",
    "ﬂ": "fl", "ﬁ": "fi", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
}


def normalise(text: str, extra: Optional[Dict[str, str]] = None) -> str:
    mapping = {**GLYPH_MAP, **(extra or {})}
    for bad, good in mapping.items():
        text = text.replace(bad, good)
    return text

# --------------------------------------------------
# Heading criteria checker
# --------------------------------------------------

def _is_heading(text: str, criteria: Dict[str, Any]) -> bool:
    # regex / pattern
    if criteria.get("check_pattern") and criteria.get("pattern_regex"):
        if not criteria["pattern_regex"].search(text):
            return False
    # word count
    if criteria.get("check_word_count"):
        wc = len(text.split())
        if not criteria["word_count_min"] <= wc <= criteria["word_count_max"]:
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

def _extract_pdf(*, data: bytes, skip_start: int, skip_end: int, first_offset: int,
                 heading_criteria: Dict[str, Any], extra_glyphs: Dict[str, str]) -> List[Tuple[str, str, Optional[str]]]:

    doc = fitz.open(stream=data, filetype="pdf")

    adaptive_min = None
    if heading_criteria.get("check_font_size"):
        all_sizes = [sp["size"]
                     for p in range(doc.page_count)
                     for blk in doc.load_page(p).get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"] if blk["type"] == 0
                     for line in blk["lines"] for sp in line["spans"]]
        if all_sizes:
            adaptive_min = statistics.mean(all_sizes) + statistics.pstdev(all_sizes or [1]) * 0.5

    def big(size: float) -> bool:
        if not heading_criteria.get("check_font_size"):
            return True
        return size >= (adaptive_min or heading_criteria["font_size_min"])

    out: List[Tuple[str, str, Optional[str]]] = []

    for pno in range(skip_start, doc.page_count - skip_end):
        page = doc.load_page(pno)
        page_dict = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)
        for blk in page_dict["blocks"]:
            if blk["type"] != 0:
                continue
            blk_txt = "\n".join(sp["text"] for line in blk["lines"] for sp in line["spans"])
            blk_txt = normalise(blk_txt, extra_glyphs)
            max_size = max(sp["size"] for line in blk["lines"] for sp in line["spans"])
            for sent in nltk.sent_tokenize(blk_txt):
                sent = sent.strip()
                if not sent:
                    continue
                marker = f"p{pno + first_offset}"
                heading = sent if (big(max_size) and _is_heading(sent, heading_criteria)) else None
                out.append((sent, marker, heading))
    doc.close()
    return out

# --------------------------------------------------
# DOCX extraction helper
# --------------------------------------------------

def _extract_docx(*, data: bytes, heading_criteria: Dict[str, Any], extra_glyphs: Dict[str, str]) -> List[Tuple[str, str, Optional[str]]]:
    doc = docx.Document(io.BytesIO(data))
    res: List[Tuple[str, str, Optional[str]]] = []
    for idx, para in enumerate(doc.paragraphs, 1):
        txt = normalise(para.text.strip(), extra_glyphs)
        if not txt:
            continue
        marker = f"para{idx}"
        heading = txt if _is_heading(txt, heading_criteria) else None
        res.append((txt, marker, heading))
    return res

# --------------------------------------------------
# Public API
# --------------------------------------------------

def extract_sentences_with_structure(*, file_content: bytes, filename: str,
                                     pdf_skip_start: int = 0, pdf_skip_end: int = 0, pdf_first_page_offset: int = 1,
                                     heading_criteria: Dict[str, Any], extra_glyphs: Dict[str, str] = None
                                     ) -> List[Tuple[str, str, Optional[str]]]:
    """Return (sentence, marker, heading_or_None) tuples for PDF or DOCX."""

    _ensure_punkt()
    extra_glyphs = extra_glyphs or {}

    ext = filename.lower().rsplit('.', 1)[-1]
    if ext == 'pdf':
        return _extract_pdf(data=file_content, skip_start=pdf_skip_start, skip_end=pdf_skip_end,
                            first_offset=pdf_first_page_offset, heading_criteria=heading_criteria,
                            extra_glyphs=extra_glyphs)
    if ext == 'docx':
        return _extract_docx(data=file_content, heading_criteria=heading_criteria, extra_glyphs=extra_glyphs)
    raise ValueError('Unsupported file type: ' + filename)
