import logging, tiktoken
from typing import List, Tuple, Optional

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")

DEFAULT_TITLE = "Introduction"

# ---------- tokens ----------
def by_tokens(data: List[Tuple[str, str, Optional[str]]],
              tok: tiktoken.Encoding,
              target=200, overlap=2):

    if not data: return []
    lens = [len(tok.encode(s[0])) for s in data]
    out, chunk, marks, titles, cur = [], [], [], [], 0

    for i, (sent, mark, title) in enumerate(data):
        if not chunk or cur + lens[i] <= target:
            chunk.append(sent); marks.append(mark)
            titles.append(title or titles[-1] if titles else DEFAULT_TITLE)
            cur += lens[i]
        else:
            out.append((" ".join(chunk), marks[0], titles[0]))
            chunk = chunk[-overlap:] + [sent]
            marks = marks[-overlap:] + [mark]
            titles = titles[-overlap:] + [title or titles[-1]]
            cur = sum(lens[i-len(chunk)+1:i+1])
    out.append((" ".join(chunk), marks[0], titles[0]))
    return out

# ---------- chapter ----------
def by_chapter(data: List[Tuple[str, str, Optional[str]]]):
    if not data: return []
    out, chunk, marks, title = [], [], [], DEFAULT_TITLE
    for sent, mark, head in data:
        if head and head != title:
            if chunk:
                out.append((" ".join(chunk), marks[0], title))
            chunk, marks, title = [], [], head
        chunk.append(sent); marks.append(mark)
    out.append((" ".join(chunk), marks[0], title))
    return out
