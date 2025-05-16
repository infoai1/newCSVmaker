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
    # Output: chunk_text, first_marker, assigned_chapter_title_for_chunk, assigned_subchapter_title_for_chunk

    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    # Titles assigned to the chunk currently being built. These are set from the first sentence of the chunk.
    current_chunk_assigned_chapter_title: Optional[str] = None
    current_chunk_assigned_sub_chapter_title: Optional[str] = None
    current_token_count = 0

    if not structured_data:
        logger.warning("chunk_structured_sentences: No structured data, returning empty.")
        return []

    logger.info(f"Token chunking (Target: ~{target_tokens}, Overlap: {overlap_sentences} sents), splitting on ch/subch context change.")

    try:
        sentence_texts = [item[0] for item in structured_data] # item[0] is sentence text
        all_tokens = tokenizer.encode_batch(sentence_texts, allowed_special="all")
        sentence_token_counts = [len(tokens) for tokens in all_tokens]
    except Exception as e:
        logger.error(f"Tiktoken encoding error: {e}", exc_info=True); return []

    for i, (sentence, marker, _is_para_ch_hd, _is_para_subch_hd, # Heading flags not directly used in this version's boundary logic
              sentence_ch_context, sentence_subch_context) in enumerate(structured_data):
        
        if i >= len(sentence_token_counts):
            logger.warning(f"Data/token count mismatch at index {i}. Skipping."); continue
        sentence_tokens = sentence_token_counts[i]

        new_heading_boundary_detected = False

        # If a chunk is being built, check if the current sentence starts a new context
        if current_chunk_sentences:
            # Effective chapter context for the current sentence (if None, use chunk's current chapter)
            effective_sentence_ch_context = sentence_ch_context if sentence_ch_context is not None else current_chunk_assigned_chapter_title
            
            if effective_sentence_ch_context != current_chunk_assigned_chapter_title:
                new_heading_boundary_detected = True
                logger.debug(f"Boundary: Sentence '{marker}' ChContext '{effective_sentence_ch_context}' differs from ChunkCh '{current_chunk_assigned_chapter_title}'.")
            # If chapter context is the same, check sub-chapter context
            elif sentence_subch_context != current_chunk_assigned_sub_chapter_title: # None is different from "Some SubTitle"
                new_heading_boundary_detected = True
                logger.debug(f"Boundary: Sentence '{marker}' SubChContext '{sentence_subch_context}' differs from ChunkSubCh '{current_chunk_assigned_sub_chapter_title}' (Ch: '{effective_sentence_ch_context}').")
        
        # Finalize current chunk IF:
        # 1. It's not empty AND a new heading context is detected for the current sentence.
        # OR
        # 2. It's not empty AND adding the current sentence would exceed the token limit.
        if current_chunk_sentences and \
           (new_heading_boundary_detected or (current_token_count + sentence_tokens > target_tokens)):
            
            chunk_text = " ".join(current_chunk_sentences)
            first_marker = current_chunk_markers[0]
            chunks.append((chunk_text, first_marker, current_chunk_assigned_chapter_title, current_chunk_assigned_sub_chapter_title))
            logger.info(f"Created chunk (ending '{current_chunk_markers[-1]}'). Tokens: {current_token_count}. Reason: {'New Heading Context' if new_heading_boundary_detected else 'Token Limit'}. Ch: '{current_chunk_assigned_chapter_title}', SubCh: '{current_chunk_assigned_sub_chapter_title}'")

            # --- Prepare for the NEXT chunk ---
            overlap_start_idx = max(0, len(current_chunk_sentences) - overlap_sentences)
            sentences_for_overlap = current_chunk_sentences[overlap_start_idx:]
            markers_for_overlap = current_chunk_markers[overlap_start_idx:]
            
            overlap_token_count = 0
            start_original_idx_of_finalized_chunk = i - len(current_chunk_sentences) 
            first_original_idx_for_overlap = start_original_idx_of_finalized_chunk + overlap_start_idx
            for k_overlap in range(len(sentences_for_overlap)):
                original_idx = first_original_idx_for_overlap + k_overlap
                if original_idx >= 0 and original_idx < len(sentence_token_counts):
                     overlap_token_count += sentence_token_counts[original_idx]
            
            current_chunk_sentences = sentences_for_overlap + [sentence]
            current_chunk_markers = markers_for_overlap + [marker]
            current_token_count = overlap_token_count + sentence_tokens
            
            # New chunk's assigned titles are from the current sentence's context that starts it
            current_chunk_assigned_chapter_title = sentence_ch_context if sentence_ch_context is not None else DEFAULT_CHAPTER_TITLE_CHUNK
            current_chunk_assigned_sub_chapter_title = sentence_subch_context
            logger.debug(f"  Started new chunk with overlap. First effective sentence: '{sentence[:30]}...'. New chunk titles: Ch='{current_chunk_assigned_chapter_title}', SubCh='{current_chunk_assigned_sub_chapter_title}'")
        else: 
            # Add current sentence to the ongoing chunk
            # If this is the very first sentence of the very first chunk, set the initial chunk titles
            if not current_chunk_sentences:
                current_chunk_assigned_chapter_title = sentence_ch_context if sentence_ch_context is not None else DEFAULT_CHAPTER_TITLE_CHUNK
                current_chunk_assigned_sub_chapter_title = sentence_subch_context
                logger.debug(f"  Starting first ever chunk. Titles set from sentence '{marker}': Ch='{current_chunk_assigned_chapter_title}', SubCh='{current_chunk_assigned_sub_chapter_title}'")

            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            current_token_count += sentence_tokens

    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        # Titles for the last chunk are already set in current_chunk_assigned_...
        chunks.append((chunk_text, first_marker, current_chunk_assigned_chapter_title, current_chunk_assigned_sub_chapter_title))
        logger.info(f"Created final chunk. Tokens: {current_token_count}. Ch: '{current_chunk_assigned_chapter_title}', SubCh: '{current_chunk_assigned_sub_chapter_title}'")

    logger.info(f"Token chunking (context change split) finished. Total chunks: {len(chunks)}.")
    return chunks

