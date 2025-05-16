import tiktoken
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

DEFAULT_CHAPTER_TITLE_CHUNK = "Introduction" 
DEFAULT_SUBCHAPTER_TITLE_CHUNK = None    

def chunk_structured_sentences(
    structured_data: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]], 
    # sentence, marker, is_para_ch_hd_flag, is_para_subch_hd_flag, ch_context_for_sentence, subch_context_for_sentence
    tokenizer: tiktoken.Encoding,
    target_tokens: int = 200,
    overlap_sentences: int = 2
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    current_chunk_assigned_chapter_title: Optional[str] = None
    current_chunk_assigned_sub_chapter_title: Optional[str] = None
    current_token_count = 0

    if not structured_data:
        logger.warning("chunk_structured_sentences: No structured data, returning empty.")
        return []

    logger.info(f"Token chunking (Target: ~{target_tokens}, Overlap: {overlap_sentences} sents), with 'peek ahead' for heading paragraphs.")

    try:
        sentence_texts = [item[0] for item in structured_data]
        all_tokens = tokenizer.encode_batch(sentence_texts, allowed_special="all")
        sentence_token_counts = [len(tokens) for tokens in all_tokens]
    except Exception as e:
        logger.error(f"Tiktoken encoding error: {e}", exc_info=True); return []

    # --- Main Loop ---
    i = 0
    while i < len(structured_data):
        sentence, marker, para_is_ch_hd, para_is_subch_hd, \
            sentence_ch_context, sentence_subch_context = structured_data[i]
        
        if i >= len(sentence_token_counts): # Should not happen if lengths match
            logger.warning(f"Data/token count mismatch at index {i}. Ending.")
            break 
        sentence_tokens = sentence_token_counts[i]

        # --- Initialize titles for a new chunk ---
        if not current_chunk_sentences:
            current_chunk_assigned_chapter_title = sentence_ch_context if sentence_ch_context is not None else DEFAULT_CHAPTER_TITLE_CHUNK
            current_chunk_assigned_sub_chapter_title = sentence_subch_context
            logger.debug(f"  Starting new chunk with sentence '{marker}'. Initial titles: Ch='{current_chunk_assigned_chapter_title}', SubCh='{current_chunk_assigned_sub_chapter_title}'")

        # --- Add current sentence to potential chunk ---
        current_chunk_sentences.append(sentence)
        current_chunk_markers.append(marker)
        current_token_count += sentence_tokens
        
        # --- Check conditions to finalize the current chunk ---
        finalize_chunk_now = False
        reason_for_finalize = ""

        # 1. Check for token limit
        if current_token_count >= target_tokens and len(current_chunk_sentences) > 1 : # Avoid finalizing if only one long sentence
             # If next sentence makes it too long, but *this* sentence ALONE is not too long compared to target.
             # This check is tricky. The original logic was: if (current_token_count + next_sentence_tokens > target_tokens)
             # For now, let's use a simpler: if current chunk hits target.
             # More refined: if adding the *next* sentence would exceed, unless this is the last sentence.
            if i + 1 < len(structured_data):
                next_sentence_tokens = sentence_token_counts[i+1]
                if (current_token_count + next_sentence_tokens > target_tokens and current_token_count > target_tokens * 0.6): # if current chunk is already substantial
                    finalize_chunk_now = True
                    reason_for_finalize = "Token Limit Approaching"
            elif current_token_count >= target_tokens: # Last sentence and already over limit
                    finalize_chunk_now = True
                    reason_for_finalize = "Token Limit Reached (last sentence)"


        # 2. "Peek Ahead" for heading if current sentence ends with a full stop
        #    and the next sentence starts a new paragraph that is a heading.
        if not finalize_chunk_now and sentence.strip().endswith("."):
            if (i + 1) < len(structured_data): # If there is a next sentence
                _next_s, next_marker, next_para_is_ch_hd, next_para_is_subch_hd, \
                next_s_ch_ctx, next_s_subch_ctx = structured_data[i+1]
                
                if next_marker.endswith(".s0"): # Next sentence is start of a new paragraph
                    is_new_context_ch = next_para_is_ch_hd and (next_s_ch_ctx != current_chunk_assigned_chapter_title)
                    is_new_context_subch = next_para_is_subch_hd and \
                                           (next_s_ch_ctx == current_chunk_assigned_chapter_title) and \
                                           (next_s_subch_ctx != current_chunk_assigned_sub_chapter_title)
                    
                    if is_new_context_ch:
                        finalize_chunk_now = True
                        reason_for_finalize = f"Next Para is New Chapter ('{next_s_ch_ctx[:30]}...')"
                    elif is_new_context_subch:
                        finalize_chunk_now = True
                        reason_for_finalize = f"Next Para is New SubChapter ('{next_s_subch_ctx[:30]}...')"
        
        # 3. If this is the last sentence in the data, always finalize the current chunk.
        if i == len(structured_data) - 1:
            finalize_chunk_now = True
            reason_for_finalize = reason_for_finalize if reason_for_finalize else "End of Data"

        # --- Finalize and prepare for next chunk if needed ---
        if finalize_chunk_now and current_chunk_sentences:
            chunk_text = " ".join(current_chunk_sentences)
            first_marker = current_chunk_markers[0]
            chunks.append((chunk_text, first_marker, current_chunk_assigned_chapter_title, current_chunk_assigned_sub_chapter_title))
            logger.info(f"Created chunk (ending '{marker}'). Segments: {len(current_chunk_sentences)}, Tokens: {current_token_count}. Reason: {reason_for_finalize}. Ch: '{current_chunk_assigned_chapter_title}', SubCh: '{current_chunk_assigned_sub_chapter_title}'")

            # Prepare for the next chunk
            # The sentence that *would have been added* (i.e. structured_data[i+1] if split happened due to peek-ahead)
            # or the current sentence if it was just too long by itself, will start the new chunk with overlap.
            
            # Overlap logic: take last `overlap_sentences` from the chunk just finalized.
            # The current `i` points to the last sentence included in the finalized chunk.
            # So, the overlap should start from `i - overlap_sentences + 1`.
            # The items for overlap are from `current_chunk_sentences`.
            
            # Start index for sentences in `structured_data` that formed the previous chunk
            start_idx_prev_chunk_in_structured_data = i - len(current_chunk_sentences) + 1

            temp_sentences_for_overlap = []
            temp_markers_for_overlap = []
            temp_overlap_token_count = 0

            if overlap_sentences > 0 and len(current_chunk_sentences) >= overlap_sentences :
                # Get sentences from the end of the *just finalized chunk* for overlap
                overlap_source_sentences = current_chunk_sentences[-overlap_sentences:]
                overlap_source_markers = current_chunk_markers[-overlap_sentences:]
                
                # Get their token counts
                # The original indices of these overlap sentences
                original_indices_of_overlap_source = list(range(start_idx_prev_chunk_in_structured_data + len(current_chunk_sentences) - overlap_sentences, 
                                                                start_idx_prev_chunk_in_structured_data + len(current_chunk_sentences)))
                
                for k_idx, orig_idx in enumerate(original_indices_of_overlap_source):
                    if orig_idx >=0 and orig_idx < len(sentence_token_counts):
                        temp_sentences_for_overlap.append(overlap_source_sentences[k_idx])
                        temp_markers_for_overlap.append(overlap_source_markers[k_idx])
                        temp_overlap_token_count += sentence_token_counts[orig_idx]
                    else:
                        logger.warning(f"Overlap: Original index {orig_idx} out of bounds.")
            
            # Reset for the next chunk
            current_chunk_sentences = list(temp_sentences_for_overlap) # Start with overlap
            current_chunk_markers = list(temp_markers_for_overlap)
            current_token_count = temp_overlap_token_count
            current_chunk_assigned_chapter_title = None # Will be set by the next sentence
            current_chunk_assigned_sub_chapter_title = None 

            # If the split was due to "peek ahead", the next iteration (i+1) will naturally become the start of the new chunk.
            # If the split was due to token limit on the current sentence, this sentence is already processed.
            # The loop naturally increments `i`.
            # If we finalized because of `new_heading_paragraph_starts_here`, `i` is the last sentence of the current chunk.
            # The next loop iteration `i+1` will be the new heading.
            # If we finalized because of token limit with `current_sentence + next_sentence > limit`, `i` is the last sentence. `i+1` starts new.
            # If we finalized because `current_sentence` itself made it too long, `i` is that sentence. `i+1` starts new.
        
        i += 1 # Move to the next sentence from structured_data

    # Add any remaining sentences if the loop finishes before finalizing
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        # Ensure titles are not None if they were established for this last chunk
        final_ch_title = current_chunk_assigned_chapter_title if current_chunk_assigned_chapter_title is not None else DEFAULT_CHAPTER_TITLE_CHUNK
        final_subch_title = current_chunk_assigned_sub_chapter_title
        chunks.append((chunk_text, current_chunk_markers[0], final_ch_title, final_subch_title))
        logger.info(f"Created final remaining chunk. Tokens: {current_token_count}. Ch: '{final_ch_title}', SubCh: '{final_subch_title}'")

    logger.info(f"Token chunking (peek ahead) finished. Total chunks: {len(chunks)}.")
    return chunks

