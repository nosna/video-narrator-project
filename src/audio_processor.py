# src/audio_processor.py

import os
from pydub import AudioSegment
from typing import List, Tuple, Optional

from utils import setup_logger, NarrationError, format_timestamp_srt, clean_filename
from config import settings
from tts_module.base import TTSResult # To type hint TTS results
from script_parser import NarrationSegment # To type hint parsed script segments

logger = setup_logger(__name__)

class AudioProcessorError(NarrationError):
    """Custom exception for audio processing errors."""
    pass

class AudioProcessor:
    """
    Assembles individual audio narration segments into a final audio track.
    """

    def __init__(self,
                 parsed_narration_segments: List[NarrationSegment],
                 tts_results: List[TTSResult],
                 video_filename_base: str = "narrated_video"):
        """
        Initializes the AudioProcessor.

        Args:
            parsed_narration_segments (List[NarrationSegment]): The script segments with
                                                                start_time_sec, end_time_sec, text, id.
            tts_results (List[TTSResult]): The results from the TTS engine, including
                                           audio_file_path, duration_sec, segment_id.
            video_filename_base (str): Base name for the output audio file.
        """
        self.parsed_narration_segments = sorted(parsed_narration_segments, key=lambda x: x['start_time_sec'])
        self.tts_results_map = {str(res['segment_id']): res for res in tts_results} # Map by segment_id for easy lookup
        self.video_filename_base = clean_filename(video_filename_base)
        self.final_audio: Optional[AudioSegment] = None

    def _calculate_gaps_and_durations(self) -> List[Tuple[str, float, Optional[str]]]:
        """
        Calculates the sequence of audio segments and silences.

        Returns:
            List[Tuple[str, float, Optional[str]]]: A list of tuples, where each tuple is:
                ('speech', duration_sec, audio_file_path) for speech segments, or
                ('silence', duration_sec, None) for silence segments.
        """
        timeline_items = []
        current_time_sec = 0.0

        if not self.parsed_narration_segments:
            logger.warning("No narration segments provided to AudioProcessor.")
            return []

        for segment in self.parsed_narration_segments:
            segment_id_str = str(segment['id'])
            tts_result = self.tts_results_map.get(segment_id_str)

            if not tts_result:
                logger.warning(f"No TTS result found for segment ID {segment_id_str}. Skipping this segment in audio assembly.")
                continue

            segment_start_time = segment['start_time_sec']
            # The *intended* duration from the script is end_time - start_time
            # The *actual* duration of the TTS audio is tts_result['duration_sec']
            # We need to decide how to handle discrepancies.
            # For now, we prioritize the script's start time and the actual TTS audio.

            # 1. Add silence before this segment if needed
            silence_duration_before = segment_start_time - current_time_sec
            if silence_duration_before > 0.01: # Add silence if gap is more than 10ms
                logger.debug(f"Adding silence: {silence_duration_before:.3f}s before segment {segment_id_str}")
                timeline_items.append(('silence', silence_duration_before, None))
            elif silence_duration_before < -0.1: # If segment starts earlier than current time (overlap)
                 logger.warning(f"Segment {segment_id_str} (starts {segment_start_time:.3f}s) overlaps with previous audio ending at {current_time_sec:.3f}s. Overlap will occur.")
                 # No negative silence, just proceed. The segment will effectively start from current_time_sec.

            current_time_sec = segment_start_time # Align current time to segment start

            # 2. Add the speech segment
            audio_file_path = tts_result['audio_file_path']
            actual_tts_duration = tts_result['duration_sec']

            if not os.path.exists(audio_file_path):
                logger.error(f"Audio file for segment {segment_id_str} not found: {audio_file_path}. Skipping.")
                continue

            # We use the actual duration of the TTS audio.
            # If actual_tts_duration is significantly different from (segment['end_time_sec'] - segment['start_time_sec']),
            # the overall timing might drift from the script's ideal end times.
            # This is a trade-off: prioritize natural TTS speech length vs. strict script timing.
            logger.debug(f"Adding speech: segment {segment_id_str}, duration {actual_tts_duration:.3f}s, file {audio_file_path}")
            timeline_items.append(('speech', actual_tts_duration, audio_file_path))
            current_time_sec += actual_tts_duration

        return timeline_items

    def assemble_audio(self, output_format: str = "mp3") -> str:
        """
        Assembles the final audio track from individual segments and silences.

        Args:
            output_format (str): The desired output format ("mp3" or "wav").

        Returns:
            str: The path to the final assembled audio file.

        Raises:
            AudioProcessorError: If assembly fails.
        """
        logger.info("Starting audio assembly process...")
        timeline_items = self._calculate_gaps_and_durations()

        if not timeline_items:
            logger.warning("Timeline is empty. No audio will be assembled.")
            # Create a very short silent audio file as a placeholder
            self.final_audio = AudioSegment.silent(duration=10) # 10ms silent audio
        else:
            # Initialize with the first item or silence if timeline starts with speech at t > 0
            # This is handled by _calculate_gaps_and_durations adding initial silence.
            self.final_audio = AudioSegment.empty()

            for item_type, duration_sec, file_path in timeline_items:
                if item_type == 'silence':
                    silence_ms = int(duration_sec * 1000)
                    if silence_ms > 0:
                        self.final_audio += AudioSegment.silent(duration=silence_ms)
                elif item_type == 'speech' and file_path:
                    try:
                        segment_audio = AudioSegment.from_file(file_path)
                        # If actual TTS duration was used in timeline, just append.
                        # If we wanted to stretch/compress to fit script's intended duration:
                        # intended_duration_ms = int(duration_sec * 1000)
                        # segment_audio = self._match_duration(segment_audio, intended_duration_ms)
                        self.final_audio += segment_audio
                    except Exception as e:
                        logger.error(f"Failed to load or process audio segment {file_path}: {e}")
                        # Add equivalent silence if a segment fails to load
                        silence_ms = int(duration_sec * 1000)
                        if silence_ms > 0:
                            self.final_audio += AudioSegment.silent(duration=silence_ms)
                        # Optionally, re-raise or collect errors

        # Export the final audio
        output_filename = f"{self.video_filename_base}_narrated_audio.{output_format.lower()}"
        output_filepath = os.path.join(settings.OUTPUT_DIR, output_filename)
        os.makedirs(os.path.dirname(output_filepath), exist_ok=True)

        logger.info(f"Exporting final assembled audio to: {output_filepath} (Format: {output_format})")
        try:
            if self.final_audio:
                if output_format.lower() == "mp3":
                    self.final_audio.export(output_filepath, format="mp3", bitrate="192k")
                elif output_format.lower() == "wav":
                    self.final_audio.export(output_filepath, format="wav")
                else:
                    raise AudioProcessorError(f"Unsupported output audio format: {output_format}")
            else: # Should not happen if we create placeholder silent audio
                raise AudioProcessorError("Final audio is None, cannot export.")
        except Exception as e:
            logger.error(f"Failed to export final audio: {e}")
            raise AudioProcessorError(f"Failed to export final audio to {output_filepath}: {e}") from e

        logger.info(f"Final audio assembled successfully. Duration: {len(self.final_audio)/1000.0:.3f}s")
        return output_filepath

    def _match_duration(self, audio_segment: AudioSegment, target_duration_ms: int) -> AudioSegment:
        """
        (Optional) Stretches or compresses an audio segment to match a target duration.
        This can affect audio quality. Use with caution.
        For simplicity, this basic version might not be perfectly implemented for quality.
        A more advanced approach would use phase vocoding or similar techniques.
        Pydub's speedup/slowdown is basic.

        Args:
            audio_segment (AudioSegment): The input audio segment.
            target_duration_ms (int): The desired duration in milliseconds.

        Returns:
            AudioSegment: The modified audio segment.
        """
        current_duration_ms = len(audio_segment)
        if current_duration_ms == 0 or target_duration_ms <=0:
            return audio_segment # Avoid division by zero or invalid target

        speed_change = current_duration_ms / target_duration_ms

        if abs(speed_change - 1.0) < 0.01: # If change is less than 1%, don't bother
            return audio_segment

        logger.debug(f"Adjusting audio speed by factor: {speed_change:.2f} (current: {current_duration_ms}ms, target: {target_duration_ms}ms)")

        # pydub's speedup changes pitch. For better quality, external tools or more complex libraries are needed.
        # This is a very basic way to change speed.
        # return audio_segment.speedup(playback_speed=speed_change) # This might not be ideal.

        # A slightly better approach with pydub might involve manipulating frames,
        # but true time-stretching without pitch change is complex.
        # For now, we'll return the original segment to avoid poor quality speed changes.
        # If strict timing is paramount over TTS naturalness, this needs a more robust solution.
        logger.warning("Duration matching (time-stretching/compressing) is not fully implemented for high quality. Using original TTS duration.")
        return audio_segment


