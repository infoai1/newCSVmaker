import nltk
import tiktoken
import streamlit as st
import logging
import os # Needed for potential path checks, though not used in final version

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- NLTK Setup ---
@st.cache_resource
def ensure_nltk_punkt():
    """Downloads the NLTK 'punkt' tokenizer models if not already downloaded."""
    try:
        # Check if 'punkt' is available locally
        nltk.data.find('tokenizers/punkt')
        logging.info("NLTK 'punkt' tokenizer already available.")
    except LookupError: # <--- Corrected Exception Type
        st.warning("NLTK 'punkt' tokenizer not found. Attempting download...")
        logging.warning("NLTK 'punkt' tokenizer not found. Attempting download...")
        try:
            # Attempt to download 'punkt'
            nltk.download('punkt')
            st.success("NLTK 'punkt' downloaded successfully.")
            logging.info("NLTK 'punkt' downloaded successfully.")
            # Verify download by trying to find it again
            try:
                nltk.data.find('tokenizers/punkt')
                logging.info("Verified 'punkt' tokenizer presence after download.")
            except LookupError:
                st.error("Download seemed successful, but 'punkt' data still not found. Check NLTK installation, download paths, or permissions.")
                logging.error("Download seemed successful, but 'punkt' data still not found.")
                st.stop()
        except Exception as download_exc: # Catch general exceptions during the download process
            st.error(f"Failed to download NLTK 'punkt': {download_exc}")
            logging.error(f"Failed to download NLTK 'punkt': {download_exc}", exc_info=True)
            st.error("Application cannot proceed without the NLTK 'punkt' model. Please ensure internet connectivity and NLTK download permissions.")
            st.stop() # Stop execution if essential data cannot be obtained
    except Exception as ex: # Catch other unexpected errors during the initial find process
        st.error(f"An unexpected error occurred while checking for NLTK data: {ex}")
        logging.error(f"An unexpected error occurred while checking for NLTK data: {ex}", exc_info=True)
        st.stop()


# --- Tiktoken Setup ---
@st.cache_resource
def load_tokenizer(encoding_name="cl100k_base"):
    """Loads and returns a tiktoken tokenizer."""
    try:
        tokenizer = tiktoken.get_encoding(encoding_name)
        logging.info(f"Tiktoken tokenizer '{encoding_name}' loaded successfully.")
        return tokenizer
    except Exception as e:
        st.error(f"Failed to load tiktoken tokenizer '{encoding_name}': {e}")
        logging.error(f"Failed to load tiktoken tokenizer '{encoding_name}': {e}", exc_info=True)
        st.stop() # Stop execution if tokenizer fails
