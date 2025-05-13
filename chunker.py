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
    Propagates chapter and sub-chapter titles.
    """
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    current_chunk_chapter_titles = [] # Track chapter titles for sentences in current chunk
    current_chunk_sub_chapter_titles = [] # Track sub-chapter titles
    current_token_count = 0

    if not structured_data:
        return []

    logging.info(f"Starting chunking by token count (Target: ~{target_tokens}, Overlap: {overlap_sentences} sentences)")

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

        # Determine effective titles for the current sentence
        effective_chapter_title = chapter_title if chapter_title is not None else (current_chunk_chapter_titles[-1] if current_chunk_chapter_titles else DEFAULT_CHAPTER_TITLE_CHUNK)
        effective_sub_chapter_title = sub_chapter_title # Can be None

        if not current_chunk_sentences or (current_token_count + sentence_tokens <= target_tokens):
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            current_chunk_chapter_titles.append(effective_chapter_title)
            current_chunk_sub_chapter_titles.append(effective_sub_chapter_title)
            current_token_count += sentence_tokens
        else:
            if current_chunk_sentences:
                chunk_text = " ".join(current_chunk_sentences)
                first_marker = current_chunk_markers[0]
                # Use titles from the first sentence of the finalized chunk
                chunk_chapter_title_to_assign = current_chunk_chapter_titles[0]
                chunk_sub_chapter_title_to_assign = current_chunk_sub_chapter_titles[0]

                chunks.append((chunk_text, first_marker, chunk_chapter_title_to_assign, chunk_sub_chapter_title_to_assign))
                logging.debug(f"Created chunk ending before sentence {i}. Tokens: {current_token_count}. Chapter: {chunk_chapter_title_to_assign}, Sub: {chunk_sub_chapter_title_to_assign}")

                overlap_start_index = max(0, len(current_chunk_sentences) - overlap_sentences)
                
                sentences_for_overlap = current_chunk_sentences[overlap_start_index:]
                markers_for_overlap = current_chunk_markers[overlap_start_index:]
                chapter_titles_for_overlap = current_chunk_chapter_titles[overlap_start_index:]
                sub_chapter_titles_for_overlap = current_chunk_sub_chapter_titles[overlap_start_index:]
                
                overlap_token_count = sum(sentence_token_counts[k] 
                                           for k in range(i - len(current_chunk_sentences) + overlap_start_index, i))

                current_chunk_sentences = sentences_for_overlap + [sentence]
                current_chunk_markers = markers_for_overlap + [marker]
                current_chunk_chapter_titles = chapter_titles_for_overlap + [effective_chapter_title]
                current_chunk_sub_chapter_titles = sub_chapter_titles_for_overlap + [effective_sub_chapter_title]
                current_token_count = overlap_token_count + sentence_tokens
            else:
                current_chunk_sentences = [sentence]
                current_chunk_markers = [marker]
                current_chunk_chapter_titles = [effective_chapter_title]
                current_chunk_sub_chapter_titles = [effective_sub_chapter_title]
                current_token_count = sentence_tokens

    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        chunk_chapter_title_to_assign = current_chunk_chapter_titles[0]
        chunk_sub_chapter_title_to_assign = current_chunk_sub_chapter_titles[0]
        chunks.append((chunk_text, first_marker, chunk_chapter_title_to_assign, chunk_sub_chapter_title_to_assign))
        logging.debug(f"Created final chunk. Tokens: {current_token_count}. Chapter: {chunk_chapter_title_to_assign}, Sub: {chunk_sub_chapter_title_to_assign}")

    logging.info(f"Finished token-based chunking. Created {len(chunks)} chunks.")
    return chunks


def chunk_by_chapter(
    structured_data: List[Tuple[str, str, Optional[str], Optional[str]]] # sentence, marker, chapter_title, sub_chapter_title
) -> List[Tuple[str, str, Optional[str], Optional[str]]]: # chunk_text, first_marker, chapter_title, first_sub_chapter_title_in_chunk
    """
    Chunks structured sentences based on detected chapter titles.
    Sub-chapter titles are also propagated (uses the first sub-chapter title encountered in the chapter chunk).
    """
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    # For "chunk_by_chapter", the main title of the chunk *is* the chapter title.
    # We also want to record the first sub-chapter title encountered within that chapter.
    current_chapter_for_chunk = DEFAULT_CHAPTER_TITLE_CHUNK
    first_sub_chapter_in_current_chunk = DEFAULT_SUBCHAPTER_TITLE_CHUNK
    
    last_seen_chapter_heading_text = None # Tracks the text of the chapter heading that started the current chunk

    if not structured_data:
        return []

    logging.info("Starting chunking by detected chapter title.")

    for i, (sentence, marker, detected_chapter_title, detected_sub_chapter_title) in enumerate(structured_data):
        # A new chapter starts if detected_chapter_title is not None AND is different from the one that started the current chunk.
        # Or if it's the very first sentence and has a chapter title.
        is_new_chapter_segment = (detected_chapter_title is not None and detected_chapter_title != last_seen_chapter_heading_text)

        if is_new_chapter_segment:
            if current_chunk_sentences: # Finalize previous chapter's chunk
                chunk_text = " ".join(current_chunk_sentences)
                first_marker = current_chunk_markers[0]
                chunks.append((chunk_text, first_marker, current_chapter_for_chunk, first_sub_chapter_in_current_chunk))
                logging.debug(f"Created chapter chunk ending before sentence {i}. Chapter: {current_chapter_for_chunk}, First Sub: {first_sub_chapter_in_current_chunk}")

            # Reset for the new chapter chunk
            current_chunk_sentences = []
            current_chunk_markers = []
            current_chapter_for_chunk = detected_chapter_title if detected_chapter_title else DEFAULT_CHAPTER_TITLE_CHUNK
            last_seen_chapter_heading_text = detected_chapter_title # Update the text that defined this chapter chunk
            first_sub_chapter_in_current_chunk = detected_sub_chapter_title # This sentence's sub-chapter is the first for the new chunk
        
        # Accumulate sentence
        if sentence:
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            # If this is the first sentence being added to current_chunk_sentences for this chapter,
            # and we haven't set a first_sub_chapter_title yet, set it.
            if not first_sub_chapter_in_current_chunk and detected_sub_chapter_title:
                first_sub_chapter_in_current_chunk = detected_sub_chapter_title
            # If the current_chapter_for_chunk is still the default and this sentence has a chapter title, update it.
            # This handles the case where the very first piece of text is part of a chapter.
            if current_chapter_for_chunk == DEFAULT_CHAPTER_TITLE_CHUNK and detected_chapter_title:
                current_chapter_for_chunk = detected_chapter_title
                last_seen_chapter_heading_text = detected_chapter_title


    # Add the last remaining chunk
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        chunks.append((chunk_text, first_marker, current_chapter_for_chunk, first_sub_chapter_in_current_chunk))
        logging.debug(f"Created final chapter chunk. Chapter: {current_chapter_for_chunk}, First Sub: {first_sub_chapter_in_current_chunk}")

    logging.info(f"Finished chunking by chapter. Created {len(chunks)} chunks.")
    return chunks
