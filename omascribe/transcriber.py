"""Transcription module using OpenAI Whisper.

Whisper auto-picks ``cuda`` when ``torch.cuda.is_available()`` reports True,
which can fail loudly on machines whose installed PyTorch wheel doesn't ship
kernels for the local GPU (the classic ``CUDA error: no kernel image is
available for execution on the device``). We default to CPU to match the
README's "CPU-based, privacy-first" promise, allow opt-in CUDA via config,
and transparently fall back to CPU if the chosen device can't actually load
the model.
"""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass

from .logger import get_logger

logger = get_logger(__name__)


@dataclass
class TranscriptSegment:
    """A segment of transcribed text with timing information."""
    start: float
    end: float
    text: str
    # Diarised speaker label ("A", "B", ...). Whisper has no diarisation, so
    # its segments leave this unset and render exactly as before.
    speaker: Optional[str] = None


@dataclass
class TranscriptResult:
    """Complete transcription result."""
    text: str
    segments: list[TranscriptSegment]
    language: str
    duration: float

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "duration": self.duration,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text, "speaker": s.speaker} for s in self.segments
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TranscriptResult":
        return cls(
            text=data["text"],
            language=data.get("language", "unknown"),
            duration=float(data.get("duration") or 0),
            segments=[TranscriptSegment(**seg) for seg in data.get("segments", [])],
        )

    def speaker_text(self) -> str:
        """The transcript with one ``Speaker X: ...`` line per utterance.

        This is what a summariser should see when speakers are known: it lets
        action items name an owner. Without speaker labels it is just ``text``.
        """
        if not any(seg.speaker for seg in self.segments):
            return self.text
        return "\n".join(f"Speaker {seg.speaker}: {seg.text}" for seg in self.segments)


def format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS, or HH:MM:SS past the hour."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_segments(segments: list[TranscriptSegment]) -> str:
    """Render segments as the markdown-ish body of a transcript file."""
    lines = []
    for seg in segments:
        speaker = f" Speaker {seg.speaker}:" if seg.speaker else ""
        lines.append(f"**[{format_timestamp(seg.start)}]{speaker}** {seg.text.strip()}")
    return "\n\n".join(lines)


_VALID_DEVICES = ("auto", "cpu", "cuda")


def _looks_like_cuda_failure(err: BaseException) -> bool:
    """Heuristic: does this exception indicate the CUDA path is unusable?"""
    msg = f"{type(err).__name__}: {err}"
    needles = (
        "no kernel image is available",
        "CUDA error",
        "CUDA driver",
        "Torch not compiled with CUDA",
        "cudaError",
        "device-side assert",
    )
    return any(n.lower() in msg.lower() for n in needles)


