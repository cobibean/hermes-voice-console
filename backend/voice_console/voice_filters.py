from __future__ import annotations

import math
import re
from array import array

from .config import VoiceConfig
from .protocol import VoiceProtocolError

_HALLUCINATIONS = {
    "thanks for watching",
    "thank you for watching",
    "please subscribe",
    "like and subscribe",
    "subtitles by the amara org community",
}


def validate_spoken_audio(pcm16: bytes, config: VoiceConfig) -> None:
    duration = len(pcm16) / (config.sample_rate * 2)
    if duration < config.min_recording_seconds:
        raise VoiceProtocolError("no_speech", "Recording was too short; hold to talk and try again")
    samples = array("h")
    samples.frombytes(pcm16)
    if not samples:
        raise VoiceProtocolError("no_speech", "No speech was detected")
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
    if rms < config.min_recording_rms:
        raise VoiceProtocolError("no_speech", "No speech was detected; try again closer to the microphone")


def filter_transcript(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    normalized = re.sub(r"[^a-z0-9 ]", "", cleaned.lower()).strip()
    if not cleaned or normalized in _HALLUCINATIONS or normalized.startswith("www "):
        raise VoiceProtocolError("no_speech", "No reliable speech was detected; try again")
    return cleaned


def prepare_tts_sentences(text: str, *, total_cap: int, sentence_cap: int) -> list[str]:
    text = re.sub(r"<think\b[^>]*>.*?</think>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"```.*?```", " Code omitted. ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^]]*)]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}(?:#{1,6}|>|[-*+] |\d+[.)] )", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_~]", "", text)
    text = re.sub(r"\s+", " ", text).strip()[:total_cap]
    if not text:
        return []
    rough = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    for sentence in rough:
        remaining = sentence.strip()
        while len(remaining) > sentence_cap:
            split_at = remaining.rfind(" ", 0, sentence_cap + 1)
            if split_at < sentence_cap // 2:
                split_at = sentence_cap
            chunks.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()
        if remaining:
            chunks.append(remaining)
    return chunks
