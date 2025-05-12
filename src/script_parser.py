# src/script_parser.py

import json
from typing import List, Dict, Any, TypedDict, Optional

from utils import setup_logger, srt_time_to_seconds, format_timestamp_srt, NarrationError

logger = setup_logger(__name__)

class NarrationSegment(TypedDict):
    """
    Represents a single segment of narration with times in seconds.
    """
    id: int
    start_time_sec: float
    end_time_sec: float
    text: str

class ScriptParserError(NarrationError):
    """Custom exception for errors during script parsing and validation."""
    pass

class ScriptParser:
    """
    Parses, validates, and formats the narration script received from Gemini.
    """

    def __init__(self, raw_json_script: str, video_duration_sec: float):
        """
        Initializes the ScriptParser.

        Args:
            raw_json_script (str): The raw JSON string received from Gemini.
            video_duration_sec (float): The total duration of the video in seconds, for validation.
        """
        self.raw_json_script = raw_json_script
        self.video_duration_sec = video_duration_sec
        self.parsed_segments: List[NarrationSegment] = []

    def parse_and_validate(self) -> List[NarrationSegment]:
        """
        Parses the raw JSON script, validates its structure and content.

        Returns:
            List[NarrationSegment]: A list of validated narration segments.

        Raises:
            ScriptParserError: If parsing or validation fails.
        """
        logger.info("Starting to parse and validate Gemini narration script.")
        try:
            raw_segments = json.loads(self.raw_json_script)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON format in Gemini response: {e}")
            logger.debug(f"Problematic JSON string: {self.raw_json_script[:500]}...") # Log first 500 chars
            raise ScriptParserError(f"Failed to decode JSON from Gemini: {e}") from e

        if not isinstance(raw_segments, list):
            logger.error(f"Gemini script is not a list, but type: {type(raw_segments)}")
            raise ScriptParserError("Expected a list of narration segments from Gemini.")

        self.parsed_segments = []
        expected_keys = {"start_time", "end_time", "narration_text"}
        last_segment_end_time = 0.0

        for i, seg_data in enumerate(raw_segments):
            segment_id = i + 1
            if not isinstance(seg_data, dict):
                raise ScriptParserError(f"Segment {segment_id} is not a dictionary: {seg_data}")

            missing_keys = expected_keys - set(seg_data.keys())
            if missing_keys:
                raise ScriptParserError(f"Segment {segment_id} is missing keys: {missing_keys}. Data: {seg_data}")

            try:
                start_time_str = seg_data["start_time"]
                end_time_str = seg_data["end_time"]
                text = seg_data["narration_text"]

                if not isinstance(start_time_str, str) or not isinstance(end_time_str, str):
                    raise ScriptParserError(f"Segment {segment_id}: Timestamps must be strings. Got: {start_time_str}, {end_time_str}")
                if not isinstance(text, str):
                    raise ScriptParserError(f"Segment {segment_id}: narration_text must be a string. Got: {type(text)}")
                if not text.strip():
                    logger.warning(f"Segment {segment_id} has empty narration text. Skipping.")
                    continue

                start_time_sec = srt_time_to_seconds(start_time_str)
                end_time_sec = srt_time_to_seconds(end_time_str)

            except ValueError as e: # Raised by srt_time_to_seconds for invalid format
                raise ScriptParserError(f"Segment {segment_id}: Invalid timestamp format. Error: {e}. Data: {seg_data}") from e
            except KeyError as e: # Should be caught by missing_keys check, but as a safeguard
                raise ScriptParserError(f"Segment {segment_id}: Missing critical key. Error: {e}. Data: {seg_data}") from e


            # --- Timestamp Validations ---
            if start_time_sec < 0:
                logger.warning(f"Segment {segment_id}: Start time ({start_time_sec:.3f}s) is negative. Clamping to 0.")
                start_time_sec = 0.0
            if end_time_sec < 0: # Should not happen if start_time < end_time
                 logger.warning(f"Segment {segment_id}: End time ({end_time_sec:.3f}s) is negative. Problematic segment.")
                 end_time_sec = start_time_sec + 0.1 # Give a small positive duration

            if start_time_sec >= end_time_sec:
                # Attempt to fix minor issues, e.g. if LLM makes end time slightly before start time
                if end_time_sec >= start_time_sec - 0.1: # If end is very close to start
                    logger.warning(f"Segment {segment_id}: Start time ({start_time_sec:.3f}s) is not before end time ({end_time_sec:.3f}s). Adjusting end time slightly.")
                    end_time_sec = start_time_sec + 0.1 # Add a minimal duration
                else:
                    raise ScriptParserError(f"Segment {segment_id}: Start time ({start_time_sec:.3f}s) must be before end time ({end_time_sec:.3f}s). Data: {seg_data}")

            if end_time_sec > self.video_duration_sec + 5.0: # Allow a small 5s leeway
                logger.warning(f"Segment {segment_id}: End time ({end_time_sec:.3f}s) exceeds video duration ({self.video_duration_sec:.3f}s by more than 5s). Clamping to video duration.")
                end_time_sec = self.video_duration_sec
                if start_time_sec >= end_time_sec: # If clamping makes start >= end
                    start_time_sec = max(0.0, end_time_sec - 0.1) # Ensure start is before new end

            if start_time_sec < last_segment_end_time - 0.5: # Allow small overlap of 500ms
                logger.warning(f"Segment {segment_id}: Start time ({start_time_sec:.3f}s) overlaps significantly with previous segment's end time ({last_segment_end_time:.3f}s). Adjusting start time.")
                start_time_sec = last_segment_end_time
                if start_time_sec >= end_time_sec: # If adjustment makes start >= end
                    end_time_sec = start_time_sec + 0.1

            self.parsed_segments.append({
                "id": segment_id,
                "start_time_sec": start_time_sec,
                "end_time_sec": end_time_sec,
                "text": text.strip()
            })
            last_segment_end_time = end_time_sec

        if not self.parsed_segments:
            logger.warning("No valid narration segments found after parsing.")
            # Depending on strictness, could raise an error here.

        logger.info(f"Successfully parsed and validated {len(self.parsed_segments)} narration segments.")
        return self.parsed_segments

    def to_srt(self) -> str:
        """
        Converts the parsed narration segments to SRT (SubRip Text) format.

        Returns:
            str: The narration script in SRT format.

        Raises:
            NarrationError: If no segments have been parsed yet.
        """
        if not self.parsed_segments:
            # Try to parse if not already done, or if it failed silently before
            if not self.raw_json_script:
                 raise NarrationError("No raw script provided to parse for SRT conversion.")
            logger.info("Segments not parsed yet or parsing yielded no results. Attempting parse before SRT conversion.")
            self.parse_and_validate() # This might raise an error if parsing fails
            if not self.parsed_segments:
                 logger.warning("Parsing yielded no segments. SRT will be empty.")
                 return ""


        srt_blocks = []
        for segment in self.parsed_segments:
            start_srt = format_timestamp_srt(segment["start_time_sec"])
            end_srt = format_timestamp_srt(segment["end_time_sec"])
            # Basic text cleaning: Ensure no more than 2 lines for typical SRT display
            lines = segment["text"].splitlines()
            cleaned_text = "\n".join(line.strip() for line in lines if line.strip())[:250] # Limit segment length

            srt_block = f"{segment['id']}\n{start_srt} --> {end_srt}\n{cleaned_text}\n"
            srt_blocks.append(srt_block)

        return "\n".join(srt_blocks)

    def get_parsed_segments(self) -> List[NarrationSegment]:
        """Returns the list of parsed and validated narration segments."""
        if not self.parsed_segments and self.raw_json_script:
            logger.info("Attempting to parse segments as they were not available.")
            self.parse_and_validate()
        return self.parsed_segments


