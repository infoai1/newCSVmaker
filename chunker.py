import tiktoken
import logging
from typing import List, Tuple, Optional

# Configure logging for this module
# If app.py sets a root logger, this will use that configuration unless specified otherwise.
logger = logging.getLogger(__name__) # Use a named logger

DEFAULT_CHAPTER_TITLE_CHUNK = "Introduction" # Fallback for chunks
DEFAULT_SUBCHAPTER_TITLE_CHUNK = None    # Fallback for chunks

def chunk_structured_sentences(
    structured_data: List[Tuple[str, str, Optional[str], Optional[str]]], # sentence, marker, chapter_title, sub_chapter_title
    tokenizer: tiktoken.Encoding,
    target_tokens: int = 200,
    overlap_sentences: int = 2
) -> List[Tuple[str, str, Optional[str], Optional[str]]]: # chunk_text, first_marker, chapter_title_of_chunk, sub_chapter_title_of_chunk
    """
    Chunks structured sentences based on a target token count with sentence overlap.
    Crucially, it will end a chunk if the next sentence to be added belongs to a newly detected chapter or sub-chapter title.
    """
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    # Titles for the chunk being built (taken from the first sentence of that chunk)
    current_chunk_assigned_chapter_title: Optional[str] = None
    current_chunk_assigned_sub_chapter_title: Optional[str] = None
    
    current_token_count = 0

    if not structured_data:
        logger.warning("chunk_structured_sentences: No structured data provided, returning empty list.")
        return []

    logger.info(f"Starting token-based chunking (Target: ~{target_tokens}, Overlap: {overlap_sentences} sentences), sensitive to heading changes.")

    try:
        sentence_texts = [item[0] for item in structured_data]
        all_tokens = tokenizer.encode_batch(sentence_texts, allowed_special="all")
        sentence_token_counts = [len(tokens) for tokens in all_tokens]
        logger.debug(f"Token counts pre-calculated for {len(sentence_token_counts)} sentences.")
    except Exception as e:
        logger.error(f"Tiktoken encoding failed during pre-calculation: {e}", exc_info=True)
        return []

    for i, (sentence, marker, extracted_ch_title, extracted_subch_title) in enumerate(structured_data):
        if i >= len(sentence_token_counts):
            logger.warning(f"Mismatch between structured_data (len {len(structured_data)}) and sentence_token_counts (len {len(sentence_token_counts)}) at index {i}. Skipping sentence.")
            continue
        
        sentence_tokens = sentence_token_counts[i]

        # If this is the first sentence of a potential new chunk
        if not current_chunk_sentences:
            current_chunk_assigned_chapter_title = extracted_ch_title if extracted_ch_title is not None else DEFAULT_CHAPTER_TITLE_CHUNK
            current_chunk_assigned_sub_chapter_title = extracted_subch_title # Can be None

        # Determine if the current sentence (`sentence`) marks a new heading boundary
        # relative to the context of `current_chunk_assigned_chapter_title` and `current_chunk_assigned_sub_chapter_title`.
        new_heading_boundary_detected = False
        if current_chunk_sentences: # Only check if there's an existing chunk context
            # A new *explicit* chapter title always signifies a new boundary.
            if extracted_ch_title is not None and extracted_ch_title != current_chunk_assigned_chapter_title:
                new_heading_boundary_detected = True
                logger.debug(f"New chapter boundary: Current sentence chapter '{extracted_ch_title}' differs from chunk's active chapter '{current_chunk_assigned_chapter_title}'.")
            # If chapter is the same (or current sentence inherits it), check for sub-chapter change.
            # A new *explicit* sub-chapter title signifies a boundary if the chapter context is the same.
            elif (extracted_ch_title is None or extracted_ch_title == current_chunk_assigned_chapter_title) and \
                 (extracted_subch_title != current_chunk_assigned_sub_chapter_title): # Note: None != "Some SubTitle" is true.
                new_heading_boundary_detected = True
                logger.debug(f"New sub-chapter boundary: Current sentence sub-chapter '{extracted_subch_title}' differs from chunk's active sub-chapter '{current_chunk_assigned_sub_chapter_title}' (Chapter: '{current_chunk_assigned_chapter_title}').")
        
        # Finalize current chunk IF:
        # 1. It's not empty AND a new heading boundary is detected for the current sentence.
        # OR
        # 2. It's not empty AND adding the current sentence would exceed the token limit.
        if current_chunk_sentences and \
           (new_heading_boundary_detected or (current_token_count + sentence_tokens > target_tokens)):
            
            chunk_text = " ".join(current_chunk_sentences)
            first_marker = current_chunk_markers[0]
            
            # The titles assigned to the chunk are those from its first sentence
            chunks.append((chunk_text, first_marker, current_chunk_assigned_chapter_title, current_chunk_assigned_sub_chapter_title))
            logger.info(f"Created chunk ending at marker '{current_chunk_markers[-1]}'. Tokens: {current_token_count}. Reason: {'New Heading Detected' if new_heading_boundary_detected else 'Token Limit'}. Ch: '{current_chunk_assigned_chapter_title}', SubCh: '{current_chunk_assigned_sub_chapter_title}'")

            # --- Prepare for the NEXT chunk (which will start with the current `sentence`) ---
            # Sentences for overlap are taken from the *end* of the chunk we just finalized.
            overlap_start_idx = max(0, len(current_chunk_sentences) - overlap_sentences)
            
            # Get the actual sentence data for overlap
            sentences_for_overlap = current_chunk_sentences[overlap_start_idx:]
            markers_for_overlap = current_chunk_markers[overlap_start_idx:]
            # Titles for overlap sentences are same as the chunk they came from
            ch_titles_for_overlap = [current_chunk_assigned_chapter_title] * len(sentences_for_overlap)
            subch_titles_for_overlap = [current_chunk_assigned_sub_chapter_title] * len(sentences_for_overlap)
            
            # Calculate token count for these overlapping sentences
            overlap_token_count = 0
            # To get original indices: current `i` is for the sentence *causing* the new chunk.
            # The chunk just finalized ended at sentence `i-1`.
            # The `current_chunk_sentences` came from indices `(i - len(current_chunk_sentences))` up to `(i-1)`.
            start_original_idx_of_finalized_chunk = i - len(current_chunk_sentences)
            first_original_idx_for_overlap = start_original_idx_of_finalized_chunk + overlap_start_idx
            
            for k_overlap in range(len(sentences_for_overlap)):
                original_idx = first_original_idx_for_overlap + k_overlap
                if original_idx < len(sentence_token_counts): # Boundary check
                     overlap_token_count += sentence_token_counts[original_idx]
                else:
                    logger.warning(f"Index out of bounds ({original_idx}) for sentence_token_counts accessing overlap tokens.")


            # Initialize the NEW chunk with overlap + current sentence
            current_chunk_sentences = sentences_for_overlap + [sentence]
            current_chunk_markers = markers_for_overlap + [marker]
            current_token_count = overlap_token_count + sentence_tokens
            
            # The NEW chunk's assigned titles will be based on THIS sentence (which started the new boundary or continued after token split)
            current_chunk_assigned_chapter_title = extracted_ch_title if extracted_ch_title is not None else DEFAULT_CHAPTER_TITLE_CHUNK
            current_chunk_assigned_sub_chapter_title = extracted_subch_title # Can be None
            logger.debug(f"  Starting new chunk with overlap. First sentence: '{sentence[:30]}...'. New chunk titles: Ch='{current_chunk_assigned_chapter_title}', SubCh='{current_chunk_assigned_sub_chapter_title}'")

        else: # Add current sentence to the ongoing chunk
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            current_token_count += sentence_tokens
            # If this was the first sentence, titles were already set. If not, they remain the same.
            logger.debug(f"  Added sentence '{marker}' to current chunk. Tokens now: {current_token_count}. Chunk titles: Ch='{current_chunk_assigned_chapter_title}', SubCh='{current_chunk_assigned_sub_chapter_title}'")


    # Add the last remaining chunk
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        # Titles are already set for current_chunk_assigned_...
        chunks.append((chunk_text, first_marker, current_chunk_assigned_chapter_title, current_chunk_assigned_sub_chapter_title))
        logger.info(f"Created final chunk. Tokens: {current_token_count}. Ch: '{current_chunk_assigned_chapter_title}', SubCh: '{current_chunk_assigned_sub_chapter_title}'")

    logger.info(f"Finished token-based chunking (heading sensitive). Total chunks created: {len(chunks)}.")
    return chunks


