#!/usr/bin/env python3
"""Build the channel's reusable brand assets in assets/brand/:

    intro_sting.mp4   2.6 s animated logo sting with sound, played before every episode
    outro_music.m4a   original music that ends every episode (its last outro_seconds play,
                      so the final chord lands on the last frame)

Both are synthesized here (no samples or licensed audio), so the channel owns them.
Run it once; the files are committed and reused by every render. Swap either file
for your own (same name, or point brand.json at it) and every episode picks it up.
"""

import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from roadtrip import style as S  # noqa: E402

BRAND = REPO_ROOT / "assets" / "brand"
SR = 48000


# -- synthesis helpers ---------------------------------------------------------

def note(name):
    names = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
    pitch, octave = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((names[pitch] + 12 * (octave + 1) - 69) / 12)


def env(n, attack, release, sustain=1.0):
    e = np.full(n, sustain)
    a = min(n, int(attack * SR))
    if a:
        e[:a] = np.linspace(0, sustain, a)
    r = min(n - a, int(release * SR))
    if r > 0:
        e[-r:] *= np.linspace(1, 0, r) ** 2
    return e


def lowpass(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):  # one-pole; fine for a few seconds of audio
        acc = (1 - a) * v + a * acc
        y[i] = acc
    return y


def pad(freqs, dur, level=0.12):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for f in freqs:
        for detune in (-0.12, 0.12):
            ff = f * 2 ** (detune / 12)
            # Soft saw from a few harmonics.
            for h in range(1, 7):
                out += np.sin(2 * np.pi * ff * h * t + h) / h ** 1.3
    return out / max(1, len(freqs)) * level * env(n, 0.6, 0.8)


def pluck(f, dur, level=0.22):
    n = int(dur * SR)
    t = np.arange(n) / SR
    tone = sum(np.sin(2 * np.pi * f * h * t) * 0.6 ** (h - 1) for h in range(1, 5))
    return tone * np.exp(-t * 5.5) * level * env(n, 0.004, 0.05)


def bell(f, dur, level=0.18):
    n = int(dur * SR)
    t = np.arange(n) / SR
    tone = (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t * 3)
            + 0.3 * np.sin(2 * np.pi * f * 5.4 * t) * np.exp(-t * 6))
    return tone * np.exp(-t * 1.8) * level * env(n, 0.003, 0.2)


def kick(level=0.5):
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 45 + 90 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9) * level


def shaker(rng, level=0.05):
    n = int(0.07 * SR)
    x = rng.standard_normal(n)
    x = x - lowpass(x, 5000)  # keep the hiss
    return x * np.exp(-np.arange(n) / SR * 60) * level


def place(buf, clip, t):
    i = int(t * SR)
    j = min(len(buf), i + len(clip))
    if j > i:
        buf[i:j] += clip[: j - i]


def stereo(mono, width=0.0, delay_ms=11):
    d = int(delay_ms / 1000 * SR)
    left = mono
    right = np.concatenate([np.zeros(d), mono[:-d]]) if d else mono
    return np.stack([left * (1 - width / 2) + right * width / 2, right * (1 - width / 2) + left * width / 2], 1)


