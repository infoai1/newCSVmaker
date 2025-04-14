import nltk
import tiktoken
import streamlit as st
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- NLTK Setup ---
@st.cache_resource
def ensure_nltk_punkt():
    """Downloads the NLTK 'punkt' tokenizer models if not already downloaded."""
    try:
        nltk.data.find('tokenizers/punkt')
        logging.info("NLTK 'punkt' tokenizer already downloaded.")
    except nltk.downloader.DownloadError as e:
        st.warning("NLTK 'punkt' tokenizer not found. Downloading...")
        try:
            nltk.download('punkt')
            st.success("NLTK 'punkt' downloaded successfully.")
            logging.info("NLTK 'punkt' downloaded successfully.")
        except Exception as download_exc:
            st.error(f"Failed to download NLTK 'punkt': {download_exc}")
            logging.error(f"Failed to download NLTK 'punkt': {download_exc}")
            st.stop() # Stop execution if essential data is missing
    except Exception as ex:
        st.error(f"An unexpected error occurred checking NLTK data: {ex}")
        logging.error(f"An unexpected error occurred checking NLTK data: {ex}")
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
        logging.error(f"Failed to load tiktoken tokenizer '{encoding_name}': {e}")
        st.stop() # Stop execution if tokenizer fails
