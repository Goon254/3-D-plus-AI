"""A small SoundFont (SF2/SF3) sample player in numpy: real instrument samples without an external synth.

Supports what scored music needs: presets -> instruments -> sample zones (key/velocity ranges, global zones),
root key / tuning, looped samples (held notes loop, then release), the volume envelope (delay, attack, hold,
decay, sustain, release), initial attenuation, pan, and SF3's Ogg Vorbis samples (decoded with
``soundfile``). Not supported (unneeded for our cues): modulators, the filter/modulation envelopes, LFOs.

Default bank: FluidR3Mono_GM (MIT; Frank Wen, mono conversion by Michael Cowgill), cached by
``scripts/setup_assets.sh`` in ``~/.cache/animatica/soundfonts``.
"""

from __future__ import annotations

import io
import math
import os
import struct
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

CACHE = Path(os.environ.get("ANIMATICA_CACHE", Path.home() / ".cache" / "animatica"))
SR = 44100

# generator operators (SoundFont 2.04 spec, section 8.1.2)
KEY_RANGE, VEL_RANGE, INSTRUMENT, SAMPLE_ID = 43, 44, 41, 53
SAMPLE_MODES, ROOT_KEY, COARSE, FINE, ATTEN, PAN = 54, 58, 51, 52, 48, 17
DELAY, ATTACK, HOLD, DECAY, SUSTAIN, RELEASE = 33, 34, 35, 36, 37, 38
RANGE_GENS = {KEY_RANGE, VEL_RANGE}


def default_soundfont() -> Path | None:
    env = os.environ.get("ANIMATICA_SOUNDFONT")
    if env and Path(env).exists():
        return Path(env)
    for name in ("FluidR3Mono_GM.sf3", "FluidR3_GM.sf2"):
        p = CACHE / "soundfonts" / name
        if p.exists():
            return p
    return None


@dataclass
class Zone:
    gens: dict[int, int | tuple[int, int]] = field(default_factory=dict)

    def range(self, gen: int) -> tuple[int, int]:
        v = self.gens.get(gen, (0, 127))
        return v if isinstance(v, tuple) else (0, 127)


@dataclass
class SampleHeader:
    name: str
    start: int
    end: int
    loop_start: int
    loop_end: int
    rate: int
    pitch: int
    correction: int
    kind: int


def _chunks(data: bytes, start: int, end: int):
    i = start
    while i + 8 <= end:
        cid = data[i : i + 4].decode("latin-1")
        size = struct.unpack_from("<I", data, i + 4)[0]
        yield cid, i + 8, size
        i += 8 + size + (size & 1)


