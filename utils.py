import nltk
import tiktoken
import streamlit as st
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- NLTK Setup ---
@st.cache_resource
def ensure_nltk_punkt():
    """Downloads the NLTK 'punkt' tokenizer models if not already downloaded."""
    try:
        nltk.data.find('tokenizers/punkt')
        logging.info("NLTK 'punkt' tokenizer already available.")
    except LookupError:
        logging.warning("NLTK 'punkt' tokenizer not found. Attempting download...")
        st.warning("NLTK 'punkt' tokenizer not found. Downloading now...")
        
        nltk_data_dir = os.path.join(os.path.expanduser('~'), 'nltk_data')
        os.makedirs(nltk_data_dir, exist_ok=True)
        if nltk_data_dir not in nltk.data.path: # Add to path if not already there
            nltk.data.path.append(nltk_data_dir)
        
        try:
            nltk.download('punkt', download_dir=nltk_data_dir)
            st.success("NLTK 'punkt' downloaded successfully.")
            logging.info(f"NLTK 'punkt' downloaded to {nltk_data_dir}")
            nltk.data.find('tokenizers/punkt') # Verify
            logging.info("Verified 'punkt' tokenizer presence after download.")
        except Exception as e:
            st.error(f"Failed to download NLTK 'punkt': {e}")
            logging.error(f"Failed to download NLTK 'punkt': {e}", exc_info=True)
            st.error("Application cannot proceed without the NLTK 'punkt' model.")
            st.stop()
    except Exception as ex:
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
        st.stop()
