from __future__ import annotations

import os
import stat
import tempfile
import wave
from pathlib import Path

from .protocol import VoiceProtocolError

SAMPLE_RATE = 16_000
SAMPLE_WIDTH = 2
CHANNELS = 1
AUDIO_MIME_BY_EXT = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
}


def mime_for_path(path: str | Path) -> str:
    return AUDIO_MIME_BY_EXT.get(Path(path).suffix.lower(), "application/octet-stream")


class OwnedAudioStore:
    """Console-owned temp/cache file manager for STT/TTS audio.

    Providers reserve output paths through this manager. Streaming/deletion only
    operates on files inside the manager directory that were reserved by this
    process, preventing arbitrary provider-returned paths from being unlinked.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir or tempfile.gettempdir()) / "hermes-voice-console-audio"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.base_dir, 0o700)
        except OSError:  # pragma: no cover - filesystem-specific
            pass
        self._owned: set[Path] = set()

    def reserve_path(self, suffix: str) -> Path:
        suffix = suffix if suffix.startswith(".") else f".{suffix}"
        fd, raw = tempfile.mkstemp(prefix="hvc_", suffix=suffix, dir=self.base_dir)
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        os.close(fd)
        path = Path(raw).resolve()
        self._owned.add(path)
        return path

    def write_bytes(self, data: bytes, suffix: str) -> Path:
        path = self.reserve_path(suffix)
        path.write_bytes(data)
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover
            pass
        return path

    def write_wav(self, pcm16: bytes) -> Path:
        path = self.reserve_path(".wav")
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(CHANNELS)
            wav.setsampwidth(SAMPLE_WIDTH)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm16)
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover
            pass
        return path

    def validate_for_stream(self, path: str | Path, *, max_bytes: int) -> Path:
        raw_path = Path(path)
        owned_path = raw_path.resolve(strict=False)
        if owned_path not in self._owned:
            raise VoiceProtocolError("tts_failed", "TTS audio path is not owned by the console")
        try:
            owned_path.relative_to(self.base_dir.resolve())
        except ValueError as exc:
            raise VoiceProtocolError("tts_failed", "TTS audio path is outside console temp dir") from exc
        try:
            # Use lstat on the original path before following symlinks. A reserved
            # path that is later replaced with a symlink must fail even if the
            # symlink target is another owned regular file.
            st = os.lstat(raw_path)
        except OSError as exc:
            raise VoiceProtocolError("tts_failed", "TTS audio file is not accessible") from exc
        if stat.S_ISLNK(st.st_mode):
            raise VoiceProtocolError("tts_failed", "TTS audio path is a symlink")
        if not stat.S_ISREG(st.st_mode):
            raise VoiceProtocolError("tts_failed", "TTS audio path is not a regular file")
        if st.st_size > max_bytes:
            raise VoiceProtocolError("tts_too_large", f"TTS audio exceeds {max_bytes // (1024 * 1024)}MB cap")
        return owned_path

    def cleanup(self, path: str | Path | None, *, retain: bool = False) -> None:
        if not path:
            return
        p = Path(path).resolve()
        if retain:
            return
        if p not in self._owned:
            return
        try:
            p.relative_to(self.base_dir.resolve())
        except ValueError:
            return
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        finally:
            self._owned.discard(p)
