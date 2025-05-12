# src/gemini_handler.py

import google.generativeai as genai
import time
import mimetypes # For guessing MIME type of local files
import re
from typing import Dict, Any, Optional

from config import settings
from utils import setup_logger, NarrationError

logger = setup_logger(__name__)

# System prompt to guide the Gemini model
# This is a critical part and will likely need iterative refinement.
NARRATION_SYSTEM_PROMPT = """
You are an expert video narrator and storyteller. Your task is to analyze the provided video
and generate an engaging, story-driven narration script. This script should not just describe
what is happening on screen frame-by-frame, but weave a compelling narrative, inferring context,
emotions, and progression, much like an audiobook bringing a film to life.

The narration must:
1.  Cover the entire runtime of the video, starting when the video starts and stopping when it ends.
    Aim for at least 95% coverage with spoken words, allowing for brief dramatic pauses.
2.  Be synchronized with the video. Spoken words should align with on-screen events
    within a reasonable tolerance (ideally +/- 1 second).
3.  Tell a story, not just provide captions. Avoid literalism like "And then we see...".
    Focus on narrative flow, pacing, tone, and engaging vocabulary.
4.  The output MUST be a valid JSON list of objects. Each object represents a narration segment
    and MUST have the following three keys:
    - "start_time": A string representing the start time of the narration segment in "HH:MM:SS,mmm" format.
    - "end_time": A string representing the end time of the narration segment in "HH:MM:SS,mmm" format.
    - "narration_text": A string containing the spoken words for this segment.

Example of a single JSON object in the list:
{{
  "start_time": "00:00:05,123",
  "end_time": "00:00:12,678",
  "narration_text": "The old lighthouse stood defiantly against the raging storm, its beam cutting through the darkness."
}}

Ensure the timestamps are accurate and reflect when the narration for that specific text segment
should begin and end in the video. The segments should be sequential and cover the video's duration.
Do not include any other text or explanations outside of the JSON list.
The video's duration is approximately {video_duration_formatted}.
"""