# Example Usage (for testing this module directly)
if __name__ == "__main__":
    # This test requires dummy TTS results and parsed segments.
    # And pydub installed.

    # Create dummy TTS audio files for testing
    dummy_tts_output_dir = os.path.join(settings.OUTPUT_DIR, "tts_audio_test_ap")
    os.makedirs(dummy_tts_output_dir, exist_ok=True)

    def create_dummy_audio(filename: str, duration_ms: int, text: str) -> TTSResult:
        filepath = os.path.join(dummy_tts_output_dir, filename)
        # Create a silent audio file with a bit of sound to make it non-empty
        try:
            silence = AudioSegment.silent(duration=duration_ms - 10 if duration_ms > 10 else duration_ms)
            # Add a tiny tone to make it not purely silent, easier to hear if something is wrong
            # tone = AudioSegment.sine(220).to_audio_segment(duration=10) if duration_ms > 10 else AudioSegment.empty()
            # dummy_audio = silence + tone
            dummy_audio = silence
            dummy_audio.export(filepath, format="mp3")
            return TTSResult(audio_file_path=filepath, duration_sec=duration_ms/1000.0, text_segment=text, segment_id=filename.split('.')[0])
        except Exception as e:
            logger.error(f"Error creating dummy audio {filename}: {e}")
            # Fallback if pydub or ffmpeg not fully set up for export
            open(filepath, 'w').write("dummy audio") # create empty file
            return TTSResult(audio_file_path=filepath, duration_sec=duration_ms/1000.0, text_segment=text, segment_id=filename.split('.')[0])


    print("--- Setting up dummy data for AudioProcessor test ---")
    mock_tts_results = [
        create_dummy_audio("narration_seg1.mp3", 3000, "Segment one text."), # 3s
        create_dummy_audio("narration_seg2.mp3", 4500, "Segment two is a bit longer."), # 4.5s
        create_dummy_audio("narration_seg3.mp3", 2000, "A short third one.") # 2s
    ]

    mock_parsed_segments: List[NarrationSegment] = [
        {"id": "narration_seg1", "start_time_sec": 1.0, "end_time_sec": 4.0, "text": "Segment one text."},
        {"id": "narration_seg2", "start_time_sec": 5.0, "end_time_sec": 9.5, "text": "Segment two is a bit longer."},
        {"id": "narration_seg3", "start_time_sec": 10.0, "end_time_sec": 12.0, "text": "A short third one."}
    ]
    
    # Test with a segment ID that might be missing in TTS results
    mock_parsed_segments_with_missing = mock_parsed_segments + [
        {"id": "narration_seg4_missing", "start_time_sec": 13.0, "end_time_sec": 15.0, "text": "This segment's audio is missing."}
    ]


    print("\n--- Testing AudioProcessor Assembly ---")
    try:
        processor = AudioProcessor(
            parsed_narration_segments=mock_parsed_segments,
            tts_results=mock_tts_results,
            video_filename_base="test_video_audio_assembly"
        )
        final_audio_path_mp3 = processor.assemble_audio(output_format="mp3")
        print(f"Assembled MP3 audio path: {final_audio_path_mp3}")
        if os.path.exists(final_audio_path_mp3):
            final_audio_segment = AudioSegment.from_mp3(final_audio_path_mp3)
            print(f"  Duration of final MP3: {len(final_audio_segment)/1000.0:.3f}s")
            # Expected total duration:
            # Silence: 1s (before seg1)
            # Seg1: 3s
            # Silence: (5.0 - (1.0+3.0)) = 1s (between seg1 and seg2)
            # Seg2: 4.5s
            # Silence: (10.0 - (5.0+4.5)) = 0.5s (between seg2 and seg3)
            # Seg3: 2s
            # Total = 1 + 3 + 1 + 4.5 + 0.5 + 2 = 12.0s
            print(f"  Expected approximate duration around 12.0s (actual TTS durations used)")


        # Test with a missing segment
        print("\n--- Testing AudioProcessor Assembly with a missing TTS segment ---")
        processor_missing = AudioProcessor(
            parsed_narration_segments=mock_parsed_segments_with_missing,
            tts_results=mock_tts_results, # tts_results does not contain seg4
            video_filename_base="test_video_missing_segment"
        )
        final_audio_path_missing_mp3 = processor_missing.assemble_audio(output_format="mp3")
        print(f"Assembled MP3 audio path (with missing segment): {final_audio_path_missing_mp3}")
        if os.path.exists(final_audio_path_missing_mp3):
            final_audio_segment_missing = AudioSegment.from_mp3(final_audio_path_missing_mp3)
            print(f"  Duration of final MP3 (with missing): {len(final_audio_segment_missing)/1000.0:.3f}s (should be same as above as missing segment is skipped)")


    except AudioProcessorError as e:
        print(f"AudioProcessor Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up dummy audio files
        # for res in mock_tts_results:
        #     if os.path.exists(res['audio_file_path']):
        #         try:
        #             os.remove(res['audio_file_path'])
        #         except Exception: pass
        # if os.path.exists(dummy_tts_output_dir):
        #     try:
        #         # os.rmdir(dummy_tts_output_dir) # Fails if dir not empty
        #         pass
        #     except Exception: pass
        logger.info(f"Dummy TTS files for AudioProcessor test are in {dummy_tts_output_dir}. Manual cleanup might be needed.")
