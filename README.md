# Video Narrator

This project leverages AI models to analyze video content, generate a story-driven narration script, convert it to speech, and optionally mux it back into the original video. The goal is to create an engaging "audiobook" version of a film or video clip.

## Table of Contents

- [Project Goal](#project-goal)
- [Features](#features)
- [How it Works (Workflow)](#how-it-works-workflow)
- [Project Structure](#project-structure)
- [Technical Stack](#technical-stack)
- [Setup Instructions (Detailed)](#setup-instructions-detailed)
- [Configuration (Detailed)](#configuration-detailed)
- [Usage Guide (CLI)](#usage-guide-cli)
    - [Command Structure](#command-structure)
    - [Core Options](#core-options)
    - [Output Control](#output-control)
    - [Examples](#examples)
    - [Interpreting Output Artifacts](#interpreting-output-artifacts)
- [Model Choices](#model-choices)
    - [Video Analysis & Narrative Generation](#video-analysis--narrative-generation)
    - [Text-to-Speech (TTS)](#text-to-speech-tts)
- [Design Decisions](#design-decisions)
- [Running Tests](#running-tests)
    - [Unit Tests](#unit-tests)
    - [Integration Tests](#integration-tests)
- [Troubleshooting Guide](#troubleshooting-guide)
- [Extending the Service](#extending-the-service)
- [Future Enhancements](#future-enhancements)

## Project Goal

To build a production-ready Python service that:
- Accepts an MP4 video (or a URL to one).
- Generates a time-coded narration script (SRT/VTT format).
- Produces a high-quality narrated audio track (WAV/MP3 format).
- Optionally, muxes the narration audio into the original video to create a new MP4 file.

The narration aims to be story-driven, accurately synchronized with on-screen events, and engaging for the listener.

## Features

-   **Automated Video Narration**: Generates spoken narration for video content.
-   **Story-Driven Narrative**: Focuses on telling a story rather than literal frame-by-frame descriptions.
-   **Time-Synchronized Output**: Narration aligns with on-screen visuals.
-   **Multiple Output Formats**:
    -   Time-coded script (SRT).
    -   Narrated audio track (MP3).
    -   (Optional) Narrated video (MP4).
-   **CLI Interface**: Easy-to-use command-line tool for processing videos.
-   **Configurable Models**: Uses Google Gemini for video understanding and Google Cloud TTS by default.
-   **Extensible Design**: Modular components for easier maintenance and future enhancements (e.g., adding new TTS engines).

## How it Works (Workflow)

The service processes videos through a pipeline of coordinated steps:

1.  **Video Input & Preprocessing (`VideoProcessor`)**:
    * Accepts a local video file path or a URL.
    * If a URL is provided, the video is downloaded to a temporary local file.
    * The video format is validated, and basic metadata (duration, resolution, FPS, size) is extracted using `ffmpeg-python`.

2.  **Video Analysis & Narrative Generation (`GeminiHandler`)**:
    * The local video file (original or downloaded) is provided to the Google Gemini API (e.g., Gemini 1.5 Pro).
    * For larger videos, the Gemini File API is used to upload the video first; smaller videos might be sent inline.
    * A carefully crafted system prompt guides Gemini to:
        * Understand the video content.
        * Generate a story-driven narration, not just captions.
        * Output this narration as a JSON list, where each item contains the narration text and its corresponding `start_time` and `end_time` in `HH:MM:SS,mmm` format.
    * The raw JSON response from Gemini is captured.

3.  **Script Parsing & Validation (`ScriptParser`)**:
    * The raw JSON string from Gemini is parsed.
    * Each narration segment is validated for:
        * Correct structure (expected keys: `start_time`, `end_time`, `narration_text`).
        * Valid timestamp formats.
        * Logical consistency (e.g., start time before end time, timestamps within video duration).
    * Minor adjustments to timestamps might be made (e.g., clamping to video duration, resolving minor overlaps).
    * The validated segments are converted into an internal structured format.
    * An SRT (SubRip Text) formatted string is generated from these segments.

4.  **Text-to-Speech Synthesis (`tts_module`)**:
    * If audio generation is enabled, each validated narration text segment is sent to the configured TTS engine (default: Google Cloud Text-to-Speech).
    * The TTS engine converts the text into an audio segment (e.g., an MP3 file). Each segment is saved as an individual file.
    * The actual duration of each spoken audio segment is recorded.

5.  **Audio Assembly (`AudioProcessor`)**:
    * The individual audio segments from TTS are assembled into a single, continuous audio track.
    * Silences are inserted between audio segments based on the `start_time` of each narration segment from the validated script, ensuring the spoken words align with the video timeline.
    * The final combined audio track is exported (e.g., as an MP3 file).

6.  **Video Muxing (Optional)**:
    * If enabled, the newly generated audio track is combined (muxed) with the original video stream using `ffmpeg`.
    * The video codec is typically copied directly to preserve quality and speed up the process, while the new audio is encoded (e.g., to AAC for MP4 compatibility).
    * This produces a new video file with the narration included.

7.  **Output**:
    * The service outputs the requested files (SRT, MP3, and/or muxed MP4) to the specified output directory.
    * Logs of the process are provided to the user via the CLI.

## Project Structure

video-narrator/
├── src/                    # Source code
│   ├── main.py             # CLI entry point
│   ├── orchestrator.py     # Main pipeline coordinator
│   ├── video_processor.py  # Handles video input, download, validation
│   ├── gemini_handler.py   # Interacts with Google Gemini API
│   ├── script_parser.py    # Parses and validates Gemini's output
│   ├── tts_module/         # Text-to-Speech components
│   │   ├── base.py         # TTSEngine abstract base class
│   │   └── impl_google_tts.py # Google Cloud TTS implementation
│   ├── audio_processor.py  # Assembles audio segments
│   ├── config.py         # Configuration management (from .env)
│   └── utils.py            # Utility functions (logging, time conversion)
├── sample_data/            # Sample video clips for testing
│   └── sample_test_clip.mp4
│   └── README.md
├── tests/                    # Automated tests
│   ├── test_script_parser.py # Unit tests for script_parser
│   └── test_pipeline_integration.py # Integration test for the full pipeline
├── .env.example            # Example environment variables file
├── requirements.txt        # Python dependencies
├── README.md               # This file
└── (Optional) Dockerfile   # For containerization

## Technical Stack

-   **Language**: Python 3.10+
-   **Core AI Models**:
    -   Google Gemini API (e.g., Gemini 1.5 Pro) for video understanding and initial timed narrative generation.
    -   Google Cloud Text-to-Speech API for audio synthesis.
-   **Key Libraries**:
    -   `google-generativeai`: Official Python SDK for the Gemini API.
    -   `google-cloud-texttospeech`: Python client for Google Cloud TTS.
    -   `ffmpeg-python`: For video metadata probing and optional muxing. Requires `ffmpeg` to be installed on the system.
    -   `pydub`: For audio manipulation (segment assembly, format conversion). Requires `ffmpeg` or `libav` for MP3 support.
    -   `click`: For creating the command-line interface.
    -   `python-dotenv`: For managing environment variables.
    -   `requests`: For downloading videos from URLs.
-   **Testing**: `unittest` (standard library), `pytest` (optional, recommended).

## Setup Instructions (Detailed)

Follow these steps to set up the Video Narrator Service on your local machine.

1.  **Clone the Repository**:
    ```bash
    git clone <your-repository-url-here> # Replace with the actual URL if you host it
    cd video-narrator
    ```
    If you received the code as a zip, extract it and navigate into the `video-narrator` directory.

2.  **Install Python**:
    Ensure you have Python 3.10 or newer installed. You can check your Python version by running:
    ```bash
    python3 --version
    ```
    If you need to install or manage Python versions, consider using tools like `pyenv`.

3.  **Install FFmpeg**:
    FFmpeg is essential for video metadata extraction, audio processing by `pydub`, and video muxing.
    * **macOS (using Homebrew)**:
        ```bash
        brew install ffmpeg
        ```
    * **Ubuntu/Debian Linux**:
        ```bash
        sudo apt update && sudo apt install ffmpeg
        ```
    * **Windows**:
        1.  Download the latest FFmpeg build from the [official FFmpeg website](https://ffmpeg.org/download.html) (e.g., from Gyan.dev or BtbN).
        2.  Extract the downloaded archive to a directory (e.g., `C:\ffmpeg`).
        3.  Add the `bin` subdirectory (e.g., `C:\ffmpeg\bin`) to your system's PATH environment variable.
    To verify installation, open a new terminal/command prompt and type:
    ```bash
    ffmpeg -version
    ```

4.  **Create and Activate a Python Virtual Environment**:
    It's highly recommended to use a virtual environment to manage project dependencies.
    ```bash
    python3 -m venv venv
    ```
    Activate the environment:
    * **macOS/Linux**:
        ```bash
        source venv/bin/activate
        ```
    * **Windows (Command Prompt/PowerShell)**:
        ```bash
        venv\Scripts\activate
        ```
    Your terminal prompt should change to indicate the active virtual environment (e.g., `(venv)`).

5.  **Install Python Dependencies**:
    With the virtual environment activated, install the required Python libraries:
    ```bash
    pip install -r requirements.txt
    ```

6.  **Set Up Environment Variables for API Keys**:
    API keys and sensitive configurations are managed using a `.env` file.
    1.  Copy the example file:
        ```bash
        cp .env.example .env
        ```
    2.  Open the newly created `.env` file in a text editor.
    3.  **`GOOGLE_API_KEY`**:
        * Obtain an API key from the [Google AI Studio](https://aistudio.google.com/app/apikey) (or Google Cloud Console if using Vertex AI Gemini models).
        * Paste this key as the value for `GOOGLE_API_KEY`.
    4.  **`GOOGLE_APPLICATION_CREDENTIALS`**:
        * This is required for Google Cloud Text-to-Speech.
        * Go to the [Google Cloud Console](https://console.cloud.google.com/).
        * Create a new project or select an existing one.
        * Enable the "Cloud Text-to-Speech API" for your project.
        * Create a service account:
            * Navigate to "IAM & Admin" > "Service Accounts".
            * Click "Create Service Account".
            * Give it a name (e.g., "video-narrator-tts-user").
            * Grant it the role "Cloud Text-to-Speech API User" (or a role with `texttospeech.synthesize` permission).
            * Click "Done".
        * Create a key for the service account:
            * Find your newly created service account in the list.
            * Click the three dots (Actions) next to it, then "Manage keys".
            * Click "Add Key" > "Create new key".
            * Choose "JSON" as the key type and click "Create".
            * A JSON file will be downloaded to your computer.
        * Move this JSON file to a secure location on your system (e.g., a directory not part of the project repository).
        * Set the `GOOGLE_APPLICATION_CREDENTIALS` variable in your `.env` file to the **absolute path** of this downloaded JSON key file.
            Example for macOS/Linux: `GOOGLE_APPLICATION_CREDENTIALS="/Users/yourusername/secure_keys/gcp-tts-key.json"`
            Example for Windows: `GOOGLE_APPLICATION_CREDENTIALS="C:\Users\yourusername\secure_keys\gcp-tts-key.json"`
    5.  (Optional) Review and customize other variables in `.env` like `GEMINI_VIDEO_MODEL`, `TTS_VOICE_NAME`, etc. See the [Configuration (Detailed)](#configuration-detailed) section.

You should now be ready to use the service!

## Configuration (Detailed)

The service uses a `.env` file in the project root to manage its configuration. Create this file by copying `.env.example`.

-   **`GOOGLE_API_KEY="YOUR_GOOGLE_API_KEY_HERE"`**
    * **Required**: Yes.
    * **Purpose**: API key for authenticating with the Google Gemini API. Used for video analysis and narrative generation.
    * **Source**: Google AI Studio or Google Cloud Console.

-   **`GEMINI_VIDEO_MODEL="gemini-1.5-pro-latest"`**
    * **Required**: No (has a default in `src/config.py`).
    * **Purpose**: Specifies which Gemini model to use for video processing. Ensure the chosen model supports video input and the desired features (e.g., long context, JSON output mode).
    * **Examples**: `gemini-1.5-pro-latest`, `gemini-1.0-pro-vision-latest`.

-   **`GOOGLE_APPLICATION_CREDENTIALS="/path/to/your/google_cloud_credentials.json"`**
    * **Required**: Yes, if audio generation is enabled (which is the default).
    * **Purpose**: Absolute path to your Google Cloud service account JSON key file. This authenticates your application to use Google Cloud services, specifically the Text-to-Speech API.
    * **Source**: Google Cloud Console (IAM & Admin > Service Accounts).

-   **`TTS_VOICE_NAME="en-US-Neural2-J"`**
    * **Required**: No (has a default in `src/tts_module/impl_google_tts.py` or `src/config.py`).
    * **Purpose**: Specifies the voice to be used by Google Cloud Text-to-Speech.
    * **Source**: Refer to the [Google Cloud TTS documentation for available voices](https://cloud.google.com/text-to-speech/docs/voices). Choose voices that match your desired language, gender, and style (Standard, WaveNet, Neural2).
    * **Example**: `en-GB-News-K`, `es-US-Studio-B`.

-   **`TTS_SPEAKING_RATE="1.0"`**
    * **Required**: No (has a default).
    * **Purpose**: Controls the speaking rate of the TTS voice. `1.0` is normal speed. Values less than `1.0` slow down speech, greater than `1.0` speed it up. Typically ranges from `0.25` to `4.0`.

-   **`OUTPUT_DIR="output"`**
    * **Required**: No (defaults to `./output/` relative to the project root).
    * **Purpose**: The directory where all generated files (SRT scripts, MP3 audio, muxed videos, raw AI outputs) will be saved.
    * The CLI `-o` or `--output-dir` option can override this.

-   **`LOG_LEVEL="INFO"`**
    * **Required**: No (defaults to `INFO`).
    * **Purpose**: Sets the logging verbosity for console output.
    * **Options**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. `DEBUG` is useful for development and troubleshooting.

-   **`MAX_INLINE_VIDEO_DURATION_S="55"`**
    * **Required**: No (has a default in `src/config.py`).
    * **Purpose**: Maximum video duration (in seconds) to attempt sending directly to Gemini API as inline data. Videos longer than this (or larger than `MAX_INLINE_VIDEO_SIZE_MB`) will be uploaded using the Gemini File API, which is better for larger files.
    * **Note**: Gemini API limits for inline data can vary; 55 seconds is a conservative estimate.

-   **`MAX_INLINE_VIDEO_SIZE_MB="19"`**
    * **Required**: No (has a default in `src/config.py`).
    * **Purpose**: Maximum video file size (in megabytes) for inline sending to Gemini.
    * **Note**: Gemini API often limits inline requests to around 20MB (including the prompt).

## Usage Guide (CLI)

The service is operated via the `src/main.py` command-line interface.

### Command Structure

```bash
python src/main.py process-video [OPTIONS] <INPUT_SOURCE>
