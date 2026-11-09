"""Procedural sound design: every sound is synthesized (no samples, no licensing).

Ported from the reference `sfx.py` with the per-sample Python loops replaced by
`scipy.signal.lfilter`, and with randomness seeded per cue index so a render is reproducible.
"""

from __future__ import annotations

import wave
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from scipy.signal import lfilter

from mvrender.cues import Cue

SR = 48000
SEED = 7
Arr = NDArray[np.float64]


def t_axis(dur: float) -> Arr:
    return np.arange(int(dur * SR)) / SR


def env(dur: float, attack: float = 0.002, decay: float = 0.1) -> Arr:
    t = t_axis(dur)
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return np.asarray(a * np.exp(-np.maximum(t - attack, 0) / decay))


def noise(dur: float, rng: np.random.Generator) -> Arr:
    return np.asarray(rng.uniform(-1, 1, int(dur * SR)))


def lowpass(x: Arr, cutoff: float) -> Arr:
    a = float(np.exp(-2 * np.pi * cutoff / SR))
    return np.asarray(lfilter([1 - a], [1, -a], x))


def highpass(x: Arr, cutoff: float) -> Arr:
    return np.asarray(x - lowpass(x, cutoff))


def sweep(f0: float, f1: float, dur: float, shape: Callable[[Arr], Arr] = np.sin) -> Arr:
    t = t_axis(dur)
    f = f0 * (f1 / f0) ** (t / dur)
    return np.asarray(shape(2 * np.pi * np.cumsum(f) / SR))


def square(ph: Arr) -> Arr:
    return np.asarray(np.sign(np.sin(ph)))


def key_click(rng: np.random.Generator, var: float = 0.0) -> Arr:
    d = 0.045
    n = highpass(noise(d, rng), 1800 + 900 * var) * env(d, 0.0005, 0.006)
    body = np.sin(2 * np.pi * (1900 + 500 * var) * t_axis(d)) * env(d, 0.0005, 0.004)
    return np.asarray(0.32 * n + 0.10 * body)


def enter_key(rng: np.random.Generator) -> Arr:
    d = 0.12
    n = lowpass(noise(d, rng), 2500) * env(d, 0.001, 0.02)
    thump = np.sin(2 * np.pi * 140 * t_axis(d)) * env(d, 0.001, 0.03)
    return np.asarray(0.55 * n + 0.45 * thump)


def out_blip() -> Arr:
    d = 0.09
    return np.asarray(0.16 * np.sin(2 * np.pi * 1320 * t_axis(d)) * env(d, 0.002, 0.025))


def pop(pitch: float = 1.0) -> Arr:
    d = 0.16
    return np.asarray(0.42 * sweep(260 * pitch, 720 * pitch, d) * env(d, 0.002, 0.045))


def ding(pitch: float = 1.0) -> Arr:
    d = 0.9
    t = t_axis(d)
    f = 880 * pitch
    s = (
        np.sin(2 * np.pi * f * t)
        + 0.35 * np.sin(2 * np.pi * 2 * f * t)
        + 0.12 * np.sin(2 * np.pi * 3.01 * f * t)
    )
    return np.asarray(0.20 * s * env(d, 0.003, 0.28))


def chime() -> Arr:
    out = np.zeros(int(1.3 * SR))
    for k, f in enumerate([1.0, 1.26, 1.5, 2.0]):
        s = ding(f * 0.75)
        o = int(k * 0.07 * SR)
        out[o : o + len(s)] += s[: len(out) - o] * 0.8
    return out


def whoosh(rng: np.random.Generator, dur: float = 0.45) -> Arr:
    n = noise(dur, rng)
    t = t_axis(dur)
    sh = np.sin(np.pi * t / dur) ** 2
    cut = np.linspace(600, 4000, len(n))
    lo, hi = lowpass(n, 700), lowpass(n, 4000)
    mixw = (cut - 600) / 3400
    return np.asarray(0.30 * (lo * (1 - mixw) + hi * mixw) * sh)


def tape_stop() -> Arr:
    d = 0.7
    return np.asarray(
        0.38 * sweep(420, 45, d, lambda p: np.tanh(2.5 * np.sin(p))) * env(d, 0.005, 0.35)
        + 0.5 * np.sin(2 * np.pi * 55 * t_axis(d)) * env(d, 0.002, 0.18)
    )