def write_wav(path, data):
    data = data / max(1e-9, np.abs(data).max()) * 0.89  # about -1 dBFS peak
    pcm = (np.clip(data, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# -- outro music ------------------------------------------------------------------

def outro_music(seconds=13.0):
    """A warm, unhurried I-V-vi-IV progression in D at 96 BPM with a ringing final chord."""
    rng = np.random.default_rng(3)
    bpm = 96
    beat = 60 / bpm
    bar = beat * 4
    chords = [("D3", "F#3", "A3", "D4"), ("A2", "E3", "A3", "C#4"), ("B2", "F#3", "B3", "D4"), ("G2", "D3", "G3", "B3")]
    n = int(seconds * SR)
    mono = np.zeros(n)
    width = np.zeros(n)
    for i, chord in enumerate(chords):
        t0 = i * bar
        freqs = [note(c) for c in chord]
        place(width, pad(freqs, bar + 0.6, 0.10), t0)
        place(mono, pluck(note(chord[0]) / 2, bar, 0.26), t0)                  # bass
        place(mono, pluck(note(chord[0]) / 2, beat * 2, 0.16), t0 + beat * 2.5)
        arp = [freqs[1] * 2, freqs[2] * 2, freqs[3] * 2, freqs[2] * 2]
        for k in range(8):                                                     # eighth-note arpeggio
            place(width, pluck(arp[k % 4], beat, 0.07 if k % 2 else 0.1), t0 + k * beat / 2)
        for k in (0, 2):
            place(mono, kick(0.45), t0 + k * beat)
        for k in range(8):
            place(width, shaker(rng, 0.035 if k % 2 else 0.02), t0 + k * beat / 2)
    end = len(chords) * bar
    final = [note(c) for c in ("D3", "A3", "D4", "F#4", "E5")]
    place(width, pad(final, seconds - end, 0.12), end)
    for k, f in enumerate(final):
        place(width, bell(f, seconds - end - k * 0.06, 0.06), end + k * 0.06)
    place(mono, kick(0.4), end)
    out = stereo(mono, 0.0, 0) + stereo(width, 0.8)
    fade = int(1.5 * SR)
    out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return out


# -- intro sting ---------------------------------------------------------------------

STING_SECONDS = 2.6


def sting_audio():
    n = int(STING_SECONDS * SR)
    rng = np.random.default_rng(11)
    t = np.arange(n) / SR
    # Rising whoosh: noise through a sweeping low-pass.
    noise = rng.standard_normal(n)
    sweep = np.zeros(n)
    acc = 0.0
    cut = 300 + 5000 * np.clip(t / 0.85, 0, 1) ** 2
    a = np.exp(-2 * np.pi * cut / SR)
    for i in range(n):
        acc = (1 - a[i]) * noise[i] + a[i] * acc
        sweep[i] = acc
    whoosh = sweep * np.clip(t / 0.85, 0, 1) ** 1.5 * np.exp(-np.clip(t - 0.85, 0, None) * 12) * 0.5
    hit = np.zeros(n)
    chord = [note(c) for c in ("D2", "D3", "A3", "D4", "F#4", "E5")]
    place(hit, pad(chord, STING_SECONDS - 0.85, 0.18), 0.85)
    for k, f in enumerate(chord[2:]):
        place(hit, bell(f, STING_SECONDS - 0.85, 0.09), 0.85 + k * 0.035)
    place(hit, kick(0.6), 0.85)
    out = stereo(whoosh, 0.6) + stereo(hit, 0.7)
    fade = int(0.5 * SR)
    out[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return out


def sting_frame(t, brand):
    img = Image.new("RGBA", (S.W, S.H), S.BG_TITLE + (255,))
    d = ImageDraw.Draw(img)
    cx, cy = S.W / 2, S.H / 2 + 70
    # A mountain ridge with the route tracing along it.
    xs = np.linspace(cx - 520, cx + 520, 200)
    ridge = cy - (np.maximum(0, 1 - np.abs(xs - (cx - 160)) / 230) * 170 + np.maximum(0, 1 - np.abs(xs - (cx + 170)) / 240) * 250
                  + np.maximum(0, 1 - np.abs(xs - (cx + 420)) / 140) * 120)
    pts = list(zip(xs, ridge))
    p = S.ease_in_out(t / 0.95)
    ss = 3
    layer = Image.new("RGBA", (S.W * ss, S.H * ss), (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)
    dl.line([(x * ss, y * ss) for x, y in pts], fill=(49, 64, 78, 255), width=4 * ss, joint="curve")
    k = max(2, int(len(pts) * p))
    dl.line([(x * ss, y * ss) for x, y in pts[:k]], fill=S.ORANGE + (255,), width=7 * ss, joint="curve")
    img.alpha_composite(layer.resize((S.W, S.H), Image.LANCZOS))
    hx, hy = pts[k - 1]
    glow = S.ease_out((t - 0.85) / 0.4) * (1 - S.ease_out((t - 1.3) / 0.8))
    if glow > 0:
        S.paste_center(img, S.circle(int(30 + 70 * glow), S.ORANGE + (int(120 * glow),)), hx, hy)
    S.paste_center(img, S.circle(26, S.ORANGE + (255,)), hx, hy)
    S.paste_center(img, S.circle(10, (255, 255, 255, 255)), hx, hy)
    a = S.ease_out((t - 0.8) / 0.5)
    text = Image.new("RGBA", img.size, (0, 0, 0, 0))
    dt = ImageDraw.Draw(text)
    dt.text((cx, cy - 250), brand["channel"].upper(), font=S.font("display", 92), fill=S.TEXT, anchor="mm")
    dt.text((cx, cy + 90), brand.get("tagline", ""), font=S.font("medium", 34), fill=S.TEAL, anchor="mm")
    img.alpha_composite(S.with_alpha(text, a), (0, int((1 - a) * 24)))
    out = S.ease_in_out((t - (STING_SECONDS - 0.35)) / 0.35)
    if out > 0:
        img = Image.blend(img, Image.new("RGBA", img.size, S.BG_TITLE + (255,)), out)
    return img.convert("RGB")


def main():
    brand = json.loads((BRAND / "brand.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        write_wav(tmp / "outro.wav", outro_music())
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp / "outro.wav"), "-c:a", "aac", "-b:a", "192k",
                        str(BRAND / brand["outro_music"])], check=True)
        write_wav(tmp / "sting.wav", sting_audio())
        frames = int(STING_SECONDS * S.FPS)
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{S.W}x{S.H}",
               "-r", str(S.FPS), "-i", "pipe:0", "-i", str(tmp / "sting.wav"), "-c:v", "libx264", "-crf", "16",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
               str(BRAND / brand["intro_sting"])]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for i in range(frames):
            proc.stdin.write(sting_frame(i / S.FPS, brand).tobytes())
        proc.stdin.close()
        if proc.wait():
            sys.exit("ffmpeg failed")
    print(f"wrote {brand['intro_sting']} and {brand['outro_music']} in {BRAND.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
