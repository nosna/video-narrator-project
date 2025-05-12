# src/tts_module/impl_google_tts.py

import os
from typing import Optional, Dict, Any
from google.cloud import texttospeech
from pydub import AudioSegment # For getting duration

from .base import TTSEngine, TTSResult
from config import settings # To access OUTPUT_DIR and other TTS specific settings
from utils import setup_logger, TTSError

logger = setup_logger(__name__)

class GoogleCloudTTS(TTSEngine):
    """
    Text-to-Speech engine using Google Cloud Text-to-Speech API.
    """

    def __init__(self):
        try:
            self.client = texttospeech.TextToSpeechClient()
            logger.info("Google Cloud TextToSpeech client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Google Cloud TextToSpeech client: {e}")
            logger.error("Please ensure you have authenticated with Google Cloud and the API is enabled.")
            logger.error("Typically, this involves setting the GOOGLE_APPLICATION_CREDENTIALS environment variable.")
            raise TTSError(f"Google Cloud TTS client initialization failed: {e}") from e

        # Default voice options, can be overridden
        self.default_voice_name = settings.TTS_VOICE_NAME if hasattr(settings, 'TTS_VOICE_NAME') else "en-US-Standard-C"
        self.default_speaking_rate = settings.TTS_SPEAKING_RATE if hasattr(settings, 'TTS_SPEAKING_RATE') else 1.0
        self.default_language_code = self.default_voice_name.split('-', 2)[0] + '-' + self.default_voice_name.split('-', 2)[1] # e.g., "en-US"

    def _synthesize(self, synthesis_input: texttospeech.SynthesisInput,
                    output_filepath: str,
                    voice_options: Optional[Dict[str, Any]] = None) -> TTSResult:
        """
        Internal synthesis method.

        Args:
            synthesis_input (texttospeech.SynthesisInput): The input text/ssml.
            output_filepath (str): Full path to save the audio file.
            voice_options (Optional[Dict[str, Any]]): Voice configuration.

        Returns:
            TTSResult: Information about the synthesized audio.
        """
        effective_voice_options = voice_options or {}
        voice_name = effective_voice_options.get("voice_name", self.default_voice_name)
        language_code = effective_voice_options.get("language_code", voice_name.split('-',2)[0] + '-' + voice_name.split('-',2)[1])
        speaking_rate = effective_voice_options.get("speaking_rate", self.default_speaking_rate)
        pitch = effective_voice_options.get("pitch", 0.0) # Default pitch

        voice = texttospeech.VoiceSelectionParams(
            language_code=language_code,
            name=voice_name
            # ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL # Or specific
        )

        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3, # MP3 is widely compatible
            speaking_rate=speaking_rate,
            pitch=pitch
        )

        logger.debug(f"Requesting TTS for: {synthesis_input} with voice {voice_name}, rate {speaking_rate}")

        try:
            response = self.client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
        except Exception as e:
            logger.error(f"Google Cloud TTS API error: {e}")
            raise TTSError(f"Google Cloud TTS API request failed: {e}") from e

        try:
            with open(output_filepath, "wb") as out:
                out.write(response.audio_content)
            logger.info(f"Audio content written to file: {output_filepath}")
        except IOError as e:
            logger.error(f"Failed to write TTS audio to file {output_filepath}: {e}")
            raise TTSError(f"Failed to write TTS audio to file: {e}") from e

        # Get duration using pydub
        try:
            audio_segment = AudioSegment.from_mp3(output_filepath)
            duration_sec = len(audio_segment) / 1000.0
        except Exception as e:
            logger.warning(f"Could not determine duration of {output_filepath} using pydub: {e}. Setting duration to 0.")
            duration_sec = 0.0 # Or raise an error / use a fallback

        original_text = synthesis_input.text if synthesis_input.text else synthesis_input.ssml

        return TTSResult(
            audio_file_path=output_filepath,
            duration_sec=duration_sec,
            text_segment=original_text, # This will be the SSML or text
            segment_id="" # This will be filled by the calling synthesize_segments or individual methods
        )

    def synthesize_ssml(self, ssml_text: str, output_filename: str, voice_options: Optional[dict] = None) -> TTSResult:
        synthesis_input = texttospeech.SynthesisInput(ssml=ssml_text)
        # Ensure output_filename is combined with the base output directory
        full_output_path = os.path.join(settings.OUTPUT_DIR, "tts_audio", output_filename)
        os.makedirs(os.path.dirname(full_output_path), exist_ok=True)
        
        result = self._synthesize(synthesis_input, full_output_path, voice_options)
        result['text_segment'] = ssml_text # ensure original ssml is stored
        return result

    def synthesize_text(self, text: str, output_filename: str, voice_options: Optional[dict] = None) -> TTSResult:
        synthesis_input = texttospeech.SynthesisInput(text=text)
        full_output_path = os.path.join(settings.OUTPUT_DIR, "tts_audio", output_filename)
        os.makedirs(os.path.dirname(full_output_path), exist_ok=True)

        result = self._synthesize(synthesis_input, full_output_path, voice_options)
        result['text_segment'] = text # ensure original text is stored
        return result

    def get_audio_file_duration(self, file_path: str) -> float:
        """
        Gets the duration of an audio file using pydub.
        """
        try:
            audio = AudioSegment.from_file(file_path) # pydub handles various formats
            return len(audio) / 1000.0  # pydub duration is in milliseconds
        except Exception as e:
            logger.error(f"Could not get duration for {file_path} using pydub: {e}")
            raise TTSError(f"Failed to get audio duration for {file_path}: {e}")


