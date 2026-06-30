from __future__ import annotations

from voice_console.fake_e2e import run_fake_e2e


def test_fake_e2e_full_voice_turn():
    result = run_fake_e2e()
    assert result["ok"] is True
    assert result["binary_chunks"] >= 1
    assert "agent.completed" in result["frames"]
    assert "tts.end" in result["frames"]