class SoundFont:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        data = self.path.read_bytes()
        if data[:4] != b"RIFF" or data[8:12] != b"sfbk":
            raise ValueError(f"{path} is not a SoundFont")
        self._data = data
        pd: dict[str, tuple[int, int]] = {}
        self._smpl = (0, 0)
        for cid, off, size in _chunks(data, 12, len(data)):
            if cid != "LIST":
                continue
            kind = data[off : off + 4].decode("latin-1")
            for sub, soff, ssize in _chunks(data, off + 4, off + size):
                if kind == "sdta" and sub == "smpl":
                    self._smpl = (soff, ssize)
                elif kind == "pdta":
                    pd[sub] = (soff, ssize)
        self._parse(pd)
        self._decoded: dict[int, np.ndarray] = {}

    def _records(self, pd, name, fmt):
        off, size = pd[name]
        n = struct.calcsize(fmt)
        return [struct.unpack_from(fmt, self._data, off + i * n) for i in range(size // n)]

    def _gens(self, rows, a, b) -> list[tuple[int, int | tuple[int, int]]]:
        out = []
        for oper, raw in rows[a:b]:
            if oper in RANGE_GENS:
                out.append((oper, (raw & 0xFF, (raw >> 8) & 0xFF)))
            else:
                out.append((oper, raw - 65536 if raw >= 32768 else raw))
        return out

    def _zones(self, bags, gens, a, b) -> list[Zone]:
        zones = []
        for i in range(a, b):
            zones.append(Zone(dict(self._gens(gens, bags[i][0], bags[i + 1][0]))))
        return zones

    def _parse(self, pd) -> None:
        phdr = self._records(pd, "phdr", "<20sHHHIII")
        pbag = self._records(pd, "pbag", "<HH")
        pgen = self._records(pd, "pgen", "<HH")
        inst = self._records(pd, "inst", "<20sH")
        ibag = self._records(pd, "ibag", "<HH")
        igen = self._records(pd, "igen", "<HH")
        shdr = self._records(pd, "shdr", "<20sIIIIIBbHH")
        self.samples = [
            SampleHeader(n.split(b"\0")[0].decode("latin-1"), s, e, ls, le, r, p, c, t)
            for n, s, e, ls, le, r, p, c, _link, t in shdr[:-1]
        ]
        self.instruments: list[tuple[Zone | None, list[Zone]]] = []
        for i in range(len(inst) - 1):
            zones = self._zones(ibag, igen, inst[i][1], inst[i + 1][1])
            glob = zones[0] if zones and SAMPLE_ID not in zones[0].gens else None
            self.instruments.append((glob, [z for z in zones if SAMPLE_ID in z.gens]))
        self.presets: dict[tuple[int, int], tuple[Zone | None, list[Zone]]] = {}
        for i in range(len(phdr) - 1):
            prog, bank, bag = phdr[i][1], phdr[i][2], phdr[i][3]
            zones = self._zones(pbag, pgen, bag, phdr[i + 1][3])
            glob = zones[0] if zones and INSTRUMENT not in zones[0].gens else None
            self.presets[(bank, prog)] = (glob, [z for z in zones if INSTRUMENT in z.gens])

    def sample_data(self, idx: int) -> np.ndarray:
        """Decoded float32 mono samples (SF3: Ogg Vorbis stream; SF2: 16-bit PCM)."""
        if idx in self._decoded:
            return self._decoded[idx]
        h = self.samples[idx]
        off, _ = self._smpl
        if h.kind & 0x10:  # SF3 compressed: start/end are byte offsets of an Ogg stream
            import soundfile as sf

            raw = self._data[off + h.start : off + h.end]
            a, _sr = sf.read(io.BytesIO(raw), dtype="float32")
            if a.ndim > 1:
                a = a.mean(axis=1)
        else:
            a = (
                np.frombuffer(
                    self._data, dtype="<i2", count=h.end - h.start, offset=off + 2 * h.start
                ).astype(np.float32)
                / 32768
            )
        self._decoded[idx] = a
        return a

    def regions(self, bank: int, prog: int, key: int, vel: int) -> list[tuple[dict, SampleHeader, int]]:
        """(merged generators, sample header, sample index) for every zone that sounds this key/velocity."""
        preset = self.presets.get((bank, prog)) or self.presets.get((0 if bank != 128 else 128, 0))
        if preset is None:
            return []
        pglob, pzones = preset
        out = []
        for pz in pzones:
            if not _in(pz.range(KEY_RANGE), key) or not _in(pz.range(VEL_RANGE), vel):
                continue
            iglob, izones = self.instruments[pz.gens[INSTRUMENT]]
            for iz in izones:
                if not _in(iz.range(KEY_RANGE), key) or not _in(iz.range(VEL_RANGE), vel):
                    continue
                g: dict = {}
                if iglob:
                    g.update(iglob.gens)
                g.update(iz.gens)
                # preset-level generators add to the instrument's (spec 9.4), for the ones we use
                for src in (pglob.gens if pglob else {}, pz.gens):
                    for k in (COARSE, FINE, ATTEN, PAN):
                        if k in src:
                            g[k] = g.get(k, 0) + src[k]
                sid = g[SAMPLE_ID]
                out.append((g, self.samples[sid], sid))
        return out


def _in(r: tuple[int, int], v: int) -> bool:
    return r[0] <= v <= r[1]


def _tc(v: int | None, default: float) -> float:
    """Timecents -> seconds (-12000 means 'instant')."""
    if v is None:
        return default
    return 0.0 if v <= -12000 else 2.0 ** (v / 1200.0)


@lru_cache(maxsize=4)
def load(path: str) -> SoundFont:
    return SoundFont(path)


def render_note(
    sf: SoundFont, bank: int, prog: int, key: int, vel: int, dur: float, sr: int = SR
) -> np.ndarray:
    """Stereo float32 audio for one note held ``dur`` seconds (plus its release tail)."""
    regions = sf.regions(bank, prog, key, vel)
    if not regions:
        return np.zeros((0, 2), dtype=np.float32)
    outs = []
    for g, h, sid in regions:
        data = sf.sample_data(sid)
        compressed = bool(h.kind & 0x10)
        loop_s = h.loop_start if compressed else h.loop_start - h.start
        loop_e = h.loop_end if compressed else h.loop_end - h.start
        root = g.get(ROOT_KEY, -1)
        root = h.pitch if root < 0 or root > 127 else root
        semis = key - root + g.get(COARSE, 0) + (g.get(FINE, 0) + h.correction) / 100.0
        step = 2.0 ** (semis / 12.0) * h.rate / sr
        attack = _tc(g.get(ATTACK), 0.001)
        hold = _tc(g.get(HOLD), 0.0)
        decay = _tc(g.get(DECAY), 0.001)
        sustain_db = max(0, g.get(SUSTAIN, 0)) / 10.0  # centibels -> dB below peak
        release = min(_tc(g.get(RELEASE), 0.01), 3.0)
        delay = _tc(g.get(DELAY), 0.0)
        loops = g.get(SAMPLE_MODES, 0) & 1 and loop_e - loop_s > 16
        total = dur + release
        n = int(total * sr)
        pos = np.arange(n, dtype=np.float64) * step
        if loops:
            ln = loop_e - loop_s
            wrap = pos >= loop_e
            pos[wrap] = loop_s + np.mod(pos[wrap] - loop_s, ln)
        else:
            n = min(n, int((len(data) - 2) / step))
            pos = pos[:n]
        if n <= 0:
            continue
        i0 = np.clip(pos.astype(np.int64), 0, len(data) - 2)
        frac = (pos - i0).astype(np.float32)
        wav = data[i0] * (1 - frac) + data[i0 + 1] * frac
        # volume envelope (linear amplitude), then release from wherever it was at note-off
        t = np.arange(n) / sr
        env = np.ones(n, dtype=np.float32)
        sus = 10 ** (-sustain_db / 20)
        a_end, h_end = delay + attack, delay + attack + hold
        env[t < delay] = 0
        m = (t >= delay) & (t < a_end)
        env[m] = (t[m] - delay) / max(attack, 1e-4)
        m = (t >= h_end) & (t < h_end + decay)
        env[m] = 1 + (sus - 1) * (t[m] - h_end) / max(decay, 1e-4)
        env[t >= h_end + decay] = sus
        off = t >= dur
        if off.any():
            level = env[int(dur * sr) - 1] if int(dur * sr) > 0 else sus
            env[off] = level * np.exp(-5.0 * (t[off] - dur) / max(release, 0.02))
        atten = 10 ** (
            -(g.get(ATTEN, 0) * 0.4) / 200
        )  # many fonts over-attenuate; 0.4 is FluidSynth's default
        gain = atten * (vel / 127.0) ** 1.6
        mono = (wav * env * gain).astype(np.float32)
        p = max(-500, min(500, g.get(PAN, 0))) / 1000.0 + 0.5
        outs.append(np.stack([mono * math.cos(p * math.pi / 2), mono * math.sin(p * math.pi / 2)], axis=1))
    if not outs:
        return np.zeros((0, 2), dtype=np.float32)
    n = max(len(o) for o in outs)
    mix = np.zeros((n, 2), dtype=np.float32)
    for o in outs:
        mix[: len(o)] += o
    return mix


@dataclass
class Note:
    t: float  # seconds
    dur: float
    key: int
    vel: int
    prog: int  # GM program (0-127); percussion uses bank 128
    bank: int = 0
    pan: float = 0.0  # -1 left .. 1 right (on top of the zone's own pan)
    gain: float = 1.0


def render(notes: list[Note], seconds: float, sf: SoundFont | None = None, sr: int = SR) -> np.ndarray:
    """Mix ``notes`` into a stereo float32 buffer of ``seconds``."""
    sf = sf or load(str(default_soundfont()))
    out = np.zeros((int(seconds * sr) + sr * 4, 2), dtype=np.float32)
    for nt in notes:
        a = render_note(sf, nt.bank, nt.prog, nt.key, nt.vel, nt.dur, sr)
        if not len(a):
            continue
        p = (nt.pan + 1) / 2
        a = (
            a
            * np.array([math.cos(p * math.pi / 2), math.sin(p * math.pi / 2)], dtype=np.float32)
            * math.sqrt(2)
            * nt.gain
        )
        s = int(nt.t * sr)
        e = min(len(out), s + len(a))
        out[s:e] += a[: e - s]
    return out[: int(seconds * sr)]