class GeminiHandler:
    """
    Handles interaction with the Google Gemini API for video understanding and narration.
    """

    def __init__(self, video_path: str, video_metadata: Dict[str, Any]):
        """
        Initializes the GeminiHandler.

        Args:
            video_path (str): Path to the local video file.
            video_metadata (Dict[str, Any]): Metadata of the video, including 'duration' and 'size'.
        """
        if not settings.GOOGLE_API_KEY:
            raise NarrationError("GOOGLE_API_KEY is not configured. Please set it in your .env file.")

        genai.configure(api_key=settings.GOOGLE_API_KEY)
        self.video_path = video_path
        self.video_metadata = video_metadata
        self.model_name = settings.GEMINI_VIDEO_MODEL
        self.model = genai.GenerativeModel(
            self.model_name,
            # It's good practice to include system instructions if the model supports it well
            # For some Gemini versions/tasks, system_instruction is a top-level param.
            # For others, it's part of the `contents`. We'll put it in `contents`.
        )
        logger.info(f"Gemini Handler initialized with model: {self.model_name}")

    def _strip_markdown_wrapper(self, text: str) -> str:
        """
        Strips common markdown code block wrappers (e.g., ```json ... ```) from a string.
        """
        stripped_text = text.strip()
        
        # Regex to find ```json ... ``` or ``` ... ```
        match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped_text, re.DOTALL | re.IGNORECASE)
        
        if match:
            logger.debug("Markdown JSON wrapper detected and stripped by GeminiHandler.")
            return match.group(1).strip()
        
        # Fallback for simple cases if regex doesn't match
        # (This part might be less necessary if the regex is robust enough)
        if stripped_text.startswith("```json"):
            stripped_text = stripped_text[len("```json"):]
        elif stripped_text.startswith("```"):
            stripped_text = stripped_text[len("```"):]
        
        if stripped_text.endswith("```"):
            stripped_text = stripped_text[:-len("```")]
            
        return stripped_text.strip()
    
    def _upload_video_if_needed(self) -> Optional[genai.types.File]:
        """
        Uploads the video to the Gemini File API if it's large or long.
        Gemini API recommends using File API for videos > 20MB or > ~1 minute.
        We use MAX_INLINE_VIDEO_SIZE_MB and MAX_INLINE_VIDEO_DURATION_S from config.

        Returns:
            Optional[genai.types.File]: The uploaded file object if uploaded, else None.
        """
        video_duration_s = self.video_metadata.get('duration', 0)
        video_size_bytes = self.video_metadata.get('size', 0)
        video_size_mb = video_size_bytes / (1024 * 1024)

        # Heuristic: if duration or size exceeds typical inline limits, upload via File API
        # These limits can vary by specific Gemini model and API version.
        # The Gemini documentation (ai.google.dev/gemini-api/docs/video-understanding)
        # mentions limits around 20MB and 1 minute for inline data.
        # Note: Gemini 1.5 Pro can handle up to 1 hour of video via File API.
        if video_duration_s > settings.MAX_INLINE_VIDEO_DURATION_S or \
           video_size_mb > settings.MAX_INLINE_VIDEO_SIZE_MB:
            logger.info(f"Video duration ({video_duration_s:.2f}s) or size ({video_size_mb:.2f}MB) exceeds inline limits. Uploading via File API.")
            try:
                # Guess MIME type
                mime_type, _ = mimetypes.guess_type(self.video_path)
                if not mime_type:
                    logger.warning(f"Could not guess MIME type for {self.video_path}. Defaulting to video/mp4.")
                    mime_type = "video/mp4" # A common default

                logger.info(f"Uploading {self.video_path} (MIME: {mime_type}) to Gemini File API...")
                video_file = genai.upload_file(path=self.video_path, mime_type=mime_type)

                # Wait for the file to be processed.
                # This is crucial as the file needs to be in an 'ACTIVE' state.
                while video_file.state.name == "PROCESSING":
                    logger.info("Video is still processing by File API...")
                    time.sleep(10) # Wait 10 seconds before checking again
                    video_file = genai.get_file(video_file.name) # Refresh file state

                if video_file.state.name == "FAILED":
                    logger.error(f"Video file upload failed. State: {video_file.state.name}, URI: {video_file.uri if hasattr(video_file, 'uri') else 'N/A'}")
                    raise NarrationError(f"Video file upload processing failed: {video_file.name}")

                logger.info(f"Video uploaded successfully: {video_file.name} (URI: {video_file.uri}), State: {video_file.state.name}")
                return video_file
            except Exception as e:
                logger.error(f"Error uploading video to Gemini File API: {e}")
                raise NarrationError(f"Failed to upload video: {e}") from e
        else:
            logger.info("Video size and duration are within inline limits. Will attempt to send inline.")
            return None # Indicates video should be sent inline

    def _format_duration(self, seconds: float) -> str:
        """Formats duration in seconds to a more readable HH:MM:SS or MM:SS string."""
        td = time.gmtime(seconds)
        if seconds >= 3600:
            return time.strftime("%H hours, %M minutes, and %S seconds", td)
        elif seconds >=60:
            return time.strftime("%M minutes and %S seconds", td)
        else:
            return time.strftime("%S seconds", td)


    def generate_narration(self) -> str:
        """
        Generates the timed narration script using the Gemini API.

        Returns:
            str: The raw response text from Gemini, expected to be a JSON string.

        Raises:
            NarrationError: If narration generation fails.
        """
        uploaded_file_resource = self._upload_video_if_needed()

        # Prepare the prompt parts
        video_duration_formatted = self._format_duration(self.video_metadata.get('duration', 0))
        system_instruction_text = NARRATION_SYSTEM_PROMPT.format(video_duration_formatted=video_duration_formatted)

        prompt_parts = []

        if uploaded_file_resource:
            # Use the uploaded file resource
            prompt_parts.append(uploaded_file_resource) # The File object itself
        else:
            # Send video data inline (ensure it's small enough)
            try:
                with open(self.video_path, "rb") as f:
                    video_bytes = f.read()
                mime_type, _ = mimetypes.guess_type(self.video_path)
                if not mime_type: mime_type = "video/mp4"
                prompt_parts.append({"mime_type": mime_type, "data": video_bytes})
            except IOError as e:
                logger.error(f"Could not read video file for inline sending: {self.video_path} - {e}")
                raise NarrationError(f"Failed to read video file for inline sending: {e}") from e

        # Add the system instruction/prompt text after the video part
        prompt_parts.append(system_instruction_text)

        logger.info(f"Sending request to Gemini model ({self.model_name}) with video and prompt...")
        # logger.debug(f"Prompt parts being sent (video data omitted for brevity if inline): {prompt_parts if uploaded_file_resource else [type(p) for p in prompt_parts]}")
        # logger.debug(f"Full text prompt being sent: {system_instruction_text}")


        try:
            # Configuration for generation - can be tuned
            generation_config = genai.types.GenerationConfig(
                # response_mime_type="application/json", # Request JSON output directly if model supports
                temperature=0.6, # Adjust for creativity vs. factuality
                # max_output_tokens=8192 # Default is often large enough
            )

            # For some models, system_instruction is a parameter to generate_content
            # For others, it's part of the 'contents' list. The SDK handles this.
            # If `system_instruction` is a direct param for your model version:
            # response = self.model.generate_content(
            #     prompt_parts,
            #     generation_config=generation_config,
            #     request_options={'timeout': 600} # 10 minutes timeout for potentially long video processing
            # )
            # Otherwise, include it in prompt_parts as done above.

            response = self.model.generate_content(
                contents=prompt_parts, # prompt_parts already includes system instructions
                generation_config=generation_config,
                request_options={'timeout': 1800} # 30 minutes timeout
            )

            # Ensure all parts of the response are accessed to catch potential errors
            # If response is streamed, you'd iterate. For non-streamed:
            if not response.candidates or not response.candidates[0].content.parts:
                logger.error("Gemini response is empty or malformed.")
                logger.debug(f"Full Gemini Response: {response}")
                # Check for safety ratings or finish reasons if available
                if response.prompt_feedback and response.prompt_feedback.block_reason:
                    raise NarrationError(f"Gemini request blocked. Reason: {response.prompt_feedback.block_reason_message or response.prompt_feedback.block_reason}")
                raise NarrationError("Gemini returned an empty or malformed response.")

            narration_json_string = response.text # .text convenience accessor
            logger.info("Successfully received narration script from Gemini.")
            # logger.debug(f"Raw Gemini Response Text:\n{narration_json_string}")
            return self._strip_markdown_wrapper(narration_json_string)

        except Exception as e:
            logger.error(f"Error during Gemini API call: {e}")
            # Attempt to get more details if it's a Google API error
            if hasattr(e, 'message'): # google.api_core.exceptions.GoogleAPIError
                 logger.error(f"Google API Error Message: {e.message}")
            if hasattr(e, 'response') and hasattr(e.response, 'text'): # For requests-like errors
                 logger.error(f"Error Response Text: {e.response.text}")

            # Check for prompt feedback if the response object exists but generation failed
            # This might not be available if the error is pre-request (e.g. network)
            try:
                if response and response.prompt_feedback and response.prompt_feedback.block_reason:
                    raise NarrationError(f"Gemini request blocked. Reason: {response.prompt_feedback.block_reason_message or response.prompt_feedback.block_reason}") from e
            except NameError: # response might not be defined
                pass
            except AttributeError: # response might not have prompt_feedback
                pass

            raise NarrationError(f"Gemini API call failed: {e}") from e

        finally:
            # Clean up the uploaded file from Gemini File API if it was created
            if uploaded_file_resource:
                try:
                    logger.info(f"Attempting to delete uploaded file: {uploaded_file_resource.name}")
                    genai.delete_file(uploaded_file_resource.name)
                    logger.info(f"Successfully deleted uploaded file: {uploaded_file_resource.name}")
                except Exception as e:
                    logger.error(f"Error deleting uploaded file {uploaded_file_resource.name}: {e}")


