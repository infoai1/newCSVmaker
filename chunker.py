import tiktoken
import logging
from typing import List, Tuple, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEFAULT_TITLE = "Introduction" # Default title for chunks without detected chapter

def chunk_structured_sentences(
    structured_data: List[Tuple[str, str, Optional[str]]],
    tokenizer: tiktoken.Encoding,
    target_tokens: int = 200,
    overlap_sentences: int = 2
) -> List[Tuple[str, str, Optional[str]]]:
    """
    Chunks structured sentences based on a target token count with sentence overlap.

    Args:
        structured_data: List of (sentence, marker, title) tuples.
        tokenizer: The tiktoken tokenizer instance.
        target_tokens: The desired approximate number of tokens per chunk.
        overlap_sentences: The number of sentences from the end of the previous
                           chunk to prepend to the next chunk.

    Returns:
        List of (chunk_text, first_marker_in_chunk, title_of_chunk) tuples.
    """
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    current_chunk_titles = [] # Track titles associated with sentences in the current chunk
    current_token_count = 0

    if not structured_data:
        return []

    logging.info(f"Starting chunking by token count (Target: ~{target_tokens}, Overlap: {overlap_sentences} sentences)")

    # Pre-calculate token counts for efficiency
    try:
        sentence_texts = [item[0] for item in structured_data]
        # Handle potential encoding errors for odd characters if necessary
        all_tokens = tokenizer.encode_batch(
             sentence_texts, allowed_special="all" # Be more permissive if needed
        )
        sentence_token_counts = [len(tokens) for tokens in all_tokens]
    except Exception as e:
        logging.error(f"Tiktoken encoding failed during pre-calculation: {e}")
        st.error(f"Text encoding error during chunking preparation: {e}")
        return [] # Cannot proceed if encoding fails

    for i, (sentence, marker, title) in enumerate(structured_data):
        # Ensure we have a token count for the sentence
        if i >= len(sentence_token_counts):
            logging.warning(f"Mismatch between structured data and token counts at index {i}. Skipping sentence.")
            continue
        sentence_tokens = sentence_token_counts[i]

        # Avoid adding excessively long single sentences that blow past the target immediately
        # This check applies when starting a new chunk or adding to an existing one.
        # Add sentence if the chunk is empty OR if adding it doesn't exceed target,
        # OR if adding it *does* exceed target BUT it's the *first* sentence of the chunk
        # (we have to include at least one sentence).
        if not current_chunk_sentences or (current_token_count + sentence_tokens <= target_tokens):
            # Add sentence to the current chunk
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            # Carry forward the last known title if the current one is None
            effective_title = title if title is not None else (current_chunk_titles[-1] if current_chunk_titles else DEFAULT_TITLE)
            current_chunk_titles.append(effective_title)
            current_token_count += sentence_tokens
        else:
            # Current chunk is not empty and adding this sentence exceeds target.
            # Finalize the PREVIOUS chunk.
            if current_chunk_sentences: # Ensure there's something to finalize
                chunk_text = " ".join(current_chunk_sentences)
                first_marker = current_chunk_markers[0]
                # Use the title from the first sentence of the finalized chunk
                chunk_title = current_chunk_titles[0]
                chunks.append((chunk_text, first_marker, chunk_title))
                logging.debug(f"Created chunk ending before sentence {i}. Tokens: {current_token_count}. Title: {chunk_title}")

                # Start the NEXT chunk with overlap
                overlap_start_index = max(0, len(current_chunk_sentences) - overlap_sentences)
                
                # Get overlapping data correctly based on indices
                sentences_for_overlap = current_chunk_sentences[overlap_start_index:]
                markers_for_overlap = current_chunk_markers[overlap_start_index:]
                titles_for_overlap = current_chunk_titles[overlap_start_index:]

                # Need token counts for the overlapping sentences
                # Re-sum token counts for the overlapping sentences based on original list
                overlap_token_count = sum(sentence_token_counts[k] 
                                           for k in range(i - len(current_chunk_sentences) + overlap_start_index, i))


                # Initialize new chunk state with overlap + current sentence
                current_chunk_sentences = sentences_for_overlap + [sentence]
                current_chunk_markers = markers_for_overlap + [marker]
                effective_title = title if title is not None else (titles_for_overlap[-1] if titles_for_overlap else DEFAULT_TITLE)
                current_chunk_titles = titles_for_overlap + [effective_title]
                current_token_count = overlap_token_count + sentence_tokens

            else: # Should not happen if logic above is correct, but as safeguard
                 # Start a new chunk with the current sentence if the previous one was somehow empty
                current_chunk_sentences = [sentence]
                current_chunk_markers = [marker]
                effective_title = title if title is not None else DEFAULT_TITLE
                current_chunk_titles = [effective_title]
                current_token_count = sentence_tokens


    # Add the last remaining chunk
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        chunk_title = current_chunk_titles[0] # Title from first sentence of this last chunk
        chunks.append((chunk_text, first_marker, chunk_title))
        logging.debug(f"Created final chunk. Tokens: {current_token_count}. Title: {chunk_title}")

    logging.info(f"Finished chunking by token count. Created {len(chunks)} chunks.")
    return chunks


def chunk_by_chapter(
    structured_data: List[Tuple[str, str, Optional[str]]]
) -> List[Tuple[str, str, Optional[str]]]:
    """
    Chunks structured sentences based on detected chapter titles.
    Sentences between titles (or before the first title) are grouped.
    """
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    current_title_for_chunk = DEFAULT_TITLE # Title for the chunk currently being built
    last_seen_heading_text = None # Keep track of the actual heading text that triggered the split

    if not structured_data:
        return []

    logging.info("Starting chunking by detected chapter title.")

    for i, (sentence, marker, detected_heading) in enumerate(structured_data):
        # A new heading is detected if it's not None AND different from the last one seen
        is_new_heading = detected_heading is not None and detected_heading != last_seen_heading_text

        if is_new_heading:
            # If we have sentences accumulated for the *previous* chapter, finalize that chunk
            if current_chunk_sentences:
                chunk_text = " ".join(current_chunk_sentences)
                first_marker = current_chunk_markers[0]
                chunks.append((chunk_text, first_marker, current_title_for_chunk))
                logging.debug(f"Created chapter chunk ending before sentence {i}. Title: {current_title_for_chunk}")

            # Reset for the new chapter
            current_chunk_sentences = []
            current_chunk_markers = []
            # The title for the *next* chunk will be the heading text we just found
            current_title_for_chunk = detected_heading
            last_seen_heading_text = detected_heading

        # Add the current sentence to the ongoing chunk (unless it's empty)
        if sentence:
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            # The title associated with these sentences is current_title_for_chunk


    # Add the last remaining chunk after the loop
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        # Use the title assigned to this last batch of sentences
        chunks.append((chunk_text, first_marker, current_title_for_chunk))
        logging.debug(f"Created final chapter chunk. Title: {current_title_for_chunk}")

    logging.info(f"Finished chunking by chapter. Created {len(chunks)} chunks.")
    return chunks
