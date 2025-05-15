import tiktoken
import logging
from typing import List, Tuple, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEFAULT_CHAPTER_TITLE_CHUNK = "Introduction"
DEFAULT_SUBCHAPTER_TITLE_CHUNK = None # Or an empty string "" or "General"

def chunk_structured_sentences(
    structured_data: List[Tuple[str, str, Optional[str], Optional[str]]], # sentence, marker, chapter_title, sub_chapter_title
    tokenizer: tiktoken.Encoding,
    target_tokens: int = 200,
    overlap_sentences: int = 2
) -> List[Tuple[str, str, Optional[str], Optional[str]]]: # chunk_text, first_marker, chapter_title, sub_chapter_title
    """
    Chunks structured sentences based on a target token count with sentence overlap.
    Also finalizes a chunk if a new chapter or sub-chapter title is encountered.
    """
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    current_chunk_chapter_titles = []
    current_chunk_sub_chapter_titles = []
    current_token_count = 0

    # Keep track of the last titles processed to detect changes
    last_processed_chapter_title: Optional[str] = None
    last_processed_sub_chapter_title: Optional[str] = None


    if not structured_data:
        return []

    logging.info(f"Starting token-based chunking (Target: ~{target_tokens}, Overlap: {overlap_sentences} sentences), now sensitive to heading changes.")

    try:
        sentence_texts = [item[0] for item in structured_data]
        all_tokens = tokenizer.encode_batch(sentence_texts, allowed_special="all")
        sentence_token_counts = [len(tokens) for tokens in all_tokens]
    except Exception as e:
        logging.error(f"Tiktoken encoding failed during pre-calculation: {e}")
        # If Streamlit context is available: st.error(f"Text encoding error: {e}")
        return []

    for i, (sentence, marker, chapter_title, sub_chapter_title) in enumerate(structured_data):
        if i >= len(sentence_token_counts):
            logging.warning(f"Mismatch data and token counts at index {i}. Skipping.")
            continue
        sentence_tokens = sentence_token_counts[i]

        # Determine effective titles for the current sentence, propagating if None
        effective_chapter_title = chapter_title if chapter_title is not None else (last_processed_chapter_title if last_processed_chapter_title is not None else DEFAULT_CHAPTER_TITLE_CHUNK)
        effective_sub_chapter_title = sub_chapter_title # Can be None, or propagate last known sub-chapter if chapter is same

        # Check for heading change:
        # A new heading is encountered if current_chapter_title differs from last_processed_chapter_title
        # OR if current_sub_chapter_title differs from last_processed_sub_chapter_title (and chapter is the same or also new)
        # The check needs to be careful if current sentence's titles are None, they should inherit.
        # The key is if the *assigned* title for the sentence (after potential inheritance from previous)
        # is different from the title of the *last sentence added to the chunk*.
        
        new_heading_detected = False
        if current_chunk_sentences: # Only check if chunk is not empty
            # Compare current sentence's titles with the titles of the *last sentence in the current chunk*
            last_chunk_sent_ch_title = current_chunk_chapter_titles[-1]
            last_chunk_sent_sch_title = current_chunk_sub_chapter_titles[-1]

            # If the current sentence brings a *new explicit* chapter title
            if chapter_title is not None and chapter_title != last_chunk_sent_ch_title:
                new_heading_detected = True
                logging.debug(f"New chapter detected ('{chapter_title}' vs '{last_chunk_sent_ch_title}') at sentence {i}. Finalizing current chunk.")
            # Else if the chapter is the same (or current is None, inheriting same), check sub-chapter
            elif (chapter_title is None or chapter_title == last_chunk_sent_ch_title) and \
                 (sub_chapter_title != last_chunk_sent_sch_title): # sub_chapter_title can be None, which is different from a non-None title
                new_heading_detected = True
                logging.debug(f"New sub-chapter detected ('{sub_chapter_title}' vs '{last_chunk_sent_sch_title}') under chapter '{effective_chapter_title}' at sentence {i}. Finalizing current chunk.")


        # Conditions to finalize the current chunk:
        # 1. New heading detected (and chunk is not empty)
        # 2. Adding current sentence would exceed target_tokens (and chunk is not empty)
        
        # Finalize chunk if a new heading is detected OR if token limit is exceeded
        if current_chunk_sentences and \
           (new_heading_detected or (current_token_count + sentence_tokens > target_tokens and current_chunk_sentences)):
            
            chunk_text = " ".join(current_chunk_sentences)
            first_marker = current_chunk_markers[0]
            chunk_chapter_title_to_assign = current_chunk_chapter_titles[0] # Title from first sentence of this chunk
            chunk_sub_chapter_title_to_assign = current_chunk_sub_chapter_titles[0]

            chunks.append((chunk_text, first_marker, chunk_chapter_title_to_assign, chunk_sub_chapter_title_to_assign))
            logging.debug(f"Created chunk. Tokens: {current_token_count}. Chapter: '{chunk_chapter_title_to_assign}', Sub: '{chunk_sub_chapter_title_to_assign}'. Finalized due to: {'heading change' if new_heading_detected else 'token limit'}.")

            # --- Start next chunk ---
            # Option 1: Reset (no overlap) if it was a heading change
            # Option 2: Overlap always, regardless of why chunk ended
            # Let's go with overlap for consistency, but be mindful of context.
            # If it was a heading change, the overlap might pull text from the previous section.
            # This is a trade-off. For strict heading separation, overlap should be conditional.
            # For now, keeping overlap consistent:

            overlap_start_index = max(0, len(current_chunk_sentences) - overlap_sentences)
            
            sentences_for_overlap = current_chunk_sentences[overlap_start_index:]
            markers_for_overlap = current_chunk_markers[overlap_start_index:]
            chapter_titles_for_overlap = current_chunk_chapter_titles[overlap_start_index:]
            sub_chapter_titles_for_overlap = current_chunk_sub_chapter_titles[overlap_start_index:]
            
            # Calculate token count for the overlapping part accurately
            # This requires getting token counts for the sentences that form the overlap
            # Assuming sentence_token_counts is aligned with structured_data
            # The indices for overlap sentences relate to the `current_chunk_sentences` list,
            # not directly to the global `i`.
            # We need to map these back to their original indices in `structured_data` to get their token counts.
            
            original_indices_for_overlap = []
            if current_chunk_markers: # Ensure markers list is not empty
                # Find the original index of the first sentence in the current_chunk
                # This is a bit tricky if markers are not unique or if we don't store original index
                # For simplicity, let's assume we can recalculate overlap tokens directly:
                # Re-encode overlapping sentences to get their token count, or sum from pre-calculated list
                # if we can reliably get the original indices.

                # Simplified overlap token count: sum tokens of sentences_for_overlap
                # This is less accurate if `sentence_token_counts` isn't directly used for these specific sentences
                # but is generally okay.
                # For more accuracy, one would re-tokenize just the `sentences_for_overlap`.
                # Let's find original indices:
                # This assumes `i` is the index of the *current sentence being processed* which *caused* the chunk to finalize.
                # The `current_chunk_sentences` are from *before* this current `i`.
                start_index_of_current_chunk_in_structured_data = (i - len(current_chunk_sentences))
                
                overlap_token_count = 0
                if sentences_for_overlap: # ensure there are sentences to overlap
                    first_original_index_for_overlap = start_index_of_current_chunk_in_structured_data + overlap_start_index
                    for k_overlap in range(len(sentences_for_overlap)):
                        original_idx = first_original_index_for_overlap + k_overlap
                        if original_idx < len(sentence_token_counts):
                             overlap_token_count += sentence_token_counts[original_idx]


            # Initialize new chunk state with overlap + current sentence (that triggered the new chunk)
            current_chunk_sentences = sentences_for_overlap + [sentence]
            current_chunk_markers = markers_for_overlap + [marker]
            # The new chunk inherits the titles of the current sentence (which might be new)
            current_chunk_chapter_titles = chapter_titles_for_overlap + [effective_chapter_title]
            current_chunk_sub_chapter_titles = sub_chapter_titles_for_overlap + [effective_sub_chapter_title]
            current_token_count = overlap_token_count + sentence_tokens

        else: # Add sentence to the current chunk (it's empty, or no new heading, and token limit not hit)
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            current_chunk_chapter_titles.append(effective_chapter_title)
            current_chunk_sub_chapter_titles.append(effective_sub_chapter_title)
            current_token_count += sentence_tokens

        # Update last processed titles for the next iteration's heading check
        # These are the titles *associated with the sentence just added/processed*.
        last_processed_chapter_title = effective_chapter_title
        last_processed_sub_chapter_title = effective_sub_chapter_title


    # Add the last remaining chunk
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        chunk_chapter_title_to_assign = current_chunk_chapter_titles[0]
        chunk_sub_chapter_title_to_assign = current_chunk_sub_chapter_titles[0]
        chunks.append((chunk_text, first_marker, chunk_chapter_title_to_assign, chunk_sub_chapter_title_to_assign))
        logging.debug(f"Created final chunk. Tokens: {current_token_count}. Chapter: '{chunk_chapter_title_to_assign}', Sub: '{chunk_sub_chapter_title_to_assign}'.")

    logging.info(f"Finished token-based chunking (heading sensitive). Created {len(chunks)} chunks.")
    return chunks


