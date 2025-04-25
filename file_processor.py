# --- file_processor.py ---
# [Keep existing imports and other functions]

# ─────────────────────────────────────────────
# 3. PDF extractor (MODIFIED)
# ─────────────────────────────────────────────
def _extract_pdf(data: bytes,
                 skip_start: int, skip_end: int, offset: int,
                 regex: Optional[re.Pattern], max_words: int,
                 # Add a margin threshold - e.g., 15% from top/bottom
                 header_footer_margin: float = 0.15
                 ) -> List[Tuple[str, str, Optional[str]]]:

    doc   = fitz.open(stream=data, filetype="pdf")
    # Ensure page range is valid
    start_page = max(0, skip_start)
    end_page = max(start_page, doc.page_count - skip_end)
    pages = range(start_page, end_page)

    if not pages:
         logging.warning("No pages selected for processing after skipping.")
         doc.close()
         return []

    # adaptive font‑size threshold once per document
    sizes = []
    try:
        for p_idx in pages:
            if p_idx >= doc.page_count: continue # Boundary check
            page_blocks = doc.load_page(p_idx).get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]
            for blk in page_blocks:
                 if blk.get("type") == 0 and "lines" in blk: # Check if it's a text block with lines
                     for ln in blk["lines"]:
                         if "spans" in ln:
                             for sp in ln["spans"]:
                                 if "size" in sp:
                                     sizes.append(sp["size"])
    except Exception as e:
        logging.error(f"Error calculating font sizes: {e}")
        # Decide whether to continue with a default threshold or stop
        thr = 12 # Default threshold if calculation fails
    else:
        # Calculate threshold only if sizes were collected
        thr = statistics.mean(sizes) + statistics.pstdev(sizes) * 0.5 if sizes else 12 # Use default if no sizes

    logging.info(f"Calculated heading font size threshold: {thr:.2f}")


    out: List[Tuple[str, str, Optional[str]]] = []
    current_heading_text = None # Keep track of the *last assigned* heading

    for p in pages:
        if p >= doc.page_count: continue # Boundary check
        try:
            page = doc.load_page(p)
            page_height = page.rect.height
            # Define vertical zones to ignore (e.g., top 15% and bottom 15%)
            header_zone_end_y = page_height * header_footer_margin
            footer_zone_start_y = page_height * (1.0 - header_footer_margin)

            page_blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)["blocks"]
            for blk in page_blocks:
                if blk.get("type") != 0 or "lines" not in blk: # Ensure it's a text block
                    continue

                # Aggregate text and calculate max font size for the block
                raw_lines = []
                block_max_fsize = 0
                for ln in blk["lines"]:
                    line_text = ""
                    if "spans" in ln:
                         for sp in ln["spans"]:
                              if "text" in sp: line_text += sp["text"]
                              if "size" in sp: block_max_fsize = max(block_max_fsize, sp["size"])
                    if line_text.strip(): # Avoid adding empty lines
                        raw_lines.append(line_text)

                if not raw_lines: continue # Skip empty blocks

                raw = " ".join(raw_lines)
                txt = _clean(raw)
                if not txt or RE_ONLY_DIG.match(txt):
                    continue

                # --- HEADING DETECTION LOGIC ---
                is_potential_heading = (block_max_fsize >= thr and
                                        _looks_like_heading(txt, regex, max_words))

                block_heading_text = None # Heading for THIS block only
                if is_potential_heading:
                    # Get block vertical position (bbox: [x0, y0, x1, y1])
                    bbox = blk["bbox"]
                    # Check if the block's top is in the header zone OR bottom is in the footer zone
                    is_in_margin = bbox[1] < header_zone_end_y or bbox[3] > footer_zone_start_y

                    if is_in_margin:
                        logging.debug(f"Ignoring potential heading in margin (Page {p + offset}, Y:{bbox[1]:.1f}-{bbox[3]:.1f}): '{txt[:50]}...'")
                        # Keep block_heading_text as None
                    else:
                        # It meets criteria AND is NOT in a margin zone
                        block_heading_text = txt
                        current_heading_text = txt # Update the ongoing chapter title
                        logging.debug(f"Detected heading (Page {p + offset}): '{txt}'")

                # --- SENTENCE EXTRACTION ---
                # Use NLTK to split the block's cleaned text into sentences
                try:
                     sentences = nltk.sent_tokenize(txt)
                except Exception as e:
                     logging.error(f"NLTK sentence tokenization failed for block on page {p + offset}: {e}. Using block as single sentence.")
                     sentences = [txt] # Fallback: treat the whole block as one sentence

                for sent in sentences:
                    # Assign the *block's* heading status to all sentences within it
                    # Or, if the block wasn't a heading, assign the *last known* good heading.
                    # Decide which behavior you prefer. Let's assign the block's status:
                    # If you want sentences *after* a heading but in a normal block
                    # to still "belong" to that heading, use `current_heading_text` here.
                    # If you only want sentences *within* the heading block itself to have the title,
                    # use `block_heading_text`. Let's try the latter for stricter association.
                    out.append((sent.strip(), f"p{p + offset}", block_heading_text)) # Associate only if block IS heading

        except Exception as page_err:
             logging.error(f"Failed processing page {p}: {page_err}", exc_info=True)
             # Continue to next page if possible

    doc.close()
    return out

# --- Back-compat wrapper (MODIFIED to pass new argument) ---
def extract_sentences_with_structure(*,
                                     file_content: bytes,
                                     filename: str,
                                     pdf_skip_start: int = 0,
                                     pdf_skip_end: int = 0,
                                     pdf_first_page_offset: int = 1,
                                     heading_criteria: Dict = None,
                                     # Keep old args for potential direct use, but prioritize criteria dict
                                     regex: str = "",
                                     max_heading_words: int = 12):
    """
    Wrapper kept so older imports still work.
    Forwards to the new `extract()` API or directly calls _extract_pdf/_extract_docx.
    Adds positional check for PDF headers.
    """
    effective_regex_str = regex
    effective_max_words = max_heading_words

    # Use heading_criteria if provided
    if heading_criteria:
        if heading_criteria.get('check_pattern') and heading_criteria.get('pattern_regex'):
            effective_regex_str = heading_criteria['pattern_regex'].pattern
        elif not heading_criteria.get('check_pattern'):
             effective_regex_str = "" # Disable regex if checkbox unchecked

        if heading_criteria.get('check_word_count'):
            effective_max_words = heading_criteria.get('word_count_max', 12)
        else:
             # Set a very high max if word count check is disabled
             effective_max_words = 999

    compiled_regex = re.compile(effective_regex_str, re.I) if effective_regex_str else None
    file_ext = filename.lower().rsplit(".", 1)[-1] if '.' in filename else ''

    if file_ext == "pdf":
        # Call the modified PDF extractor, passing the arguments
        # You could add header_footer_margin to heading_criteria if you want it user-configurable
        return _extract_pdf(data=file_content,
                            skip_start=pdf_skip_start,
                            skip_end=pdf_skip_end,
                            offset=pdf_first_page_offset,
                            regex=compiled_regex,
                            max_words=effective_max_words,
                            header_footer_margin=0.15) # Using 15% margin default
    elif file_ext == "docx":
        # DOCX headers/footers are usually handled differently by the library
        # and might not appear as simple paragraphs, so positional check is less relevant/easy.
        return _extract_docx(data=file_content,
                             regex=compiled_regex,
                             max_words=effective_max_words)
    else:
        raise ValueError(f"Unsupported file type: {filename}")


# Ensure the original _extract_docx and other helper functions (_clean, _looks_like_heading) remain the same
