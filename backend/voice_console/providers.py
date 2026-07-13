from __future__ import annotations

import asyncio
import json
import os
import wave
from dataclasses import dataclass
from pathlib import Path

import httpx

from .audio import OwnedAudioStore, mime_for_path
from .config import VoiceConfig
from .protocol import VoiceProtocolError, sanitize_provider_error


class ProviderUnavailable(RuntimeError):
    """Raised when a configured provider lacks credentials/dependencies."""


@dataclass(frozen=True)
class Transcript:
    text: str
    provider: str
    latency_ms: int | None = None


@dataclass(frozen=True)
class SynthesizedAudio:
    path: Path
    mime: str
    provider: str


class SttProvider:
    name = "base"

    async def transcribe(
        self, pcm16: bytes, *, config: VoiceConfig, store: OwnedAudioStore
    ) -> Transcript:
        raise NotImplementedError


class FakeSttProvider(SttProvider):
    name = "fake"

    async def transcribe(
        self, pcm16: bytes, *, config: VoiceConfig, store: OwnedAudioStore
    ) -> Transcript:
        text = os.environ.get("VOICE_CONSOLE_FAKE_TRANSCRIPT") or config.fake_transcript
        return Transcript(text=text, provider=self.name)


class OpenAIWhisperProvider(SttProvider):
    name = "openai"

    async def transcribe(
        self, pcm16: bytes, *, config: VoiceConfig, store: OwnedAudioStore
    ) -> Transcript:
        key = os.environ.get("OPENAI_API_KEY") or os.environ.get("VOICE_TOOLS_OPENAI_KEY")
        if not key:
            raise ProviderUnavailable(
                "OPENAI_API_KEY or VOICE_TOOLS_OPENAI_KEY is required for OpenAI STT"
            )
        wav_path = store.write_wav(pcm16)
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                with wav_path.open("rb") as fh:
                    resp = await client.post(
                        "https://api.openai.com/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {key}"},
                        data={"model": config.openai_stt_model},
                        files={"file": ("recording.wav", fh, "audio/wav")},
                    )
            if resp.status_code >= 400:
                raise VoiceProtocolError("stt_failed", sanitize_provider_error(resp.text))
            data = resp.json()
            return Transcript(text=str(data.get("text") or ""), provider=self.name)
        finally:
            store.cleanup(wav_path, retain=config.retain_audio_debug)


class GroqWhisperProvider(SttProvider):
    name = "groq"

    async def transcribe(
        self, pcm16: bytes, *, config: VoiceConfig, store: OwnedAudioStore
    ) -> Transcript:
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            raise ProviderUnavailable("GROQ_API_KEY is required for Groq STT")
        wav_path = store.write_wav(pcm16)
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                with wav_path.open("rb") as fh:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {key}"},
                        data={"model": config.groq_stt_model},
                        files={"file": ("recording.wav", fh, "audio/wav")},
                    )
            if resp.status_code >= 400:
                raise VoiceProtocolError("stt_failed", sanitize_provider_error(resp.text))
            data = resp.json()
            return Transcript(text=str(data.get("text") or ""), provider=self.name)
        finally:
            store.cleanup(wav_path, retain=config.retain_audio_debug)


class FasterWhisperProvider(SttProvider):
    name = "faster_whisper"

    async def transcribe(
        self, pcm16: bytes, *, config: VoiceConfig, store: OwnedAudioStore
    ) -> Transcript:
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise ProviderUnavailable("Install faster-whisper to use local STT") from exc
        wav_path = store.write_wav(pcm16)
        try:

            def _run() -> str:
                model = WhisperModel(os.environ.get("VOICE_CONSOLE_FASTER_WHISPER_MODEL", "base"))
                segments, _info = model.transcribe(str(wav_path))
                return " ".join(seg.text.strip() for seg in segments).strip()

            return Transcript(text=await asyncio.to_thread(_run), provider=self.name)
        finally:
            store.cleanup(wav_path, retain=config.retain_audio_debug)


class TtsProvider:
    name = "base"

    async def synthesize(
        self, text: str, *, config: VoiceConfig, store: OwnedAudioStore
    ) -> SynthesizedAudio:
        raise NotImplementedError


class FakeTtsProvider(TtsProvider):
    name = "fake"

    async def synthesize(
        self, text: str, *, config: VoiceConfig, store: OwnedAudioStore
    ) -> SynthesizedAudio:
        path = store.reserve_path(".wav")
        # A tiny valid silent WAV. Browsers/tests can decode it; fake E2E only checks frames.
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16_000)
            wav.writeframes(b"\x00\x00" * 1600)
        return SynthesizedAudio(path=path, mime="audio/wav", provider=self.name)


