"""Voiceover clean-up: trim the ends, cap long pauses between sentences, optional tempo.

TTS voices (and people) often leave 1-2 s gaps between sentences, which drags on
screen. Clips are processed into .cache/voiceover/ and the originals are untouched.
"""

import hashlib
import subprocess
import wave

import numpy as np

from .style import REPO_ROOT

CACHE = REPO_ROOT / ".cache" / "voiceover"
SR = 48000


def _decode(path, tempo=1.0):
    filters = ["-af", f"atempo={tempo}"] if tempo != 1.0 else []
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), *filters, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def tighten(path, max_pause=0.45, tempo=1.0, threshold_db=-40, lead=0.05, tail=0.15):
    """Return a cached WAV of `path` with pauses capped at max_pause seconds (0 = leave
    pauses alone) and the pace scaled by `tempo` (pitch is preserved)."""
    if not max_pause and tempo == 1.0:
        return path
    max_pause = max_pause or 1e9
    key = hashlib.sha1(f"{path.resolve()}|{path.stat().st_mtime_ns}|{max_pause}|{tempo}|{threshold_db}".encode()).hexdigest()[:12]
    out = CACHE / f"{path.stem}-{key}.wav"
    if out.exists():
        return out
    x = _decode(path, tempo)
    win = int(0.02 * SR)
    n = len(x) // win
    if n == 0:
        return path
    rms = np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(1) + 1e-12)
    loud = 20 * np.log10(rms / max(rms.max(), 1e-9)) > threshold_db
    if not loud.any():
        return path
    first, last = np.argmax(loud), n - 1 - np.argmax(loud[::-1])
    keep = []
    i = first
    max_win = int(max_pause / 0.02)
    while i <= last:
        if loud[i]:
            keep.append((i, i + 1))
            i += 1
            continue
        j = i
        while j <= last and not loud[j]:
            j += 1
        gap = j - i
        if gap > max_win:  # keep the edges of the pause, drop the middle
            keep.append((i, i + max_win // 2))
            keep.append((j - (max_win - max_win // 2), j))
        else:
            keep.append((i, j))
        i = j
    pieces, fade = [], int(0.01 * SR)
    lead_n, tail_n = int(lead * SR), int(tail * SR)
    start = max(0, first * win - lead_n)
    merged = []
    for a, b in keep:
        if merged and merged[-1][1] == a:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    for k, (a, b) in enumerate(merged):
        s = start if k == 0 else a * win
        e = min(len(x), b * win + (tail_n if k == len(merged) - 1 else 0))
        seg = x[s:e].copy()
        if len(seg) > 2 * fade:
            seg[:fade] *= np.linspace(0, 1, fade)
            seg[-fade:] *= np.linspace(1, 0, fade)
        pieces.append(seg)
    y = np.concatenate(pieces)
    CACHE.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(y, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return out
