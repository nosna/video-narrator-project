# src/utils.py

import logging
import re
from datetime import timedelta

from config import settings # Import the instantiated settings

# --- Logging Setup ---
def setup_logger(name: str, level: str = settings.LOG_LEVEL) -> logging.Logger:
    """
    Sets up a configured logger.
    """
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False # Prevent duplicate logs in parent loggers
    return logger

# --- Time Conversion Utilities ---
def format_timestamp_srt(seconds: float) -> str:
    """
    Converts seconds to SRT timestamp format (HH:MM:SS,mmm).
    """
    delta = timedelta(seconds=seconds)
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds_val = divmod(remainder, 60)
    milliseconds = delta.microseconds // 1000
    return f"{hours:02}:{minutes:02}:{seconds_val:02},{milliseconds:03}"

def srt_time_to_seconds(srt_time: str) -> float:
    """
    Converts an SRT timestamp string (HH:MM:SS,mmm) to seconds.
    """
    try:
        time_parts = srt_time.split(',')
        hms_part = time_parts[0]
        ms_part = time_parts[1]

        h, m, s = map(int, hms_part.split(':'))
        ms = int(ms_part)

        return h * 3600 + m * 60 + s + ms / 1000.0
    except Exception as e:
        # Fallback for simpler HH:MM:SS or MM:SS if parsing fails
        try:
            parts = list(map(int, srt_time.replace(',', '.').split(':')))
            if len(parts) == 3: # HH:MM:SS.mmm or HH:MM:SS
                return parts[0] * 3600 + parts[1] * 60 + float(parts[2])
            elif len(parts) == 2: # MM:SS.mmm or MM:SS
                return parts[0] * 60 + float(parts[1])
            elif len(parts) == 1: # SS.mmm or SS
                return float(parts[0])
            else:
                raise ValueError(f"Invalid SRT time format: {srt_time}") from e
        except ValueError as ve:
            logger = setup_logger(__name__)
            logger.error(f"Could not parse SRT time '{srt_time}': {ve}")
            raise

def clean_filename(filename: str) -> str:
    """
    Cleans a filename by removing or replacing invalid characters.
    """
    # Remove characters that are not alphanumeric, underscores, hyphens, or dots
    filename = re.sub(r'[^\w\-\.]', '_', filename)
    # Replace multiple underscores with a single one
    filename = re.sub(r'_+', '_', filename)
    # Remove leading/trailing underscores or hyphens
    filename = filename.strip('_-')
    return filename


# --- Placeholder for more complex error classes if needed ---
class VideoProcessingError(Exception):
    """Custom exception for video processing errors."""
    pass

class NarrationError(Exception):
    """Custom exception for narration generation errors."""
    pass

class TTSError(Exception):
    """Custom exception for TTS errors."""
    pass

# Example of using the logger within this utils file itself
# logger = setup_logger(__name__)
# logger.info("Utils module loaded.")
