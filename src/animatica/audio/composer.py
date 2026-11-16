"""Composer: per-scene music cues with character leitmotifs, rendered with real instrument samples.

The screenplay gives every scene an emotional intent. A *cue sheet* (JSON, one cue per scene) turns that into
musical choices: key, tempo, and one or more *sections* (mood + mode + which leitmotifs play). The Composer
arranges each cue into General MIDI tracks:

* one track per leitmotif (each character owns a melody **and** a timbre: Tembo = marimba + tuba,
  Neema = flute, Kiki = pizzicato strings, ...), transposed into the cue's key and mode, so the same tune
  can come back in a minor key when the hero is sad and in a major key when he decides to go on;
* harmony pad, bass, an ostinato (kalimba/mbira or marimba patterns) and hand percussion, all chosen by mood.

Each cue is written as ``<cue>.mid`` (open it in MuseScore or any DAW to re-orchestrate) and rendered with
FluidSynth (LGPL, called as a CLI subprocess) and a General MIDI SoundFont (GeneralUser GS, or FluidR3_GM;
see THIRD_PARTY.md). Without FluidSynth a small numpy synth renders the same notes, so tests and CI stay
offline. The melodies are original; the colour (kalimba, marimba, shakers, hand drums, choir) draws on East
and Southern African instruments without quoting any song.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .midi import DRUM_CHANNEL, Note, Track, write_midi
from .music import highpass

SR = 48000

SCALES = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "lydian": [0, 2, 4, 6, 7, 9, 11],
}
MINOR_MODES = {"minor", "dorian"}
KEYS = {
    "C": 0,
    "Db": 1,
    "D": 2,
    "Eb": 3,
    "E": 4,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "Ab": 8,
    "A": 9,
    "Bb": 10,
    "B": 11,
}

# General MIDI programs (0-based) used by the score
GM = {
    "celesta": 8,
    "music_box": 10,
    "marimba": 12,
    "xylophone": 13,
    "acoustic_bass": 32,
    "pizzicato": 45,
    "harp": 46,
    "tremolo_strings": 44,
    "strings": 48,
    "slow_strings": 49,
    "choir_aahs": 52,
    "voice_oohs": 53,
    "tuba": 58,
    "french_horn": 60,
    "clarinet": 71,
    "piccolo": 72,
    "flute": 73,
    "pan_flute": 75,
    "ocarina": 79,
    "kalimba": 108,
}


@dataclass(frozen=True)
class Motif:
    """A leitmotif: scale degrees (None = rest) with durations in beats, its instrument and register."""

    name: str
    character: str
    notes: tuple[tuple[int | None, float], ...]
    program: int
    register: int  # MIDI pitch near which the tonic is placed
    vel: int = 84
    legato: float = 0.9
    double: int | None = None  # program doubling the line an octave below (Tembo's tuba)

    @property
    def beats(self) -> float:
        return sum(d for _, d in self.notes)


# Original melodies. Degrees are relative to the cue's tonic in the cue's mode (7 = octave).
MOTIFS: dict[str, Motif] = {
    m.name: m
    for m in [
        # "The Singing Spring": a rising call that answers itself, ends on the tonic. Kalimba.
        Motif(
            "main",
            "theme",
            (
                (0, 1),
                (1, 0.5),
                (2, 0.5),
                (4, 1),
                (2, 1),
                (5, 1.5),
                (4, 0.5),
                (2, 1),
                (1, 1),
                (0, 1),
                (2, 1),
                (4, 1),
                (7, 1),
                (5, 2),
                (4, 1),
                (0, 1),
            ),
            GM["kalimba"],
            72,
            vel=92,
            legato=1.0,
        ),
        # Tembo: heavy-footed, bouncy, a little clumsy (a stumble on beat 3). Marimba doubled by tuba.
        Motif(
            "tembo",
            "Tembo",
            ((0, 0.5), (0, 0.5), (4, 1), (3, 0.5), (2, 0.5), (1, 1), (0, 0.5), (-3, 0.5), (0, 1), (None, 1)),
            GM["marimba"],
            60,
            vel=96,
            legato=0.7,
            double=GM["tuba"],
        ),
        # Zuri: quick runs up and a show-off leap. Piccolo.
        Motif(
            "zuri",
            "Zuri",
            (
                (0, 0.25),
                (1, 0.25),
                (2, 0.25),
                (4, 0.25),
                (5, 0.5),
                (4, 0.5),
                (7, 1),
                (6, 0.25),
                (5, 0.25),
                (4, 0.5),
                (2, 1),
            ),
            GM["piccolo"],
            74,
            vel=80,
            legato=0.8,
        ),
        # Kiki: repeated-note alarm, a jump, then a nervous scurry down. Pizzicato strings.
        Motif(
            "kiki",
            "Kiki",
            (
                (4, 0.25),
                (4, 0.25),
                (4, 0.25),
                (None, 0.25),
                (7, 0.75),
                (None, 0.25),
                (6, 0.25),
                (5, 0.25),
                (4, 0.25),
                (2, 0.25),
                (None, 1),
            ),
            GM["pizzicato"],
            72,
            vel=100,
            legato=0.5,
        ),
        # Neema: shy start, then a long rising line ("standing tall"). Flute.
        Motif(
            "neema",
            "Neema",
            ((0, 1.5), (2, 0.5), (4, 2), (5, 1), (7, 3)),
            GM["flute"],
            72,
            vel=78,
            legato=1.0,
        ),
        # Bibi Kobe: slow, low, wise; falls and comes home. Hummed voices.
        Motif(
            "bibi",
            "Bibi Kobe",
            ((0, 2), (-1, 1), (-3, 1), (-2, 2), (0, 2)),
            GM["voice_oohs"],
            55,
            vel=90,
            legato=1.0,
        ),
    ]
}


@dataclass(frozen=True)
class Style:
    """How a mood is orchestrated."""

    mode: str
    progression: tuple[int, ...]  # chord roots as scale degrees
    chord_bars: int
    pad: int | None
    ostinato: str | None  # pattern name
    ostinato_program: int | None
    bass: str | None  # pattern name
    bass_program: int | None
    drums: str | None
    intensity: float


STYLES: dict[str, Style] = {
    "wonder": Style(
        "major", (0, 3, 0, 4), 2, GM["slow_strings"], "arp8_sparse", GM["kalimba"], None, None, None, 0.5
    ),
    "worry": Style(
        "minor",
        (0, 5, 3, 4),
        2,
        GM["slow_strings"],
        "arp8_sparse",
        GM["kalimba"],
        "whole",
        GM["acoustic_bass"],
        None,
        0.42,
    ),
    "comedy": Style(
        "major", (0, 3, 4, 0), 1, None, "offbeat", GM["marimba"], "oompah", GM["tuba"], "woodblock", 0.75
    ),
    "droop": Style(
        "minor", (3, 0), 1, GM["slow_strings"], None, None, "whole", GM["acoustic_bass"], None, 0.35
    ),
    "mystery": Style(
        "dorian",
        (0, 3, 0, 6),
        2,
        GM["voice_oohs"],
        "mbira",
        GM["kalimba"],
        "whole",
        GM["acoustic_bass"],
        "shaker_sparse",
        0.45,
    ),
    "adventure": Style(
        "mixolydian",
        (0, 6, 3, 0),
        1,
        GM["strings"],
        "interlock",
        GM["marimba"],
        "sync",
        GM["acoustic_bass"],
        "travel",
        0.82,
    ),
    "tender": Style(
        "major",
        (0, 5, 3, 4),
        2,
        GM["slow_strings"],
        "arp_slow",
        GM["harp"],
        "whole",
        GM["acoustic_bass"],
        None,
        0.4,
    ),
    "sad": Style(
        "minor", (0, 5, 2, 6), 2, GM["slow_strings"], "arp8_sparse", GM["kalimba"], None, None, None, 0.34
    ),
    "tension": Style(
        "minor",
        (0, 0, 5, 4),
        1,
        GM["tremolo_strings"],
        "pulse",
        GM["marimba"],
        "heartbeat",
        GM["acoustic_bass"],
        "heartbeat",
        0.6,
    ),
    "soaring": Style(
        "major",
        (3, 4, 5, 4, 3, 4, 0, 0),
        1,
        GM["choir_aahs"],
        "arp_slow",
        GM["harp"],
        "whole",
        GM["strings"],
        "swell",
        0.85,
    ),
    "night": Style(
        "lydian", (0, 1, 0, 4), 2, GM["choir_aahs"], "twinkle", GM["celesta"], None, None, "triangle", 0.45
    ),
    "build": Style(
        "minor",
        (0, 5, 6, 4),
        1,
        GM["strings"],
        "interlock",
        GM["marimba"],
        "sync",
        GM["acoustic_bass"],
        "build",
        0.7,
    ),
    "triumph": Style(
        "major",
        (0, 4, 5, 3),
        1,
        GM["choir_aahs"],
        "interlock",
        GM["marimba"],
        "sync",
        GM["acoustic_bass"],
        "triumph",
        0.95,
    ),
    "solo": Style("major", (0, 3, 4, 0), 2, None, None, None, None, None, None, 0.45),
}


@dataclass
class Section:
    at: float  # start as a fraction of the cue
    mood: str
    motifs: list[str] = field(default_factory=list)
    mode: str | None = None  # override the mood's mode
    layered: bool = False  # motifs enter one bar apart and overlap
    double: int | None = None  # extra program doubling the melody an octave below (e.g. choir)


@dataclass
class Cue:
    id: str
    scene: str
    seconds: float
    key: str
    bpm: float
    sections: list[Section]
    intent: str = ""
    reprise_of: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> Cue:
        secs = [Section(**s) for s in d.get("sections", [])]
        return cls(
            id=d["id"],
            scene=d.get("scene", d["id"]),
            seconds=float(d["seconds"]),
            key=d["key"],
            bpm=float(d["bpm"]),
            sections=secs,
            intent=d.get("intent", ""),
            reprise_of=d.get("reprise_of"),
        )


def load_cue_sheet(path: str | Path) -> list[Cue]:
    data = json.loads(Path(path).read_text())
    return [Cue.from_dict(c) for c in data["cues"]]


# ---------------------------------------------------------------- arrangement


@dataclass
class Arrangement:
    cue: Cue
    bpm: float  # nudged so a whole number of bars lands exactly on the scene length
    bars: int
    tracks: list[Track]
    bar_moods: list[str]
    bar_modes: list[str]
    bar_chords: list[int]

    @property
    def programs(self) -> list[int]:
        return sorted({t.program for t in self.tracks if t.channel != DRUM_CHANNEL})

    def fingerprint(self) -> str:
        """Identity of the musical material: two cues with the same fingerprint are the same cue."""
        sig = {
            "key": self.cue.key,
            "bpm": round(self.bpm),
            "moods": self.bar_moods,
            "modes": self.bar_modes,
            "chords": self.bar_chords,
            "programs": self.programs,
            "motifs": [s.motifs for s in self.cue.sections],
        }
        return hashlib.sha1(json.dumps(sig, sort_keys=True).encode()).hexdigest()[:12]

    def motif_entries(self) -> list[tuple[str, float]]:
        """(motif, start beat) for every leitmotif statement, from the motif tracks."""
        out = []
        for t in self.tracks:
            if t.name.startswith("motif:") and t.notes:
                name = t.name.split(":", 1)[1]
                out.extend((name, s) for s in t.entries)
        return sorted(out, key=lambda e: e[1])


def _scale(mode: str) -> list[int]:
    return SCALES[mode]


def _pitch(tonic: int, mode: str, deg: int) -> int:
    sc = _scale(mode)
    return tonic + sc[deg % 7] + 12 * (deg // 7)


def _tonic_near(key_pc: int, register: int) -> int:
    base = register - ((register - key_pc) % 12)
    return base + 12 if register - base > 6 else base


def _chord(tonic: int, mode: str, deg: int, dominant: bool = False) -> list[int]:
    notes = [_pitch(tonic, mode, deg + i) for i in (0, 2, 4)]
    if dominant and mode in MINOR_MODES and deg % 7 == 4:
        notes[1] += 1  # harmonic-minor V: a real leading tone for the cadence
    return notes


DRUMS = {  # GM percussion: 16 steps per 4/4 bar -> [(pitch, step, vel)]
    "woodblock": [(76, s, 70) for s in (2, 6, 10, 14)] + [(77, 12, 60), (35, 0, 60), (35, 8, 50)],
    "shaker_sparse": [(70, s, 34 + 10 * (s % 4 == 0)) for s in range(0, 16, 2)],
    "travel": [(70, s, 40 + 18 * (s % 4 == 0)) for s in range(16)]
    + [(64, 0, 90), (63, 6, 70), (62, 8, 62), (64, 10, 84), (60, 13, 58), (61, 14, 66)],
    "heartbeat": [(41, 0, 92), (41, 3, 70), (41, 8, 86), (41, 11, 64)],
    "swell": [(70, s, 30 + 4 * s) for s in range(0, 16, 2)] + [(43, 0, 80)],
    "triangle": [(81, 0, 46), (81, 8, 32)],
    "build": [(64, s, 50 + 3 * s) for s in range(0, 16, 2)] + [(41, 0, 90), (70, 4, 40), (70, 12, 40)],
    "triumph": [(70, s, 44 + 18 * (s % 4 == 0)) for s in range(16)]
    + [
        (41, 0, 100),
        (64, 0, 92),
        (63, 6, 74),
        (62, 8, 66),
        (64, 10, 88),
        (60, 12, 60),
        (61, 14, 70),
        (69, 4, 50),
    ],
}


def _rng(cue_id: str) -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha1(cue_id.encode()).hexdigest()[:8], 16))


def arrange(cue: Cue, beats_per_bar: int = 4) -> Arrangement:
    """Turn a cue into GM tracks. Deterministic for a given cue."""
    rng = _rng(cue.id)
    bar_s = beats_per_bar * 60.0 / cue.bpm
    bars = max(2, round(cue.seconds / bar_s))
    bpm = bars * beats_per_bar * 60.0 / cue.seconds
    key_pc = KEYS[cue.key]
    secs = sorted(cue.sections, key=lambda s: s.at) or [Section(0.0, "wonder")]
    # which section owns each bar
    bar_sec: list[Section] = []
    for b in range(bars):
        frac = b / bars
        cur = secs[0]
        for s in secs:
            if s.at <= frac + 1e-6:
                cur = s
        bar_sec.append(cur)
    bar_moods = [s.mood for s in bar_sec]
    bar_modes = [s.mode or STYLES[s.mood].mode for s in bar_sec]

    # chord per bar: walk each section's progression from its own first bar; cadence V -> I at the end
    bar_chords: list[int] = []
    for b in range(bars):
        st = STYLES[bar_moods[b]]
        first = next(i for i in range(bars) if bar_sec[i] is bar_sec[b])
        idx = ((b - first) // st.chord_bars) % len(st.progression)
        bar_chords.append(st.progression[idx])
    if bars >= 3 and bar_moods[-1] not in ("droop",):
        bar_chords[-2] = 4
    bar_chords[-1] = 0

    pad_tonic = _tonic_near(key_pc, 60)
    bass_tonic = _tonic_near(key_pc, 45)
    ost_tonic = _tonic_near(key_pc, 67)
    tracks: dict[str, Track] = {}
    channels: dict[int, int] = {}  # one MIDI channel per GM program (programs are channel-wide)

    def track(name: str, program: int, drum: bool = False, **kw) -> Track:
        if name not in tracks:
            if drum:
                ch = DRUM_CHANNEL
            else:
                if program not in channels:
                    free = [c for c in range(16) if c != DRUM_CHANNEL and c not in channels.values()]
                    if not free:
                        raise ValueError(f"cue {cue.id}: more than 15 instruments")
                    channels[program] = free[0]
                ch = channels[program]
            tracks[name] = Track(name, ch, program, **kw)
        return tracks[name]

    B = beats_per_bar
    for b in range(bars):
        st = STYLES[bar_moods[b]]
        mode = bar_modes[b]
        last = b == bars - 1
        inten = st.intensity
        if bar_moods[b] == "build":  # crescendo through the section
            first = next(i for i in range(bars) if bar_sec[i] is bar_sec[b])
            span = sum(1 for s in bar_sec if s is bar_sec[b])
            inten = 0.45 + 0.5 * (b - first + 1) / span

        def vel(base: float, inten: float = inten) -> int:
            return int(max(20, min(127, base * (0.55 + 0.5 * inten))))

        chord = _chord(pad_tonic, mode, bar_chords[b], dominant=b == bars - 2)
        t0 = b * B
        if st.pad is not None:
            pad = track(f"pad:{st.pad}", st.pad, volume=78, pan=64, reverb=90, chorus=30)
            for p in chord:
                pad.notes.append(Note(t0, B * (1.25 if last else 1.0), p, vel(62)))
        if st.bass and st.bass_program is not None:
            bs = track(f"bass:{st.bass_program}", st.bass_program, volume=82, pan=58, reverb=30)
            root = _pitch(bass_tonic, mode, bar_chords[b])
            fifth = _pitch(bass_tonic, mode, bar_chords[b] + 4)
            if st.bass == "whole" or last:
                bs.notes.append(Note(t0, B, root, vel(70)))
            elif st.bass == "oompah":
                for k, p in enumerate((root, fifth, root, fifth)):
                    bs.notes.append(Note(t0 + k, 0.45, p - (12 if k % 2 == 0 else 0) + 12, vel(84)))
            elif st.bass == "sync":
                for beat, p, d in (
                    (0, root, 1.4),
                    (1.5, root, 0.5),
                    (2.5, fifth, 0.5),
                    (3.0, root + 12, 0.9),
                ):
                    bs.notes.append(Note(t0 + beat, d, p, vel(80)))
            elif st.bass == "heartbeat":
                bs.notes.append(Note(t0, 0.6, root, vel(78)))
                bs.notes.append(Note(t0 + 0.75, 0.5, root, vel(62)))
        if st.ostinato and st.ostinato_program is not None and not last:
            os_ = track(f"ost:{st.ostinato_program}", st.ostinato_program, volume=76, pan=84, reverb=60)
            ch_tones = [_pitch(ost_tonic, mode, bar_chords[b] + i) for i in (0, 2, 4, 7)]
            pat = st.ostinato
            if pat == "arp8_sparse":
                seq = [(0, 0), (1, 1), (2, 2), (3, 1), (4, 0), (5, 2), (6, 3), (7, 2)]
                for k, i in seq:
                    if rng.random() < 0.8:
                        os_.notes.append(Note(t0 + k * 0.5, 0.9, ch_tones[i], vel(58)))
            elif pat == "arp_slow":
                for k, i in enumerate((0, 1, 2, 3)):
                    os_.notes.append(Note(t0 + k, 1.4, ch_tones[i], vel(54)))
            elif pat == "offbeat":
                for k in range(4):
                    for p in ch_tones[:3]:
                        os_.notes.append(Note(t0 + k + 0.5, 0.25, p, vel(60)))
            elif pat == "mbira":  # 3-against-2: a twelve-pulse figure, as on a lamellophone
                hits = [0, 2, 3, 5, 6, 8, 9, 11]
                for k, h in enumerate(hits):
                    p = ch_tones[(k * 2) % 4] - (12 if k % 3 == 0 else 0)
                    os_.notes.append(Note(t0 + h * B / 12, 0.6, p, vel(52)))
            elif pat == "interlock":  # two marimba voices interlocking in 16ths (3+3+2)
                for s in range(16):
                    if s % 8 in (0, 3, 6):
                        os_.notes.append(Note(t0 + s / 4, 0.3, ch_tones[(s // 3) % 3], vel(64)))
                    elif s % 2 == 1 and rng.random() < 0.45:
                        os_.notes.append(Note(t0 + s / 4, 0.2, ch_tones[3], vel(46)))
            elif pat == "pulse":
                for k in range(8):
                    os_.notes.append(Note(t0 + k * 0.5, 0.3, ch_tones[0] - 12, vel(50 + 6 * (k % 2 == 0))))
            elif pat == "twinkle":
                for k in rng.choice(8, size=3, replace=False):
                    os_.notes.append(Note(t0 + k * 0.5, 1.5, ch_tones[int(rng.integers(0, 4))] + 12, vel(50)))
        if st.drums and not last:
            dr = track("drums", 0, drum=True, volume=86, reverb=40)
            for p, s, v in DRUMS[st.drums]:
                jitter = rng.normal(0, 3)
                dr.notes.append(Note(t0 + s / 4, 0.2, p, vel(v + jitter)))
        if last:  # final chord: ostinato instrument (or kalimba) rings the tonic
            prog = st.ostinato_program or GM["kalimba"]
            os_ = track(f"ost:{prog}", prog, volume=76, pan=84, reverb=60)
            os_.notes.append(Note(t0, B * 1.5, _pitch(ost_tonic, mode, 0), vel(66)))
            if st.pad is None and bar_moods[b] != "solo":  # no pad to hold the cadence: a full button chord
                for deg in (-7, 2, 4):
                    os_.notes.append(Note(t0, B * 1.5, _pitch(ost_tonic, mode, deg), vel(60)))
                hold = track(f"pad:{GM['slow_strings']}", GM["slow_strings"], volume=70, pan=64, reverb=90)
                for p in _chord(pad_tonic, mode, 0):  # strings sustain it into the next scene
                    hold.notes.append(Note(t0, B * 1.25, p, vel(50)))

    # leitmotifs, per section
    for si, sec in enumerate(secs):
        sbars = [b for b in range(bars) if bar_sec[b] is sec]
        if not sbars or not sec.motifs:
            continue
        b0, b1 = sbars[0], sbars[-1] + 1
        if si == 0 and len(sbars) >= 5:
            b0 += 1  # a bar of intro before the first statement
        if b1 == bars and b1 - b0 >= 3:
            b1 -= 1  # keep the cadence bar for the final chord
        cursor = float(b0 * B)
        k = 0
        while cursor < b1 * B - 0.5 and sec.motifs:
            name = sec.motifs[k % len(sec.motifs)]
            m = MOTIFS[name]
            mt = track(f"motif:{name}", m.program, volume=100, pan=[40, 88, 64][k % 3], reverb=70)
            mt.entries.append(cursor)
            dbl = sec.double or m.double
            dt = track(f"double:{dbl}", dbl, volume=70, reverb=70) if dbl is not None else None
            tonic = _tonic_near(key_pc, m.register)
            t = cursor
            for deg, d in m.notes:
                if t >= b1 * B:
                    break
                bar = min(bars - 1, int(t // B))
                if deg is not None:
                    st = STYLES[bar_moods[bar]]
                    v = int(max(30, min(127, m.vel * (0.6 + 0.45 * st.intensity))))
                    dur = min(d * m.legato, b1 * B - t)
                    p = _pitch(tonic, bar_modes[bar], deg)
                    mt.notes.append(Note(t, dur, p, v))
                    if dt is not None:
                        dt.notes.append(Note(t, dur, p - 12, int(v * 0.75)))
                t += d
            k += 1
            if sec.layered:
                cursor += B
            else:
                used = math.ceil(m.beats / B) * B
                gap = B if (b1 * B - (cursor + used)) >= 2 * B else 0
                cursor += used + gap
                if len(sec.motifs) == 1 and gap == 0 and b1 * B - cursor < m.beats * 0.5:
                    break
    return Arrangement(cue, bpm, bars, list(tracks.values()), bar_moods, bar_modes, bar_chords)


# ---------------------------------------------------------------- rendering


def find_soundfont() -> Path | None:
    cands = [os.environ.get("ANIMATICA_SOUNDFONT", "")]
    cache = Path(os.environ.get("ANIMATICA_CACHE", Path.home() / ".cache" / "animatica"))
    cands += [
        str(cache / "soundfonts" / "GeneralUser-GS.sf2"),
        "/usr/share/sounds/sf2/FluidR3_GM.sf2",
        "/usr/share/soundfonts/FluidR3_GM.sf2",
    ]
    for c in cands:
        if c and Path(c).is_file():
            return Path(c)
    return None


def fluidsynth_bin() -> str | None:
    exe = shutil.which("fluidsynth")
    if exe:
        return exe
    cache = Path(os.environ.get("ANIMATICA_CACHE", Path.home() / ".cache" / "animatica"))
    for c in (cache / "fluidsynth" / "bin" / "fluidsynth.exe", cache / "fluidsynth" / "bin" / "fluidsynth"):
        if c.is_file():
            return str(c)
    return None


def renderer() -> str:
    return "fluidsynth" if fluidsynth_bin() and find_soundfont() else "numpy"


def _read(path: Path) -> np.ndarray:
    import wave

    with wave.open(str(path), "rb") as w:
        n, ch, sw, sr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(n)
    if sw == 2:
        a = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif sw == 4:
        a = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width {sw}")
    a = a.reshape(-1, ch)
    if ch == 1:
        a = np.repeat(a, 2, axis=1)
    if sr != SR:
        x = np.linspace(0, len(a) - 1, int(len(a) * SR / sr))
        a = np.stack([np.interp(x, np.arange(len(a)), a[:, c]) for c in range(2)], 1).astype(np.float32)
    return a


def write_wav(path: str | Path, a: np.ndarray, sr: int = SR) -> Path:
    import wave

    path = Path(path)
    pcm = (np.clip(a, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(pcm.shape[1] if pcm.ndim == 2 else 1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


def _render_fluidsynth(mid: Path, gain: float = 0.6) -> np.ndarray:
    exe, sf2 = fluidsynth_bin(), find_soundfont()
    assert exe and sf2
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "o.wav"
        cmd = [
            exe,
            "-ni",
            "-q",
            "-g",
            str(gain),
            "-r",
            str(SR),
            "-o",
            "synth.reverb.active=1",
            "-F",
            str(out),
            str(sf2),
            str(mid),
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        return _read(out)


def _family(program: int) -> str:
    if program in (8, 9, 10, 11, 12, 13, 14, 108):
        return "mallet"
    if program in (45, 46) or 24 <= program <= 31 or 104 <= program <= 107:
        return "pluck"
    if 32 <= program <= 39:
        return "bass"
    if 48 <= program <= 55 or 88 <= program <= 95 or program == 44:
        return "pad"
    return "wind"


def _render_numpy(arr: Arrangement) -> np.ndarray:
    """Offline fallback: a small additive synth that plays the same notes (timbre per instrument family)."""
    spb = 60.0 / arr.bpm
    n = int((arr.bars * 4 * spb + 2.5) * SR)
    out = np.zeros((n, 2), np.float32)
    rng = np.random.default_rng(7)
    for tr in arr.tracks:
        fam = "drum" if tr.channel == DRUM_CHANNEL else _family(tr.program)
        pan = tr.pan / 127
        gain = tr.volume / 127
        for nt in tr.notes:
            s0 = int(nt.start * spb * SR)
            dur = nt.dur * spb
            amp = (nt.vel / 127) ** 1.6 * gain * 0.18
            f = 440 * 2 ** ((nt.pitch - 69) / 12)
            if fam == "drum":
                ln = int(0.25 * SR)
                t = np.arange(ln) / SR
                if nt.pitch in (69, 70, 82):
                    w = rng.standard_normal(ln) * np.exp(-t * 40) * 0.5
                elif nt.pitch in (76, 77, 81):
                    w = np.sin(2 * np.pi * (1800 if nt.pitch != 81 else 4200) * t) * np.exp(
                        -t * (60 if nt.pitch != 81 else 6)
                    )
                else:
                    f0 = {35: 55, 41: 80, 43: 100}.get(nt.pitch, 180 + 20 * (nt.pitch - 60))
                    w = np.sin(2 * np.pi * f0 * t * (1 + 0.5 * np.exp(-t * 30))) * np.exp(-t * 14)
            else:
                rel = {"mallet": 1.2, "pluck": 0.6, "bass": 0.3, "pad": 0.8, "wind": 0.15}[fam]
                ln = int((dur + rel) * SR)
                t = np.arange(ln) / SR
                if fam == "mallet":
                    w = (
                        np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 4 * f * t) * np.exp(-t * 18)
                    ) * np.exp(-t * 3.5)
                elif fam == "pluck":
                    w = (np.sin(2 * np.pi * f * t) + 0.4 * np.sin(4 * np.pi * f * t)) * np.exp(-t * 7)
                else:
                    att = {"bass": 0.01, "pad": 0.35, "wind": 0.06}[fam]
                    env = np.minimum(1, t / att) * np.clip((dur + rel - t) / rel, 0, 1)
                    w = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(4 * np.pi * f * t + 0.3)
                    if fam == "wind":
                        w += 0.04 * rng.standard_normal(ln) * env
                        w *= 1 + 0.03 * np.sin(2 * np.pi * 5.2 * t)
                    w *= env * (0.5 if fam == "pad" else 1.0)
            ln = min(len(w), n - s0)
            if ln <= 0:
                continue
            seg = (w[:ln] * amp).astype(np.float32)
            out[s0 : s0 + ln, 0] += seg * (1 - pan) * 1.4
            out[s0 : s0 + ln, 1] += seg * pan * 1.4
    d = int(0.07 * SR)
    out[d:] += 0.22 * out[:-d, ::-1]
    return out


def _rms_db(a: np.ndarray) -> float:
    return 20 * math.log10(max(1e-9, float(np.sqrt(np.mean(a.astype(np.float64) ** 2)))))


def spectral_centroid(a: np.ndarray) -> float:
    mono = a.mean(axis=1) if a.ndim == 2 else a
    p = np.abs(np.fft.rfft(mono)) ** 2
    f = np.fft.rfftfreq(len(mono), 1 / SR)
    return float((p * f).sum() / max(p.sum(), 1e-12))


def render_cue(arr: Arrangement, out_dir: str | Path, tail: float = 1.5, engine: str | None = None) -> dict:
    """Write ``<id>.mid`` and ``<id>.wav`` (cue length + a reverb tail for the crossfade); return a report."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mid = write_midi(out_dir / f"{arr.cue.id}.mid", arr.tracks, arr.bpm)
    engine = engine or renderer()
    audio = _render_fluidsynth(mid) if engine == "fluidsynth" else _render_numpy(arr)
    n = int((arr.cue.seconds + tail) * SR)
    audio = audio[:n] if len(audio) >= n else np.pad(audio, ((0, n - len(audio)), (0, 0)))
    audio = highpass(audio, 70.0, sr=SR, slope_hz=30.0)  # no rumble under dialogue
    t = np.arange(n) / SR
    fade = np.clip((arr.cue.seconds + tail - t) / tail, 0, 1) ** 1.5
    audio = audio * fade[:, None].astype(np.float32)
    # level: quieter moods sit lower, but every cue is audible (target RMS by intensity)
    inten = float(np.mean([STYLES[m].intensity for m in arr.bar_moods]))
    target = -26.0 + 8.0 * inten
    body = audio[: int(arr.cue.seconds * SR)]
    audio = audio * 10 ** ((target - _rms_db(body)) / 20)
    peak = float(np.abs(audio).max())
    if peak > 0.89:
        audio *= 0.89 / peak
    wav = write_wav(out_dir / f"{arr.cue.id}.wav", audio)
    return {
        "id": arr.cue.id,
        "scene": arr.cue.scene,
        "intent": arr.cue.intent,
        "seconds": arr.cue.seconds,
        "key": arr.cue.key,
        "modes": sorted(set(arr.bar_modes)),
        "moods": [s.mood for s in arr.cue.sections],
        "bpm": round(arr.bpm, 1),
        "bars": arr.bars,
        "programs": arr.programs,
        "motifs": [m for m, _ in arr.motif_entries()],
        "reprise_of": arr.cue.reprise_of,
        "fingerprint": arr.fingerprint(),
        "engine": engine,
        "rms_db": round(_rms_db(audio[: int(arr.cue.seconds * SR)]), 1),
        "centroid_hz": round(spectral_centroid(audio[: int(arr.cue.seconds * SR)])),
        "midi": mid.name,
        "wav": wav.name,
    }


