import tiktoken
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)

DEFAULT_CHAPTER_TITLE_CHUNK = "Introduction" 
DEFAULT_SUBCHAPTER_TITLE_CHUNK = None    

def is_sentence_the_heading_text(sentence_text: str, heading_text: Optional[str]) -> bool:
    """Checks if the sentence text substantially matches the heading text."""
    if not heading_text or not sentence_text:
        return False
    # Simple check: if the sentence starts with the heading text, or vice-versa,
    # and they are of comparable length (e.g. sentence isn't much longer).
    # This handles cases where NLTK might split a heading like "CHAPTER ONE: The Beginning"
    # into "CHAPTER ONE:" and "The Beginning".
    # For simplicity, we'll check if sentence is IN heading or heading is IN sentence,
    # and they are reasonably close in length.
    # A more robust check might involve token similarity.
    s_clean = sentence_text.strip().lower()
    h_clean = heading_text.strip().lower()
    if s_clean == h_clean:
        return True
    # If the sentence is the start of the heading and the heading isn't massively longer
    if h_clean.startswith(s_clean) and len(h_clean) < len(s_clean) * 2 and len(s_clean) > 5 : # Avoid tiny sentence matches
        return True
    # If the heading is the start of the sentence (e.g. heading "Topic" and sentence "Topic of the day")
    if s_clean.startswith(h_clean) and len(s_clean) < len(h_clean) * 2 and len(h_clean) > 5 :
        return True
    return False

