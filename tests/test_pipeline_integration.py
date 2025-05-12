# tests/test_pipeline_integration.py

import unittest
import os
import sys
import shutil # For cleaning up output directory and checking for ffmpeg
import time

# Adjust path to import from src
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
src_path = os.path.join(project_root, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Conditional imports based on whether src path was successfully added
try:
    from src.orchestrator import Orchestrator # type: ignore
    from src.config import settings # type: ignore
    from src.utils import TTSError, NarrationError, VideoProcessingError # type: ignore
    from pydub import AudioSegment # type: ignore
except ImportError as e:
    print(f"Failed to import src modules for integration test: {e}")
    print("Ensure the test is run from the project root or sys.path is correctly configured.")
    # Define dummy classes if imports fail, so the test file can still be parsed
    class Orchestrator: pass # type: ignore
    class settings: # type: ignore
        OUTPUT_DIR = "output_test_dummy"
        GOOGLE_API_KEY = None # type: ignore
    class TTSError(Exception): pass # type: ignore
    class NarrationError(Exception): pass # type: ignore
    class VideoProcessingError(Exception): pass # type: ignore
    class AudioSegment: # type: ignore
        @staticmethod
        def from_file(f): return AudioSegment()
        def __len__(self): return 1000


# Define the path for the sample video clip
# The user needs to place a short video here.
SAMPLE_VIDEO_FILENAME = "sample_test_clip.mp4"
SAMPLE_VIDEO_PATH = os.path.join(project_root, "sample_data", SAMPLE_VIDEO_FILENAME)

# Define a specific output directory for this test run
# Ensure settings.OUTPUT_DIR is available, even if it's the dummy one from failed import
TEST_OUTPUT_DIR = os.path.join(settings.OUTPUT_DIR, "integration_test_run")


@unittest.skipIf(not os.path.exists(SAMPLE_VIDEO_PATH),
                 f"Skipping integration tests: Sample video '{SAMPLE_VIDEO_PATH}' not found.")
@unittest.skipIf(not (settings.GOOGLE_API_KEY and settings.GOOGLE_API_KEY != "YOUR_GOOGLE_API_KEY_HERE" and
                      os.getenv("GOOGLE_APPLICATION_CREDENTIALS")), # Assuming GoogleCloudTTS
                 "Skipping integration tests: GOOGLE_API_KEY or GOOGLE_APPLICATION_CREDENTIALS (for TTS) not configured.")
class TestPipelineIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Set up for all tests in this class."""
        # Ensure the test output directory is clean before starting
        if os.path.exists(TEST_OUTPUT_DIR):
            shutil.rmtree(TEST_OUTPUT_DIR)
        os.makedirs(TEST_OUTPUT_DIR, exist_ok=True)
        print(f"Integration test output will be in: {TEST_OUTPUT_DIR}")

    @classmethod
    def tearDownClass(cls):
        """Clean up after all tests in this class."""
        # Optionally, remove the test output directory after tests
        # For debugging, it might be useful to keep it.
        if os.path.exists(TEST_OUTPUT_DIR) and os.getenv("CI_KEEP_ARTIFACTS") is None: # Keep if CI_KEEP_ARTIFACTS is set
            shutil.rmtree(TEST_OUTPUT_DIR)
            print(f"Cleaned up test output directory: {TEST_OUTPUT_DIR}")
        else:
            print(f"Test output directory {TEST_OUTPUT_DIR} was kept.")


    def _get_expected_video_filename_base(self):
        # Derives the base filename from the sample video, similar to Orchestrator
        return os.path.splitext(SAMPLE_VIDEO_FILENAME)[0]

    def test_01_full_pipeline_with_audio_no_mux(self): # Renamed to run first
        """
        Tests the full pipeline: video processing, Gemini script, SRT, TTS, and audio assembly.
        Does not test muxing.
        This test relies on actual API calls to Gemini and Google Cloud TTS.
        """
        print(f"\nRunning test_01_full_pipeline_with_audio_no_mux with video: {SAMPLE_VIDEO_PATH}")
        orchestrator = Orchestrator(
            input_path_or_url=SAMPLE_VIDEO_PATH,
            output_dir=TEST_OUTPUT_DIR
            # TTS engine defaults to GoogleCloudTTS in Orchestrator
        )

        results = {}
        try:
            results = orchestrator.run_pipeline(generate_audio=True, mux_video=False)
        except (TTSError, NarrationError, VideoProcessingError, Exception) as e:
            # Log the error and fail the test, but also print current results if any
            print(f"Pipeline execution failed with error: {e}")
            if results.get("logs"):
                print("Pipeline Logs on Failure:")
                for log_entry in results["logs"]:
                    print(f"  {log_entry}")
            self.fail(f"Orchestrator pipeline failed: {e}")


        print("Pipeline results from orchestrator (no_mux test):", results)

        # 1. Check SRT file
        self.assertIsNotNone(results.get("srt_file"), "SRT file path should be in results.")
        srt_file_path = results["srt_file"]
        self.assertTrue(os.path.exists(srt_file_path), f"SRT file not found at {srt_file_path}")
        
        expected_srt_filename = f"{self._get_expected_video_filename_base()}_narration.srt"
        self.assertEqual(os.path.basename(srt_file_path), expected_srt_filename, "SRT filename mismatch.")

        with open(srt_file_path, 'r', encoding='utf-8') as f:
            srt_content = f.read()
        self.assertTrue(len(srt_content) > 0, "SRT file should not be empty.")
        self.assertIn("-->", srt_content, "SRT file content seems invalid (missing '-->').")

        # 2. Check Audio file
        self.assertIsNotNone(results.get("audio_file"), "Audio file path should be in results.")
        audio_file_path = results["audio_file"]
        self.assertTrue(os.path.exists(audio_file_path), f"Audio file not found at {audio_file_path}")

        expected_audio_filename = f"{self._get_expected_video_filename_base()}_narrated_audio.mp3" # Assuming mp3 default
        self.assertEqual(os.path.basename(audio_file_path), expected_audio_filename, "Audio filename mismatch.")

        try:
            audio = AudioSegment.from_file(audio_file_path)
            self.assertTrue(len(audio) > 100, "Generated audio duration seems too short (less than 0.1s).") # Duration in ms
        except Exception as e:
            self.fail(f"Could not process generated audio file {audio_file_path}: {e}")

        # 3. Check that muxed file was NOT created
        self.assertIsNone(results.get("muxed_video_file"), "Muxed video file should not be created in this test.")

        # 4. Check logs for errors (basic check)
        if results.get("logs"):
            for log_entry in results["logs"]:
                self.assertNotIn("ERROR:", log_entry.upper(), f"Error found in pipeline logs: {log_entry}")
                self.assertNotIn("FAILED", log_entry.upper(), f"Failure indicated in pipeline logs: {log_entry}")

    @unittest.skipIf(shutil.which("ffmpeg") is None and shutil.which("ffmpeg.exe") is None,
                     "ffmpeg command not found in PATH, skipping muxing test.")
    def test_02_full_pipeline_with_muxing(self): # Renamed to run after no_mux
        """
        Tests the full pipeline, including muxing the audio into the video.
        Relies on ffmpeg being installed and in PATH.
        """
        print(f"\nRunning test_02_full_pipeline_with_muxing with video: {SAMPLE_VIDEO_PATH}")
        orchestrator = Orchestrator(
            input_path_or_url=SAMPLE_VIDEO_PATH,
            output_dir=TEST_OUTPUT_DIR
        )

        results = {}
        try:
            results = orchestrator.run_pipeline(generate_audio=True, mux_video=True)
        except (TTSError, NarrationError, VideoProcessingError, Exception) as e:
            print(f"Pipeline execution (with muxing) failed with error: {e}")
            if results.get("logs"):
                print("Pipeline Logs on Failure (muxing test):")
                for log_entry in results["logs"]:
                    print(f"  {log_entry}")
            self.fail(f"Orchestrator pipeline (with muxing) failed: {e}")

        print("Pipeline results from orchestrator (muxing test):", results)

        # Assertions for SRT and Audio (similar to the no_mux test, ensuring they are still produced)
        self.assertIsNotNone(results.get("srt_file"), "SRT file path should be in results (muxing test).")
        self.assertTrue(os.path.exists(results["srt_file"]), "SRT file not found (muxing test).")
        self.assertIsNotNone(results.get("audio_file"), "Audio file path should be in results (muxing test).")
        self.assertTrue(os.path.exists(results["audio_file"]), "Audio file not found (muxing test).")

        # Check Muxed Video file
        self.assertIsNotNone(results.get("muxed_video_file"), "Muxed video file path should be in results.")
        muxed_video_path = results["muxed_video_file"]
        self.assertTrue(os.path.exists(muxed_video_path), f"Muxed video file not found at {muxed_video_path}")

        expected_muxed_filename = f"{self._get_expected_video_filename_base()}_narrated_final.mp4" # Assuming mp4 default
        self.assertEqual(os.path.basename(muxed_video_path), expected_muxed_filename, "Muxed video filename mismatch.")

        # Basic check: muxed file should be larger than a tiny threshold
        self.assertTrue(os.path.getsize(muxed_video_path) > 1024, "Muxed video file size seems too small (<1KB).")

        # 4. Check logs for errors (basic check)
        if results.get("logs"):
            for log_entry in results["logs"]:
                self.assertNotIn("ERROR:", log_entry.upper(), f"Error found in pipeline logs (muxing test): {log_entry}")
                self.assertNotIn("FAILED", log_entry.upper(), f"Failure indicated in pipeline logs (muxing test): {log_entry}")


if __name__ == '__main__':
    # This allows running the tests directly using `python tests/test_pipeline_integration.py`
    # For more comprehensive test runs, use `python -m unittest discover` or `pytest`.
    suite = unittest.TestSuite()
    # Ensure tests run in a specific order if needed (e.g., no_mux before mux)
    # Test names are now prefixed with test_01_ and test_02_ for ordering.
    suite.addTest(unittest.makeSuite(TestPipelineIntegration))
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
