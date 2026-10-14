"""Soundtrack: brand intro sting, voiceover, a music bed under it, and outro music at the end."""

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


def mix(out_path, total, sting=None, sting_dur=0.0, outro=None, outro_seconds=10.0, segments=(),
        bed=None, bed_volume=0.16):
    """Write the full soundtrack (sting + episode) as a WAV of exactly `total` seconds.

    Voiceover clips start VO_LEAD after their segment begins (offset by the sting).
    The music bed loops under the episode, ducking whenever someone is talking, and
    hands over to the outro: the last `outro_seconds` of the outro music play over the
    end of the episode, dipping under any narration there.
    """
    inputs, chains, labels = [], [], []
    fmt = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"

    def add_input(*args):
        inputs.extend([*args])
        return len([a for a in inputs if a == "-i"]) - 1

    chains.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{total:.3f}[base]")
    labels.append("[base]")
    if sting and has_audio(sting):
        k = add_input("-i", str(sting))
        chains.append(f"[{k}:a]{fmt},atrim=0:{sting_dur:.3f}[sting]")
        labels.append("[sting]")
    vo = [s for s in segments if s.vo_path]
    outro_start = max(0.0, total - outro_seconds) if outro else total
    if vo:
        names = []
        for seg in vo:
            k = add_input("-i", str(seg.vo_path))
            ms = int((sting_dur + seg.start + VO_LEAD) * 1000)
            names.append(f"[v{k}]")
            chains.append(f"[{k}:a]{fmt},adelay={ms}|{ms}{names[-1]}")
        chains.append(f"{''.join(names)}amix=inputs={len(names)}:normalize=0:duration=longest,"
                      f"apad=whole_dur={total:.3f}" + (",asplit=2[vo][key]" if bed else "[vo]"))
        labels.append("[vo]")
    if bed:
        k = add_input("-stream_loop", "-1", "-i", str(bed))
        start, end = sting_dur, outro_start + 1.5
        ms = int(start * 1000)
        chains.append(f"[{k}:a]{fmt},atrim=0:{end - start:.3f},asetpts=PTS-STARTPTS,volume={bed_volume},"
                      f"afade=t=in:d=2,afade=t=out:st={max(0.0, end - start - 2.5):.3f}:d=2.5,"
                      f"adelay={ms}|{ms},apad=whole_dur={total:.3f}" + ("[bedraw]" if vo else "[bed]"))
        if vo:
            # Duck the bed about 10 dB while the narrator talks.
            chains.append("[bedraw][key]sidechaincompress=threshold=0.02:ratio=8:attack=40:release=600[bed]")
        labels.append("[bed]")
    if outro:
        k = add_input("-i", str(outro))
        ms = int(outro_start * 1000)
        # Lower the music while someone is talking over it.
        talking = [(sting_dur + s.start + VO_LEAD, sting_dur + s.start + VO_LEAD + s.vo_dur) for s in vo
                   if sting_dur + s.start + VO_LEAD + s.vo_dur > outro_start]
        duck = "".join(f",volume=enable='between(t,{a - outro_start - 0.2:.2f},{b - outro_start + 0.3:.2f})':volume=0.4"
                       for a, b in talking)
        # Use the *end* of the music so its final chord lands on the last frame.
        skip = max(0.0, media_duration(outro) - outro_seconds)
        chains.append(f"[{k}:a]{fmt},atrim={skip:.3f}:{skip + outro_seconds:.3f},asetpts=PTS-STARTPTS,"
                      f"afade=t=in:d=1.0,afade=t=out:st={max(0.0, outro_seconds - 0.6):.3f}:d=0.6{duck},"
                      f"adelay={ms}|{ms}[music]")
        labels.append("[music]")
    chains.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=first,"
                  f"alimiter=limit=0.95[out]")
    raw = out_path.with_suffix(".raw.wav")
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(chains),
           "-map", "[out]", "-c:a", "pcm_f32le", "-ar", "48000", str(raw)]
    subprocess.run(cmd, check=True)
    normalize(raw, out_path)
    raw.unlink()
    return out_path


LOUDNESS = "I=-14:TP=-2:LRA=11"  # YouTube plays back at about -14 LUFS


def normalize(src, dst):
    """Two-pass EBU R128 loudness normalization to YouTube's playback level."""
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af", f"loudnorm={LOUDNESS}:print_format=json",
                            "-f", "null", "-"], capture_output=True, text=True, check=True).stderr
    m = json.loads(probe[probe.rindex("{"):probe.rindex("}") + 1])
    measured = (f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
                f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", f"loudnorm={LOUDNESS}{measured}",
                    "-ar", "48000", "-c:a", "pcm_s16le", str(dst)], check=True)