def tape_start() -> Arr:
    d = 0.5
    return np.asarray(
        0.30 * sweep(60, 480, d, lambda p: np.tanh(2.5 * np.sin(p))) * np.sin(np.pi * t_axis(d) / d) ** 0.7
    )


def error_buzz() -> Arr:
    d = 0.42
    t = t_axis(d)
    out = np.zeros(len(t))
    for k, f in enumerate([196, 147]):
        o = int(k * 0.15 * SR)
        seg = lowpass(square(2 * np.pi * f * t[: len(t) - o]), 1800)
        out[o:] += 0.26 * seg * env(len(seg) / SR, 0.004, 0.08)
    return out


def impact(rng: np.random.Generator) -> Arr:
    d = 1.0
    t = t_axis(d)
    boom = np.sin(2 * np.pi * (45 + 60 * np.exp(-t * 18)) * t) * env(d, 0.002, 0.30)
    crack = lowpass(noise(d, rng), 3000) * env(d, 0.001, 0.03)
    return np.asarray(0.55 * boom + 0.25 * crack)


def block_tick(var: float) -> Arr:
    d = 0.06
    return np.asarray(0.13 * np.sin(2 * np.pi * (1500 + 400 * var) * t_axis(d)) * env(d, 0.001, 0.015))


def code_tick(rng: np.random.Generator, level: float = 1.0) -> Arr:
    d = 0.05
    n = highpass(noise(d, rng), 3000) * env(d, 0.0005, 0.005)
    body = np.sin(2 * np.pi * 2600 * t_axis(d)) * env(d, 0.0005, 0.008)
    return np.asarray(level * (0.14 * n + 0.08 * body))


def ambient_pad(total: float, level_db: float = -31.0) -> Arr:
    """Very quiet evolving drone so the track never goes dead silent."""
    t = t_axis(total)
    out = np.zeros(len(t))
    for f, a in [(110, 1.0), (164.8, 0.6), (220, 0.5), (246.9, 0.25), (329.6, 0.2)]:
        lfo = 0.6 + 0.4 * np.sin(2 * np.pi * (0.05 + f / 9000) * t + f)
        out += a * lfo * (np.sin(2 * np.pi * f * t) + 0.15 * np.sin(2 * np.pi * f * 1.003 * t))
    out = lowpass(out, 900)
    fade = np.minimum(1, np.minimum(t / 2.0, (total - t) / 2.0))
    return np.asarray(10 ** (level_db / 20) * out / np.max(np.abs(out)) * fade)


def make(kind: str, p: float, rng: np.random.Generator) -> Arr:
    makers: dict[str, Callable[[], Arr]] = {
        "key": lambda: key_click(rng, p * 2 - 1) * (0.7 + 0.3 * p),
        "enter": lambda: enter_key(rng),
        "blip": out_blip,
        "pop": lambda: pop(p),
        "ding": lambda: ding(p) * 0.8,
        "chime": chime,
        "whoosh": lambda: whoosh(rng, 0.45) * p,
        "tape_stop": tape_stop,
        "tape_start": tape_start,
        "error": error_buzz,
        "impact": lambda: impact(rng),
        "block": lambda: block_tick(p),
        "tick": lambda: code_tick(rng, p),
    }
    return makers[kind]()


def synthesize(cues: Sequence[Cue], total_s: float, *, ambient: bool = True) -> NDArray[np.int16]:
    """Mix every cue (seeded per cue index) into a stereo 16-bit track of `total_s` seconds."""
    mix = np.zeros(int(total_s * SR) + SR)
    for i, c in enumerate(cues):
        snd = make(c.kind, c.p, np.random.default_rng(SEED + i))
        o = int(c.t * SR)
        n = min(len(snd), len(mix) - o)
        if n > 0:
            mix[o : o + n] += snd[:n]
    if ambient:
        pad = ambient_pad(total_s)
        mix[: len(pad)] += pad
    mix = mix[: int(total_s * SR)]
    mix = np.tanh(mix * 1.4) / np.tanh(1.4)  # soft limiter
    mix *= 0.89 / max(1e-9, float(np.max(np.abs(mix))))  # peak about -1 dBFS
    st = np.stack([mix, mix], axis=1)
    return np.asarray((st * 32767).astype("<i2"))


def write_wav(path: str | Path, samples: NDArray[np.int16]) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(samples.tobytes())
