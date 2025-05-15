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
    # Titles assigned to the chunk being built (from its first sentence's context)
    current_chunk_assigned_chapter_title: Optional[str] = None
    current_chunk_assigned_sub_chapter_title: Optional[str] = None
    current_token_count = 0

    if not structured_data:
        logger.warning("chunk_structured_sentences: No structured data, returning empty.")
        return []

    logger.info(f"Token chunking (Target: ~{target_tokens}, Overlap: {overlap_sentences} sents), using heading flags.")

    try:
        sentence_texts = [item[0] for item in structured_data]
        all_tokens = tokenizer.encode_batch(sentence_texts, allowed_special="all")
        sentence_token_counts = [len(tokens) for tokens in all_tokens]
    except Exception as e:
        logger.error(f"Tiktoken encoding error: {e}", exc_info=True); return []

    for i, (sentence, marker, is_para_ch_hd, is_para_subch_hd, ch_context, subch_context) in enumerate(structured_data):
        if i >= len(sentence_token_counts):
            logger.warning(f"Data/token count mismatch at index {i}. Skipping."); continue
        sentence_tokens = sentence_token_counts[i]

        new_heading_boundary_detected = False
        # A sentence starts a new boundary IF its original paragraph was a heading AND
        # this heading context is different from the current chunk's assigned context.
        # We only consider the *first sentence from a heading paragraph* as the definitive start of that heading text for boundary detection.
        # This relies on the marker format "paraX.s0" for the first sentence of a paragraph.
        is_first_sentence_of_para = marker.endswith(".s0")

        if current_chunk_sentences: # If there's an active chunk
            if is_first_sentence_of_para:
                if is_para_ch_hd and ch_context != current_chunk_assigned_chapter_title:
                    new_heading_boundary_detected = True
                    logger.debug(f"Boundary: Para {marker} is new Chapter '{ch_context}', chunk was '{current_chunk_assigned_chapter_title}'.")
                elif is_para_subch_hd and (ch_context == current_chunk_assigned_chapter_title and subch_context != current_chunk_assigned_sub_chapter_title):
                    new_heading_boundary_detected = True
                    logger.debug(f"Boundary: Para {marker} is new SubChapter '{subch_context}' under '{ch_context}', chunk was subch '{current_chunk_assigned_sub_chapter_title}'.")
        
        if current_chunk_sentences and \
           (new_heading_boundary_detected or (current_token_count + sentence_tokens > target_tokens)):
            
            chunk_text = " ".join(current_chunk_sentences)
            first_marker = current_chunk_markers[0]
            chunks.append((chunk_text, first_marker, current_chunk_assigned_chapter_title, current_chunk_assigned_sub_chapter_title))
            logger.info(f"Created chunk (ending '{current_chunk_markers[-1]}'). Tokens: {current_token_count}. Reason: {'New Heading Para' if new_heading_boundary_detected else 'Token Limit'}. Ch: '{current_chunk_assigned_chapter_title}', SubCh: '{current_chunk_assigned_sub_chapter_title}'")

            overlap_start_idx = max(0, len(current_chunk_sentences) - overlap_sentences)
            sentences_for_overlap = current_chunk_sentences[overlap_start_idx:]
            markers_for_overlap = current_chunk_markers[overlap_start_idx:]
            
            overlap_token_count = 0
            start_original_idx_of_finalized_chunk = i - len(current_chunk_sentences)
            first_original_idx_for_overlap = start_original_idx_of_finalized_chunk + overlap_start_idx
            for k_overlap in range(len(sentences_for_overlap)):
                original_idx = first_original_idx_for_overlap + k_overlap
                if original_idx < len(sentence_token_counts):
                     overlap_token_count += sentence_token_counts[original_idx]
            
            current_chunk_sentences = sentences_for_overlap + [sentence]
            current_chunk_markers = markers_for_overlap + [marker]
            current_token_count = overlap_token_count + sentence_tokens
            
            # New chunk's assigned titles are from the current sentence's context
            current_chunk_assigned_chapter_title = ch_context if ch_context is not None else DEFAULT_CHAPTER_TITLE_CHUNK
            current_chunk_assigned_sub_chapter_title = subch_context
            # logger.debug(f"  Started new chunk with overlap. First effective sentence: '{sentence[:30]}...'. New chunk titles: Ch='{current_chunk_assigned_chapter_title}', SubCh='{current_chunk_assigned_sub_chapter_title}'")
        else: 
            if not current_chunk_sentences: # First sentence of the very first chunk
                current_chunk_assigned_chapter_title = ch_context if ch_context is not None else DEFAULT_CHAPTER_TITLE_CHUNK
                current_chunk_assigned_sub_chapter_title = subch_context
                # logger.debug(f"  Starting first ever chunk. Titles set from sentence '{marker}'")

            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            current_token_count += sentence_tokens
            # logger.debug(f"  Added sentence '{marker}' to current chunk. Tokens: {current_token_count}.")

    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        final_ch_title = current_chunk_assigned_chapter_title if current_chunk_assigned_chapter_title is not None else DEFAULT_CHAPTER_TITLE_CHUNK
        final_subch_title = current_chunk_assigned_sub_chapter_title
        chunks.append((chunk_text, first_marker, final_ch_title, final_subch_title))
        logger.info(f"Created final chunk. Tokens: {current_token_count}. Ch: '{final_ch_title}', SubCh: '{final_subch_title}'")

    logger.info(f"Token chunking (using heading flags) finished. Total chunks: {len(chunks)}.")
    return chunks

