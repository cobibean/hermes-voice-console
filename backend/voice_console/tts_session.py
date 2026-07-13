from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .audio import OwnedAudioStore
from .config import VoiceConfig
from .protocol import VoiceProtocolError, sanitize_provider_error
from .providers import ProviderUnavailable, TtsProvider
from .voice_filters import prepare_tts_sentences
from .voice_session import RecordingSession

log = logging.getLogger(__name__)

SendJson = Callable[[dict[str, Any]], Awaitable[None]]
SendBytes = Callable[[bytes], Awaitable[None]]
SendError = Callable[[VoiceProtocolError], Awaitable[None]]


class TtsSession:
    """Own synthesis, playback streaming, and cancellation for one socket."""

    def __init__(
        self,
        *,
        config: VoiceConfig,
        provider: TtsProvider,
        audio_store: OwnedAudioStore,
        recording_session: RecordingSession,
        send_json: SendJson,
        send_bytes: SendBytes,
        send_error: SendError,
    ) -> None:
        self.config = config
        self.provider = provider
        self.audio_store = audio_store
        self.recording_session = recording_session
        self.send_json = send_json
        self.send_bytes = send_bytes
        self.send_error = send_error
        self.task: asyncio.Task[None] | None = None

    def start(self, turn_id: str, text: str) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = asyncio.create_task(self._synthesize_and_send(turn_id, text))

    async def cancel(self, turn_id: str) -> None:
        self.recording_session.cancel(turn_id)
        if self.task and not self.task.done():
            self.task.cancel()
        await self.send_json({"type": "tts.cancelled", "turn_id": turn_id})

    def close(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()

    async def _synthesize_and_send(self, turn_id: str, text: str) -> None:
        if not text.strip() or self.recording_session.is_cancelled(turn_id):
            return
        sentences = prepare_tts_sentences(
            text,
            total_cap=self.config.max_tts_text_chars,
            sentence_cap=self.config.tts_sentence_max_chars,
        )
        if not sentences:
            return

        try:
            for chunk_index, sentence in enumerate(sentences):
                if self.recording_session.is_cancelled(turn_id):
                    return
                audio_path = None
                try:
                    audio = await asyncio.wait_for(
                        self.provider.synthesize(
                            sentence,
                            config=self.config,
                            store=self.audio_store,
                        ),
                        timeout=self.config.tts_chunk_timeout_seconds,
                    )
                    audio_path = audio.path
                    path = self.audio_store.validate_for_stream(
                        audio.path,
                        max_bytes=self.config.max_tts_audio_bytes,
                    )
                    if self.recording_session.is_cancelled(turn_id):
                        return
                    await self.send_json(
                        {
                            "type": "tts.start",
                            "turn_id": turn_id,
                            "chunk_index": chunk_index,
                            "mime": audio.mime,
                            "provider": audio.provider,
                        }
                    )
                    with path.open("rb") as file_handle:
                        while not self.recording_session.is_cancelled(turn_id):
                            chunk = file_handle.read(32 * 1024)
                            if not chunk:
                                break
                            await self.send_bytes(chunk)
                    if not self.recording_session.is_cancelled(turn_id):
                        await self.send_json(
                            {
                                "type": "tts.end",
                                "turn_id": turn_id,
                                "chunk_index": chunk_index,
                            }
                        )
                finally:
                    if audio_path:
                        self.audio_store.cleanup(
                            audio_path,
                            retain=self.config.retain_audio_debug,
                        )
            if not self.recording_session.is_cancelled(turn_id):
                await self.send_json({"type": "tts.complete", "turn_id": turn_id})
        except asyncio.CancelledError:
            self.recording_session.cancel(turn_id)
            raise
        except TimeoutError:
            await self.send_error(VoiceProtocolError("tts_timeout", "Speech synthesis timed out; the text answer is still available"))
        except ProviderUnavailable as exc:
            await self.send_error(
                VoiceProtocolError("tts_unavailable", sanitize_provider_error(str(exc)))
            )
        except VoiceProtocolError as exc:
            await self.send_error(exc)
        except Exception:
            log.exception("unexpected TTS failure")
            await self.send_error(VoiceProtocolError("internal_error", "internal voice error"))
        finally:
            self.recording_session.forget_cancel(turn_id)