# chunk_by_chapter (remains the same as the last correct version that handles 6-tuples)
def chunk_by_chapter(
    structured_data: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]] 
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    current_chapter_for_chunk: Optional[str] = None 
    first_sub_chapter_in_current_chunk: Optional[str] = None
    active_chapter_heading_text_para: Optional[str] = None 

    if not structured_data: return []
    logger.info("Starting chunking by chapter (using heading flags).")

    for i, (sentence, marker, is_para_ch_hd, is_para_subch_hd, ch_context_of_sentence, subch_context_of_sentence) in enumerate(structured_data):
        is_new_chapter_boundary = False
        is_first_sentence_of_para = marker.endswith(".s0")

        if is_first_sentence_of_para and is_para_ch_hd:
            if active_chapter_heading_text_para is None or ch_context_of_sentence != active_chapter_heading_text_para:
                is_new_chapter_boundary = True
        
        if is_new_chapter_boundary:
            if current_chunk_sentences: 
                chunk_text = " ".join(current_chunk_sentences)
                chunks.append((chunk_text, current_chunk_markers[0], 
                               current_chapter_for_chunk if current_chapter_for_chunk else DEFAULT_CHAPTER_TITLE_CHUNK, 
                               first_sub_chapter_in_current_chunk))
            current_chunk_sentences, current_chunk_markers = [], []
            current_chapter_for_chunk = ch_context_of_sentence 
            active_chapter_heading_text_para = ch_context_of_sentence
            first_sub_chapter_in_current_chunk = subch_context_of_sentence if is_para_subch_hd else None
        
        if sentence: 
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            if current_chapter_for_chunk is None: 
                current_chapter_for_chunk = ch_context_of_sentence if ch_context_of_sentence else DEFAULT_CHAPTER_TITLE_CHUNK
            if not first_sub_chapter_in_current_chunk and is_first_sentence_of_para and is_para_subch_hd:
                if ch_context_of_sentence == active_chapter_heading_text_para: 
                    first_sub_chapter_in_current_chunk = subch_context_of_sentence
        
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        chunks.append((chunk_text, current_chunk_markers[0], 
                       current_chapter_for_chunk if current_chapter_for_chunk else DEFAULT_CHAPTER_TITLE_CHUNK, 
                       first_sub_chapter_in_current_chunk))
    logger.info(f"Chunking by chapter finished. Total chunks: {len(chunks)}.")
    return chunks
