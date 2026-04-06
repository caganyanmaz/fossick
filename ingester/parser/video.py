from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

from ingester.parser.base import BaseParser, ParsedDocument

_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm", "flv"}
_WHISPER_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"


class VideoParser(BaseParser):
    def __init__(self, keyframes: int = 10) -> None:
        self._keyframes = keyframes

    def can_parse(self, path: str) -> bool:
        return Path(path).suffix.lstrip(".").lower() in _EXTENSIONS

    def parse(self, path: str) -> ParsedDocument:
        p = Path(path)
        filetype = p.suffix.lstrip(".").lower()
        stat = p.stat()

        base_meta: dict[str, Any] = {
            "filename": p.name,
            "path": str(p),
            "filetype": filetype,
            "size_bytes": stat.st_size,
            "mtime": stat.st_mtime,
            "duration_seconds": 0.0,
            "frame_paths": [],
            "transcript_chars": 0,
        }

        if not shutil.which("ffmpeg"):
            logger.warning("ffmpeg not found; returning metadata only for {}", path)
            return ParsedDocument(text="", metadata=base_meta, source_path=str(p))

        with tempfile.TemporaryDirectory() as tmpdir:
            duration = self._get_duration(str(p))
            base_meta["duration_seconds"] = duration

            transcript = self._extract_transcript(str(p), tmpdir)
            base_meta["transcript_chars"] = len(transcript)

            frame_paths = self._extract_keyframes(str(p), tmpdir, duration)
            base_meta["frame_paths"] = frame_paths

        return ParsedDocument(text=transcript, metadata=base_meta, source_path=str(p))

    def _get_duration(self, path: str) -> float:
        if not shutil.which("ffprobe"):
            return 0.0
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_streams",
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            data = json.loads(result.stdout)
            for stream in data.get("streams", []):
                dur = stream.get("duration")
                if dur:
                    return float(dur)
        except Exception as exc:
            logger.warning("ffprobe failed for {}: {}", path, exc)
        return 0.0

    def _extract_transcript(self, path: str, tmpdir: str) -> str:
        api_key = os.environ.get("WHISPER_API_KEY") or os.environ.get("LLM_API_KEY") or ""
        if not api_key:
            logger.warning("No Whisper API key found; skipping transcription for {}", path)
            return ""

        wav_path = os.path.join(tmpdir, "audio.wav")
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", path,
                    "-vn", "-ar", "16000", "-ac", "1",
                    "-f", "wav", wav_path,
                ],
                capture_output=True,
                timeout=120,
                check=True,
            )
        except Exception as exc:
            logger.warning("ffmpeg audio extraction failed for {}: {}", path, exc)
            return ""

        try:
            import httpx

            with open(wav_path, "rb") as f:
                wav_bytes = f.read()

            response = httpx.post(
                _WHISPER_ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data={"model": "whisper-1"},
                timeout=120.0,
            )
            response.raise_for_status()
            return str(response.json().get("text", ""))
        except Exception as exc:
            logger.warning("Whisper API call failed for {}: {}", path, exc)
            return ""

    def _extract_keyframes(self, path: str, tmpdir: str, duration: float) -> list[str]:
        if duration <= 0:
            return []
        interval = max(1.0, duration / self._keyframes)
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", path,
                    "-vf", f"fps=1/{interval}",
                    os.path.join(tmpdir, "frame_%04d.jpg"),
                ],
                capture_output=True,
                timeout=120,
                check=True,
            )
        except Exception as exc:
            logger.warning("ffmpeg keyframe extraction failed for {}: {}", path, exc)
            return []

        frames = sorted(
            str(f) for f in Path(tmpdir).glob("frame_*.jpg")
        )
        return frames