def chunk_by_chapter(
    structured_data: List[Tuple[str, str, Optional[str], Optional[str]]] 
) -> List[Tuple[str, str, Optional[str], Optional[str]]]:
    """
    Chunks structured sentences based on detected chapter titles.
    Sub-chapter titles are also propagated (uses the first sub-chapter title encountered in the chapter chunk).
    """
    chunks = []
    current_chunk_sentences = []
    current_chunk_markers = []
    
    # Title for the chunk currently being built (this IS the chapter title for this chunker)
    current_chapter_for_chunk: Optional[str] = None 
    # The first sub-chapter encountered within this current chapter chunk
    first_sub_chapter_in_current_chunk: Optional[str] = None
    
    # Tracks the actual text of the chapter heading that started the current chunk,
    # to distinguish between a continued chapter (where detected_chapter_title might be None but contextually the same)
    # and an actual new chapter title.
    active_chapter_heading_text_for_chunk: Optional[str] = None


    if not structured_data:
        logger.warning("chunk_by_chapter: No structured data, returning empty list.")
        return []

    logger.info("Starting chunking by detected chapter title.")

    for i, (sentence, marker, detected_ch_title, detected_subch_title) in enumerate(structured_data):
        
        is_new_chapter_boundary = False
        # A new chapter boundary is if an explicit chapter title is detected AND
        # (it's the first one ever OR it's different from the active one for the current chunk)
        if detected_ch_title is not None:
            if active_chapter_heading_text_for_chunk is None: # First chapter encountered
                is_new_chapter_boundary = True
            elif detected_ch_title != active_chapter_heading_text_for_chunk: # A new, different chapter title
                is_new_chapter_boundary = True
        
        if is_new_chapter_boundary:
            logger.debug(f"New chapter boundary detected at sentence {i}. Old active chapter: '{active_chapter_heading_text_for_chunk}', New detected: '{detected_ch_title}'.")
            if current_chunk_sentences: 
                chunk_text = " ".join(current_chunk_sentences)
                first_marker = current_chunk_markers[0]
                # Use the chapter title that was active for the chunk being finalized
                final_ch_title_for_prev_chunk = current_chapter_for_chunk if current_chapter_for_chunk is not None else DEFAULT_CHAPTER_TITLE_CHUNK
                chunks.append((chunk_text, first_marker, final_ch_title_for_prev_chunk, first_sub_chapter_in_current_chunk))
                logger.info(f"Created chapter chunk ending before s{i}. Ch: '{final_ch_title_for_prev_chunk}', First SubCh: '{first_sub_chapter_in_current_chunk}'")

            # Reset for the new chapter chunk
            current_chunk_sentences = []
            current_chunk_markers = []
            current_chapter_for_chunk = detected_ch_title # This is the title for the new chunk
            active_chapter_heading_text_for_chunk = detected_ch_title # This is the defining heading text
            first_sub_chapter_in_current_chunk = detected_subch_title # This sentence's sub-chapter is the first for the new chunk
        
        # Accumulate sentence
        if sentence: # Ensure sentence is not empty
            current_chunk_sentences.append(sentence)
            current_chunk_markers.append(marker)
            
            # If current_chapter_for_chunk is still None (e.g., first item in data has no chapter title)
            # or default, try to set it from the first available detected_ch_title.
            if current_chapter_for_chunk is None and detected_ch_title is not None:
                current_chapter_for_chunk = detected_ch_title
                if active_chapter_heading_text_for_chunk is None: # If truly the first chapter seen
                     active_chapter_heading_text_for_chunk = detected_ch_title

            # If this is the first sentence being added to this chapter's chunk and we haven't found a sub-chapter yet,
            # use this sentence's sub-chapter title (if any).
            if not first_sub_chapter_in_current_chunk and detected_subch_title:
                first_sub_chapter_in_current_chunk = detected_subch_title
        
        # logger.debug(f"  s{i}: text='{sentence[:20]}...', ch='{detected_ch_title}', subch='{detected_subch_title}'. Current chunk ch='{current_chapter_for_chunk}', first_sub='{first_sub_chapter_in_current_chunk}'")


    # Add the last remaining chunk
    if current_chunk_sentences:
        chunk_text = " ".join(current_chunk_sentences)
        first_marker = current_chunk_markers[0]
        final_ch_title_for_last_chunk = current_chapter_for_chunk if current_chapter_for_chunk is not None else DEFAULT_CHAPTER_TITLE_CHUNK
        chunks.append((chunk_text, first_marker, final_ch_title_for_last_chunk, first_sub_chapter_in_current_chunk))
        logger.info(f"Created final chapter chunk. Ch: '{final_ch_title_for_last_chunk}', First SubCh: '{first_sub_chapter_in_current_chunk}'")

    logger.info(f"Finished chunking by chapter. Total chunks created: {len(chunks)}.")
    return chunks
