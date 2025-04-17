import fitz  # PyMuPDF
import docx
import re
import nltk
import io
import logging
import os
import streamlit as st
from typing import List, Tuple, Dict, Any, Optional

# Configure logging (use the same configuration as utils or configure separately)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- NLTK Check ---
def ensure_nltk_punkt_available():
    """
    Verifies punkt is available before processing.
    More robust version with multiple fallback methods.
    """
    try:
        # First try to find punkt
        nltk.data.find('tokenizers/punkt')
        logging.info("NLTK punkt tokenizer found and ready to use.")
        return True
    except LookupError:
        logging.warning("NLTK punkt not found. Attempting download...")
        
        # Set download location to multiple possible paths, trying each one
        possible_dirs = [
            os.path.join(os.path.expanduser('~'), 'nltk_data'),  # Home directory
            os.path.join('/tmp', 'nltk_data'),  # /tmp for Linux/Mac
            os.path.join(os.getcwd(), 'nltk_data'),  # Current working directory
            os.path.join('.', 'nltk_data')  # Relative to current directory
        ]
        
        for nltk_data_dir in possible_dirs:
            try:
                os.makedirs(nltk_data_dir, exist_ok=True)
                nltk.data.path.append(nltk_data_dir)
                logging.info(f"Attempting to download punkt to {nltk_data_dir}")
                
                # Attempt download with a timeout
                nltk.download('punkt', download_dir=nltk_data_dir, quiet=False)
                
                # Verify download was successful
                nltk.data.find('tokenizers/punkt')
                logging.info(f"Successfully downloaded punkt to {nltk_data_dir}")
                return True
                
            except (OSError, IOError, PermissionError) as e:
                logging.warning(f"Failed to download to {nltk_data_dir}: {e}")
                continue
            except Exception as e:
                logging.warning(f"Unexpected error trying {nltk_data_dir}: {e}")
                continue
        
        # If we got here, all download attempts failed
        logging.error("All attempts to download punkt failed. Checking if we can use a simple fallback.")
        
        # As a last resort, try to create a very simple sentence tokenizer
        try:
            # Check if we can monkey-patch a simple tokenizer
            def simple_sent_tokenize(text):
                """Fallback tokenizer that splits on periods followed by whitespace."""
                if not text:
                    return []
                # Simple rule: split on period + whitespace or period + end of string
                sentences = re.split(r'\.(?:\s+|\s*$)', text)
                # Filter out empty sentences and add periods back
                return [s.strip() + "." for s in sentences if s.strip()]
            
            # Replace NLTK's sent_token
