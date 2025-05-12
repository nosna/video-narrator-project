# src/tts_module/base.py

from abc import ABC, abstractmethod
from typing import List, Optional, TypedDict, Any

from utils import TTSError # Assuming TTSError is in utils

class TTSResult(TypedDict):
    """
    Represents the result of a TTS operation for a single text segment.
    """
    audio_file_path: str # Path to the generated audio file (e.g., .wav or .mp3)
    duration_sec: float    # Actual duration of the generated audio in seconds
    text_segment: str      # The original text that was synthesized
    segment_id: Any        # Original ID of the segment, if provided

class TTSEngine(ABC):
    """
    Abstract base class for Text-to-Speech engines.
    """

    @abstractmethod
    def synthesize_ssml(self, ssml_text: str, output_filename: str, voice_options: Optional[dict] = None) -> TTSResult:
        """
        Synthesizes speech from SSML (Speech Synthesis Markup Language) text.
        SSML allows for more control over pronunciation, pauses, prosody, etc.

        Args:
            ssml_text (str): The SSML text to synthesize.
            output_filename (str): The desired filename for the output audio file (e.g., "segment_1.mp3").
                                   The engine should save the file to a path constructed with this.
            voice_options (Optional[dict]): Provider-specific voice options (e.g., voice name, speaking rate, pitch).

        Returns:
            TTSResult: A dictionary containing the path to the audio file, its duration,
                       the original text, and segment ID.

        Raises:
            TTSError: If synthesis fails.
        """
        pass

    @abstractmethod
    def synthesize_text(self, text: str, output_filename: str, voice_options: Optional[dict] = None) -> TTSResult:
        """
        Synthesizes speech from plain text.

        Args:
            text (str): The plain text to synthesize.
            output_filename (str): The desired filename for the output audio file.
            voice_options (Optional[dict]): Provider-specific voice options.

        Returns:
            TTSResult: A dictionary containing the path to the audio file, its duration,
                       the original text, and segment ID.

        Raises:
            TTSError: If synthesis fails.
        """
        pass

    def synthesize_segments(self, segments: List[dict], base_output_dir: str, voice_options: Optional[dict] = None) -> List[TTSResult]:
        """
        Synthesizes speech for a list of text segments.
        This is a convenience method that calls synthesize_text or synthesize_ssml for each segment.

        Args:
            segments (List[dict]): A list of segments, where each segment is a dictionary
                                   expected to have at least a 'text' key and an 'id' key.
                                   Example: [{"id": 1, "text": "Hello world"}, {"id": 2, "text": "How are you?"}]
            base_output_dir (str): The base directory where individual audio segment files will be saved.
            voice_options (Optional[dict]): Provider-specific voice options.

        Returns:
            List[TTSResult]: A list of TTSResult objects, one for each segment.

        Raises:
            TTSError: If synthesis fails for any segment.
        """
        results = []
        for i, segment_data in enumerate(segments):
            text_to_synthesize = segment_data.get("text", "")
            segment_id = segment_data.get("id", f"segment_{i+1}") # Fallback ID

            if not text_to_synthesize.strip():
                # Skip empty segments or handle as needed
                continue

            # Create a unique filename for each segment's audio output
            # The TTS implementation will prepend base_output_dir
            output_filename = f"narration_{segment_id}.mp3" # Default to mp3, implementation can change

            # Check if text is SSML (basic check, can be more sophisticated)
            is_ssml = text_to_synthesize.strip().startswith("<speak>") and \
                      text_to_synthesize.strip().endswith("</speak>")

            if is_ssml:
                result = self.synthesize_ssml(text_to_synthesize, output_filename, voice_options)
            else:
                result = self.synthesize_text(text_to_synthesize, output_filename, voice_options)
            
            # Ensure the result includes the segment_id
            if 'segment_id' not in result: # Should be set by the concrete implementation
                result['segment_id'] = segment_id
            if 'text_segment' not in result: # Should be set by the concrete implementation
                result['text_segment'] = text_to_synthesize

            results.append(result)
        return results

    def get_audio_file_duration(self, file_path: str) -> float:
        """
        Helper method to get the duration of an audio file.
        Requires a library like pydub or ffprobe, or can be implemented by the subclass
        if the TTS API provides duration info directly.

        Args:
            file_path (str): Path to the audio file.

        Returns:
            float: Duration of the audio file in seconds.

        Raises:
            TTSError: If duration cannot be determined.
        """
        # This is a generic implementation placeholder.
        # Concrete classes should provide a more robust way, often using pydub.
        # For now, we'll raise NotImplementedError to force subclasses to implement or override.
        raise NotImplementedError("Subclasses should implement get_audio_file_duration or ensure TTSResult provides it.")