def assemble(cues: list[Cue], cue_dir: str | Path, out: str | Path, xfade: float = 0.6) -> Path:
    """Lay the cue WAVs end to end at their scene starts; each cue's tail crossfades into the next."""
    cue_dir = Path(cue_dir)
    total = sum(c.seconds for c in cues)
    n = int((total + 2.0) * SR)
    mix = np.zeros((n, 2), np.float32)
    start = 0.0
    for c in cues:
        a = _read(cue_dir / f"{c.id}.wav")
        s0 = int(start * SR)
        fin = min(len(a), int(xfade * SR))
        a = a.copy()
        a[:fin] *= np.linspace(0, 1, fin, dtype=np.float32)[:, None] ** 0.5
        ln = min(len(a), n - s0)
        mix[s0 : s0 + ln] += a[:ln]
        start += c.seconds
    return write_wav(out, mix[: int((total + 1.0) * SR)])


def score_film(cue_sheet: str | Path, out_dir: str | Path, engine: str | None = None) -> dict:
    """Arrange and render every cue of a cue sheet, then assemble ``score.wav``; writes ``score.json``."""
    cues = load_cue_sheet(cue_sheet)
    out_dir = Path(out_dir)
    reports = [render_cue(arrange(c), out_dir, engine=engine) for c in cues]
    score = assemble(cues, out_dir, out_dir / "score.wav")
    rep = {
        "cue_sheet": str(cue_sheet),
        "renderer": reports[0]["engine"] if reports else None,
        "cues": reports,
        "score": score.name,
    }
    (out_dir / "score.json").write_text(json.dumps(rep, indent=2))
    return rep
