# src/main.py

import os
import click
import json # For pretty printing dict results

# Adjust the Python path to include the 'src' directory parent if running main.py directly for testing
# This is often needed if 'src' is not installed as a package.
import sys
if os.path.join(os.getcwd(), 'src') not in sys.path and os.path.join(os.getcwd()) not in sys.path :
    # Add current directory to sys.path if src is directly inside it
    if os.path.isdir(os.path.join(os.getcwd(), 'src')):
         sys.path.insert(0, os.getcwd())
    else: # if main.py is run from within src, add parent
         sys.path.insert(0, os.path.dirname(os.getcwd()))


from orchestrator import Orchestrator
from config import settings # To access default output_dir
from utils import setup_logger

# Initialize logger for main module
logger = setup_logger(__name__)

@click.group()
def cli():
    """
    Video Narration Service CLI.
    This tool processes a video file or URL to generate a timed narration script,
    an audio track, and optionally a new video with the narration muxed in.
    """
    pass

@cli.command("process-video")
@click.option('--file-path', '-f', type=click.Path(exists=True, dir_okay=False, readable=True),
              help="Path to the local video file.")
@click.option('--url', '-u', type=str,
              help="URL of the video to process.")
@click.option('--output-dir', '-o', type=click.Path(file_okay=False, writable=True, resolve_path=True),
              default=settings.OUTPUT_DIR, show_default=True,
              help="Directory to save output files.")
@click.option('--script-only', is_flag=True, default=False,
              help="Only generate the narration script (SRT), skip audio generation and muxing.")
@click.option('--no-audio', is_flag=True, default=False,
              help="Generate script but do not generate the audio track or mux video.")
@click.option('--mux-video', is_flag=True, default=False,
              help="Mux the generated audio into the video. Requires audio generation.")
@click.option('--tts-engine', type=click.Choice(['google', 'piper'], case_sensitive=False), # Add more choices as implemented
              default='google', show_default=True,
              help="TTS engine to use for audio generation.")
def process_video_command(file_path: str, url: str, output_dir: str,
                          script_only: bool, no_audio: bool, mux_video: bool, tts_engine: str):
    """
    Processes a single video to generate narration.

    You must provide either --file-path or --url.
    """
    if not file_path and not url:
        raise click.UsageError("You must provide either --file-path (-f) or --url (-u).")
    if file_path and url:
        raise click.UsageError("Please provide either --file-path (-f) or --url (-u), not both.")

    input_source = file_path if file_path else url
    click.echo(f"Starting video narration process for: {input_source}")
    click.echo(f"Output directory: {output_dir}")

    # Determine TTS engine class
    selected_tts_engine_class = None
    if tts_engine.lower() == 'google':
        from tts_module.impl_google_tts import GoogleCloudTTS
        selected_tts_engine_class = GoogleCloudTTS
    # Example for PiperTTS if it were implemented
    # elif tts_engine.lower() == 'piper':
    #     try:
    #         from src.tts_module.impl_piper_tts import PiperTTS
    #         selected_tts_engine_class = PiperTTS
    #     except ImportError:
    #         logger.error("PiperTTS module not found or not fully implemented.")
    #         click.echo(click.style("Error: PiperTTS engine selected but module is not available.", fg="red"))
    #         return
    else:
        click.echo(click.style(f"Error: TTS engine '{tts_engine}' is not recognized.", fg="red"))
        return

    if (not no_audio and not script_only) and not selected_tts_engine_class:
        click.echo(click.style("Error: Could not initialize the selected TTS engine.", fg="red"))
        return


    # Instantiate and run orchestrator
    orchestrator = Orchestrator(
        input_path_or_url=input_source,
        output_dir=output_dir,
        tts_engine_class=selected_tts_engine_class
    )

    generate_audio_flag = True
    if script_only or no_audio:
        generate_audio_flag = False

    mux_video_flag = mux_video
    if not generate_audio_flag and mux_video:
        click.echo(click.style("Warning: --mux-video requires audio generation. Muxing will be skipped.", fg="yellow"))
        mux_video_flag = False
    
    if script_only and mux_video:
        click.echo(click.style("Warning: --script-only is active, --mux-video will be ignored.", fg="yellow"))
        mux_video_flag = False


    try:
        click.echo("Pipeline starting... This may take some time depending on video length and chosen models.")
        results = orchestrator.run_pipeline(
            generate_audio=generate_audio_flag,
            mux_video=mux_video_flag
        )
        click.echo(click.style("Pipeline completed successfully!", fg="green"))
        click.echo("\nGenerated Artifacts:")
        if results.get("srt_file"):
            click.echo(f"  SRT Script: {results['srt_file']}")
        if results.get("audio_file"):
            click.echo(f"  Audio File: {results['audio_file']}")
        if results.get("muxed_video_file"):
            click.echo(f"  Muxed Video: {results['muxed_video_file']}")

        click.echo("\nPipeline Logs:")
        for log_entry in results.get("logs", []):
            if "ERROR" in log_entry:
                click.echo(click.style(f"  {log_entry}", fg="red"))
            elif "WARNING" in log_entry:
                click.echo(click.style(f"  {log_entry}", fg="yellow"))
            else:
                click.echo(f"  {log_entry}")

    except Exception as e:
        logger.error(f"CLI command failed: {e}", exc_info=True)
        click.echo(click.style(f"An error occurred: {e}", fg="red"))
        click.echo("Check logs for more details.")

if __name__ == "__main__":
    # This allows running the CLI directly, e.g., python src/main.py process-video ...
    # The sys.path adjustment at the top helps with module resolution in this case.
    cli()
