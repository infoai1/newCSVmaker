import streamlit as st, pandas as pd
from utils import ensure_punkt, get_tokenizer
from file_processor import extract
from chunker import by_tokens, by_chapter

# ----- UI -----
st.set_page_config(page_title="📚 Book‑to‑Chunks", layout="wide")
st.title("📚 Book‑to‑Chunks Converter")

with st.sidebar:
    f     = st.file_uploader("Upload PDF or DOCX", type=["pdf", "docx"])
    mode  = st.radio("Chunking mode", ["~200 tokens +2 sent overlap",
                                       "By chapter heading"])
    skip0 = st.number_input("Skip pages at start (PDF)", 0, 50, 0)
    skip1 = st.number_input("Skip pages at end (PDF)",   0, 50, 0)
    first = st.number_input("First processed page#",     1, 999, 1)
    regex = st.text_input("Heading regex (blank = font‑size only)",
                          r"^(chapter|section|part)\s+[ivxlcdm\d]+")
    go    = st.button("🚀 Process")

# ----- logic -----
if go and f:
    ensure_punkt()
    tok  = get_tokenizer()
    st.info("Extracting…")
    data = extract(f.getvalue(), f.name,
                   skip_start=skip0, skip_end=skip1,
                   first_page_no=first, regex=regex)

    st.success(f"{len(data):,} sentences extracted")
    st.info("Chunking…")
    chunks = by_tokens(data, tok) if mode.startswith("~") else by_chapter(data)
    st.success(f"{len(chunks):,} chunks ready")

    df = pd.DataFrame(chunks, columns=["Text Chunk", "Marker", "Title"])
    st.dataframe(df, use_container_width=True)
    st.download_button("📥 Download CSV",
                       df.to_csv(index=False).encode(),
                       file_name=f"{f.name.rsplit('.',1)[0]}_chunks.csv")
else:
    st.write("👈 Upload a file & hit **Process**")
