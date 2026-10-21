"""Script -> narrated, mixed, loudness-mastered MP3, using the free offline audio kit."""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import audio_kit as ak  # noqa: E402

MODELS = Path(__file__).resolve().parent.parent / "models"
PAUSE = re.compile(r"\[pause (\d+(?:\.\d+)?)\]")


SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def speak(script: str, voice: str, speed: float = 0.82, para_gap: float = 1.8, sentence_gap: float = 0.45) -> np.ndarray:
    """Synthesize a script, honouring [pause N] markers and leaving a breath between paragraphs."""
    k = ak.kokoro(str(MODELS))
    out: list[np.ndarray] = []
    for para in [p for p in script.split("\n\n") if p.strip()]:
        pos = 0
        for m in list(PAUSE.finditer(para)) + [None]:
            chunk = para[pos: m.start() if m else len(para)].strip()
            if chunk:
                for sent in SENTENCE.split(chunk):
                    samples, sr = k.create(ak.normalize(sent), voice=voice, speed=speed, lang="en-us")
                    out.append(samples.astype(np.float32))
                    out.append(np.zeros(int(sentence_gap * ak.SR), dtype=np.float32))
            if m:
                out.append(np.zeros(int(float(m.group(1)) * ak.SR), dtype=np.float32))
                pos = m.end()
        out.append(np.zeros(int(para_gap * ak.SR), dtype=np.float32))
    return np.concatenate(out) if out else np.zeros(ak.SR, dtype=np.float32)


def render(script: str, out_mp3: Path, *, voice: str, title: str, album: str, root_hz: float = 98.0,
           seed: int = 7, bed_db: float = -27.0, speed: float = 0.82, bitrate: str = "96k") -> float:
    v = speak(script, voice, speed=speed)
    bed = ak.pad_bed(len(v) / ak.SR + 6, root_hz=root_hz, seed=seed, gain_db=bed_db)
    mixed = ak.mix(v, bed=bed, intro=ak.sting(root_hz=root_hz * 2), head=1.0, tail=3.0)
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "mix.wav"
        sf.write(wav, mixed, ak.SR)
        ak.master(str(wav), str(out_mp3), title=title, artist="Tonight's Sky, Softly", album=album, bitrate=bitrate)
    return ak.duration_s(str(out_mp3))
