# src/video_processor.py

import os
import requests
import cv2 # Using OpenCV for metadata
import tempfile
from typing import Optional, Tuple, Dict, Any
from urllib.parse import urlparse

from config import settings
from utils import setup_logger, VideoProcessingError, clean_filename

logger = setup_logger(__name__)

class VideoProcessor:
    """
    Handles video input, downloading, validation, and metadata extraction.
    """

    def __init__(self, input_path_or_url: str):
        """
        Initializes the VideoProcessor.

        Args:
            input_path_or_url (str): Path to a local video file or a URL to a video.
        """
        self.input_path_or_url = input_path_or_url
        self.is_url = self._check_if_url(input_path_or_url)
        self.local_video_path: Optional[str] = None
        self.video_metadata: Dict[str, Any] = {}
        self._temp_file_handle = None # To keep temp file alive

    def _check_if_url(self, path: str) -> bool:
        """Checks if the given path is a URL."""
        try:
            result = urlparse(path)
            return all([result.scheme, result.netloc])
        except ValueError:
            return False

    def _download_video(self, url: str) -> str:
        """
        Downloads a video from a URL to a temporary file.
        """
        logger.info(f"Downloading video from URL: {url}")
        try:
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()

            parsed_url = urlparse(url)
            path_part = parsed_url.path
            _, ext = os.path.splitext(path_part)
            if not ext:
                content_type = response.headers.get('content-type')
                if content_type and 'video/' in content_type:
                    ext = '.' + content_type.split('/')[-1].split(';')[0].strip()
                else:
                    ext = ".mp4"

            ext = clean_filename(ext)
            if not ext.startswith('.'):
                ext = '.' + ext

            temp_download_dir = os.path.join(settings.OUTPUT_DIR, "temp_video_downloads")
            os.makedirs(temp_download_dir, exist_ok=True)

            self._temp_file_handle = tempfile.NamedTemporaryFile(
                delete=False,
                suffix=ext,
                dir=temp_download_dir
            )
            temp_video_path = self._temp_file_handle.name

            with open(temp_video_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"Video downloaded successfully to: {temp_video_path}")
            return temp_video_path
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download video from {url}: {e}")
            raise VideoProcessingError(f"Failed to download video: {e}") from e
        except IOError as e:
            logger.error(f"Failed to write downloaded video to disk: {e}")
            raise VideoProcessingError(f"Failed to write video to disk: {e}") from e

    def _get_video_metadata(self, video_path: str) -> Dict[str, Any]:
        """
        Extracts metadata from the video file using OpenCV.
        This method avoids direct dependency on ffprobe for metadata extraction.

        Args:
            video_path (str): Path to the local video file.

        Returns:
            Dict[str, Any]: A dictionary containing video metadata.
                             Includes 'duration' (seconds), 'width', 'height',
                             'fps', 'size' (bytes).
                             'format_name' and 'codec_name' will be placeholders.
        Raises:
            VideoProcessingError: If metadata extraction fails.
        """
        logger.info(f"Extracting metadata from: {video_path} using OpenCV")
        
        if not os.path.exists(video_path):
            raise VideoProcessingError(f"Video file not found for metadata extraction: {video_path}")

        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise VideoProcessingError(f"OpenCV could not open video file: {video_path}")

            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if fps > 0 else 0
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            cap.release() # Release the capture object

            file_size = os.path.getsize(video_path)

            # Try to infer format from extension (very basic)
            _, file_extension = os.path.splitext(video_path)
            inferred_format_name = file_extension.lower().replace('.', '') if file_extension else "unknown"


            metadata = {
                'duration': float(duration),
                'width': int(width),
                'height': int(height),
                'fps': float(fps),
                'codec_name': "unknown (OpenCV)", # OpenCV doesn't easily provide this like ffprobe
                'format_name': inferred_format_name, # Basic inference
                'size': int(file_size),
                'filename': os.path.basename(video_path),
                'filepath': video_path
            }
            logger.info(f"Video metadata extracted using OpenCV: {metadata}")
            return metadata

        except cv2.error as e: # Catch OpenCV specific errors
            logger.error(f"OpenCV error while processing {video_path}: {e}")
            raise VideoProcessingError(f"OpenCV error processing video file {video_path}: {e}") from e
        except Exception as e_gen: # Catch any other unexpected errors
            logger.error(f"Unexpected error during OpenCV metadata extraction for {video_path}: {e_gen}")
            raise VideoProcessingError(f"Unexpected error extracting metadata from video file {video_path}: {e_gen}") from e_gen


    def _parse_fps(self, fps_str: str) -> float:
        """
        Parses FPS string. With OpenCV, we usually get a float directly,
        but this method is kept for consistency if other metadata sources are used.
        """
        # This method might be less relevant if OpenCV always provides FPS as float.
        # However, keeping it in case fps_str comes from another source or for future flexibility.
        if isinstance(fps_str, (float, int)):
            return float(fps_str)
        if isinstance(fps_str, str):
            if '/' in fps_str:
                try:
                    num, den = map(int, fps_str.split('/'))
                    return num / den if den != 0 else 0.0
                except ValueError:
                    return 0.0
            try:
                return float(fps_str)
            except ValueError:
                return 0.0
        return 0.0


    def process(self) -> Tuple[str, Dict[str, Any]]:
        """
        Processes the video: downloads if URL, validates, and extracts metadata.
        """
        if self.is_url:
            try:
                self.local_video_path = self._download_video(self.input_path_or_url)
            except VideoProcessingError as e:
                self._temp_file_handle = None
                raise
        else:
            self.local_video_path = self.input_path_or_url

        if not self.local_video_path or not os.path.exists(self.local_video_path):
            logger.error(f"Video file not found: {self.local_video_path}")
            self._cleanup_temp_file()
            raise VideoProcessingError(f"Video file not found: {self.local_video_path}")

        try:
            self.video_metadata = self._get_video_metadata(self.local_video_path)
        except VideoProcessingError as e:
            self._cleanup_temp_file()
            raise

        if self.video_metadata['duration'] <= 0:
            logger.warning(f"Video duration is zero or negative for {self.local_video_path}")

        # Basic format check based on inferred extension (less reliable than ffprobe's format_name)
        supported_extensions = ['mp4', 'mpeg', 'mov', 'avi', 'flv', 'webm', 'wmv', 'mkv']
        inferred_format = self.video_metadata.get('format_name', '')
        
        if inferred_format not in supported_extensions:
            logger.warning(f"Video format (inferred as '{inferred_format}') may not be widely supported or optimal for Gemini.")


        return self.local_video_path, self.video_metadata

    def _cleanup_temp_file(self):
        """Cleans up the temporary downloaded file if it exists."""
        if self.is_url and self._temp_file_handle:
            file_to_delete = self._temp_file_handle.name
            try:
                self._temp_file_handle.close()
                if os.path.exists(file_to_delete):
                    os.unlink(file_to_delete)
                logger.info(f"Cleaned up temporary file: {file_to_delete}")
            except Exception as e:
                logger.error(f"Error cleaning up temporary file {file_to_delete}: {e}")
            finally:
                self._temp_file_handle = None
                if self.local_video_path and self.local_video_path == file_to_delete:
                     self.local_video_path = None


    def __del__(self):
        self._cleanup_temp_file()

