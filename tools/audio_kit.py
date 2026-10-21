"""Free, offline audio production kit: Kokoro TTS + numpy synth beds + ffmpeg mastering."""
from __future__ import annotations
import os, re, subprocess, json, math
import numpy as np
import soundfile as sf

SR = 24000
_MODEL = None

def kokoro(model_dir: str):
    global _MODEL
    if _MODEL is None:
        from kokoro_onnx import Kokoro
        _MODEL = Kokoro(os.path.join(model_dir, "kokoro-v1.0.onnx"), os.path.join(model_dir, "voices-v1.0.bin"))
    return _MODEL

_NUM_WORDS = {0:"zero",1:"one",2:"two",3:"three",4:"four",5:"five",6:"six",7:"seven",8:"eight",9:"nine",10:"ten",11:"eleven",12:"twelve"}

def normalize(text: str) -> str:
    """Make times, degrees, magnitudes and symbols speakable."""
    t = text
    t = re.sub(r"(\d{1,2}):(\d{2})\s*(am|pm|AM|PM)", lambda m: f"{int(m.group(1))} {'oh ' if m.group(2)[0]=='0' and m.group(2)!='00' else ''}{'' if m.group(2)=='00' else m.group(2).lstrip('0')} {m.group(3).lower().replace('am','A M').replace('pm','P M')}".replace("  "," "), t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*°", r"\1 degrees", t)
    t = t.replace("−", "minus ").replace("–", ", ").replace("—", ", ")
    t = re.sub(r"\bmag(?:nitude)?\s*(-?\d+(?:\.\d+)?)", lambda m: "magnitude " + ("minus " if m.group(1).startswith("-") else "") + m.group(1).lstrip("-"), t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def split_paragraphs(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return parts

def tts(text: str, voice: str, model_dir: str, speed: float = 1.0, lang: str = "en-us", pause: float = 0.55) -> np.ndarray:
    """Synthesize paragraph by paragraph with a natural pause between paragraphs."""
    k = kokoro(model_dir)
    chunks = []
    gap = np.zeros(int(pause * SR), dtype=np.float32)
    for p in split_paragraphs(text):
        samples, sr = k.create(normalize(p), voice=voice, speed=speed, lang=lang)
        assert sr == SR
        chunks.append(samples.astype(np.float32)); chunks.append(gap)
    return np.concatenate(chunks) if chunks else np.zeros(SR, dtype=np.float32)

# ---------- synthesized music beds (no samples, no licences) ----------
def _env(n, a, r):
    e = np.ones(n, dtype=np.float32)
    ai = min(n, int(a*SR)); ri = min(n, int(r*SR))
    if ai: e[:ai] = np.linspace(0,1,ai)
    if ri: e[-ri:] *= np.linspace(1,0,ri)
    return e

def pad_bed(duration: float, root_hz: float = 110.0, seed: int = 7, gain_db: float = -24.0) -> np.ndarray:
    """Slow evolving ambient pad: detuned sines on a minor-ninth chord with slow LFO, low-passed."""
    rng = np.random.default_rng(seed)
    n = int(duration * SR); t = np.arange(n) / SR
    ratios = [1, 1.5, 2, 2.4, 3, 4.5]  # root, fifth, octave, minor third(ish), fifth, ninth
    out = np.zeros(n, dtype=np.float32)
    for i, r in enumerate(ratios):
        f = root_hz * r
        for det in (-0.4, 0.0, 0.4):
            ph = rng.uniform(0, 2*np.pi)
            lfo = 0.5 + 0.5*np.sin(2*np.pi*(0.02 + 0.01*i)*t + ph)
            out += (np.sin(2*np.pi*(f+det)*t + ph) * lfo).astype(np.float32) / (len(ratios)*3) / (1 + i*0.6)
    # gentle noise "air", low-passed with an FFT convolution (fast for long beds)
    air = rng.normal(0, 1, n).astype(np.float32)
    k = np.exp(-np.arange(2048) / 50.0).astype(np.float32); k /= k.sum()
    m = 1 << int(np.ceil(np.log2(n + len(k))))
    y = np.fft.irfft(np.fft.rfft(air, m) * np.fft.rfft(k, m), m)[:n].astype(np.float32)
    out += y / (np.max(np.abs(y)) + 1e-9) * 0.08
    out *= _env(n, 3.0, 4.0)
    out /= (np.max(np.abs(out)) + 1e-9)
    return out * (10 ** (gain_db/20))

def sting(duration: float = 2.2, root_hz: float = 220.0, gain_db: float = -16.0) -> np.ndarray:
    """Short bell-like identity sting."""
    n = int(duration*SR); t = np.arange(n)/SR
    out = np.zeros(n, dtype=np.float32)
    for k, (r, g) in enumerate([(1,1.0),(2,0.5),(3,0.3),(4.2,0.15),(5.4,0.1)]):
        out += (g*np.sin(2*np.pi*root_hz*r*t)*np.exp(-t*(1.2+k*0.8))).astype(np.float32)
    for r in (1.5, 2.5):  # soft upper notes staggered
        d = int(0.18*SR*r); tt = t[:n-d]
        out[d:] += (0.35*np.sin(2*np.pi*root_hz*r*tt)*np.exp(-tt*1.5)).astype(np.float32)
    out /= (np.max(np.abs(out))+1e-9)
    return out*(10**(gain_db/20))

def mix(voice: np.ndarray, bed: np.ndarray | None = None, intro: np.ndarray | None = None, head: float = 0.8, tail: float = 1.5) -> np.ndarray:
    pre = np.zeros(int(head*SR), dtype=np.float32)
    post = np.zeros(int(tail*SR), dtype=np.float32)
    parts = [pre]
    if intro is not None: parts.append(intro)
    parts += [voice, post]
    v = np.concatenate(parts)
    if bed is not None:
        b = bed
        if len(b) < len(v): b = np.concatenate([b, np.zeros(len(v)-len(b), dtype=np.float32)])
        b = b[:len(v)].copy(); b[-int(3*SR):] *= np.linspace(1,0,int(3*SR))
        v = v + b
    return np.clip(v, -1, 1)

def master(wav_in: str, out_path: str, title: str = "", artist: str = "", album: str = "", bitrate: str = "128k"):
    """Loudness-normalize to podcast spec (-16 LUFS, -1.5 dBTP) and encode MP3 with tags."""
    meta = []
    for k, v in (("title", title), ("artist", artist), ("album", album)):
        if v: meta += ["-metadata", f"{k}={v}"]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", wav_in,
           "-af", "highpass=f=70,loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-ac", "1",
           "-codec:a", "libmp3lame", "-b:a", bitrate, *meta, out_path]
    subprocess.run(cmd, check=True)
    return out_path

def duration_s(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path], capture_output=True, text=True, check=True)
    return float(json.loads(out.stdout)["format"]["duration"])
