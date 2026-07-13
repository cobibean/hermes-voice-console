from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import StrEnum

from .config import VoiceConfig
from .protocol import VoiceProtocolError, validate_turn_id

MAX_CANCELLED_TURNS = 256


class RecordingState(StrEnum):
    IDLE = "idle"
    RECORDING = "recording"


@dataclass
class RecordingSession:
    config: VoiceConfig
    state: RecordingState = RecordingState.IDLE
    turn_id: str | None = None
    _buf: bytearray = field(default_factory=bytearray)
    _recording_started_at: float = 0.0
    _cancelled: OrderedDict[str, float] = field(default_factory=OrderedDict)

    @property
    def buffer_size(self) -> int:
        return len(self._buf)

    def start_recording(self, turn_id: str) -> None:
        if self.state is not RecordingState.IDLE:
            raise VoiceProtocolError("bad_state", "already recording")
        tid = validate_turn_id(turn_id, required=True)
        self.state = RecordingState.RECORDING
        self.turn_id = tid
        self._buf = bytearray()
        self._recording_started_at = time.monotonic()

    def _expired(self) -> bool:
        return (
            time.monotonic() - self._recording_started_at > self.config.max_recording_wall_seconds
        )

    def _reset(self) -> None:
        self.state = RecordingState.IDLE
        self.turn_id = None
        self._buf = bytearray()

    def add_audio(self, chunk: bytes) -> None:
        if self.state is not RecordingState.RECORDING:
            raise VoiceProtocolError(
                "audio_outside_recording", "binary audio frame received outside RECORDING state"
            )
        if self._expired():
            self._reset()
            raise VoiceProtocolError(
                "recording_timeout", "recording exceeded max wall-clock duration"
            )
        if len(self._buf) + len(chunk) > self.config.max_recording_bytes:
            self._reset()
            raise VoiceProtocolError(
                "recording_too_large", "recording exceeded max buffer / duration limit"
            )
        self._buf.extend(chunk)

    def stop_recording(self, turn_id: str) -> tuple[str, bytes]:
        if self.state is not RecordingState.RECORDING:
            raise VoiceProtocolError("bad_state", f"cannot stop recording from {self.state.value}")
        tid = validate_turn_id(turn_id, required=True)
        if tid != self.turn_id:
            raise VoiceProtocolError(
                "turn_mismatch", "recording.stop turn_id does not match active recording"
            )
        if self._expired():
            self._reset()
            raise VoiceProtocolError(
                "recording_timeout", "recording exceeded max wall-clock duration"
            )
        pcm = bytes(self._buf)
        active = self.turn_id or tid
        self._reset()
        if not pcm:
            raise VoiceProtocolError("empty_recording", "no audio captured")
        return active, pcm

    def expire_if_active(self, turn_id: str) -> bool:
        if self.state is RecordingState.RECORDING and self.turn_id == turn_id:
            self._reset()
            return True
        return False

    def discard_recording(self, turn_id: str) -> bool:
        """Discard an interrupted gesture without ever submitting its audio."""
        tid = validate_turn_id(turn_id, required=True)
        if self.state is not RecordingState.RECORDING or self.turn_id != tid:
            return False
        self._reset()
        return True

    def cancel(self, turn_id: str | None) -> None:
        tid = validate_turn_id(turn_id or "", required=False)
        if not tid:
            return
        self._cancelled[tid] = time.monotonic()
        self._cancelled.move_to_end(tid)
        while len(self._cancelled) > MAX_CANCELLED_TURNS:
            self._cancelled.popitem(last=False)

    def is_cancelled(self, turn_id: str) -> bool:
        return turn_id in self._cancelled

    def forget_cancel(self, turn_id: str) -> None:
        self._cancelled.pop(turn_id, None)
