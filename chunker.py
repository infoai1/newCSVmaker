import tiktoken
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

DEFAULT_CHAPTER_TITLE_CHUNK = "Introduction" 
DEFAULT_SUBCHAPTER_TITLE_CHUNK = None    

def chunk_structured_sentences(
    structured_data: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]], 
    # sentence, marker, is_ch_heading_para, is_subch_heading_para, ch_context, subch_context
    tokenizer: tiktoken.Encoding,
    target_tokens: int = 200,
    overlap_sentences: int = 2
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    # Output: chunk_text, first_marker, assigned_chapter_title, assigned_subchapter_title

    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    current_chunk_assigned_chapter_title: Optional[str] = None
    current_chunk_assigned_sub_chapter_title: Optional[str] = None
    current_token_count = 0

    if not structured_data:
        logger.warning("chunk_structured_sentences: No structured data, returning empty.")
        return []

    logger.info(f"Token chunking (Target: ~{target_tokens}, Overlap: {overlap_sentences} sents), using heading flags to split chunks.")

    try:
        sentence_texts = [item[0] for item in structured_data] # item[0] is sentence text
        all_tokens = tokenizer.encode_batch(sentence_texts, allowed_special="all")
        sentence_token_counts = [len(tokens) for tokens in all_tokens]
    except Exception as e:
        logger.error(f"Tiktoken encoding error: {e}", exc_info=True); return []

    for i, (sentence, marker, is_para_ch_hd, is_para_subch_hd, ch_context, subch_context) in enumerate(structured_data):
        if i >= len(sentence_token_counts):
            logger.warning(f"Data/token count mismatch at index {i}. Skipping."); continue
        sentence_tokens = sentence_token_counts[i]

        new_heading_boundary_detected = False
        is_first_sentence_of_para = marker.endswith(".s0")

        # Establish titles for the current chunk if it's empty
        if not current_chunk_sentences:
            current_chunk_assigned_chapter_title = ch_context if ch_context is not None else DEFAULT_CHAPTER_TITLE_CHUNK
            current_chunk_assigned_sub_chapter_title = subch_context # Can be None
            logger.debug(f"  Starting new/first chunk with sentence '{marker}'. Initial titles: Ch='{current_chunk_assigned_chapter_title}', SubCh='{current_chunk_assigned_sub_chapter_title}'")


        # Check for heading boundary:
        # A new boundary occurs if this sentence is the start of a paragraph that IS a heading,
        # AND that heading's context is different from the current chunk's established context.
        if current_chunk_sentences and is_first_sentence_of_para: # Must have a chunk to compare against, and be start of new para
            if is_para_ch_hd: # If the original paragraph of this sentence IS a chapter heading
                if ch_context != current_chunk_assigned_chapter_title:
                    new_heading_boundary_detected = True
                    logger.debug(f"Boundary: Para {marker} IS new Chapter ('{ch_context}'). Current chunk Ch: '{current_chunk_assigned_chapter_title}'.")
            
            if not new_heading_boundary_detected and is_para_subch_hd: # If not already a new chapter boundary, check for sub-chapter
                # Sub-chapter boundary if:
                # 1. Original para IS a sub-chapter heading
                # 2. Chapter context is the SAME as current chunk's chapter
                # 3. Sub-chapter context is DIFFERENT from current chunk's sub-chapter
                if (ch_context == current_chunk_assigned_chapter_title and \
                    subch_context != current_chunk_assigned_sub_chapter_title):
                    new_heading_boundary_detected = True
                    logger.debug(f"Boundary: Para {marker} IS new SubChapter ('{subch_context}') under Ch '{ch_context}'. Current chunk SubCh: '{current_chunk_assigned_sub_chapter_title}'.")
        
        # Finalize current chunk IF:
        # 1. It's not empty AND a new heading boundary is detected for the current sentence.
        # OR
        # 2. It's not empty AND adding the current sentence would exceed the token limit.
        if current_chunk_sentences and \
           (new_heading_boundary_detected or (current_token_count + sentence_tokens > target_tokens)):
            
            chunk_text = " ".join(current_chunk_sentences)
            first_marker = current_chunk_markers[0]
            chunks.append((chunk_text, first_marker, current_chunk_assigned_chapter_title, current_chunk_assigned_sub_chapter_title))
            logger.info(f"Created chunk (ending '{current_chunk_markers[-1]}'). Tokens: {current_token_count}. Reason: {'New Heading Para' if new_heading_boundary_detected else 'Token Limit'}. Ch: '{current_chunk_assigned_chapter_title}', SubCh: '{current_chunk_assigned_sub_chapter_title}'")

            # --- Prepare for the NEXT chunk (which will start with the current `sentence`) ---
            overlap_start_idx = max(0, len(current_chunk_sentences) - overlap_sentences)
            sentences_for_overlap = current_chunk_sentences[overlap_start_idx:]
            markers_for_overlap = current_chunk_markers[overlap_start_idx:]
            
            overlap_token_count = 0
            # Calculate token count for these overlapping sentences
            start_original_idx_of_finalized_chunk = i - len(current_chunk_sentences) # Original index of first sentence in the chunk just finalized
            first_original_idx_for_overlap = start_original_idx_of_finalized_chunk + overlap_start_idx
            
            for k_overlap in range(len(sentences_for_overlap)):
                original_idx = first_original_idx_for_overlap + k_overlap
                if original_idx >= 0 and original_idx < len(sentence_token_counts): # Boundary check
                     overlap_token_count += sentence_token_counts[original_idx]
                else: # Should not happen if indexing is correct
                    logger.warning(f"Index out of bounds ({original_idx}) for sentence_token_counts accessing overlap tokens for chunk ending with '{current_chunk_markers[-1]}'.")

            # Initialize the NEW chunk with overlap + current sentence
            current_chunk_sentences = sentences_for_overlap + [sentence]
            current_chunk_markers = markers_for_overlap + [marker]
            current_token_count = overlap_token_count + sentence_tokens
            
            # New chunk's assigned titles are from the current sentence's context
            current_chunk_assigned_chapter_title = ch_context if ch_context is not None else DEFAULT_CHAPTER_TITLE_CHUNK
            current_chunk_assigned_sub_chapter_title = subch_context
            logger.debug(f"  Started new chunk with overlap. First effective sentence: '{sentence[:30]}...'. New chunk titles: Ch='{current_chunk_assigned_chapter_title}', SubCh='{current_chunk_assigned_sub_chapter_title}'")
        else: 
            # Add current sentence to the ongoing chunk
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            current_token_count += sentence_tokens
            # If it was the first sentence of a new chunk, its titles were set above.
            # logger.debug(f"  Added sentence '{marker}' to current chunk. Tokens: {current_token_count}.")

    # Add the last remaining chunk
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        final_ch_title = current_chunk_assigned_chapter_title # Already defaulted if was None
        final_subch_title = current_chunk_assigned_sub_chapter_title
        chunks.append((chunk_text, first_marker, final_ch_title, final_subch_title))
        logger.info(f"Created final chunk. Tokens: {current_token_count}. Ch: '{final_ch_title}', SubCh: '{final_subch_title}'")

    logger.info(f"Token chunking (using heading flags) finished. Total chunks: {len(chunks)}.")
    return chunks

