# ---------- file_processor.py  ▸  v1.2  ----------
import fitz, docx, re, statistics, nltk, logging
from typing import List, Tuple, Optional, Dict

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")

# ------------------------------------------------------------------
# 1.  Glyph fixes  +  whitespace squeeze
# ------------------------------------------------------------------
GLYPH_MAP: Dict[str, str] = {
    "ﬂ": "fl", "ﬁ": "fi", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    # broken ligatures you saw
    "Te ": "The ", "te ": "the ",
    # extra common ones
    "!nd": "find", "!rst": "first", "!n": "fin",
}
RE_WS     = re.compile(r"\s+")
RE_DIGIT  = re.compile(r"^\d{1,4}$")                    # line that is ONLY digits
RE_PNO_LEAD = re.compile(r"^\d+\s+")                    # digits + space at start of line
RE_MID = re.compile(r"([A-Za-z])!([A-Za-z])")           # a!n  →  afin

def _clean(raw: str) -> str:
    # 1. flatten hard breaks
    txt = raw.replace("\n", " ")
    # 2. drop leading page numbers (PDF export often gives "3  The Creation…")
    txt = RE_PNO_LEAD.sub("", txt)
    # 3. map special glyphs
    txt = RE_MID.sub(r"\1fi\2", txt)   # a!n → afin
    for bad, good in GLYPH_MAP.items():
        txt = txt.replace(bad, good)
    # 4. collapse whitespace
    txt = RE_WS.sub(" ", txt).strip()
    return txt

# ------------------------------------------------------------------
# 2.  Heading detector  (no regex → size OR regex if supplied)
# ------------------------------------------------------------------
def _is_heading(text: str, *, regex: Optional[re.Pattern], max_words: int) -> bool:
    if not (2 <= len(text.split()) <= max_words):
        return False
    return True if regex is None else bool(regex.search(text))

# ------------------------------------------------------------------
# 3.  PDF extractor
# ------------------------------------------------------------------
def _pdf_sentences(data: bytes, skip_start: int, skip_end: int,
                   first_offset: int, regex: Optional[re.Pattern],
                   max_words: int) -> List[Tuple[str, str, Optional[str]]]:

    doc   = fitz.open(stream=data, filetype="pdf")
    pages = range(skip_start, doc.page_count - skip_end)

    sizes = [sp["size"]
             for p in pages
             for blk in doc.load_page(p).get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]
             if blk["type"] == 0
             for ln in blk["lines"] for sp in ln["spans"]]
    thr = statistics.mean(sizes) + statistics.pstdev(sizes) * 0.5 if sizes else 0

    out: List[Tuple[str, str, Optional[str]]] = []
    for p in pages:
        page = doc.load_page(p)
        for blk in page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]:
            if blk["type"] != 0:
                continue
            raw  = " ".join(sp["text"] for ln in blk["lines"] for sp in ln["spans"])
            text = _clean(raw)
            # skip empty or pure‑digit lines
            if not text or RE_DIGIT.match(text):
                continue
            size    = max(sp["size"] for ln in blk["lines"] for sp in ln["spans"])
            heading = text if (size >= thr and _is_heading(text, regex=regex, max_words=max_words)) else None
            for sent in nltk.sent_tokenize(text):
                out.append((sent, f"p{p+first_offset}", heading))
    doc.close()
    return out

# ------------------------------------------------------------------
# 4.  DOCX extractor (simple, uses same cleaners)
# ------------------------------------------------------------------
def _docx_sentences(data: bytes, regex: Optional[re.Pattern],
                    max_words: int) -> List[Tuple[str, str, Optional[str]]]:
    doc = docx.Document(data)
    res = []
    for i, para in enumerate(doc.paragraphs, 1):
        txt = _clean(para.text)
        if not txt:
            continue
        heading = txt if _is_heading(txt, regex=regex, max_words=max_words) else None
        for sent in nltk.sent_tokenize(txt):
            res.append((sent, f"para{i}", heading))
    return res

# ------------------------------------------------------------------
# 5.  Public API (signature unchanged)
# ------------------------------------------------------------------
def extract(file_bytes: bytes, filename: str,
            skip_start: int = 0, skip_end: int = 0, first_page_no: int = 1,
            regex: str = "",            # ← leave blank to rely on font‑size only
            max_words: int = 12) -> List[Tuple[str, str, Optional[str]]]:

    patt = re.compile(regex, re.I) if regex else None
    ext  = filename.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        return _pdf_sentences(file_bytes, skip_start, skip_end,
                              first_page_no, patt, max_words)
    if ext == "docx":
        return _docx_sentences(file_bytes, patt, max_words)
    raise ValueError("Only PDF or DOCX are supported")
