"""Audio utilities wrapping AssemblyAI transcription and recording.

The recording functionality is kept to mirror the original behavior,
though the FastAPI layer will typically handle uploaded audio files
instead of recording directly from a microphone.
"""

import tempfile
from typing import Any, Dict, List, Optional
import time
import logging
from pathlib import Path

import assemblyai as aai  # type: ignore[import]
import requests
try:
    import sounddevice as sd  # type: ignore[import]
    import soundfile as sf  # type: ignore[import]
except ModuleNotFoundError:  # pragma: no cover
    sd = None  # type: ignore[assignment]
    sf = None  # type: ignore[assignment]

from .config import config


logger = logging.getLogger(__name__)


aai.settings.api_key = config.ASSEMBLYAI_API_KEY


def _transcribe_via_rest_detailed(audio_file: str) -> Dict[str, Any]:
    base_url = str(getattr(config, "ASSEMBLYAI_BASE_URL", "https://api.assemblyai.com")).rstrip("/")
    api_key = str(getattr(config, "ASSEMBLYAI_API_KEY", ""))
    if not api_key:
        raise RuntimeError("Missing ASSEMBLYAI_API_KEY")

    headers = {"authorization": api_key}

    with open(audio_file, "rb") as f:
        upload_resp = requests.post(
            f"{base_url}/v2/upload",
            headers=headers,
            data=f,
            timeout=120,
        )
    upload_resp.raise_for_status()
    upload_url = upload_resp.json()["upload_url"]

    speech_model = str(getattr(config, "ASSEMBLYAI_SPEECH_MODEL", "universal-2"))
    payload = {
        "audio_url": upload_url,
        "speech_models": [speech_model],
        # Request structured metadata so we can store real timestamps/confidence/language.
        "language_detection": True,
    }
    transcript_resp = requests.post(
        f"{base_url}/v2/transcript",
        headers={**headers, "content-type": "application/json"},
        json=payload,
        timeout=60,
    )
    transcript_resp.raise_for_status()
    transcript_id = transcript_resp.json()["id"]

    polling_url = f"{base_url}/v2/transcript/{transcript_id}"
    for _ in range(120):
        poll_resp = requests.get(polling_url, headers=headers, timeout=30)
        poll_resp.raise_for_status()
        data = poll_resp.json()
        status = data.get("status")
        if status == "completed":
            # Ensure we fetch the word-level timestamps & confidences.
            words_url = f"{polling_url}/words"
            try:
                words_resp = requests.get(words_url, headers=headers, timeout=30)
                if words_resp.status_code == 200:
                    data["words"] = words_resp.json() or []
            except Exception:
                # If the words endpoint fails, keep the base transcript.
                data.setdefault("words", [])
            data.setdefault("words", [])
            return data
        if status == "error":
            raise RuntimeError(f"Transcription failed: {data.get('error')}")
        time.sleep(2)

    raise TimeoutError("Transcription polling timed out")


def _transcribe_via_rest(audio_file: str) -> str:
    data = _transcribe_via_rest_detailed(audio_file)
    text = str(data.get("text") or "")
    return text


def transcribe_audio_file_detailed(audio_file: str) -> Dict[str, Any]:
    """Return structured transcript data for ingestion metadata.

    Output keys:
    - text: str
    - language_code: Optional[str]
    - confidence: Optional[float]
    - words: list[dict] (with start/end/confidence/text)
    """

    path = Path(audio_file)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file}")
    if path.stat().st_size == 0:
        raise ValueError(f"Audio file is empty: {audio_file}")

    model = str(getattr(config, "ASSEMBLYAI_SPEECH_MODEL", "universal-2"))
    sdk_supported_models = {"best", "nano"}
    if model.lower() not in sdk_supported_models:
        return _transcribe_via_rest_detailed(audio_file)

    # SDK path: attempt, but fall back to REST detailed.
    try:
        transcriber = aai.Transcriber()
        try:
            cfg = aai.TranscriptionConfig(speech_model=model)
        except TypeError:
            cfg = aai.TranscriptionConfig(speech_models=[model])
        try:
            transcript = transcriber.transcribe(audio_file, config=cfg)
        except TypeError:
            transcript = transcriber.transcribe(audio_file, cfg)
        text = str(getattr(transcript, "text", "") or "")
        # The SDK may not expose words/language consistently; use REST for metadata.
        if not text.strip():
            raise ValueError("SDK transcript text empty")
        return _transcribe_via_rest_detailed(audio_file)
    except Exception:
        return _transcribe_via_rest_detailed(audio_file)


