from __future__ import annotations

import os
from pathlib import Path

import pytest

from voice_console.audio import OwnedAudioStore
from voice_console.config import VoiceConfig
from voice_console.protocol import VoiceProtocolError, validate_hello, validate_turn_id
from voice_console.providers import FakeSttProvider, FakeTtsProvider
from voice_console.voice_session import RecordingSession


def test_turn_id_validation_requires_safe_charset():
    assert validate_turn_id("vt_123:4.5-6") == "vt_123:4.5-6"
    with pytest.raises(VoiceProtocolError):
        validate_turn_id("bad id!")
    with pytest.raises(VoiceProtocolError):
        validate_turn_id("x" * 129)
    with pytest.raises(VoiceProtocolError):
        validate_turn_id(None)


def test_hello_validation():
    validate_hello({"type": "hello", "version": 1, "mode": "push_to_talk", "input_format": "pcm16", "input_sample_rate": 16000})
    with pytest.raises(VoiceProtocolError) as exc:
        validate_hello({"type": "hello", "version": 999})
    assert exc.value.code == "unsupported_version"
    with pytest.raises(VoiceProtocolError) as exc2:
        validate_hello({"type": "hello", "input_sample_rate": 44100})
    assert exc2.value.code == "unsupported_sample_rate"


def test_recording_stop_requires_matching_turn_and_clears_buffer():
    session = RecordingSession(VoiceConfig(max_recording_seconds=1, max_buffer_mb=1))
    session.start_recording("turn-1")
    session.add_audio(b"\x00\x00" * 10)
    with pytest.raises(VoiceProtocolError) as missing:
        session.stop_recording("")
    assert missing.value.code == "bad_turn_id"
    with pytest.raises(VoiceProtocolError) as mismatch:
        session.stop_recording("turn-2")
    assert mismatch.value.code == "turn_mismatch"
    active, pcm = session.stop_recording("turn-1")
    assert active == "turn-1"
    assert pcm == b"\x00\x00" * 10
    assert session.buffer_size == 0
    assert session.turn_id is None


def test_recording_size_and_wall_caps():
    session = RecordingSession(VoiceConfig(max_recording_seconds=1, max_buffer_mb=1, max_recording_wall_seconds=1))
    session.start_recording("big")
    with pytest.raises(VoiceProtocolError) as exc:
        session.add_audio(b"\x00" * 40000)
    assert exc.value.code == "recording_too_large"
    session.start_recording("slow")
    session._recording_started_at -= 5
    with pytest.raises(VoiceProtocolError) as exc2:
        session.stop_recording("slow")
    assert exc2.value.code == "recording_timeout"


def test_owned_audio_store_rejects_unowned_symlink_and_oversize(tmp_path):
    store = OwnedAudioStore(tmp_path)
    owned = store.write_bytes(b"abc", ".mp3")
    assert store.validate_for_stream(owned, max_bytes=10) == owned.resolve()
    with pytest.raises(VoiceProtocolError) as unowned:
        store.validate_for_stream(tmp_path / "other.mp3", max_bytes=10)
    assert unowned.value.code == "tts_failed"
    big = store.write_bytes(b"x" * 20, ".mp3")
    with pytest.raises(VoiceProtocolError) as too_big:
        store.validate_for_stream(big, max_bytes=10)
    assert too_big.value.code == "tts_too_large"
    target = store.write_bytes(b"ok", ".wav")
    link = store.reserve_path(".wav")
    link.unlink()
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")
    with pytest.raises(VoiceProtocolError):
        store.validate_for_stream(link, max_bytes=100)


@pytest.mark.asyncio
async def test_fake_providers_roundtrip(tmp_path):
    cfg = VoiceConfig(fake_transcript="hello provider")
    store = OwnedAudioStore(tmp_path)
    transcript = await FakeSttProvider().transcribe(b"\x00\x00", config=cfg, store=store)
    assert transcript.text == "hello provider"
    audio = await FakeTtsProvider().synthesize("hello", config=cfg, store=store)
    path = store.validate_for_stream(audio.path, max_bytes=cfg.max_tts_audio_bytes)
    assert path.exists()
    assert audio.mime == "audio/wav"



def test_expire_if_active_resets_silent_recording():
    session = RecordingSession(VoiceConfig(max_recording_wall_seconds=1))
    session.start_recording("silent")
    assert session.expire_if_active("wrong") is False
    assert session.buffer_size == 0
    assert session.expire_if_active("silent") is True
    with pytest.raises(VoiceProtocolError) as exc:
        session.stop_recording("silent")
    assert exc.value.code == "bad_state"
