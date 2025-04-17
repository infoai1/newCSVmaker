import fitz  # PyMuPDF
import docx
import re
import nltk
import io
import logging
import os
import streamlit as st
from typing import List, Tuple, Dict, Any, Optional

# --------------------------------------------------
# Logging setup
# --------------------------------------------------
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# --------------------------------------------------
# NLTK: ensure 'punkt' is available (re‑uses earlier helper)
# --------------------------------------------------

def ensure_nltk_punkt_available() -> bool:
    """Ensure that the NLTK punkt tokenizer is installed (safeguard)."""
    try:
        nltk.data.find('tokenizers/punkt')
        return True
    except LookupError:
        logging.warning("NLTK punkt not found, trying to download…")
        try:
            nltk.download('punkt', quiet=True)
            nltk.data.find('tokenizers/punkt')
            logging.info("Downloaded punkt successfully.")
            return True
        except Exception as e:
            logging.error("Failed to download punkt: %s", e)
            return False

# --------------------------------------------------
#  ███╗   ██╗ █████╗ ██████╗  ██████╗ ██╗     ██╗███████╗
#  ████╗  ██║██╔══██╗██╔══██╗██╔═══██╗██║     ██║██╔════╝
#  ██╔██╗ ██║███████║██████╔╝██║   ██║██║     ██║█████╗  
#  ██║╚██╗██║██╔══██║██╔══██╗██║   ██║██║     ██║██╔══╝  
#  ██║ ╚████║██║  ██║██║  ██║╚██████╔╝███████╗██║███████╗
#  ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝╚══════╝
# --------------------------------------------------
#  UTILITY:  Glyph‑normalisation fixes bad PDF encodings
# --------------------------------------------------

def _normalise_glyphs(text: str) -> str:
    """Replace problematic glyphs produced by missing / wrong ToUnicode CMaps.

    This fixes headings where fancy small‑cap 'T' appears as '!' or '#', and
    converts common ligatures to simple ASCII. Extend `GLYPH_MAP` as needed.
    """
    GLYPH_MAP = {
        "!e ": "The ",   # '!e Creation' -> 'The Creation'
        "!E ": "THE ",
        "#e ": "The ",
        "#E ": "THE ",
        "ﬂ": "fl",      # ligatures
        "ﬁ": "fi",
        "ﬀ": "ff",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
    }
    for bad, good in GLYPH_MAP.items():
        text = text.replace(bad, good)
    return text

# --------------------------------------------------
#  CORE: extract sentences with structural info
# --------------------------------------------------

def extract_sentences_with_structure(
    *,
    file_content: bytes,
    filename: str,
    pdf_skip_start: int = 0,
    pdf_skip_end: int = 0,
    pdf_first_page_offset: int = 1,
    heading_criteria: Dict[str, Any],
    subtitle_criteria: Dict[str, Any]
) -> List[Tuple[str, str, Optional[str]]]:
    """Return list of (sentence, marker, detected_heading) tuples.

    * `marker` is `pX` for PDF page number (adjusted by offset) or para idx for DOCX.
    * `detected_heading` is a string if the sentence qualifies as a heading; else None.
    """

    if not ensure_nltk_punkt_available():
        raise RuntimeError("NLTK punkt model unavailable; cannot tokenise.")

    if filename.lower().endswith(".pdf"):
        return _extract_from_pdf(bytes_data=file_content,
                                 skip_start=pdf_skip_start,
                                 skip_end=pdf_skip_end,
                                 first_page_offset=pdf_first_page_offset,
                                 heading_criteria=heading_criteria,
                                 subtitle_criteria=subtitle_criteria)
    elif filename.lower().endswith(".docx"):
        return _extract_from_docx(bytes_data=file_content,
                                  heading_criteria=heading_criteria,
                                  subtitle_criteria=subtitle_criteria)
    else:
        raise ValueError("Unsupported file type: {}".format(filename))

# --------------------------------------------------
#  PDF helper
# --------------------------------------------------

def _extract_from_pdf(*, bytes_data: bytes, skip_start: int, skip_end: int, first_page_offset: int,
                      heading_criteria: Dict[str, Any], subtitle_criteria: Dict[str, Any]
                      ) -> List[Tuple[str, str, Optional[str]]]:
    doc = fitz.open(stream=bytes_data, filetype="pdf")
    page_count = doc.page_count
    start = skip_start
    end = page_count - skip_end

    structured: List[Tuple[str, str, Optional[str]]] = []

    for page_number in range(start, end):
        page = doc.load_page(page_number)
        textpage = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)

        # Combine block lines into paragraphs
        for block in textpage.get("blocks", []):
            if block["type"] != 0:
                continue  # skip images etc.
            block_text = "\n".join(line["spans"][0]["text"] for line in block["lines"] if line["spans"])

            # glyph normalisation (critical!)
            block_text = _normalise_glyphs(block_text)

            # sentence split
            sentences = nltk.sent_tokenize(block_text)

            for sent in sentences:
                sent_clean = sent.strip()
                if not sent_clean:
                    continue
                marker = f"p{page_number + first_page_offset}"
                heading = _classify_heading(sent_clean, heading_criteria)
                structured.append((sent_clean, marker, heading))

    doc.close()
    return structured

# --------------------------------------------------
#  DOCX helper
# --------------------------------------------------

def _extract_from_docx(*, bytes_data: bytes, heading_criteria: Dict[str, Any],
                       subtitle_criteria: Dict[str, Any]) -> List[Tuple[str, str, Optional[str]]]:
    file_like = io.BytesIO(bytes_data)
    document = docx.Document(file_like)

    structured: List[Tuple[str, str, Optional[str]]] = []

    for idx, para in enumerate(document.paragraphs, start=1):
        text = _normalise_glyphs(para.text.strip())
        if not text:
            continue
        marker = f"para{idx}"
        heading = _classify_heading(text, heading_criteria)
        structured.append((text, marker, heading))

    return structured

# --------------------------------------------------
#  Heading classifier helper
# --------------------------------------------------

def _classify_heading(text: str, criteria: Dict[str, Any]) -> Optional[str]:
    """Return the text as heading if it passes ALL active criteria, else None."""

    # 1. Pattern / keyword
    if criteria.get('check_pattern') and criteria.get('pattern_regex'):
        if not criteria['pattern_regex'].search(text):
            return None

    # 2. Word count
    if criteria.get('check_word_count'):
        wc = len(text.split())
        if not (criteria['word_count_min'] <= wc <= criteria['word_count_max']):
            return None

    # 3. Case checks
    if criteria.get('check_case'):
        if criteria.get('case_upper') and not text.isupper():
            return None
        if criteria.get('case_title') and not text.istitle():
            return None

    # Font‑size / style / layout checks are PDF‑only and need span info; skipped here.
    # They should already have been evaluated in the block‑level extraction step if enabled.

    return text  # passes all active filters
