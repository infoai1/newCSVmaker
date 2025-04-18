import fitz, docx, re, statistics, nltk, logging
from typing import List, Tuple, Optional, Dict

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")

# ---------- glyph map & cleaners ----------
GLYPH_MAP: Dict[str, str] = {
    "ﬂ": "fl", "ﬁ": "fi", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    "Te ": "The ", "te ": "the ",
    "!nd": "find", "!rst": "first", "!n": "fin",
}
RE_WS       = re.compile(r"\s+")
RE_DIGITS   = re.compile(r"^\d{1,4}$")
RE_PAGENO   = re.compile(r"^\d+\s+")
RE_MID_FI   = re.compile(r"([A-Za-z])!([A-Za-z])")

def _clean(raw: str) -> str:
    txt = raw.replace("\n", " ")
    txt = RE_PAGENO.sub("", txt)
    txt = RE_MID_FI.sub(r"\1fi\2", txt)
    for bad, good in GLYPH_MAP.items():
        txt = txt.replace(bad, good)
    return RE_WS.sub(" ", txt).strip()

def _is_heading(txt: str, regex: Optional[re.Pattern], max_words: int) -> bool:
    if not (2 <= len(txt.split()) <= max_words):
        return False
    return True if regex is None else bool(regex.search(txt))

# ---------- PDF ----------
def _pdf(data: bytes, s0: int, s1: int, offset: int,
         regex: Optional[re.Pattern], max_words: int
         ) -> List[Tuple[str, str, Optional[str]]]:

    doc   = fitz.open(stream=data, filetype="pdf")
    pages = range(s0, doc.page_count - s1)

    sizes = [sp["size"]
             for p in pages
             for blk in doc.load_page(p).get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]
             if blk["type"] == 0
             for ln in blk["lines"] for sp in ln["spans"]]
    thr = statistics.mean(sizes) + statistics.pstdev(sizes) * 0.5 if sizes else 0

    out = []
    for p in pages:
        page = doc.load_page(p)
        for blk in page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]:
            if blk["type"] != 0:
                continue
            raw = " ".join(sp["text"] for ln in blk["lines"] for sp in ln["spans"])
            txt = _clean(raw)
            if not txt or RE_DIGITS.match(txt):
                continue
            size = max(sp["size"] for ln in blk["lines"] for sp in ln["spans"])
            head = txt if (size >= thr and _is_heading(txt, regex, max_words)) else None
            for sent in nltk.sent_tokenize(txt):
                out.append((sent, f"p{p+offset}", head))
    doc.close()
    return out

# ---------- DOCX ----------
def _docx(data: bytes, regex: Optional[re.Pattern], max_words: int):
    doc = docx.Document(data)
    res = []
    for i, para in enumerate(doc.paragraphs, 1):
        txt = _clean(para.text)
        if not txt:
            continue
        head = txt if _is_heading(txt, regex, max_words) else None
        for sent in nltk.sent_tokenize(txt):
            res.append((sent, f"para{i}", head))
    return res

# ---------- public ----------
def extract(file_bytes: bytes, filename: str,
            skip_start=0, skip_end=0, first_page_no=1,
            regex: str = "", max_words: int = 12):

    patt = re.compile(regex, re.I) if regex else None
    ext  = filename.lower().rsplit(".", 1)[-1]
    if ext == "pdf":
        return _pdf(file_bytes, skip_start, skip_end, first_page_no, patt, max_words)
    if ext == "docx":
        return _docx(file_bytes, patt, max_words)
    raise ValueError("Only PDF or DOCX are supported")