# Example Usage (for testing this module directly)
if __name__ == "__main__":
    # This example assumes you have a 'sample_video.mp4' and your .env is configured.
    # Create a dummy video file for testing if you don't have one.
    # For this test to run, you need:
    # 1. A .env file with GOOGLE_API_KEY
    # 2. A sample video file, e.g., sample_video.mp4 (can be very short)
    #    If you used the VideoProcessor example, it might download one to settings.OUTPUT_DIR

    sample_video_file = os.path.join(settings.OUTPUT_DIR, "ForBiggerBlazes.mp4") # Assuming it was downloaded by VideoProcessor test
    if not os.path.exists(sample_video_file):
        # Fallback: try to find a sample video in the root directory
        sample_video_file_root = "sample_video.mp4"
        if os.path.exists(sample_video_file_root):
            sample_video_file = sample_video_file_root
        else:
            print(f"Please create a sample video file at '{sample_video_file}' or '{sample_video_file_root}' for testing.")
            print("Or ensure VideoProcessor example ran and downloaded a video.")
            exit()
    
    print(f"Using sample video: {sample_video_file}")

    # Get dummy metadata (replace with actual metadata if running after VideoProcessor)
    try:
        from video_processor import VideoProcessor as VP_Test # Relative import for testing
        vp = VP_Test(sample_video_file)
        _, test_video_metadata = vp.process()
        print(f"Video metadata for test: {test_video_metadata}")
    except Exception as e:
        print(f"Could not get metadata using VideoProcessor, using dummy: {e}")
        test_video_metadata = {'duration': 15, 'size': 1024*1024*1} # 15s, 1MB (dummy)


    if not settings.GOOGLE_API_KEY or settings.GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY_HERE":
        print("GOOGLE_API_KEY not set in .env or is placeholder. Skipping GeminiHandler test.")
    else:
        try:
            print(f"\n--- Testing GeminiHandler with video: {sample_video_file} ---")
            handler = GeminiHandler(video_path=sample_video_file, video_metadata=test_video_metadata)
            raw_narration_script = handler.generate_narration()
            print("\n--- Raw Narration Script from Gemini ---")
            print(raw_narration_script)
            print("--------------------------------------")

            # Basic validation of the output
            if raw_narration_script.strip().startswith("[") and raw_narration_script.strip().endswith("]"):
                print("Script seems to be a JSON list.")
            else:
                print("Warning: Script does not appear to be a JSON list as expected.")

        except NarrationError as e:
            print(f"Narration Error: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            import traceback
            traceback.print_exc()

