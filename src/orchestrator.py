# src/orchestrator.py

import os
import time
from typing import Optional, Type

from config import settings
from utils import setup_logger, clean_filename, NarrationError, VideoProcessingError
from video_processor import VideoProcessor
from gemini_handler import GeminiHandler
from script_parser import ScriptParser, NarrationSegment
from tts_module.base import TTSEngine, TTSResult
from tts_module.impl_google_tts import GoogleCloudTTS # Default TTS
# from .tts_module.impl_piper_tts import PiperTTS # Example for another TTS
from audio_processor import AudioProcessor

# Optional: For muxing video and audio
try:
    import ffmpeg
except ImportError:
    ffmpeg = None # type: ignore

logger = setup_logger(__name__)

class Orchestrator:
    """
    Orchestrates the entire video narration pipeline.
    """

    def __init__(self,
                 input_path_or_url: str,
                 output_dir: str = settings.OUTPUT_DIR,
                 tts_engine_class: Type[TTSEngine] = GoogleCloudTTS): # Allow swapping TTS engine
        """
        Initializes the Orchestrator.

        Args:
            input_path_or_url (str): Path to a local video file or a URL to a video.
            output_dir (str): Directory to save output files.
            tts_engine_class (Type[TTSEngine]): The class of the TTS engine to use.
        """
        self.input_path_or_url = input_path_or_url
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        # Ensure the tts_audio subdirectory also exists as TTS implementations might use it
        os.makedirs(os.path.join(self.output_dir, "tts_audio"), exist_ok=True)

        self.video_processor: Optional[VideoProcessor] = None
        self.gemini_handler: Optional[GeminiHandler] = None
        self.script_parser: Optional[ScriptParser] = None
        self.tts_engine: Optional[TTSEngine] = None
        try:
            self.tts_engine_class = tts_engine_class
            self.tts_engine = self.tts_engine_class()
        except Exception as e:
            logger.error(f"Failed to initialize TTS engine {tts_engine_class.__name__}: {e}")
            self.tts_engine = None # Ensure it's None if initialization fails
            # Depending on requirements, could re-raise or proceed without TTS for script-only generation

        self.audio_processor: Optional[AudioProcessor] = None

        self.processed_video_path: Optional[str] = None
        self.video_metadata: Optional[dict] = None
        self.raw_narration_script: Optional[str] = None
        self.parsed_segments: Optional[List[NarrationSegment]] = None
        self.tts_results: Optional[List[TTSResult]] = None
        self.final_srt_path: Optional[str] = None
        self.final_audio_path: Optional[str] = None
        self.final_muxed_video_path: Optional[str] = None
        self.video_filename_base: str = "video"


    def run_pipeline(self, generate_audio: bool = True, mux_video: bool = False) -> dict:
        """
        Runs the full narration pipeline.

        Args:
            generate_audio (bool): Whether to generate the audio track.
                                   If False, only the script (SRT) will be produced.
            mux_video (bool): Whether to mux the generated audio with the original video.
                              Requires generate_audio to be True and ffmpeg to be installed.

        Returns:
            dict: A dictionary containing paths to the generated artifacts.
                  Keys: "srt_file", "audio_file", "muxed_video_file".
                  Values will be None if the artifact was not generated.
        """
        start_time = time.time()
        logger.info(f"Starting narration pipeline for: {self.input_path_or_url}")

        results = {
            "srt_file": None,
            "audio_file": None,
            "muxed_video_file": None,
            "logs": [] # To store key log messages or errors
        }

        try:
            # 1. Process Video Input
            logger.info("Step 1: Processing video input...")
            self.video_processor = VideoProcessor(self.input_path_or_url)
            self.processed_video_path, self.video_metadata = self.video_processor.process()
            self.video_filename_base = clean_filename(os.path.splitext(self.video_metadata['filename'])[0])
            logger.info(f"Video processed. Local path: {self.processed_video_path}, Duration: {self.video_metadata['duration']:.2f}s")
            results["logs"].append(f"Video processed: {self.processed_video_path}")

            # 2. Generate Narration Script with Gemini
            logger.info("Step 2: Generating narration script with Gemini...")
            if not self.processed_video_path or not self.video_metadata:
                 raise NarrationError("Video processing failed, cannot proceed to Gemini.")
            self.gemini_handler = GeminiHandler(self.processed_video_path, self.video_metadata)
            self.raw_narration_script = self.gemini_handler.generate_narration()
            logger.info("Raw narration script received from Gemini.")
            results["logs"].append("Raw script received from Gemini.")
            # Save raw script for debugging
            raw_script_path = os.path.join(self.output_dir, f"{self.video_filename_base}_gemini_raw_output.json")
            with open(raw_script_path, "w", encoding="utf-8") as f:
                f.write(self.raw_narration_script)
            logger.info(f"Saved raw Gemini output to: {raw_script_path}")


            # 3. Parse and Validate Script
            logger.info("Step 3: Parsing and validating narration script...")
            if not self.raw_narration_script:
                raise NarrationError("No raw script from Gemini to parse.")
            self.script_parser = ScriptParser(self.raw_narration_script, self.video_metadata['duration'])
            self.parsed_segments = self.script_parser.parse_and_validate()
            logger.info(f"Script parsed into {len(self.parsed_segments)} segments.")
            results["logs"].append(f"Script parsed into {len(self.parsed_segments)} segments.")

            # Generate and save SRT file
            srt_content = self.script_parser.to_srt()
            self.final_srt_path = os.path.join(self.output_dir, f"{self.video_filename_base}_narration.srt")
            with open(self.final_srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
            logger.info(f"SRT file saved to: {self.final_srt_path}")
            results["srt_file"] = self.final_srt_path

            if not generate_audio:
                logger.info("Audio generation skipped as per request.")
                results["logs"].append("Audio generation skipped.")
                return results

            # 4. Text-to-Speech
            logger.info("Step 4: Performing Text-to-Speech...")
            if not self.tts_engine:
                raise NarrationError("TTS engine not initialized. Cannot generate audio.")
            if not self.parsed_segments:
                logger.warning("No parsed segments available for TTS. Audio generation will be skipped.")
                results["logs"].append("No parsed segments for TTS, audio skipped.")
                return results

            # Prepare segments for TTS engine (list of dicts with 'id' and 'text')
            tts_input_segments = [{"id": seg["id"], "text": seg["text"]} for seg in self.parsed_segments]
            self.tts_results = self.tts_engine.synthesize_segments(
                tts_input_segments,
                base_output_dir=os.path.join(self.output_dir, "tts_audio") # TTS impl should use this
            )
            logger.info(f"TTS completed for {len(self.tts_results)} segments.")
            results["logs"].append(f"TTS completed for {len(self.tts_results)} segments.")


            # 5. Assemble Audio
            logger.info("Step 5: Assembling final audio track...")
            if not self.tts_results:
                logger.warning("No TTS results available for audio assembly. Audio generation will be skipped.")
                results["logs"].append("No TTS results for assembly, audio skipped.")
                return results

            self.audio_processor = AudioProcessor(
                self.parsed_segments,
                self.tts_results,
                video_filename_base=self.video_filename_base
            )
            self.final_audio_path = self.audio_processor.assemble_audio(output_format="mp3")
            logger.info(f"Final audio track saved to: {self.final_audio_path}")
            results["audio_file"] = self.final_audio_path
            results["logs"].append(f"Final audio saved: {self.final_audio_path}")


            # 6. Optional: Mux Video
            if mux_video:
                if not ffmpeg:
                    logger.warning("ffmpeg-python library not available. Skipping video muxing.")
                    results["logs"].append("ffmpeg not found, muxing skipped.")
                elif not self.processed_video_path or not self.final_audio_path:
                    logger.warning("Original video or final audio path not available. Skipping video muxing.")
                    results["logs"].append("Video/audio path missing, muxing skipped.")
                else:
                    logger.info("Step 6: Muxing audio into video...")
                    self.final_muxed_video_path = self._mux_video_audio(
                        self.processed_video_path,
                        self.final_audio_path,
                        f"{self.video_filename_base}_narrated_final.mp4"
                    )
                    logger.info(f"Muxed video saved to: {self.final_muxed_video_path}")
                    results["muxed_video_file"] = self.final_muxed_video_path
                    results["logs"].append(f"Muxed video saved: {self.final_muxed_video_path}")

        except NarrationError as e: # Catch our custom errors
            logger.error(f"Narration pipeline error: {e}")
            results["logs"].append(f"ERROR: {e}")
            # Potentially re-raise or handle gracefully
        except VideoProcessingError as e: # Catch video processing specific errors
            logger.error(f"Video processing pipeline error: {e}")
            results["logs"].append(f"VIDEO ERROR: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred in the pipeline: {e}", exc_info=True)
            results["logs"].append(f"UNEXPECTED ERROR: {e}")
            # Potentially re-raise
        finally:
            # Cleanup temporary files from VideoProcessor if it was a URL
            if self.video_processor and self.video_processor.is_url:
                self.video_processor._cleanup_temp_file() # Call its cleanup method
            
            # TTS implementations might also create temp files, though our GoogleCloudTTS writes directly.
            # If TTS engine has a cleanup method, call it here.
            # if hasattr(self.tts_engine, 'cleanup'):
            #     self.tts_engine.cleanup()

            end_time = time.time()
            logger.info(f"Narration pipeline finished in {end_time - start_time:.2f} seconds.")
            results["logs"].append(f"Pipeline finished in {end_time - start_time:.2f}s.")
        
        return results

    def _mux_video_audio(self, video_path: str, audio_path: str, output_filename: str) -> str:
        """
        Muxes the video and audio tracks together using ffmpeg-python.
        """
        output_filepath = os.path.join(self.output_dir, output_filename)
        
        try:
            input_video = ffmpeg.input(video_path)
            input_audio = ffmpeg.input(audio_path)

            # -c:v copy: copies video stream without re-encoding
            # -c:a aac: re-encodes audio to AAC (common for MP4)
            # -shortest: finishes encoding when the shortest input stream ends (typically audio)
            (
                ffmpeg
                .output(input_video['v'], input_audio['a'], output_filepath, vcodec='copy', acodec='aac', shortest=None)
                .overwrite_output()
                .run(quiet=True) # quiet=True suppresses ffmpeg console output
            )
            return output_filepath
        except ffmpeg.Error as e:
            logger.error(f"ffmpeg error during muxing: {e.stderr.decode('utf8') if e.stderr else str(e)}")
            raise NarrationError(f"Failed to mux video and audio: {e}") from e
        except Exception as e:
            logger.error(f"Unexpected error during muxing: {e}")
            raise NarrationError(f"Unexpected error during muxing: {e}") from e


# Example Usage (for testing this module directly)
if __name__ == "__main__":
    # This is a more complex test as it runs the whole pipeline.
    # Prerequisites:
    # 1. .env file with GOOGLE_API_KEY (and GOOGLE_APPLICATION_CREDENTIALS if using Google TTS).
    # 2. A sample video file or URL.
    # 3. All libraries installed (google-generativeai, google-cloud-texttospeech, pydub, ffmpeg-python).
    # 4. ffmpeg installed on the system.

    # Use a small, publicly available video for testing
    # test_video_input = "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4"
    # Or a local file:
    test_video_input = "sample_video.mp4" # Make sure this exists or provide full path

    if not os.path.exists(test_video_input) and not test_video_input.startswith("http"):
         print(f"Test video '{test_video_input}' not found. Please provide a valid local path or URL.")
         exit()

    if (not settings.GOOGLE_API_KEY or settings.GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY_HERE" or
        not os.getenv("GOOGLE_APPLICATION_CREDENTIALS")): # Assuming GoogleCloudTTS is default
        print("API keys (GOOGLE_API_KEY and/or GOOGLE_APPLICATION_CREDENTIALS for TTS) not fully configured in .env. Orchestrator test might fail or be limited.")
        # Allow to proceed for script-only generation if generate_audio=False

    print(f"--- Testing Orchestrator with input: {test_video_input} ---")
    orchestrator = Orchestrator(input_path_or_url=test_video_input)

    try:
        # Test script generation only first
        print("\n--- Test 1: Script generation only ---")
        results_script_only = orchestrator.run_pipeline(generate_audio=False, mux_video=False)
        print("Script-only results:", results_script_only)
        if results_script_only.get("srt_file"):
            print(f"SRT file created at: {results_script_only['srt_file']}")
        else:
            print("SRT file generation failed or was skipped.")

        # Test full pipeline (if keys are likely set)
        if settings.GOOGLE_API_KEY and settings.GOOGLE_API_KEY != "YOUR_GOOGLE_API_KEY_HERE" and os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            print("\n--- Test 2: Full pipeline (Script, Audio, No Mux) ---")
            # Re-instantiate orchestrator or reset its state if you want a clean run for the second test
            orchestrator_full = Orchestrator(input_path_or_url=test_video_input)
            results_full_no_mux = orchestrator_full.run_pipeline(generate_audio=True, mux_video=False)
            print("Full pipeline (no mux) results:", results_full_no_mux)
            if results_full_no_mux.get("audio_file"):
                print(f"Audio file created at: {results_full_no_mux['audio_file']}")

            if ffmpeg:
                print("\n--- Test 3: Full pipeline with Muxing ---")
                orchestrator_mux = Orchestrator(input_path_or_url=test_video_input)
                results_mux = orchestrator_mux.run_pipeline(generate_audio=True, mux_video=True)
                print("Full pipeline (with mux) results:", results_mux)
                if results_mux.get("muxed_video_file"):
                    print(f"Muxed video file created at: {results_mux['muxed_video_file']}")
            else:
                print("\nSkipping Muxing test as ffmpeg-python is not available or import failed.")

        else:
            print("\nSkipping full audio/mux pipeline tests due to incomplete API key configuration for TTS.")

    except Exception as e:
        print(f"An error occurred during orchestrator test: {e}")
        import traceback
        traceback.print_exc()