def transcribe_audio_file(audio_file: str) -> str:
    """Transcribe an audio file using AssemblyAI (same as original)."""

    logger.info("🎤 Starting transcription for: %s", audio_file)

    path = Path(audio_file)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file}")
    file_size = path.stat().st_size
    if file_size == 0:
        raise ValueError(f"Audio file is empty: {audio_file}")
    logger.info("📊 File size: %d bytes", file_size)

    transcriber = aai.Transcriber()
    model = str(getattr(config, "ASSEMBLYAI_SPEECH_MODEL", "universal-2"))

    # Some AssemblyAI SDK versions validate `speech_model` against an enum that only
    # supports values like "best"/"nano". If the configured model is a newer API model
    # (e.g. universal-2/universal-3), bypass the SDK and use REST directly.
    sdk_supported_models = {"best", "nano"}
    if model.lower() not in sdk_supported_models:
        logger.info(
            "ℹ️ Using REST transcription directly (SDK speech_model enum mismatch). Configured=%s",
            model,
        )
        text = _transcribe_via_rest(audio_file)
        if not str(text or "").strip():
            raise ValueError(f"REST transcription returned empty text for {audio_file}")
        logger.info("✅ Transcription successful via REST: %d characters", len(text))
        if bool(getattr(config, "LOG_TRANSCRIPTS", False)):
            limit = int(getattr(config, "TRANSCRIPT_LOG_CHARS", 400))
            snippet = (text or "")[:limit]
            logger.info("🗣️ Transcribed audio via REST (first %d chars): %s", limit, snippet)
        return text

    # AssemblyAI SDK versions differ in how the speech model is specified.
    # Newer API requirements need a speech model selection (e.g. universal-2).
    # Prefer using TranscriptionConfig, with fallbacks for older signatures.
    try:
        try:
            cfg = aai.TranscriptionConfig(speech_model=model)
        except TypeError:
            cfg = aai.TranscriptionConfig(speech_models=[model])

        logger.info("🔄 Sending to AssemblyAI...")
        try:
            transcript = transcriber.transcribe(audio_file, config=cfg)
        except TypeError:
            transcript = transcriber.transcribe(audio_file, cfg)
        text = transcript.text
        if not str(text or "").strip():
            raise ValueError(f"Transcription returned empty text for {audio_file}")
        logger.info("✅ Transcription successful: %d characters", len(text))
        if bool(getattr(config, "LOG_TRANSCRIPTS", False)):
            limit = int(getattr(config, "TRANSCRIPT_LOG_CHARS", 400))
            snippet = (text or "")[:limit]
            logger.info("🗣️ Transcribed audio (first %d chars): %s", limit, snippet)
        return text
    except Exception as sdk_error:
        logger.warning("⚠️ SDK transcription failed, trying REST fallback: %s", sdk_error)
        try:
            text = _transcribe_via_rest(audio_file)
            if not str(text or "").strip():
                raise ValueError(f"REST transcription returned empty text for {audio_file}")
            if bool(getattr(config, "LOG_TRANSCRIPTS", False)):
                limit = int(getattr(config, "TRANSCRIPT_LOG_CHARS", 400))
                snippet = (text or "")[:limit]
                logger.info("🗣️ Transcribed audio via REST (first %d chars): %s", limit, snippet)
            return text
        except Exception as rest_error:
            logger.exception("❌ Both SDK and REST transcription failed")
            raise RuntimeError(
                f"Transcription failed: SDK error: {sdk_error}, REST error: {rest_error}"
            ) from rest_error


def record_audio(duration: int = 10, sample_rate: int = 16000) -> str:
    """Record audio from the default microphone and save to a temp file.

    This follows the original implementation's behavior.
    """

    if sd is None or sf is None:
        raise RuntimeError("Audio recording dependencies are not installed (missing 'sounddevice'/'soundfile')")

    audio_data = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float64",
    )
    sd.wait()

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    sf.write(temp_file.name, audio_data, sample_rate)
    return temp_file.name
