import tiktoken
import logging
from typing import List, Tuple, Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

DEFAULT_TITLE = "Introduction" # Or consider leaving as None/empty string

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
    current_chunk_titles = []
    current_token_count = 0
    sentence_token_counts = [] # Store token counts for efficient overlap calculation

    if not structured_data:
        return []

    logging.info(f"Starting chunking by token count (Target: ~{target_tokens}, Overlap: {overlap_sentences} sentences)")

    # Pre-calculate token counts for all sentences
    sentence_texts = [item[0] for item in structured_data]
    all_tokens = tokenizer.encode_batch(sentence_texts)
    sentence_token_counts = [len(tokens) for tokens in all_tokens]

    for i, (sentence, marker, title) in enumerate(structured_data):
        sentence_tokens = sentence_token_counts[i]

        # Check if adding the current sentence would exceed the target token count
        if current_token_count > 0 and current_token_count + sentence_tokens > target_tokens:
            # --- Finalize the current chunk ---
            chunk_text = " ".join(current_chunk_sentences)
            # Use marker and title from the *first* sentence of the finalized chunk
            first_marker = current_chunk_markers[0] if current_chunk_markers else "Unknown Marker"
            # Use the title associated with the majority or first sentence of the chunk
            chunk_title = current_chunk_titles[0] if current_chunk_titles else DEFAULT_TITLE
            chunks.append((chunk_text, first_marker, chunk_title))
            logging.debug(f"Created chunk ending at sentence {i-1}. Tokens: {current_token_count}. Title: {chunk_title}")

            # --- Start the next chunk with overlap ---
            overlap_start_index = max(0, len(current_chunk_sentences) - overlap_sentences)
            sentences_for_overlap = current_chunk_sentences[overlap_start_index:]
            markers_for_overlap = current_chunk_markers[overlap_start_index:]
            titles_for_overlap = current_chunk_titles[overlap_start_index:]

            # Calculate token count for the overlapping sentences
            overlap_token_count = sum(sentence_token_counts[j]
                                      for j, s in enumerate(current_chunk_sentences)
                                      if j >= overlap_start_index)

            # Initialize new chunk with overlap + current sentence
            current_chunk_sentences = sentences_for_overlap + [sentence]
            current_chunk_markers = markers_for_overlap + [marker]
            current_chunk_titles = titles_for_overlap + [title]
            current_token_count = overlap_token_count + sentence_tokens
            # Ensure sentence_token_counts list aligns with current_chunk_sentences if needed later (it's pre-calculated)

        else:
            # --- Add sentence to the current chunk ---
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            current_chunk_titles.append(title if title is not None else (current_chunk_titles[-1] if current_chunk_titles else DEFAULT_TITLE)) # Carry forward last known title
            current_token_count += sentence_tokens

    # --- Add the last remaining chunk ---
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0] if current_chunk_markers else "Unknown Marker"
        chunk_title = current_chunk_titles[0] if current_chunk_titles else DEFAULT_TITLE
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
    current_title = None # Track the title of the current chunk being built
    first_title_found = False

    if not structured_data:
        return []

    logging.info("Starting chunking by detected chapter title.")

    for i, (sentence, marker, title) in enumerate(structured_data):

        # Normalize title for comparison (handle None)
        normalized_title = title if title is not None else DEFAULT_TITLE # Assign default if None

        if not first_title_found and title is not None:
             # This is the first actual title encountered
             first_title_found = True
             # If there were sentences before the first title, finalize that chunk
             if current_chunk_sentences:
                 chunk_text = " ".join(current_chunk_sentences)
                 first_marker = current_chunk_markers[0]
                 # Use DEFAULT_TITLE for the intro section before the first detected title
                 chunks.append((chunk_text, first_marker, DEFAULT_TITLE))
                 logging.debug(f"Created pre-chapter chunk ending before sentence {i}. Title: {DEFAULT_TITLE}")
                 # Reset for the new chapter
                 current_chunk_sentences = []
                 current_chunk_markers = []

             # Start tracking the new chapter title
             current_title = normalized_title


        elif first_title_found and title is not None and title != current_title:
             # A new chapter title is detected, and it's different from the current one
             # Finalize the previous chapter's chunk
             if current_chunk_sentences:
                 chunk_text = " ".join(current_chunk_sentences)
                 first_marker = current_chunk_markers[0]
                 chunks.append((chunk_text, first_marker, current_title))
                 logging.debug(f"Created chapter chunk ending before sentence {i}. Title: {current_title}")

             # Reset for the new chapter
             current_chunk_sentences = []
             current_chunk_markers = []
             current_title = normalized_title # Update to the new title


        # Add the current sentence to the ongoing chunk
        # Only add if sentence is not empty
        if sentence:
             current_chunk_sentences.append(sentence)
             current_chunk_markers.append(marker)
             # Ensure current_title is set correctly, especially for the first chunk
             if current_title is None:
                 current_title = DEFAULT_TITLE


    # --- Add the last remaining chunk ---
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        # Use the last tracked title (or default if none was ever found)
        final_title = current_title if current_title is not None else DEFAULT_TITLE
        chunks.append((chunk_text, first_marker, final_title))
        logging.debug(f"Created final chapter chunk. Title: {final_title}")

    logging.info(f"Finished chunking by chapter. Created {len(chunks)} chunks.")
    return chunks
