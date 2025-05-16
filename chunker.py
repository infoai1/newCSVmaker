import tiktoken
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

DEFAULT_CHAPTER_TITLE_CHUNK = "Introduction" 
DEFAULT_SUBCHAPTER_TITLE_CHUNK = None    

def chunk_structured_sentences(
    structured_data: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]], 
    # sentence, marker, is_para_chapter_heading, is_para_subchapter_heading, 
    # chapter_context_for_sentence, subchapter_context_for_sentence
    tokenizer: tiktoken.Encoding,
    target_tokens: int = 200,
    overlap_sentences: int = 2
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    # Output: chunk_text, first_marker, assigned_chapter_title_for_chunk, assigned_subchapter_title_for_chunk

    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    current_chunk_assigned_chapter_title: Optional[str] = None
    current_chunk_assigned_sub_chapter_title: Optional[str] = None
    current_token_count = 0

    if not structured_data:
        logger.warning("chunk_structured_sentences: No structured data, returning empty.")
        return []

    logger.info(f"Token chunking (Target: ~{target_tokens}, Overlap: {overlap_sentences} sents), splitting strictly before new heading PARAGRAPHS.")

    try:
        sentence_texts = [item[0] for item in structured_data]
        all_tokens = tokenizer.encode_batch(sentence_texts, allowed_special="all")
        sentence_token_counts = [len(tokens) for tokens in all_tokens]
    except Exception as e:
        logger.error(f"Tiktoken encoding error: {e}", exc_info=True); return []

    for i, (sentence, marker, para_is_ch_heading, para_is_subch_heading, 
              sentence_ch_context, sentence_subch_context) in enumerate(structured_data):
        
        if i >= len(sentence_token_counts):
            logger.warning(f"Data/token count mismatch at index {i}. Skipping."); continue
        sentence_tokens = sentence_token_counts[i]

        new_heading_paragraph_starts_here = False
        is_first_sentence_of_its_para = marker.endswith(".s0")

        # If a chunk is already being built, check if this new sentence starts a new heading paragraph
        if current_chunk_sentences and is_first_sentence_of_its_para:
            # Check if the new paragraph is a chapter heading different from current chunk's chapter
            if para_is_ch_heading: # The current sentence's paragraph IS a chapter heading
                # sentence_ch_context will be the text of this chapter heading
                if sentence_ch_context != current_chunk_assigned_chapter_title:
                    new_heading_paragraph_starts_here = True
                    logger.debug(f"CHUNK SPLIT Trigger: New CHAPTER para '{marker}' ('{sentence_ch_context[:30]}...'). Chunk was Ch: '{current_chunk_assigned_chapter_title}'.")
            
            # If not a new chapter, check if it's a new sub-chapter paragraph
            elif para_is_subch_heading: # The current sentence's paragraph IS a sub-chapter heading
                # sentence_subch_context will be the text of this sub-chapter heading
                # Chapter context must be the same for it to be a sub-chapter under the current chapter
                if (sentence_ch_context == current_chunk_assigned_chapter_title and \
                    sentence_subch_context != current_chunk_assigned_sub_chapter_title):
                    new_heading_paragraph_starts_here = True
                    logger.debug(f"CHUNK SPLIT Trigger: New SUB-CHAPTER para '{marker}' ('{sentence_subch_context[:30]}...'). Chunk was Ch: '{current_chunk_assigned_chapter_title}', SubCh: '{current_chunk_assigned_sub_chapter_title}'.")
        
        # Finalize current chunk IF:
        # 1. It's not empty AND this sentence starts a new heading paragraph.
        # OR
        # 2. It's not empty AND adding the current sentence would exceed the token limit.
        if current_chunk_sentences and \
           (new_heading_paragraph_starts_here or (current_token_count + sentence_tokens > target_tokens)):
            
            chunk_text = " ".join(current_chunk_sentences)
            first_marker = current_chunk_markers[0]
            chunks.append((chunk_text, first_marker, current_chunk_assigned_chapter_title, current_chunk_assigned_sub_chapter_title))
            logger.info(f"Created chunk (ending '{current_chunk_markers[-1]}'). Tokens: {current_token_count}. Reason: {'New Heading Paragraph' if new_heading_paragraph_starts_here else 'Token Limit'}. Ch: '{current_chunk_assigned_chapter_title}', SubCh: '{current_chunk_assigned_sub_chapter_title}'")

            # --- Prepare for the NEXT chunk (which starts with the current `sentence`) ---
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
            
            # New chunk's assigned titles are from the current sentence's context (which is the heading itself if new_heading_paragraph_starts_here)
            current_chunk_assigned_chapter_title = sentence_ch_context if sentence_ch_context is not None else DEFAULT_CHAPTER_TITLE_CHUNK
            current_chunk_assigned_sub_chapter_title = sentence_subch_context
            logger.debug(f"  Started new chunk. First effective sentence: '{marker}'-'{sentence[:30]}...'. New chunk titles: Ch='{current_chunk_assigned_chapter_title}', SubCh='{current_chunk_assigned_sub_chapter_title}'")
        else: 
            # Add current sentence to the ongoing chunk
            # If this is the very first sentence of the very first chunk, set the initial chunk titles
            if not current_chunk_sentences:
                current_chunk_assigned_chapter_title = sentence_ch_context if sentence_ch_context is not None else DEFAULT_CHAPTER_TITLE_CHUNK
                current_chunk_assigned_sub_chapter_title = sentence_subch_context
                logger.debug(f"  Starting first ever chunk. Titles from sentence '{marker}': Ch='{current_chunk_assigned_chapter_title}', SubCh='{current_chunk_assigned_sub_chapter_title}'")

            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            current_token_count += sentence_tokens

    # Add the last remaining chunk
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        chunks.append((chunk_text, current_chunk_markers[0], current_chunk_assigned_chapter_title, current_chunk_assigned_sub_chapter_title))
        logger.info(f"Created final chunk. Tokens: {current_token_count}. Ch: '{current_chunk_assigned_chapter_title}', SubCh: '{current_chunk_assigned_sub_chapter_title}'")

    logger.info(f"Token chunking (paragraph heading split) finished. Total chunks: {len(chunks)}.")
    return chunks

# chunk_by_chapter - this version uses the 6-tuple structure correctly
def chunk_by_chapter(
    structured_data: List[Tuple[str, str, bool, bool, Optional[str], Optional[str]]] 
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    current_chapter_for_chunk: Optional[str] = None 
    first_sub_chapter_in_current_chunk: Optional[str] = None
    active_chapter_heading_text_para: Optional[str] = None # Text of the para that IS the chapter heading

    if not structured_data: return []
    logger.info("Starting chunking by chapter (based on paragraph heading flags).")

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
