# tests/test_script_parser.py

import unittest
import os
import sys

# Adjust path to import from src
# This assumes 'tests' is a subdirectory of the project root, and 'src' is also in the project root.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
src_path = os.path.join(project_root, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from script_parser import ScriptParser, ScriptParserError, NarrationSegment # type: ignore
# The 'type: ignore' is because the linter might not recognize 'src' path adjustment immediately

class TestScriptParser(unittest.TestCase):

    def setUp(self):
        self.video_duration_sec = 60.0  # Example video duration for tests

    def test_valid_script_parsing(self):
        """Test parsing a valid JSON script."""
        valid_json_script = """
        [
            {
                "start_time": "00:00:01,500",
                "end_time": "00:00:05,000",
                "narration_text": "First segment."
            },
            {
                "start_time": "00:00:06,000",
                "end_time": "00:00:10,250",
                "narration_text": "Second segment."
            }
        ]
        """
        parser = ScriptParser(valid_json_script, self.video_duration_sec)
        segments = parser.parse_and_validate()
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0]['text'], "First segment.")
        self.assertAlmostEqual(segments[0]['start_time_sec'], 1.5)
        self.assertAlmostEqual(segments[0]['end_time_sec'], 5.0)
        self.assertEqual(segments[1]['id'], 2) # ID should be 1-based index

    def test_invalid_json_format(self):
        """Test parsing malformed JSON."""
        invalid_json = "[{'start_time': '00:00:01,000', 'end_time': '00:00:05,000', 'narration_text': 'Segment.'},]" # Trailing comma
        parser = ScriptParser(invalid_json, self.video_duration_sec)
        with self.assertRaisesRegex(ScriptParserError, "Failed to decode JSON"):
            parser.parse_and_validate()

    def test_script_not_a_list(self):
        """Test when the root of the JSON is not a list."""
        not_a_list_json = """
        { "error": "This is not a list of segments." }
        """
        parser = ScriptParser(not_a_list_json, self.video_duration_sec)
        with self.assertRaisesRegex(ScriptParserError, "Expected a list of narration segments"):
            parser.parse_and_validate()

    def test_segment_not_a_dictionary(self):
        """Test when a segment in the list is not a dictionary."""
        segment_not_dict_json = """
        [
            "This is not a dictionary"
        ]
        """
        parser = ScriptParser(segment_not_dict_json, self.video_duration_sec)
        with self.assertRaisesRegex(ScriptParserError, "Segment 1 is not a dictionary"):
            parser.parse_and_validate()

    def test_missing_keys_in_segment(self):
        """Test a segment missing required keys."""
        missing_keys_json = """
        [
            {"start_time": "00:00:01,000", "narration_text": "Missing end_time"}
        ]
        """
        parser = ScriptParser(missing_keys_json, self.video_duration_sec)
        with self.assertRaisesRegex(ScriptParserError, "Segment 1 is missing keys:.*end_time"):
            parser.parse_and_validate()

    def test_invalid_timestamp_format(self):
        """Test segment with invalid timestamp string format."""
        invalid_timestamp_json = """
        [
            {"start_time": "00-00-01:000", "end_time": "00:00:05,000", "narration_text": "Invalid start time"}
        ]
        """
        parser = ScriptParser(invalid_timestamp_json, self.video_duration_sec)
        with self.assertRaisesRegex(ScriptParserError, "Segment 1: Invalid timestamp format"):
            parser.parse_and_validate()

    def test_start_time_not_before_end_time(self):
        """Test segment where start_time is not strictly before end_time."""
        invalid_time_logic_json = """
        [
            {"start_time": "00:00:05,000", "end_time": "00:00:03,000", "narration_text": "Start after end"}
        ]
        """
        parser = ScriptParser(invalid_time_logic_json, self.video_duration_sec)
        with self.assertRaisesRegex(ScriptParserError, "Start time .* must be before end time"):
            parser.parse_and_validate()

    def test_timestamp_adjustment_end_time_exceeds_video(self):
        """Test clamping of end_time if it exceeds video duration."""
        script = """
        [
            {"start_time": "00:00:58,000", "end_time": "00:01:05,000", "narration_text": "Exceeds duration"}
        ]
        """ # video_duration_sec is 60.0
        parser = ScriptParser(script, self.video_duration_sec)
        segments = parser.parse_and_validate()
        self.assertAlmostEqual(segments[0]['end_time_sec'], self.video_duration_sec) # Clamped to 60.0
        self.assertTrue(segments[0]['start_time_sec'] < segments[0]['end_time_sec'])

    def test_timestamp_adjustment_overlap(self):
        """Test adjustment of start_time if it overlaps significantly with previous segment."""
        script = """
        [
            {"start_time": "00:00:01,000", "end_time": "00:00:05,000", "narration_text": "Segment A"},
            {"start_time": "00:00:04,000", "end_time": "00:00:08,000", "narration_text": "Segment B overlaps A"}
        ]
        """ # Segment B starts at 4s, Segment A ends at 5s. Significant overlap (more than 0.5s)
        parser = ScriptParser(script, self.video_duration_sec)
        segments = parser.parse_and_validate()
        self.assertAlmostEqual(segments[0]['end_time_sec'], 5.0)
        self.assertAlmostEqual(segments[1]['start_time_sec'], 5.0) # Adjusted to end of A
        self.assertAlmostEqual(segments[1]['end_time_sec'], 8.0)

    def test_empty_narration_text_skipped(self):
        """Test that segments with empty or whitespace-only narration text are skipped."""
        script = """
        [
            {"start_time": "00:00:01,000", "end_time": "00:00:05,000", "narration_text": "  "},
            {"start_time": "00:00:06,000", "end_time": "00:00:08,000", "narration_text": "Valid text."}
        ]
        """
        parser = ScriptParser(script, self.video_duration_sec)
        segments = parser.parse_and_validate()
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]['text'], "Valid text.")

    def test_to_srt_conversion(self):
        """Test conversion of parsed segments to SRT format."""
        valid_json_script = """
        [
            {"start_time": "00:00:01,503", "end_time": "00:00:05,000", "narration_text": "First segment.\\nLine two."},
            {"start_time": "00:00:06,000", "end_time": "00:00:10,257", "narration_text": "Second segment."}
        ]
        """
        parser = ScriptParser(valid_json_script, self.video_duration_sec)
        parser.parse_and_validate()
        srt_output = parser.to_srt()
        
        expected_srt = (
            "1\n"
            "00:00:01,503 --> 00:00:05,000\n"
            "First segment.\nLine two.\n\n"
            "2\n"
            "00:00:06,000 --> 00:00:10,257\n"
            "Second segment.\n"
        )
        self.assertEqual(srt_output.strip(), expected_srt.strip())

    def test_to_srt_empty_script(self):
        """Test SRT conversion with no valid segments."""
        empty_script = "[]"
        parser = ScriptParser(empty_script, self.video_duration_sec)
        parser.parse_and_validate()
        srt_output = parser.to_srt()
        self.assertEqual(srt_output, "")

    def test_negative_start_time_clamped(self):
        """Test that negative start times are clamped to 0."""
        script = """
        [
            {"start_time": "-00:00:02,000", "end_time": "00:00:03,000", "narration_text": "Negative start"}
        ]
        """
        parser = ScriptParser(script, self.video_duration_sec)
        segments = parser.parse_and_validate()
        self.assertEqual(len(segments), 1)
        self.assertAlmostEqual(segments[0]['start_time_sec'], 0.0)
        self.assertAlmostEqual(segments[0]['end_time_sec'], 3.0)

    def test_start_equals_end_time_adjusted(self):
        """Test that if start_time == end_time, end_time is slightly adjusted."""
        script = """
        [
            {"start_time": "00:00:02,000", "end_time": "00:00:02,000", "narration_text": "Start equals end"}
        ]
        """
        parser = ScriptParser(script, self.video_duration_sec)
        segments = parser.parse_and_validate()
        self.assertEqual(len(segments), 1)
        self.assertAlmostEqual(segments[0]['start_time_sec'], 2.0)
        self.assertAlmostEqual(segments[0]['end_time_sec'], 2.1) # Adjusted by +0.1s

if __name__ == '__main__':
    unittest.main()