# chunk_by_chapter - this version should work with the 6-tuple structure correctly
def chunk_by_chapter(
    structured_data: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]] 
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    current_chapter_for_chunk: Optional[str] = None 
    first_sub_chapter_in_current_chunk: Optional[str] = None
    # The text of the paragraph that was identified as the current chapter's heading
    active_chapter_heading_text_for_chunk: Optional[str] = None 

    if not structured_data: return []
    logger.info("Starting chunking by chapter (using heading flags).")

    for i, (sentence, marker, is_para_ch_hd, is_para_subch_hd, ch_context, subch_context) in enumerate(structured_data):
        is_new_chapter_boundary = False
        is_first_sentence_of_para = marker.endswith(".s0")

        # A new chapter boundary is defined by the start of a paragraph that IS a chapter heading,
        # and its text (ch_context) is different from the currently active chapter heading text.
        if is_first_sentence_of_para and is_para_ch_hd:
            if active_chapter_heading_text_for_chunk is None or ch_context != active_chapter_heading_text_for_chunk:
                is_new_chapter_boundary = True
        
        if is_new_chapter_boundary:
            if current_chunk_sentences: 
                chunk_text = " ".join(current_chunk_sentences)
                chunks.append((chunk_text, current_chunk_markers[0], 
                               current_chapter_for_chunk if current_chapter_for_chunk else DEFAULT_CHAPTER_TITLE_CHUNK, 
                               first_sub_chapter_in_current_chunk))
            current_chunk_sentences, current_chunk_markers = [], []
            current_chapter_for_chunk = ch_context # This IS the chapter title text
            active_chapter_heading_text_for_chunk = ch_context
            # If this chapter heading paragraph is ALSO a sub-chapter, use its text as the first sub-chapter
            first_sub_chapter_in_current_chunk = subch_context if is_para_subch_hd else None
        
        if sentence: 
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            if current_chapter_for_chunk is None: # For first chunk if it doesn't start with a chapter heading para
                current_chapter_for_chunk = ch_context if ch_context else DEFAULT_CHAPTER_TITLE_CHUNK
            # If this is the first sentence of a sub-chapter paragraph within the current chapter context
            if not first_sub_chapter_in_current_chunk and is_first_sentence_of_para and is_para_subch_hd:
                if ch_context == active_chapter_heading_text_for_chunk: # Ensure it's under the current chapter
                    first_sub_chapter_in_current_chunk = subch_context
        
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        chunks.append((chunk_text, current_chunk_markers[0], 
                       current_chapter_for_chunk if current_chapter_for_chunk else DEFAULT_CHAPTER_TITLE_CHUNK, 
                       first_sub_chapter_in_current_chunk))
    logger.info(f"Chunking by chapter finished. Total chunks: {len(chunks)}.")
    return chunks