def chunk_structured_sentences(
    structured_data: List[Tuple[str, str, Optional[str], Optional[str]]], 
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

    logger.info(f"Token chunking (Target: ~{target_tokens}, Overlap: {overlap_sentences} sents), sensitive to actual heading text.")

    try:
        sentence_texts = [item[0] for item in structured_data]
        all_tokens = tokenizer.encode_batch(sentence_texts, allowed_special="all")
        sentence_token_counts = [len(tokens) for tokens in all_tokens]
    except Exception as e:
        logger.error(f"Tiktoken encoding error: {e}", exc_info=True); return []

    for i, (sentence, marker, extracted_ch_title, extracted_subch_title) in enumerate(structured_data):
        if i >= len(sentence_token_counts):
            logger.warning(f"Data/token count mismatch at index {i}. Skipping."); continue
        sentence_tokens = sentence_token_counts[i]

        # Effective titles for the current sentence based on extraction context
        # This is the context the sentence *belongs to*.
        current_sentence_context_ch_title = extracted_ch_title if extracted_ch_title is not None else \
                                           (current_chunk_assigned_chapter_title if current_chunk_sentences else DEFAULT_CHAPTER_TITLE_CHUNK)
        current_sentence_context_subch_title = extracted_subch_title # Can be None

        new_heading_boundary_detected = False
        is_this_sentence_a_heading = False

        if current_chunk_sentences: # If there's an active chunk being built
            # Rule 1: Does the *context* of this sentence represent a new chapter/sub-chapter?
            if current_sentence_context_ch_title != current_chunk_assigned_chapter_title:
                new_heading_boundary_detected = True
                logger.debug(f"CtxChChange: NewCh='{current_sentence_context_ch_title}', OldCh='{current_chunk_assigned_chapter_title}' for s: '{sentence[:20]}...'")
            elif current_sentence_context_subch_title != current_chunk_assigned_sub_chapter_title:
                new_heading_boundary_detected = True
                logger.debug(f"CtxSubChChange: NewSubCh='{current_sentence_context_subch_title}', OldSubCh='{current_chunk_assigned_sub_chapter_title}' for s: '{sentence[:20]}...'")

            # Rule 2: Is the *text of this sentence itself* a heading that differs from current chunk's context?
            # This is to catch when a heading text appears mid-paragraph after NLTK sentence splitting.
            if not new_heading_boundary_detected: # Only if context hasn't already changed
                if is_sentence_the_heading_text(sentence, current_sentence_context_ch_title) and \
                   current_sentence_context_ch_title != current_chunk_assigned_chapter_title:
                    is_this_sentence_a_heading = True
                    new_heading_boundary_detected = True
                    logger.debug(f"SentenceIsNewCh: '{sentence[:20]}...' IS chapter '{current_sentence_context_ch_title}', different from chunk's '{current_chunk_assigned_chapter_title}'")
                elif is_sentence_the_heading_text(sentence, current_sentence_context_subch_title) and \
                     (current_sentence_context_ch_title == current_chunk_assigned_chapter_title and \
                      current_sentence_context_subch_title != current_chunk_assigned_sub_chapter_title):
                    is_this_sentence_a_heading = True
                    new_heading_boundary_detected = True
                    logger.debug(f"SentenceIsNewSubCh: '{sentence[:20]}...' IS sub-ch '{current_sentence_context_subch_title}', different from chunk's '{current_chunk_assigned_sub_chapter_title}'")
        
        # Finalize current chunk IF:
        # 1. It's not empty AND a new heading boundary is detected for the current sentence.
        # OR
        # 2. It's not empty AND adding the current sentence would exceed the token limit.
        if current_chunk_sentences and \
           (new_heading_boundary_detected or (current_token_count + sentence_tokens > target_tokens)):
            
            chunk_text = " ".join(current_chunk_sentences)
            first_marker = current_chunk_markers[0]
            chunks.append((chunk_text, first_marker, current_chunk_assigned_chapter_title, current_chunk_assigned_sub_chapter_title))
            logger.info(f"Created chunk (ending '{current_chunk_markers[-1]}'). Tokens: {current_token_count}. Reason: {'New Heading' if new_heading_boundary_detected else 'Token Limit'}. Ch: '{current_chunk_assigned_chapter_title}', SubCh: '{current_chunk_assigned_sub_chapter_title}'")

            # --- Prepare for the NEXT chunk ---
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
            current_chunk_assigned_chapter_title = current_sentence_context_ch_title
            current_chunk_assigned_sub_chapter_title = current_sentence_context_subch_title
            logger.debug(f"  Started new chunk with overlap. First effective sentence: '{sentence[:30]}...'. New chunk titles: Ch='{current_chunk_assigned_chapter_title}', SubCh='{current_chunk_assigned_sub_chapter_title}'")

        else: # Add current sentence to the ongoing chunk
            # If this is the very first sentence of the very first chunk:
            if not current_chunk_sentences:
                current_chunk_assigned_chapter_title = current_sentence_context_ch_title
                current_chunk_assigned_sub_chapter_title = current_sentence_context_subch_title
                logger.debug(f"  Starting first ever chunk. Titles set to Ch='{current_chunk_assigned_chapter_title}', SubCh='{current_chunk_assigned_sub_chapter_title}' from sentence '{marker}'")

            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            current_token_count += sentence_tokens
            # logger.debug(f"  Added sentence '{marker}' to current chunk. Tokens: {current_token_count}.")

    # Add the last remaining chunk
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        # Ensure titles are not None if they were established
        final_ch_title = current_chunk_assigned_chapter_title if current_chunk_assigned_chapter_title is not None else DEFAULT_CHAPTER_TITLE_CHUNK
        final_subch_title = current_chunk_assigned_sub_chapter_title # Can be None
        chunks.append((chunk_text, first_marker, final_ch_title, final_subch_title))
        logger.info(f"Created final chunk. Tokens: {current_token_count}. Ch: '{final_ch_title}', SubCh: '{final_subch_title}'")

    logger.info(f"Token chunking (heading sensitive) finished. Total chunks: {len(chunks)}.")
    return chunks

# chunk_by_chapter remains the same as the last approved version
def chunk_by_chapter(
    structured_data: List[Tuple[str, str, Optional[str], Optional[str]]] 
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
    logger.info("Starting chunking by detected chapter title.")

    for i, (sentence, marker, detected_ch_title, detected_subch_title) in enumerate(structured_data):
        is_new_chapter_boundary = False
        if detected_ch_title is not None:
            if active_chapter_heading_text_for_chunk is None: 
                is_new_chapter_boundary = True
            elif detected_ch_title != active_chapter_heading_text_for_chunk: 
                is_new_chapter_boundary = True
        
        if i == 0 and detected_ch_title is not None and not current_chunk_sentences: # Ensure it's truly the start
             is_new_chapter_boundary = True

        if is_new_chapter_boundary:
            # logger.debug(f"New chapter boundary at s{i}. Old active: '{active_chapter_heading_text_for_chunk}', New detected: '{detected_ch_title}'.")
            if current_chunk_sentences: 
                chunk_text = " ".join(current_chunk_sentences)
                first_marker = current_chunk_markers[0]
                final_ch_title_for_prev_chunk = current_chapter_for_chunk if current_chapter_for_chunk is not None else DEFAULT_CHAPTER_TITLE_CHUNK
                chunks.append((chunk_text, first_marker, final_ch_title_for_prev_chunk, first_sub_chapter_in_current_chunk))
                # logger.info(f"Created chapter chunk (ending before s{i}). Ch: '{final_ch_title_for_prev_chunk}', SubCh: '{first_sub_chapter_in_current_chunk}'")

            current_chunk_sentences = []
            current_chunk_markers = []
            current_chapter_for_chunk = detected_ch_title 
            active_chapter_heading_text_for_chunk = detected_ch_title 
            first_sub_chapter_in_current_chunk = detected_subch_title 
        
        if sentence: 
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            
            if current_chapter_for_chunk is None and detected_ch_title is not None: # First title for the very first chunk
                current_chapter_for_chunk = detected_ch_title
                if active_chapter_heading_text_for_chunk is None: 
                     active_chapter_heading_text_for_chunk = detected_ch_title

            if not first_sub_chapter_in_current_chunk and detected_subch_title:
                first_sub_chapter_in_current_chunk = detected_subch_title
        
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        final_ch_title_for_last_chunk = current_chapter_for_chunk if current_chapter_for_chunk is not None else DEFAULT_CHAPTER_TITLE_CHUNK
        chunks.append((chunk_text, first_marker, final_ch_title_for_last_chunk, first_sub_chapter_in_current_chunk))
        # logger.info(f"Created final chapter chunk. Ch: '{final_ch_title_for_last_chunk}', SubCh: '{first_sub_chapter_in_current_chunk}'")

    logger.info(f"Chunking by chapter finished. Total chunks: {len(chunks)}.")
    return chunks
