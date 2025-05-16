import tiktoken
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

DEFAULT_CHAPTER_TITLE_CHUNK = "Introduction" 
DEFAULT_SUBCHAPTER_TITLE_CHUNK = None    

def chunk_structured_sentences(
    structured_data: List[Tuple[str, str, Optional[str], Optional[str]]], 
    # text_segment, marker, chapter_context, subchapter_context
    tokenizer: tiktoken.Encoding,
    target_tokens: int = 200,
    overlap_sentences: int = 2 # Note: overlap is now harder to define if a heading is a single segment
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    # Output: chunk_text, first_marker, assigned_chapter_title_for_chunk, assigned_subchapter_title_for_chunk

    chunks = []
    current_chunk_segments = [] # Stores (text_segment, marker, ch_ctx, subch_ctx) tuples
    current_token_count = 0

    if not structured_data:
        logger.warning("chunk_structured_sentences: No structured data, returning empty.")
        return []

    logger.info(f"Token chunking (Target: ~{target_tokens}, Overlap: {overlap_sentences} segments), splitting on context change from line-by-line processor.")

    try:
        segment_texts = [item[0] for item in structured_data]
        all_tokens = tokenizer.encode_batch(segment_texts, allowed_special="all")
        segment_token_counts = [len(tokens) for tokens in all_tokens]
    except Exception as e:
        logger.error(f"Tiktoken encoding error: {e}", exc_info=True); return []

    for i, (text_segment, marker, segment_ch_context, segment_subch_context) in enumerate(structured_data):
        if i >= len(segment_token_counts):
            logger.warning(f"Data/token count mismatch at index {i}. Skipping."); continue
        
        segment_tokens = segment_token_counts[i]
        new_heading_context_detected = False

        # If a chunk is being built, check if the current segment starts a new context
        if current_chunk_segments:
            # Get context of the last segment added to the current chunk
            _last_text, _last_marker, last_chunk_seg_ch_ctx, last_chunk_seg_subch_ctx = current_chunk_segments[-1]
            
            if segment_ch_context != last_chunk_seg_ch_ctx:
                new_heading_context_detected = True
                logger.debug(f"Boundary: Segment '{marker}' ChContext '{segment_ch_context}' differs from last segment's ChContext '{last_chunk_seg_ch_ctx}'.")
            elif segment_subch_context != last_chunk_seg_subch_ctx: 
                new_heading_context_detected = True
                logger.debug(f"Boundary: Segment '{marker}' SubChContext '{segment_subch_context}' differs from last segment's SubChContext '{last_chunk_seg_subch_ctx}' (Ch: '{segment_ch_context}').")
        
        if current_chunk_segments and \
           (new_heading_context_detected or (current_token_count + segment_tokens > target_tokens and len(current_chunk_segments) > 0)): # Ensure chunk has content before splitting by token limit
            
            # Finalize the current chunk
            chunk_text_parts = [seg_data[0] for seg_data in current_chunk_segments]
            # For line-by-line, a "sentence" is now a full line if it's a heading, or an NLTK sentence if body.
            # Joining with space is generally okay.
            chunk_text = " ".join(chunk_text_parts) 
            first_marker_of_chunk = current_chunk_segments[0][1]
            # Titles of the chunk are from the first segment of that chunk
            ch_title_for_chunk = current_chunk_segments[0][2] 
            subch_title_for_chunk = current_chunk_segments[0][3]

            chunks.append((chunk_text, first_marker_of_chunk, ch_title_for_chunk, subch_title_for_chunk))
            logger.info(f"Created chunk (ending '{current_chunk_segments[-1][1]}'). Segments: {len(current_chunk_segments)}, Tokens: {current_token_count}. Reason: {'New Heading Context' if new_heading_context_detected else 'Token Limit'}. Ch: '{ch_title_for_chunk}', SubCh: '{subch_title_for_chunk}'")

            # --- Prepare for the NEXT chunk ---
            # Overlap is now based on segments. If a heading is one segment, overlap might be tricky.
            # For simplicity, overlap will take last N segments.
            overlap_start_idx = max(0, len(current_chunk_segments) - overlap_sentences)
            segments_for_overlap = current_chunk_segments[overlap_start_idx:]
            
            overlap_token_count = 0
            # To find original indices for token counts:
            # `i` is index of current segment causing the split.
            # `current_chunk_segments` were from indices before `i`.
            start_original_idx_of_finalized_chunk_segments = i - len(current_chunk_segments)
            first_original_idx_for_overlap_segments = start_original_idx_of_finalized_chunk_segments + overlap_start_idx

            for k_overlap in range(len(segments_for_overlap)):
                original_idx = first_original_idx_for_overlap_segments + k_overlap
                if original_idx >=0 and original_idx < len(segment_token_counts):
                    overlap_token_count += segment_token_counts[original_idx]

            current_chunk_segments = segments_for_overlap + [(text_segment, marker, segment_ch_context, segment_subch_context)]
            current_token_count = overlap_token_count + segment_tokens
            
            logger.debug(f"  Started new chunk with overlap. First segment: '{marker}'-'{text_segment[:30]}...'. New chunk context: Ch='{segment_ch_context}', SubCh='{segment_subch_context}'")
        else: 
            current_chunk_segments.append((text_segment, marker, segment_ch_context, segment_subch_context))
            current_token_count += segment_tokens

    # Add the last remaining chunk
    if current_chunk_segments:
        chunk_text_parts = [seg_data[0] for seg_data in current_chunk_segments]
        chunk_text = " ".join(chunk_text_parts)
        first_marker_of_chunk = current_chunk_segments[0][1]
        ch_title_for_chunk = current_chunk_segments[0][2]
        subch_title_for_chunk = current_chunk_segments[0][3]
        chunks.append((chunk_text, first_marker_of_chunk, ch_title_for_chunk, subch_title_for_chunk))
        logger.info(f"Created final chunk. Segments: {len(current_chunk_segments)}. Tokens: {current_token_count}. Ch: '{ch_title_for_chunk}', SubCh: '{subch_title_for_chunk}'")

    logger.info(f"Token chunking (line-by-line context) finished. Total chunks: {len(chunks)}.")
    return chunks

def chunk_by_chapter(
    structured_data: List[Tuple[str, str, Optional[str], Optional[str]]] 
    # Expects: (text_segment, marker, chapter_context, subchapter_context) from line-by-line processor
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    current_chapter_for_chunk: Optional[str] = None 
    first_sub_chapter_in_current_chunk: Optional[str] = None
    # Text of the heading that defined the current chapter context
    active_chapter_heading_text: Optional[str] = None 

    if not structured_data: return []
    logger.info("Starting chunking by chapter (line-by-line processor input).")

    for i, (text_segment, marker, segment_ch_context, segment_subch_context) in enumerate(structured_data):
        is_new_chapter_boundary = False
        
        # A new chapter boundary is if the segment_ch_context is new AND this segment IS a chapter heading
        # How to know if segment IS a chapter heading? The line-by-line processor makes segment_ch_context
        # BE the heading text if that line was a chapter.
        if segment_ch_context is not None and segment_ch_context != DEFAULT_CHAPTER_TITLE_FALLBACK: # A "real" chapter title
            if active_chapter_heading_text is None or segment_ch_context != active_chapter_heading_text:
                # Additional check: is this text_segment itself the ch_context?
                # This implies it's the heading line itself.
                if text_segment == segment_ch_context:
                    is_new_chapter_boundary = True
        
        if is_new_chapter_boundary:
            if current_chunk_sentences: 
                chunk_text = " ".join(current_chunk_sentences)
                chunks.append((chunk_text, current_chunk_markers[0], 
                               current_chapter_for_chunk if current_chapter_for_chunk else DEFAULT_CHAPTER_TITLE_FALLBACK, 
                               first_sub_chapter_in_current_chunk))
            current_chunk_sentences, current_chunk_markers = [], []
            current_chapter_for_chunk = segment_ch_context 
            active_chapter_heading_text = segment_ch_context
            # If this new chapter line is also a sub-chapter (unlikely but possible), set it.
            # Otherwise, reset sub-chapter.
            first_sub_chapter_in_current_chunk = segment_subch_context if text_segment == segment_subch_context else None
        
        if text_segment: 
            current_chunk_sentences.append(text_segment)
            current_chunk_markers.append(marker)
            if current_chapter_for_chunk is None: 
                current_chapter_for_chunk = segment_ch_context if segment_ch_context else DEFAULT_CHAPTER_TITLE_FALLBACK
            
            # Capture the first sub-chapter context encountered within this chapter block
            if not first_sub_chapter_in_current_chunk and segment_subch_context is not None and segment_subch_context != DEFAULT_SUBCHAPTER_TITLE_FALLBACK:
                 # Check if this segment IS the sub-chapter heading text
                if text_segment == segment_subch_context:
                    first_sub_chapter_in_current_chunk = segment_subch_context
        
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        chunks.append((chunk_text, current_chunk_markers[0], 
                       current_chapter_for_chunk if current_chapter_for_chunk else DEFAULT_CHAPTER_TITLE_FALLBACK, 
                       first_sub_chapter_in_current_chunk))
    logger.info(f"Chunking by chapter finished. Total chunks: {len(chunks)}.")
    return chunks