# Example Usage (for testing this module directly)
if __name__ == "__main__":
    sample_video_duration = 60.0  # 60 seconds

    # Test Case 1: Valid JSON
    valid_json_script = """
    [
        {
            "start_time": "00:00:01,500",
            "end_time": "00:00:05,000",
            "narration_text": "This is the first narration segment.\\nIt has two lines."
        },
        {
            "start_time": "00:00:06,000",
            "end_time": "00:00:10,250",
            "narration_text": "A second segment follows."
        },
        {
            "start_time": "00:00:10,000",
            "end_time": "00:00:15,000",
            "narration_text": "This segment slightly overlaps but should be adjusted."
        },
        {
            "start_time": "00:01:02,000",
            "end_time": "00:01:05,000",
            "narration_text": "This segment is beyond video duration and should be clamped."
        }
    ]
    """
    print("--- Testing with Valid JSON ---")
    try:
        parser = ScriptParser(valid_json_script, sample_video_duration)
        segments = parser.parse_and_validate()
        # print("Parsed Segments:")
        # for seg in segments:
        #     print(seg)
        srt_output = parser.to_srt()
        print("\nSRT Output:")
        print(srt_output)
    except ScriptParserError as e:
        print(f"Error: {e}")

    # Test Case 2: Invalid JSON structure
    invalid_json_structure = """
    {
        "script": [
            {"start_time": "00:00:01,000", "end_time": "00:00:05,000", "narration_text": "Bad structure"}
        ]
    }
    """
    print("\n--- Testing with Invalid JSON Structure (not a list) ---")
    try:
        parser = ScriptParser(invalid_json_structure, sample_video_duration)
        parser.parse_and_validate()
    except ScriptParserError as e:
        print(f"Successfully caught error: {e}")

    # Test Case 3: Missing keys in a segment
    missing_keys_json = """
    [
        {"start_time": "00:00:01,000", "narration_text": "Missing end_time"}
    ]
    """
    print("\n--- Testing with Missing Keys in Segment ---")
    try:
        parser = ScriptParser(missing_keys_json, sample_video_duration)
        parser.parse_and_validate()
    except ScriptParserError as e:
        print(f"Successfully caught error: {e}")

    # Test Case 4: Invalid timestamp format
    invalid_timestamp_json = """
    [
        {"start_time": "00:00:01", "end_time": "00-00-05,000", "narration_text": "Invalid time"}
    ]
    """
    print("\n--- Testing with Invalid Timestamp Format ---")
    try:
        parser = ScriptParser(invalid_timestamp_json, sample_video_duration)
        parser.parse_and_validate()
    except ScriptParserError as e:
        print(f"Successfully caught error: {e}")

    # Test Case 5: Start time not before end time
    invalid_time_logic_json = """
    [
        {"start_time": "00:00:05,000", "end_time": "00:00:03,000", "narration_text": "Start after end"}
    ]
    """
    print("\n--- Testing with Start Time Not Before End Time ---")
    try:
        parser = ScriptParser(invalid_time_logic_json, sample_video_duration)
        parser.parse_and_validate()
    except ScriptParserError as e:
        print(f"Successfully caught error: {e}")

    # Test Case 6: Empty JSON list
    empty_json_list = "[]"
    print("\n--- Testing with Empty JSON List ---")
    try:
        parser = ScriptParser(empty_json_list, sample_video_duration)
        segments = parser.parse_and_validate()
        print(f"Parsed segments: {segments}")
        srt_output = parser.to_srt()
        print(f"SRT output for empty list: '{srt_output}'")
        assert srt_output == ""
        print("Test passed: Empty SRT for empty list.")
    except ScriptParserError as e:
        print(f"Error: {e}")

    # Test Case 7: Malformed JSON
    malformed_json = """[{"start_time": "00:00:01,000", "end_time": "00:00:05,000", "narration_text": "Text" },]""" # trailing comma
    print("\n--- Testing with Malformed JSON (trailing comma) ---")
    try:
        parser = ScriptParser(malformed_json, sample_video_duration)
        parser.parse_and_validate()
    except ScriptParserError as e:
        print(f"Successfully caught error: {e}")
