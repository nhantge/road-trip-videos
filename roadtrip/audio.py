"""Soundtrack: brand intro sting, voiceover clips and outro music over the last seconds."""

import json
import subprocess

from .style import REPO_ROOT
from .timeline import VO_LEAD

BRAND_DIR = REPO_ROOT / "assets" / "brand"


def load_brand():
    return json.loads((BRAND_DIR / "brand.json").read_text())


def media_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def has_audio(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return bool(out.stdout.strip())


def mix(out_path, total, sting=None, sting_dur=0.0, outro=None, outro_seconds=10.0, segments=()):
    """Write the full soundtrack (sting + episode) as a WAV of exactly `total` seconds.

    Voiceover clips start VO_LEAD after their segment begins (offset by the sting).
    The last `outro_seconds` of the outro music play over the end of the episode, dipping
    under any narration there.
    """
    inputs, chains, labels = [], [], []
    fmt = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    chains.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[base]")
    labels.append("[base]")
    if sting and has_audio(sting):
        inputs += ["-i", str(sting)]
        chains.append(f"[{len(inputs) // 2 - 1}:a]{fmt},atrim=0:{sting_dur:.3f}[sting]")
        labels.append("[sting]")
    vo = [s for s in segments if s.vo_path]
    outro_start = max(0.0, total - outro_seconds)
    for seg in vo:
        inputs += ["-i", str(seg.vo_path)]
        ms = int((sting_dur + seg.start + VO_LEAD) * 1000)
        name = f"vo{len(labels)}"
        chains.append(f"[{len(inputs) // 2 - 1}:a]{fmt},adelay={ms}|{ms}[{name}]")
        labels.append(f"[{name}]")
    if outro:
        inputs += ["-i", str(outro)]
        ms = int(outro_start * 1000)
        # Lower the music while someone is talking over it.
        talking = [(sting_dur + s.start + VO_LEAD, sting_dur + s.start + VO_LEAD + s.vo_dur) for s in vo
                   if sting_dur + s.start + VO_LEAD + s.vo_dur > outro_start]
        duck = "".join(f",volume=enable='between(t,{a - outro_start - 0.2:.2f},{b - outro_start + 0.3:.2f})':volume=0.4"
                       for a, b in talking)
        # Use the *end* of the music so its final chord lands on the last frame.
        skip = max(0.0, media_duration(outro) - outro_seconds)
        chains.append(f"[{len(inputs) // 2 - 1}:a]{fmt},atrim={skip:.3f}:{skip + outro_seconds:.3f},asetpts=PTS-STARTPTS,"
                      f"afade=t=in:d=1.0,afade=t=out:st={max(0.0, outro_seconds - 0.6):.3f}:d=0.6{duck},"
                      f"adelay={ms}|{ms}[music]")
        labels.append("[music]")
    chains.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=first,"
                  f"alimiter=limit=0.95[out]")
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chains),
           "-map", "[out]", "-c:a", "pcm_s16le", "-ar", "48000", str(out_path)]
    subprocess.run(cmd, check=True)
    return out_path