# chunk_by_chapter needs to be adapted for the new 6-tuple structure from file_processor
def chunk_by_chapter(
    structured_data: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]] 
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    current_chapter_for_chunk: Optional[str] = None 
    first_sub_chapter_in_current_chunk: Optional[str] = None
    active_chapter_heading_text_for_chunk: Optional[str] = None 

    if not structured_data:
        logger.warning("chunk_by_chapter: No structured data, returning empty list.")
        return []
    logger.info("Starting chunking by detected chapter title (using heading flags).")

    for i, (sentence, marker, is_para_ch_hd, is_para_subch_hd, ch_context, subch_context) in enumerate(structured_data):
        is_new_chapter_boundary = False
        is_first_sentence_of_para = marker.endswith(".s0")

        if is_first_sentence_of_para and is_para_ch_hd:
            # The ch_context for a paragraph flagged as a chapter heading IS the heading text itself.
            if active_chapter_heading_text_for_chunk is None or ch_context != active_chapter_heading_text_for_chunk:
                is_new_chapter_boundary = True
        
        if is_new_chapter_boundary:
            if current_chunk_sentences: 
                chunk_text = " ".join(current_chunk_sentences)
                first_marker = current_chunk_markers[0]
                final_ch_title_for_prev_chunk = current_chapter_for_chunk if current_chapter_for_chunk is not None else DEFAULT_CHAPTER_TITLE_CHUNK
                chunks.append((chunk_text, first_marker, final_ch_title_for_prev_chunk, first_sub_chapter_in_current_chunk))

            current_chunk_sentences = []
            current_chunk_markers = []
            current_chapter_for_chunk = ch_context 
            active_chapter_heading_text_for_chunk = ch_context 
            # If this chapter heading paragraph is ALSO a sub-chapter, its sub-chapter context is its own text.
            # Otherwise, reset sub-chapter for the new chapter.
            first_sub_chapter_in_current_chunk = subch_context if is_para_subch_hd else None
        
        if sentence: 
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            
            if current_chapter_for_chunk is None: # For the very first chunk before any chapter heading is found
                current_chapter_for_chunk = ch_context if ch_context is not None else DEFAULT_CHAPTER_TITLE_CHUNK
                if active_chapter_heading_text_for_chunk is None and is_para_ch_hd and is_first_sentence_of_para: # If this is the first sentence of a chapter para
                     active_chapter_heading_text_for_chunk = ch_context
            
            # Capture the first sub-chapter whose paragraph was flagged as a sub-chapter heading within this chapter.
            if not first_sub_chapter_in_current_chunk and is_first_sentence_of_para and is_para_subch_hd:
                # Ensure this sub-chapter belongs to the current active chapter context
                if ch_context == active_chapter_heading_text_for_chunk: # The sub-chapter's ch_context should match the active chapter
                    first_sub_chapter_in_current_chunk = subch_context
        
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        final_ch_title_for_last_chunk = current_chapter_for_chunk if current_chapter_for_chunk is not None else DEFAULT_CHAPTER_TITLE_CHUNK
        chunks.append((chunk_text, first_marker, final_ch_title_for_last_chunk, first_sub_chapter_in_current_chunk))

    logger.info(f"Chunking by chapter (using heading flags) finished. Total chunks: {len(chunks)}.")
    return chunks