class EdgeTtsProvider(TtsProvider):
    name = "edge"

    async def synthesize(
        self, text: str, *, config: VoiceConfig, store: OwnedAudioStore
    ) -> SynthesizedAudio:
        try:
            import edge_tts  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise ProviderUnavailable("Install edge-tts to use Edge TTS") from exc
        path = store.reserve_path(".mp3")
        try:
            communicate = edge_tts.Communicate(text, config.edge_tts_voice)
            await communicate.save(str(path))
            store.validate_for_stream(path, max_bytes=config.max_tts_audio_bytes)
            return SynthesizedAudio(path=path, mime=mime_for_path(path), provider=self.name)
        except BaseException:
            store.cleanup(path, retain=False)
            raise


class OpenAITtsProvider(TtsProvider):
    name = "openai"

    async def synthesize(
        self, text: str, *, config: VoiceConfig, store: OwnedAudioStore
    ) -> SynthesizedAudio:
        key = os.environ.get("OPENAI_API_KEY") or os.environ.get("VOICE_TOOLS_OPENAI_KEY")
        if not key:
            raise ProviderUnavailable(
                "OPENAI_API_KEY or VOICE_TOOLS_OPENAI_KEY is required for OpenAI TTS"
            )
        path = store.reserve_path(".mp3")
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    content=json.dumps(
                        {
                            "model": config.openai_tts_model,
                            "voice": config.openai_tts_voice,
                            "input": text,
                        }
                    ),
                )
            if resp.status_code >= 400:
                raise VoiceProtocolError("tts_failed", sanitize_provider_error(resp.text))
            if len(resp.content) > config.max_tts_audio_bytes:
                raise VoiceProtocolError(
                    "tts_too_large", f"TTS audio exceeds {config.max_tts_audio_mb}MB cap"
                )
            path.write_bytes(resp.content)
            return SynthesizedAudio(path=path, mime=mime_for_path(path), provider=self.name)
        except BaseException:
            store.cleanup(path, retain=False)
            raise


class ElevenLabsTtsProvider(TtsProvider):
    name = "elevenlabs"

    async def synthesize(
        self, text: str, *, config: VoiceConfig, store: OwnedAudioStore
    ) -> SynthesizedAudio:
        key = os.environ.get("ELEVENLABS_API_KEY")
        voice_id = config.elevenlabs_voice_id or os.environ.get("ELEVENLABS_VOICE_ID")
        if not key or not voice_id:
            raise ProviderUnavailable(
                "ELEVENLABS_API_KEY and elevenlabs_voice_id are required for ElevenLabs TTS"
            )
        path = store.reserve_path(".mp3")
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    headers={
                        "xi-api-key": key,
                        "Content-Type": "application/json",
                        "Accept": "audio/mpeg",
                    },
                    json={"text": text, "model_id": "eleven_multilingual_v2"},
                )
            if resp.status_code >= 400:
                raise VoiceProtocolError("tts_failed", sanitize_provider_error(resp.text))
            if len(resp.content) > config.max_tts_audio_bytes:
                raise VoiceProtocolError(
                    "tts_too_large", f"TTS audio exceeds {config.max_tts_audio_mb}MB cap"
                )
            path.write_bytes(resp.content)
            return SynthesizedAudio(path=path, mime=mime_for_path(path), provider=self.name)
        except BaseException:
            store.cleanup(path, retain=False)
            raise


def make_stt_provider(name: str) -> SttProvider:
    normalized = name.strip().lower()
    if normalized in {"fake", "browser_stub_for_tests"}:
        return FakeSttProvider()
    if normalized in {"openai", "openai_whisper"}:
        return OpenAIWhisperProvider()
    if normalized in {"groq", "groq_whisper"}:
        return GroqWhisperProvider()
    if normalized in {"faster_whisper", "faster_whisper_local", "local"}:
        return FasterWhisperProvider()
    raise ProviderUnavailable(f"unsupported STT provider: {name}")


def make_tts_provider(name: str) -> TtsProvider:
    normalized = name.strip().lower()
    if normalized in {"fake", "browser_stub_for_tests"}:
        return FakeTtsProvider()
    if normalized in {"edge", "edge_tts"}:
        return EdgeTtsProvider()
    if normalized in {"openai", "openai_tts"}:
        return OpenAITtsProvider()
    if normalized in {"elevenlabs", "elevenlabs_tts"}:
        return ElevenLabsTtsProvider()
    raise ProviderUnavailable(f"unsupported TTS provider: {name}")
