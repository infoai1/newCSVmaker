# -*- coding: utf-8 -*-
"""
chunker.py  •  v1.0  (May 2025)
=================================================
Create clean text‑chunks **without** chapter / sub‑chapter headings.
Designed for non‑coders: just install pandas once, then run one line.

INPUT  — a CSV that already contains one sentence per row and the
         following columns (case‑sensitive):

    sentence              the sentence text
    marker                any reference / verse marker (string, optional)
    is_para_ch_hd         TRUE if the row is a *chapter heading*
    is_para_subch_hd      TRUE if the row is a *sub‑chapter heading*
    ch_context            the *current* chapter title for that sentence
    subch_context         the *current* sub‑chapter title (can be blank)

OUTPUT — a new CSV (default: clean_chunks.csv) with *no* headings inside
         the body text.  Columns:

    Chapter Name | Sub Chapter Name | Text Chunk

Each chunk stays below ~220 words (≈ 250 tokens) and overlaps the next
chunk by 2 sentences so you don’t lose context.

USAGE ---------------------------------------------------------------
1)  Open a terminal / Anaconda prompt.
2)  Install pandas once (skip if already installed):
        pip install pandas
3)  Run the script:
        python chunker.py your_sentence_file.csv  \
                       --output_csv cleaned_chunks.csv

That’s it – the cleaned file appears next to the script.

---------------------------------------------------------------------
"""

import argparse
from pathlib import Path

import pandas as pd

###############################################################################
# Helper functions                                                             #
###############################################################################


def load_sentences(csv_path: Path) -> pd.DataFrame:
    """Read the input CSV and make sure the required columns exist."""
    df = pd.read_csv(csv_path)

    required = {
        "sentence",
        "is_para_ch_hd",
        "is_para_subch_hd",
        "ch_context",
        "subch_context",
    }
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(
            f"Input CSV is missing required column(s): {', '.join(sorted(missing))}"
        )

    # optional column – if absent create an empty one to avoid KeyError later
    if "marker" not in df.columns:
        df["marker"] = ""

    return df


def _word_count(sentences):
    """Rough token proxy = word count (good enough for chunk limit)."""
    return sum(len(s.split()) for s in sentences)


def chunk_sentences(
    df: pd.DataFrame,
    max_words: int = 220,
    overlap_sentences: int = 2,
) -> pd.DataFrame:
    """Convert sentence‑level data‑frame to chunk‑level data‑frame."""

    chunks = []
    cur_sentences: list[str] = []
    cur_ch_title = ""
    cur_subch_title = ""

    for i, row in df.iterrows():
        sentence = str(row["sentence"]).strip()

        # ── Detect chapter / sub‑chapter headings ───────────────────────────────
        if row["is_para_ch_hd"] or row["is_para_subch_hd"]:
            # Update the *context* titles that will be attached to *future* chunks
            if row["ch_context"]:
                cur_ch_title = row["ch_context"]
            if row["subch_context"]:
                cur_subch_title = row["subch_context"]
            # Crucially: **do NOT append the heading sentence itself**
            continue

        # ── Normal sentence – append to current block ───────────────────────────
        cur_sentences.append(sentence)

        # If block is getting long, close it and start a new one with overlap
        if _word_count(cur_sentences) >= max_words:
            chunks.append(
                {
                    "Chapter Name": cur_ch_title,
                    "Sub Chapter Name": cur_subch_title,
                    "Text Chunk": " ".join(cur_sentences),
                }
            )
            # keep the last *overlap_sentences* sentences as the first lines of next block
            cur_sentences = cur_sentences[-overlap_sentences:]

    # ── Any leftovers at EOF become the final chunk ────────────────────────────
    if cur_sentences:
        chunks.append(
            {
                "Chapter Name": cur_ch_title,
                "Sub Chapter Name": cur_subch_title,
                "Text Chunk": " ".join(cur_sentences),
            }
        )

    return pd.DataFrame(chunks)


###############################################################################
# Main CLI                                                                     #
###############################################################################


def main():  # noqa: D401 – simple CLI entry‑point
    parser = argparse.ArgumentParser(
        description="Create clean overlapping chunks from sentence‑level CSV.",
        epilog="Example: python chunker.py sentences.csv --output_csv clean.csv",
    )
    parser.add_argument("input_csv", type=Path, help="Sentence‑level CSV file")
    parser.add_argument(
        "--output_csv",
        "-o",
        type=Path,
        default=Path("clean_chunks.csv"),
        help="Name of the cleaned chunk CSV to write (default: clean_chunks.csv)",
    )
    parser.add_argument(
        "--max_words",
        type=int,
        default=220,
        help="Maximum words per chunk (≈ token count). Default: 220",
    )
    parser.add_argument(
        "--overlap_sentences",
        type=int,
        default=2,
        help="How many sentences should carry over to the next chunk (default: 2)",
    )

    args = parser.parse_args()

    # --------‑‑ Load, process, save ‑‑--------------------------------------------------
    df_in = load_sentences(args.input_csv)
    df_out = chunk_sentences(
        df_in, max_words=args.max_words, overlap_sentences=args.overlap_sentences
    )

    df_out.to_csv(args.output_csv, index=False)
    print(f"✔  Saved {len(df_out):,} clean chunks to → {args.output_csv}")


if __name__ == "__main__":
    main()