# Example Usage (for testing this module directly)
if __name__ == "__main__":
    # This test requires GOOGLE_APPLICATION_CREDENTIALS to be set in your environment,
    # and the google-cloud-texttospeech library installed.
    # Also, ensure pydub is installed.
    if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        print("GOOGLE_APPLICATION_CREDENTIALS not set. Skipping GoogleCloudTTS test.")
        exit()
    
    # Ensure output directory for TTS audio exists
    tts_audio_output_dir = os.path.join(settings.OUTPUT_DIR, "tts_audio")
    os.makedirs(tts_audio_output_dir, exist_ok=True)
    print(f"TTS audio will be saved in: {tts_audio_output_dir}")

    try:
        gtts_engine = GoogleCloudTTS()

        # Test plain text synthesis
        print("\n--- Testing Plain Text Synthesis ---")
        text_to_say = "Hello from Google Cloud Text-to-Speech. This is a test narration."
        text_result = gtts_engine.synthesize_text(
            text_to_say,
            "test_plain_text.mp3",
            voice_options={"voice_name": "en-US-News-K"} # Example of a different voice
        )
        text_result['segment_id'] = "plain_test_1" # Manually add for this direct test
        print(f"Plain text synthesis result: {text_result}")
        if os.path.exists(text_result['audio_file_path']):
            print(f"Audio file created: {text_result['audio_file_path']}")
            # duration_check = gtts_engine.get_audio_file_duration(text_result['audio_file_path'])
            # print(f"Duration check via pydub: {duration_check:.3f}s (should match result['duration_sec'])")


        # Test SSML synthesis
        print("\n--- Testing SSML Synthesis ---")
        ssml_to_say = """
        <speak>
          Here is a sentence with <emphasis level="strong">strong emphasis</emphasis>.
          <break time="500ms"/>
          And here is a word pronounced as characters: <say-as interpret-as="characters">SSML</say-as>.
        </speak>
        """
        ssml_result = gtts_engine.synthesize_ssml(
            ssml_to_say,
            "test_ssml_text.mp3"
            # Using default voice options from constructor or settings
        )
        ssml_result['segment_id'] = "ssml_test_1" # Manually add for this direct test
        print(f"SSML synthesis result: {ssml_result}")
        if os.path.exists(ssml_result['audio_file_path']):
            print(f"Audio file created: {ssml_result['audio_file_path']}")

        # Test synthesize_segments
        print("\n--- Testing Synthesize Segments ---")
        segments_to_process = [
            {"id": "seg1", "text": "This is the first segment for batch processing."},
            {"id": "seg2", "text": "And this is the second one, <emphasis level='moderate'>with a bit of flair</emphasis>."}, # Note: this is not full SSML
            {"id": "seg3", "text": "<speak>This one <emphasis>is</emphasis> SSML.</speak>"}
        ]
        # The base_output_dir is handled inside the synthesize_text/ssml methods now
        batch_results = gtts_engine.synthesize_segments(segments_to_process, tts_audio_output_dir)
        print("Batch synthesis results:")
        for res in batch_results:
            print(res)
            if os.path.exists(res['audio_file_path']):
                print(f"  File created: {res['audio_file_path']}")

    except TTSError as e:
        print(f"TTS Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()

