# -*- coding: utf-8 -*-
"""
chunker.py  •  v1.1  (May 2025)
=================================================
*Create clean text-chunks **without** chapter / sub-chapter headings.*

**Designed for non-coders** → just install pandas once, then run one line.

---
### What’s new in v1.1
* ✅  *Heading-in-body auto-repair* – if a heading string (chapter/sub-chapter)
  appears **anywhere in the first 400 characters** of the chunk body, it is
  stripped out automatically. This fixes legacy files where headings sneaked
  in because they were not flagged correctly.
* ✅  Extra command-line switch `--repair_only` to *clean an existing chunk CSV*
  (no need to re-chunk from sentences).

---
### 1 / Sentence-level ➡ chunk-level (standard mode)
```bash
pip install pandas   # one-time
python chunker.py sentences.csv          # outputs clean_chunks.csv
```

### 2 / Repair an already-chunked file
```bash
python chunker.py sm_chunks.csv --repair_only -o sm_chunks_clean.csv
```

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
    """Rough token proxy = word count (good enough for chunk limit)."""
    return sum(len(s.split()) for s in sentences)


def _strip_heading_from_text(text: str, ch: str, subch: str, threshold: int = 400) -> str:
    """Remove the first occurrence of *ch* or *subch* if it sits early."""
    for h in (subch, ch):
        if h and h.lower() in text.lower():
            m = re.search(re.escape(h), text, flags=re.IGNORECASE)
            if m and m.start() < threshold:
                text = text[: m.start()] + text[m.end() :]
                text = text.lstrip(" .-–—")
    return text

###############################################################################
# Sentence-level ➡ chunk-level                                                #
###############################################################################

def load_sentence_df(csv_path: Path) -> pd.DataFrame:
    """Read the sentence-level CSV and validate required columns."""
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
        raise ValueError("Missing required columns: " + ", ".join(sorted(missing)))
    if "marker" not in df.columns:
        df["marker"] = ""
    return df


def chunk_sentences(
    df: pd.DataFrame,
    max_words: int = 220,
    overlap_sentences: int = 2,
) -> pd.DataFrame:
    """Convert sentence-level DF → chunk-level DF (no headings inside)."""

    chunks: list[dict] = []
    cur_sentences: list[str] = []
    cur_ch_title = ""
    cur_subch_title = ""

    for _, row in df.iterrows():
        sentence: str = str(row["sentence"]).strip()

        # ───── heading row? update context & skip content ────────────────
        if row["is_para_ch_hd"] or row["is_para_subch_hd"]:
            if row["ch_context"]:
                cur_ch_title = row["ch_context"]
            if row["subch_context"]:
                cur_subch_title = row["subch_context"]
            continue  # don’t add heading to content

        # append normal sentence
        cur_sentences.append(sentence)

        # close chunk if long enough
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
            # overlap for next chunk
            cur_sentences = cur_sentences[-overlap_sentences:]

    # leftovers
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
    """Clean an *existing* chunk-level DF by stripping embedded headings."""
    if not {{"Text Chunk", "Chapter Name", "Sub Chapter Name"}}.issubset(df.columns):
        raise ValueError("Repair expects a chunk-level CSV with columns: 'Text Chunk', 'Chapter Name', 'Sub Chapter Name'")

    df = df.copy()
    for idx, row in df.iterrows():
        df.at[idx, "Text Chunk"] = _strip_heading_from_text(
            str(row["Text Chunk"]),
            str(row.get("Chapter Name", "")),
            str(row.get("Sub Chapter Name", "")),
        )
    return df

###############################################################################
# CLI                                                                          #
###############################################################################

def main():  # noqa: D401 – simple CLI entry-point
    p = argparse.ArgumentParser(
        description="Sentence-level chunker & chunk-file repair utility",
        epilog="Examples:\n  python chunker.py sentences.csv\n  python chunker.py sm_chunks.csv --repair_only -o fixed.csv",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument("input_csv", type=Path, help="Input CSV (sentences *or* chunks)")
    p.add_argument("-o", "--output_csv", type=Path, default=Path("clean_chunks.csv"))
    p.add_argument("--max_words", type=int, default=220, help="Max words per chunk (std mode)")
    p.add_argument("--overlap_sentences", type=int, default=2, help="Sentence overlap (std mode)")
    p.add_argument("--repair_only", action="store_true", help="Do not re-chunk – just repair headings in existing chunk CSV")

    args = p.parse_args()

    if args.repair_only:
        df_in = pd.read_csv(args.input_csv)
        df_out = repair_chunk_file(df_in)
    else:
        df_sentences = load_sentence_df(args.input_csv)
        df_out = chunk_sentences(
            df_sentences,
            max_words=args.max_words,
            overlap_sentences=args.overlap_sentences,
        )

    df_out.to_csv(args.output_csv, index=False)
    print(f"✔ Saved {len(df_out):,} rows to → {args.output_csv}")


if __name__ == "__main__":
    main()
