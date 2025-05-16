# -*- coding: utf-8 -*-
"""
chunker.py  •  v1.3  (May 2025)
=================================================
Self‑contained **chunking toolkit** that matches the original function
names your Streamlit app expects while dropping heavy dependencies.

✔ *No external libraries except pandas* (only needed for DataFrame export).  
✔ Works as a **CLI tool** *and* as an **importable module**.  
✔ Provides **legacy interfaces**:
  • `chunk_structured_sentences` *(same signature)*  
  • `chunk_by_chapter`  
so **`app.py` and `file_processor.py` need zero edits**.

---
## Function table
| name in v1.3                     | typical use                           |
|----------------------------------|---------------------------------------|
| `chunk_structured_sentences()`   | token‑limited chunks + overlap        |
| `chunk_by_chapter()`             | one chunk per chapter                 |
| `chunk_sentences_df()`           | new API – sentence‑level **DataFrame**|
| `repair_chunk_file()`            | strip stray headings from chunk CSV   |

---
## Command‑line examples
```bash
pip install pandas               # one‑time

# 1) Fresh chunks from sentence CSV (has heading flags)
python chunker.py sentences.csv

# 2) Repair already‑chunked CSV(s)
python chunker.py chunks.csv --repair_only
python chunker.py . --repair_only      # every CSV in folder
```
Each repaired file gets a `_clean.csv` suffix.
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
from pathlib import Path
from typing import List, Tuple, Optional

import pandas as pd

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_CHAPTER_TITLE_CHUNK = "Introduction"
DEFAULT_SUBCHAPTER_TITLE_CHUNK: Optional[str] = None
RE_WS = re.compile(r"\s+")

# -----------------------------------------------------------------------------
# Helper utilities
# -----------------------------------------------------------------------------

def _clean(text: str) -> str:
    """Collapse whitespace like the original code did."""
    return RE_WS.sub(" ", text.replace("\n", " ").strip())


def _word_tokens(sentence: str) -> int:
    """Cheap token proxy: word count; good enough for ±5%."""
    return len(sentence.split())


def _strip_heading_from_text(chunk_text: str, ch: str, subch: str, /, threshold: int = 400) -> str:
    """Delete heading text if it crept inside the chunk body (first 400 chars)."""
    for h in (subch, ch):
        if h and h.lower() in chunk_text.lower():
            m = re.search(re.escape(h), chunk_text, re.IGNORECASE)
            if m and m.start() < threshold:
                chunk_text = chunk_text[: m.start()] + chunk_text[m.end() :]
                chunk_text = chunk_text.lstrip(" .-–—")
    return chunk_text.strip()

# -----------------------------------------------------------------------------
# Core public functions (legacy-compatible)
# -----------------------------------------------------------------------------

def chunk_structured_sentences(
    structured_data: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]],
    tokenizer=None,  # kept for backward signature compatibility; ignored
    target_tokens: int = 200,
    overlap_sentences: int = 2,
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    """Create ~`target_tokens` chunks **with sentence overlap**.

    Returns a list of tuples:
        (chunk_text, first_marker, chapter_title, subchapter_title)
    """

    if not structured_data:
        logger.warning("chunk_structured_sentences: empty input -> empty output")
        return []

    chunks: list[Tuple[str, str, Optional[str], Optional[str]]] = []

    current_sentences: List[str] = []
    current_markers: List[str] = []
    assigned_chapter: Optional[str] = None
    assigned_subchapter: Optional[str] = None
    current_token_sum = 0

    pending_ch_title: Optional[str] = None  # updated when we *see* a heading
    pending_subch_title: Optional[str] = None

    for sent, marker, is_ch_hd, is_subch_hd, ch_ctx, subch_ctx in structured_data:
        sent = _clean(sent)

        # detect heading rows
        if is_ch_hd or is_subch_hd:
            if is_ch_hd:
                pending_ch_title = ch_ctx or DEFAULT_CHAPTER_TITLE_CHUNK
                pending_subch_title = None  # reset sub‑chapter when new chapter starts
            if is_subch_hd:
                pending_subch_title = subch_ctx or DEFAULT_SUBCHAPTER_TITLE_CHUNK
            # Skip adding heading text itself to content
            continue

        # first real sentence of a chunk → lock in titles
        if not current_sentences:
            assigned_chapter = pending_ch_title or ch_ctx or DEFAULT_CHAPTER_TITLE_CHUNK
            assigned_subchapter = pending_subch_title or subch_ctx or DEFAULT_SUBCHAPTER_TITLE_CHUNK

        current_sentences.append(sent)
        current_markers.append(marker)
        current_token_sum += _word_tokens(sent)

        # when token budget exceeded – close, overlap, reset
        if current_token_sum >= target_tokens:
            chunk_text = " ".join(current_sentences)
            chunk_text = _strip_heading_from_text(chunk_text, assigned_chapter, assigned_subchapter)
            chunks.append((chunk_text, current_markers[0] if current_markers else "", assigned_chapter, assigned_subchapter))

            # keep overlap sentences for next chunk
            current_sentences = current_sentences[-overlap_sentences:]
            current_markers = current_markers[-overlap_sentences:]
            current_token_sum = sum(_word_tokens(s) for s in current_sentences)
            # titles remain the same until new real sentence assigns again

    # leftover sentences → final chunk
    if current_sentences:
        chunk_text = " ".join(current_sentences)
        chunk_text = _strip_heading_from_text(chunk_text, assigned_chapter, assigned_subchapter)
        chunks.append((chunk_text, current_markers[0] if current_markers else "", assigned_chapter, assigned_subchapter))

    logger.info("chunk_structured_sentences: produced %d chunks", len(chunks))
    return chunks


def chunk_by_chapter(
    structured_data: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]]
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    """Simpler mode: **one chunk per chapter** (ignores token limits)."""

    if not structured_data:
        return []

    chunks: list[Tuple[str, str, Optional[str], Optional[str]]] = []
    current_sentences: list[str] = []
    current_markers: list[str] = []
    current_chapter: Optional[str] = None
    current_subch: Optional[str] = None

    for sent, marker, is_ch_hd, is_subch_hd, ch_ctx, subch_ctx in structured_data:
        sent = _clean(sent)

        if is_ch_hd:  # new chapter begins – flush previous
            if current_sentences:
                chunks.append((" ".join(current_sentences), current_markers[0] if current_markers else "", current_chapter, current_subch))
            current_sentences = []
            current_markers = []
            current_chapter = ch_ctx or DEFAULT_CHAPTER_TITLE_CHUNK
            current_subch = None  # reset subchapter at new chapter
            continue  # skip heading text itself

        if is_subch_hd:
            current_subch = subch_ctx or DEFAULT_SUBCHAPTER_TITLE_CHUNK
            continue  # skip heading text

        # normal sentence
        if current_chapter is None:
            current_chapter = ch_ctx or DEFAULT_CHAPTER_TITLE_CHUNK
        current_sentences.append(sent)
        current_markers.append(marker)

    # flush remainder
    if current_sentences:
        chunks.append((" ".join(current_sentences), current_markers[0] if current_markers else "", current_chapter, current_subch))

    logger.info("chunk_by_chapter: produced %d chapter‑chunks", len(chunks))
    return chunks

# -----------------------------------------------------------------------------
# Newer DataFrame‑based API (used by CLI) – keeps all features
# -----------------------------------------------------------------------------

def _list_to_df(structured: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]]) -> pd.DataFrame:
    cols = [
        "sentence",
        "marker",
        "is_para_ch_hd",
        "is_para_subch_hd",
        "ch_context",
        "subch_context",
    ]
    return pd.DataFrame(structured, columns=cols)


def chunk_sentences_df(df: pd.DataFrame, max_words: int = 220, overlap_sentences: int = 2) -> pd.DataFrame:
    """DataFrame‑centric version; used by CLI. Returns DF with 3 cols."""
    tuples = chunk_structured_sentences(
        df[[
            "sentence",
            "marker",
            "is_para_ch_hd",
            "is_para_subch_hd",
            "ch_context",
            "subch_context",
        ]].itertuples(index=False, name=None),
        target_tokens=max_words,
        overlap_sentences=overlap_sentences,
    )
    return pd.DataFrame(tuples, columns=["Text Chunk", "Source Marker", "Detected Chapter", "Detected Sub-Chapter"])


# -----------------------------------------------------------------------------
# Repair function for already‑chunked CSVs
# -----------------------------------------------------------------------------

def repair_chunk_file(df: pd.DataFrame) -> pd.DataFrame:
    """Remove headings that slipped into *Text Chunk*."""
    required_cols = {"Text Chunk", "Detected Chapter", "Detected Sub-Chapter"}
    if not required_cols.issubset(df.columns):
        raise ValueError("repair_chunk_file expects a chunk‑level CSV with columns: " + ", ".join(required_cols))

    df = df.copy()
    for idx, row in df.iterrows():
        df.at[idx, "Text Chunk"] = _strip_heading_from_text(
            str(row["Text Chunk"]),
            str(row.get("Detected Chapter", "")),
            str(row.get("Detected Sub-Chapter", "")),
        )
    return df

# -----------------------------------------------------------------------------
# CLI driver
# -----------------------------------------------------------------------------

def _process_file(path: Path, args):
    if args.repair_only:
        df_in = pd.read_csv(path)
        df_out = repair_chunk_file(df_in)
        out_path = path.with_name(path.stem + "_clean.csv")
    else:
        # sentence‑level CSV expected
        df_sent = pd.read_csv(path)
        df_out = chunk_sentences_df(df_sent, max_words=args.max_words, overlap_sentences=args.overlap_sentences)
        out_path = args.output_csv
    df_out.to_csv(out_path, index=False, quoting=csv.QUOTE_MINIMAL)
    print(f"✔ {path.name} → {out_path.name}  ({len(df_out):,} rows)")


def main():
    parser = argparse.ArgumentParser(
        description="Sentence‑level chunker & chunk‑file repair tool (tiktoken‑free)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("input_path", type=Path, help="Sentence CSV *or* chunk CSV *or* directory containing CSVs")
    parser.add_argument("-o", "--output_csv", type=Path, default=Path("clean_chunks.csv"))
    parser.add_argument("--max_words", type=int, default=220)
    parser.add_argument("--overlap_sentences", type=int, default=2)
    parser.add_argument("--repair_only", action="store_true", help="Just clean headings inside existing chunk CSV(s)")

    args = parser.parse_args()

    if args.input_path.is_dir():
        csvs = list(args.input_path.glob("*.csv"))
        if not csvs:
            raise SystemExit("No *.csv files in the provided directory.")
        for csv_file in csvs:
            _process_file(csv_file, args)
    else:
        _process_file(args.input_path, args)


if __name__ == "__main__":
    main()
