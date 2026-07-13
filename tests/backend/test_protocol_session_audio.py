from __future__ import annotations

import os

import pytest
from voice_console.audio import OwnedAudioStore
from voice_console.config import VoiceConfig
from voice_console.protocol import (
    VoiceProtocolError,
    validate_hello,
    validate_input_text,
    validate_turn_id,
)
from voice_console.providers import FakeSttProvider, FakeTtsProvider
from voice_console.voice_filters import (
    filter_transcript,
    prepare_tts_sentences,
    validate_spoken_audio,
)
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
    validate_hello(
        {
            "type": "hello",
            "version": 1,
            "mode": "push_to_talk",
            "input_format": "pcm16",
            "input_sample_rate": 16000,
        }
    )
    with pytest.raises(VoiceProtocolError) as exc:
        validate_hello({"type": "hello", "version": 999})
    assert exc.value.code == "unsupported_version"
    with pytest.raises(VoiceProtocolError) as exc2:
        validate_hello({"type": "hello", "input_sample_rate": 44100})
    assert exc2.value.code == "unsupported_sample_rate"


def test_shared_input_validator_trims_and_bounds_text():
    assert validate_input_text("  hello  ", max_chars=10) == "hello"
    with pytest.raises(VoiceProtocolError, match="required"):
        validate_input_text("   ", max_chars=10)
    with pytest.raises(VoiceProtocolError, match="exceeds"):
        validate_input_text("too long", max_chars=3)


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


def test_recording_discard_clears_audio_without_returning_it():
    session = RecordingSession(VoiceConfig())
    session.start_recording("discard-me")
    session.add_audio(b"\xe8\x03" * 4800)
    assert session.discard_recording("discard-me") is True
    assert session.buffer_size == 0
    with pytest.raises(VoiceProtocolError) as exc:
        session.stop_recording("discard-me")
    assert exc.value.code == "bad_state"


def test_voice_filters_reject_silence_and_known_hallucinations():
    config = VoiceConfig()
    with pytest.raises(VoiceProtocolError, match="No speech"):
        validate_spoken_audio(b"\x00\x00" * 4800, config)
    validate_spoken_audio(b"\xe8\x03" * 4800, config)
    with pytest.raises(VoiceProtocolError, match="reliable speech"):
        filter_transcript("Thanks for watching!")
    assert filter_transcript("  Give JobHunter a status check. ") == "Give JobHunter a status check."


def test_tts_preparation_strips_private_and_markdown_content_and_bounds_chunks():
    chunks = prepare_tts_sentences(
        "<think>secret reasoning</think> # Result\nUse **this answer**. [Docs](https://example.test).",
        total_cap=200,
        sentence_cap=80,
    )
    spoken = " ".join(chunks)
    assert "secret" not in spoken
    assert "**" not in spoken
    assert "https://" not in spoken
    assert all(len(chunk) <= 80 for chunk in chunks)


def test_recording_size_and_wall_caps():
    session = RecordingSession(
        VoiceConfig(max_recording_seconds=1, max_buffer_mb=1, max_recording_wall_seconds=1)
    )
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