def chunk_by_chapter(
    structured_data: List[Tuple[str, str, Optional[str], Optional[str]]] # sentence, marker, chapter_title, sub_chapter_title
) -> List[Tuple[str, str, Optional[str], Optional[str]]]: # chunk_text, first_marker, chapter_title, first_sub_chapter_title_in_chunk
    """
    Chunks structured sentences based on detected chapter titles.
    Sub-chapter titles are also propagated (uses the first sub-chapter title encountered in the chapter chunk).
    This function inherently respects chapter boundaries.
    """
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    current_chapter_for_chunk = DEFAULT_CHAPTER_TITLE_CHUNK
    first_sub_chapter_in_current_chunk = DEFAULT_SUBCHAPTER_TITLE_CHUNK
    
    # Tracks the actual text of the chapter heading that started the current chunk,
    # to distinguish between a continued chapter (where detected_chapter_title might be None but contextually the same)
    # and an actual new chapter title.
    active_chapter_heading_text_for_chunk: Optional[str] = None


    if not structured_data:
        return []

    logging.info("Starting chunking by detected chapter title.")

    for i, (sentence, marker, detected_chapter_title, detected_sub_chapter_title) in enumerate(structured_data):
        # A new chapter segment starts if:
        # 1. An explicit chapter title is detected for the current sentence.
        # 2. This explicit title is different from the `active_chapter_heading_text_for_chunk`.
        #    (Handles cases where a chapter starts, then has None titles for its body, then a new chapter title appears)
        
        is_new_chapter_boundary = False
        if detected_chapter_title is not None:
            if active_chapter_heading_text_for_chunk is None: # First ever chapter title encountered
                is_new_chapter_boundary = True
            elif detected_chapter_title != active_chapter_heading_text_for_chunk: # A genuinely new chapter
                is_new_chapter_boundary = True
        
        # If it's the very first sentence and it has a chapter title, it's a new boundary.
        if i == 0 and detected_chapter_title is not None:
             is_new_chapter_boundary = True


        if is_new_chapter_boundary:
            if current_chunk_sentences: # Finalize previous chapter's chunk
                chunk_text = " ".join(current_chunk_sentences)
                first_marker = current_chunk_markers[0]
                # Use the chapter title that was active for the chunk being finalized
                chunks.append((chunk_text, first_marker, current_chapter_for_chunk, first_sub_chapter_in_current_chunk))
                logging.debug(f"Created chapter chunk ending before sentence {i}. Chapter: '{current_chapter_for_chunk}', First Sub: '{first_sub_chapter_in_current_chunk}'")

            # Reset for the new chapter chunk
            current_chunk_sentences = []
            current_chunk_markers = []
            current_chapter_for_chunk = detected_chapter_title # This is the title for the new chunk
            active_chapter_heading_text_for_chunk = detected_chapter_title # This is the defining heading text
            first_sub_chapter_in_current_chunk = detected_sub_chapter_title # This sentence's sub-chapter is the first for the new chunk
        
        # Accumulate sentence
        if sentence:
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            
            # If this is the first sentence being added to current_chunk_sentences for this chapter (i.e., chunk just started),
            # and we haven't set a first_sub_chapter_title yet (or it was reset), set it.
            if not first_sub_chapter_in_current_chunk and detected_sub_chapter_title:
                first_sub_chapter_in_current_chunk = detected_sub_chapter_title
            
            # Ensure current_chapter_for_chunk is updated if it was default and a title is found
            if current_chapter_for_chunk == DEFAULT_CHAPTER_TITLE_CHUNK and detected_chapter_title:
                current_chapter_for_chunk = detected_chapter_title
                if active_chapter_heading_text_for_chunk is None: # Ensure active_heading is also set if this is the first actual title
                    active_chapter_heading_text_for_chunk = detected_chapter_title


    # Add the last remaining chunk
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        # Ensure current_chapter_for_chunk is not default if any title was ever seen for this last chunk
        if not current_chapter_for_chunk or current_chapter_for_chunk == DEFAULT_CHAPTER_TITLE_CHUNK:
             if active_chapter_heading_text_for_chunk:
                  current_chapter_for_chunk = active_chapter_heading_text_for_chunk
             # else, if no chapter title ever seen, it remains default.

        chunks.append((chunk_text, first_marker, current_chapter_for_chunk, first_sub_chapter_in_current_chunk))
        logging.debug(f"Created final chapter chunk. Chapter: '{current_chapter_for_chunk}', First Sub: '{first_sub_chapter_in_current_chunk}'")

    logging.info(f"Finished chunking by chapter. Created {len(chunks)} chunks.")
    return chunks
