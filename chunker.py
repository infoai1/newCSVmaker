# -*- coding: utf-8 -*-
"""
chunker.py  •  v1.2  (May 2025)
=================================================
A **one‑stop, zero‑hassle** CSV cleaner for non‑coders.

* ✔  Converts **sentence‑level CSV ➞ chunk‑level CSV** *without* letting
  headings creep into the text body.
* ✔  **Repairs existing chunk files** in place – removes any heading that
  mistakenly sits inside *Text Chunk*.
* ✔  **Batch mode** – point it at a folder and it cleans every *.csv* file
  inside. No loops, no Python skills needed.

---
## Quick Start
```bash
# 1) Run this ONCE
pip install pandas

# 2) Put chunker.py next to your CSV files.

# 3‑A) Standard (sentence ➞ chunks)
python chunker.py sentences.csv              # ➜ clean_chunks.csv

# 3‑B) Repair ONE already‑chunked file
python chunker.py sm_chunks.csv --repair_only

# 3‑C) Repair EVERY *.csv* in the current folder
python chunker.py . --repair_only
```

Each repaired file is saved as **Name_clean.csv** so your originals stay safe.

---
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List

import pandas as pd

###############################################################################
# Utility helpers                                                             #
###############################################################################

def _word_count(sentences: List[str]) -> int:
    """Token proxy = word count (good enough for chunk limit)."""
    return sum(len(s.split()) for s in sentences)


def _strip_heading_from_text(text: str, ch: str, subch: str, threshold: int = 400) -> str:
    """Remove the first occurrence of *ch* or *subch* if it sits near the top."""
    for h in (subch, ch):
        h_low = h.lower().strip()
        if h_low and h_low in text.lower():
            m = re.search(re.escape(h), text, flags=re.IGNORECASE)
            if m and m.start() < threshold:
                text = text[: m.start()] + text[m.end() :]
                text = text.lstrip(" .-–—")
    return text

###############################################################################
# Sentence‑level ➡ chunk‑level                                                #
###############################################################################

def _load_sentence_df(csv_path: Path) -> pd.DataFrame:
    """Read sentence‑level CSV and make sure required columns exist."""
    df = pd.read_csv(csv_path)
    needed = {
        "sentence",
        "is_para_ch_hd",
        "is_para_subch_hd",
        "ch_context",
        "subch_context",
    }
    missing = needed.difference(df.columns)
    if missing:
        raise ValueError(
            f"{csv_path.name} is missing columns: {', '.join(sorted(missing))}"
        )
    if "marker" not in df.columns:
        df["marker"] = ""
    return df


def chunk_sentences(
    df: pd.DataFrame,
    max_words: int = 220,
    overlap_sentences: int = 2,
) -> pd.DataFrame:
    """Turn a sentence‑level DF into chunk‑level DF – **no headings inside**."""

    chunks: list[dict] = []
    cur_sentences: list[str] = []
    cur_ch_title = ""
    cur_subch_title = ""

    for _, row in df.iterrows():
        sentence: str = str(row["sentence"]).strip()

        # ── Heading row? update context titles, *do not* keep text ────────────
        if row["is_para_ch_hd"] or row["is_para_subch_hd"]:
            if row["ch_context"]:
                cur_ch_title = row["ch_context"]
            if row["subch_context"]:
                cur_subch_title = row["subch_context"]
            continue

        cur_sentences.append(sentence)

        if _word_count(cur_sentences) >= max_words:
            chunk_text = " ".join(cur_sentences)
            chunk_text = _strip_heading_from_text(chunk_text, cur_ch_title, cur_subch_title)
            chunks.append(
                {
                    "Chapter Name": cur_ch_title,
                    "Sub Chapter Name": cur_subch_title,
                    "Text Chunk": chunk_text,
                }
            )
            cur_sentences = cur_sentences[-overlap_sentences:]

    if cur_sentences:
        chunk_text = " ".join(cur_sentences)
        chunk_text = _strip_heading_from_text(chunk_text, cur_ch_title, cur_subch_title)
        chunks.append(
            {
                "Chapter Name": cur_ch_title,
                "Sub Chapter Name": cur_subch_title,
                "Text Chunk": chunk_text,
            }
        )

    return pd.DataFrame(chunks)

###############################################################################
# Repair mode                                                                 #
###############################################################################

def repair_chunk_file(df: pd.DataFrame) -> pd.DataFrame:
    """Remove stray headings from a *chunk‑level* CSV."""
    required_cols = {"Text Chunk", "Chapter Name", "Sub Chapter Name"}
    if not required_cols.issubset(df.columns):
        raise ValueError("Expected a chunk‑level CSV with columns: " + ", ".join(required_cols))
    df = df.copy()
    for idx, row in df.iterrows():
        df.at[idx, "Text Chunk"] = _strip_heading_from_text(
            str(row["Text Chunk"]),
            str(row.get("Chapter Name", "")),
            str(row.get("Sub Chapter Name", "")),
        )
    return df

###############################################################################
# Dispatcher                                                                  #
###############################################################################

def _process_path(path: Path, args):
    """Handle a single file in either normal or repair mode."""
    if args.repair_only:
        df_in = pd.read_csv(path)
        df_out = repair_chunk_file(df_in)
    else:
        df_sent = _load_sentence_df(path)
        df_out = chunk_sentences(
            df_sent,
            max_words=args.max_words,
            overlap_sentences=args.overlap_sentences,
        )

    out_path = path.with_name(path.stem + "_clean.csv") if args.repair_only else args.output_csv
    df_out.to_csv(out_path, index=False)
    print(f"✔ {path.name}  ➜  {out_path.name}  ({len(df_out):,} rows)")

###############################################################################
# CLI                                                                         #
###############################################################################

def main():  # noqa: D401 – simple CLI entry‑point
    p = argparse.ArgumentParser(
        description="Sentence‑level chunker **and** batch repair tool.",
        epilog=(
            "Examples:\n"
            "  python chunker.py sentences.csv\n"
            "  python chunker.py sm_chunks.csv --repair_only\n"
            "  python chunker.py . --repair_only   # folder batch\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument(
        "input_path",
        type=Path,
        help="CSV file *or* directory containing CSVs",
    )
    p.add_argument(
        "-o",
        "--output_csv",
        type=Path,
        default=Path("clean_chunks.csv"),
        help="Output CSV name when *not* in repair‑only mode",
    )
    p.add_argument("--max_words", type=int, default=220)
    p.add_argument("--overlap_sentences", type=int, default=2)
    p.add_argument("--repair_only", action="store_true", help="Don’t re‑chunk; just clean")

    args = p.parse_args()

    if args.input_path.is_dir():
        csv_files = list(args.input_path.glob("*.csv"))
        if not csv_files:
            raise SystemExit("No *.csv files found in directory.")
        for csv in csv_files:
            _process_path(csv, args)
    else:
        _process_path(args.input_path, args)


if __name__ == "__main__":
    main()
