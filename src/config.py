# src/config.py

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Settings:
    """
    Configuration settings for the application.
    Reads values from environment variables.
    """
    # Google API Key for Gemini
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    if not GOOGLE_API_KEY:
        print("Warning: GOOGLE_API_KEY not found in environment variables.")

    # Gemini Model for video processing
    # Default to a known capable model if not specified
    GEMINI_VIDEO_MODEL: str = os.getenv("GEMINI_VIDEO_MODEL", "gemini-1.5-pro-latest")

    # Output directory for generated files
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "output")

    # --- TTS Configuration (Example for a generic setup) ---
    # You might need more specific configs depending on the TTS provider
    # For instance, if using Google Cloud TTS:
    # GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    # TTS_VOICE_NAME: str = os.getenv("TTS_VOICE_NAME", "en-US-Wavenet-D") # Example
    # TTS_SPEAKING_RATE: float = float(os.getenv("TTS_SPEAKING_RATE", "1.0"))

    # --- Video Processing ---
    # Maximum video duration to process directly (in seconds)
    # Longer videos might require chunking or different handling via File API
    MAX_INLINE_VIDEO_DURATION_S: int = 55 # Gemini inline video data is often limited

    # Maximum file size for inline video data (in MB)
    MAX_INLINE_VIDEO_SIZE_MB: int = 19 # Gemini inline video data is often limited to <20MB

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()


# Instantiate settings to be imported by other modules
settings = Settings()

# Ensure output directory exists
if not os.path.exists(settings.OUTPUT_DIR):
    try:
        os.makedirs(settings.OUTPUT_DIR)
        print(f"Created output directory: {settings.OUTPUT_DIR}")
    except OSError as e:
        print(f"Error creating output directory {settings.OUTPUT_DIR}: {e}")
        # Potentially raise an error or exit if output dir is critical