class WhisperTranscriber:
    """Transcribe audio files using Whisper."""

    def __init__(self, model_name: str = "base", device: str = "cpu"):
        """Initialize the transcriber.

        Args:
            model_name: Whisper model to use (tiny, base, small, medium, large)
            device: One of ``"cpu"``, ``"cuda"``, or ``"auto"``. Defaults to
                ``"cpu"`` because that matches the documented privacy-first
                CPU pipeline and avoids broken CUDA installs taking the app
                down. ``"auto"`` lets Whisper pick (CUDA when available) but
                still falls back to CPU on load failure.
        """
        if device not in _VALID_DEVICES:
            logger.warning(f"Unknown whisper device {device!r}, falling back to 'cpu'")
            device = "cpu"
        logger.info(f"Initializing WhisperTranscriber (model: {model_name}, device: {device})")
        self.model_name = model_name
        self.requested_device = device
        self.active_device: Optional[str] = None
        self.model = None  # type: ignore[assignment]

    def _resolve_device(self) -> Optional[str]:
        """Translate the requested device into something to pass to Whisper.

        Returns ``None`` for ``auto`` so Whisper does its own detection.
        """
        if self.requested_device == "auto":
            return None
        return self.requested_device

    def load_model(self):
        """Load the Whisper model (lazy loading), with CUDA-failure fallback."""
        if self.model is not None:
            return

        # Import lazily so unit tests / non-transcription code paths don't
        # need the whisper/torch wheels installed.
        try:
            import whisper  # noqa: WPS433 (intentional local import)
        except ImportError:
            raise ImportError(
                "Local Whisper is not installed. Install the extra "
                "(pip install -e '.[whisper]') or set transcriber: assemblyai."
            )

        target = self._resolve_device()
        try:
            logger.info(
                f"Loading Whisper {self.model_name} model "
                f"(device={target or 'auto'})..."
            )
            self.model = whisper.load_model(self.model_name, device=target)
            # whisper exposes .device on the model after load
            self.active_device = str(getattr(self.model, "device", target or "auto"))
            logger.info(f"Whisper model loaded successfully on {self.active_device}")
            return
        except Exception as exc:  # noqa: BLE001 - we want to handle anything torch throws
            if target == "cpu" or not _looks_like_cuda_failure(exc):
                logger.error(f"Whisper model load failed: {exc}", exc_info=True)
                raise

            logger.warning(
                f"Whisper failed to load on {target or 'auto'} ({exc}). "
                "Falling back to CPU."
            )
            try:
                self.model = whisper.load_model(self.model_name, device="cpu")
                self.active_device = "cpu"
                logger.info("Whisper model loaded successfully on cpu (after CUDA failure)")
            except Exception as cpu_exc:
                logger.error(f"CPU fallback also failed: {cpu_exc}", exc_info=True)
                raise

    def transcribe(
        self,
        audio_path: str,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> TranscriptResult:
        """Transcribe an audio file."""
        logger.info(f"Starting transcription: {audio_path}")
        self.load_model()

        audio_file = Path(audio_path)
        if not audio_file.exists():
            logger.error(f"Audio file not found: {audio_file}")
            raise FileNotFoundError(f"Audio file not found: {audio_file}")

        file_size_mb = audio_file.stat().st_size / (1024 * 1024)
        logger.info(f"Transcribing {audio_file.name} ({file_size_mb:.1f} MB)...")

        if self.model is None:
            logger.error("Model not loaded")
            raise RuntimeError("Model not loaded")

        # fp16 only makes sense on CUDA. Forcing fp16=False on CPU avoids
        # noisy "FP16 is not supported on CPU; using FP32 instead" warnings
        # and a small perf hit from Whisper trying anyway.
        use_fp16 = self.active_device is not None and self.active_device.startswith("cuda")

        result = self.model.transcribe(
            str(audio_file),
            language=None,
            task="transcribe",
            verbose=False,
            fp16=use_fp16,
        )

        segments = [
            TranscriptSegment(
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
            )
            for seg in result["segments"]
        ]

        duration = segments[-1].end if segments else 0.0

        logger.info(
            f"Transcription complete: {len(segments)} segments, "
            f"{duration:.1f}s duration, language: {result.get('language', 'unknown')}"
        )

        return TranscriptResult(
            text=result["text"].strip(),
            segments=segments,
            language=result.get("language", "unknown"),
            duration=duration,
        )

    def format_transcript_with_timestamps(self, result: TranscriptResult) -> str:
        """Format transcript with timestamps for each segment."""
        return format_segments(result.segments)

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Format seconds as HH:MM:SS."""
        return format_timestamp(seconds)

    def describe(self) -> str:
        return f"Whisper {self.model_name}"


class AssemblyAIError(RuntimeError):
    """AssemblyAI rejected a request or failed the transcription.

    ``status_code`` is the HTTP status when there was one. ``transient`` says
    whether trying the same thing again later can succeed; None leaves that to
    the status code. ``remote_failed`` means AssemblyAI accepted the job and
    then reported it failed, so the transcript id is spent.
    """

    def __init__(self, message: str, status_code: Optional[int] = None,
                 transient: Optional[bool] = None, remote_failed: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.transient = transient
        self.remote_failed = remote_failed


class AssemblyAITranscriber:
    """Transcribe audio files with AssemblyAI, with speaker labels.

    Same interface as :class:`WhisperTranscriber`. The recording is uploaded,
    transcribed server-side and polled for. Nothing is cached locally beyond
    the returned text.
    """

    BASE_URL = "https://api.assemblyai.com"
    # universal-3-5-pro covers 18 languages; universal-2 is the fallback the
    # API routes to for anything else, so language detection never dead-ends.
    SPEECH_MODELS = ["universal-3-5-pro", "universal-2"]
    POLL_INTERVAL = 3.0
    # A multi-hour meeting still finishes well inside this; it only exists so
    # a stuck job cannot hang the processing worker forever.
    TIMEOUT = 60 * 60

    def __init__(self, api_key: Optional[str] = None, session=None):
        # A missing key is reported when transcribing, not here: the app builds
        # its transcriber at startup, and a missing key must not stop it from
        # opening (settings, old notes and recording all still work).
        self.api_key = api_key or os.getenv("ASSEMBLYAI_API_KEY") or ""
        if session is None:
            try:
                import requests  # noqa: WPS433
            except ImportError:
                raise ImportError("requests is not installed. Run: pip install -e '.[assemblyai]'")
            session = requests.Session()
        self.session = session
        # The key goes in verbatim: AssemblyAI rejects a "Bearer " prefix.
        self.session.headers.update({"authorization": self.api_key})

    def describe(self) -> str:
        return "AssemblyAI"

    def load_model(self) -> None:
        """Nothing to load; kept so callers can treat both transcribers alike."""

    def _check(self, response, action: str) -> dict:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            detail = payload.get("error") or response.text[:200]
            raise AssemblyAIError(f"AssemblyAI {action} failed ({response.status_code}): {detail}",
                                  status_code=response.status_code)
        return payload

    # AssemblyAI works on 16 kHz mono speech. The recorder writes 48 kHz PCM,
    # ~11 MB a minute, and a 34-minute meeting (377 MB) had its upload cut off
    # mid-TLS where 198 MB went through. FLAC at 16 kHz mono is lossless for
    # what the model uses and roughly a tenth of the size.
    UPLOAD_ATTEMPTS = 3

    def _compress(self, audio_file: Path, scratch: Path) -> Path:
        """A 16 kHz mono FLAC copy for upload; the original if ffmpeg can't make one."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            logger.warning("ffmpeg not found; uploading the original recording uncompressed")
            return audio_file
        target = scratch / f"{audio_file.stem}.flac"
        try:
            subprocess.run(
                [ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", str(audio_file),
                 "-ac", "1", "-ar", "16000", "-c:a", "flac", str(target)],
                check=True, capture_output=True, timeout=600,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            detail = getattr(exc, "stderr", b"") or b""
            logger.warning(f"Could not compress for upload ({exc} {detail[:200]!r}); uploading the original")
            return audio_file
        return target

    def _upload(self, upload_file: Path) -> dict:
        """POST the file, retrying a dropped connection (the file is re-opened each time)."""
        size_mb = upload_file.stat().st_size / (1024 * 1024)
        for attempt in range(1, self.UPLOAD_ATTEMPTS + 1):
            logger.info(f"Uploading {upload_file.name} ({size_mb:.1f} MB) to AssemblyAI, attempt {attempt}...")
            try:
                with upload_file.open("rb") as stream:
                    response = self.session.post(f"{self.BASE_URL}/v2/upload", data=stream, timeout=600)
            except OSError as exc:  # requests' ConnectionError/SSLError derive from OSError
                if attempt == self.UPLOAD_ATTEMPTS:
                    raise AssemblyAIError(f"AssemblyAI upload failed after {attempt} attempts: {exc}",
                                          transient=True) from exc
                logger.warning(f"Upload attempt {attempt} failed: {exc}")
                time.sleep(2 * attempt)
                continue
            return self._check(response, "upload")
        raise AssertionError("unreachable")

    def transcribe(
        self,
        audio_path: str,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> TranscriptResult:
        """Upload, transcribe with speaker labels, and wait for the result."""
        return self.wait(self.submit(audio_path))

    def submit(self, audio_path: str) -> str:
        """Compress, upload and request a transcript. Returns its id.

        Split from wait() so a caller can persist the id before polling: a
        retry or a restart then resumes the same transcript instead of
        uploading the meeting again.
        """
        if not self.api_key:
            raise ValueError("AssemblyAI API key required. Set ASSEMBLYAI_API_KEY environment variable.")
        audio_file = Path(audio_path)
        if not audio_file.exists():
            logger.error(f"Audio file not found: {audio_file}")
            raise FileNotFoundError(f"Audio file not found: {audio_file}")

        with tempfile.TemporaryDirectory(prefix="omascribe-upload-") as scratch:
            upload_file = self._compress(audio_file, Path(scratch))
            upload = self._upload(upload_file)

        job = self._check(
            self.session.post(
                f"{self.BASE_URL}/v2/transcript",
                json={
                    "audio_url": upload["upload_url"],
                    "speech_models": self.SPEECH_MODELS,
                    "speaker_labels": True,
                    "language_detection": True,
                },
                timeout=60,
            ),
            "transcript request",
        )
        transcript_id = job["id"]
        logger.info(f"AssemblyAI transcript {transcript_id} queued")
        return transcript_id

    def wait(self, transcript_id: str) -> TranscriptResult:
        """Poll a submitted transcript until it completes, then build the result."""
        if not self.api_key:
            raise ValueError("AssemblyAI API key required. Set ASSEMBLYAI_API_KEY environment variable.")
        logger.info(f"Waiting for AssemblyAI transcript {transcript_id}")
        deadline = time.monotonic() + self.TIMEOUT
        while True:
            result = self._check(
                self.session.get(f"{self.BASE_URL}/v2/transcript/{transcript_id}", timeout=60),
                "transcript poll",
            )
            status = result.get("status")
            if status == "completed":
                break
            if status == "error":
                raise AssemblyAIError(f"AssemblyAI transcription failed: {result.get('error', 'unknown error')}",
                                      transient=False, remote_failed=True)
            if time.monotonic() > deadline:
                raise AssemblyAIError(f"AssemblyAI transcript {transcript_id} still {status} after {self.TIMEOUT}s",
                                      transient=True)
            time.sleep(self.POLL_INTERVAL)

        # Utterances are the diarised turns; words/segments without speakers
        # would lose exactly what we came here for. Times are milliseconds.
        segments = [
            TranscriptSegment(
                start=u["start"] / 1000,
                end=u["end"] / 1000,
                text=(u.get("text") or "").strip(),
                speaker=u.get("speaker"),
            )
            for u in (result.get("utterances") or [])
        ]
        text = (result.get("text") or "").strip()
        if not segments and text:
            segments = [TranscriptSegment(start=0.0, end=float(result.get("audio_duration") or 0), text=text)]

        duration = float(result.get("audio_duration") or (segments[-1].end if segments else 0.0))
        language = result.get("language_code") or "unknown"
        speakers = len({seg.speaker for seg in segments if seg.speaker})
        logger.info(
            f"Transcription complete: {len(segments)} utterances, {speakers} speakers, "
            f"{duration:.1f}s, language: {language}, model: {result.get('speech_model_used', '?')}"
        )
        return TranscriptResult(text=text, segments=segments, language=language, duration=duration)

    def format_transcript_with_timestamps(self, result: TranscriptResult) -> str:
        return format_segments(result.segments)


def build_transcriber(config) -> "WhisperTranscriber | AssemblyAITranscriber":
    """Construct the transcriber the config asks for."""
    if getattr(config, "transcriber", "whisper") == "assemblyai":
        return AssemblyAITranscriber(api_key=config.assemblyai_api_key or None)
    return WhisperTranscriber(config.whisper_model, device=config.whisper_device)

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python transcriber.py <audio_file>")
        sys.exit(1)

    transcriber = WhisperTranscriber()
    result = transcriber.transcribe(sys.argv[1])

    print(f"\nLanguage: {result.language}")
    print(f"Duration: {result.duration:.1f}s")
    print(f"\nTranscript:\n{result.text}")
    print(f"\nWith timestamps:\n{transcriber.format_transcript_with_timestamps(result)}")