# chunk_by_chapter needs to be adapted for the new 6-tuple structure from file_processor
def chunk_by_chapter(
    structured_data: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]] 
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    # Output: chunk_text, first_marker, chapter_title_of_chunk, first_sub_chapter_title_in_chunk
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    
    current_chapter_for_chunk: Optional[str] = None 
    first_sub_chapter_in_current_chunk: Optional[str] = None
    active_chapter_heading_text_for_chunk: Optional[str] = None # The text of the paragraph that defined the current chapter context

    if not structured_data:
        logger.warning("chunk_by_chapter: No structured data, returning empty list.")
        return []
    logger.info("Starting chunking by detected chapter title (using heading flags).")

    for i, (sentence, marker, is_para_ch_hd, is_para_subch_hd, ch_context, subch_context) in enumerate(structured_data):
        is_new_chapter_boundary = False
        is_first_sentence_of_para = marker.endswith(".s0")

        # A new chapter boundary is if the original paragraph was a chapter heading,
        # AND it's the first sentence from that paragraph,
        # AND its chapter context (which is its own text if it's a heading) is different from the active chapter text.
        if is_first_sentence_of_para and is_para_ch_hd:
            if active_chapter_heading_text_for_chunk is None or ch_context != active_chapter_heading_text_for_chunk:
                is_new_chapter_boundary = True
        
        if is_new_chapter_boundary:
            # logger.debug(f"New chapter boundary at {marker}. Old active: '{active_chapter_heading_text_for_chunk}', New detected context: '{ch_context}'.")
            if current_chunk_sentences: 
                chunk_text = " ".join(current_chunk_sentences)
                first_marker = current_chunk_markers[0]
                final_ch_title_for_prev_chunk = current_chapter_for_chunk if current_chapter_for_chunk is not None else DEFAULT_CHAPTER_TITLE_CHUNK
                chunks.append((chunk_text, first_marker, final_ch_title_for_prev_chunk, first_sub_chapter_in_current_chunk))
                # logger.info(f"Created chapter chunk (ending before {marker}). Ch: '{final_ch_title_for_prev_chunk}', SubCh: '{first_sub_chapter_in_current_chunk}'")

            current_chunk_sentences = []
            current_chunk_markers = []
            current_chapter_for_chunk = ch_context # The text of the chapter heading
            active_chapter_heading_text_for_chunk = ch_context 
            first_sub_chapter_in_current_chunk = subch_context if is_para_subch_hd else None # if this ch heading is also a subch heading
            # If this chapter heading paragraph was ALSO a sub-chapter heading paragraph, use its context.
            # More likely, a sub-chapter will appear later within this chapter.
            if is_first_sentence_of_para and is_para_subch_hd and ch_context == active_chapter_heading_text_for_chunk:
                 first_sub_chapter_in_current_chunk = subch_context


        if sentence: 
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            
            # For the first chunk, or if current_chapter_for_chunk is still the default
            if current_chapter_for_chunk is None or current_chapter_for_chunk == DEFAULT_CHAPTER_TITLE_FALLBACK:
                if ch_context is not None and ch_context != DEFAULT_CHAPTER_TITLE_FALLBACK : # Use the first available valid chapter context
                    current_chapter_for_chunk = ch_context
                    if active_chapter_heading_text_for_chunk is None:
                         active_chapter_heading_text_for_chunk = ch_context
            
            # Capture the first sub-chapter seen within this current chapter chunk
            # This should ideally be when is_para_subch_hd is true for the first sentence of that sub_ch para
            if not first_sub_chapter_in_current_chunk and is_first_sentence_of_para and is_para_subch_hd:
                # Ensure this sub-chapter belongs to the current active chapter context
                if ch_context == active_chapter_heading_text_for_chunk:
                    first_sub_chapter_in_current_chunk = subch_context
        
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        final_ch_title_for_last_chunk = current_chapter_for_chunk if current_chapter_for_chunk is not None else DEFAULT_CHAPTER_TITLE_CHUNK
        chunks.append((chunk_text, first_marker, final_ch_title_for_last_chunk, first_sub_chapter_in_current_chunk))
        # logger.info(f"Created final chapter chunk. Ch: '{final_ch_title_for_last_chunk}', SubCh: '{first_sub_chapter_in_current_chunk}'")

    logger.info(f"Chunking by chapter (using heading flags) finished. Total chunks: {len(chunks)}.")
    return chunks
