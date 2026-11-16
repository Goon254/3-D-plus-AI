"""A tiny Standard MIDI File (SMF type 1) writer and reader: no dependency, deterministic bytes.

The Composer builds :class:`Note` lists per track; :func:`write_midi` turns them into a ``.mid`` that
FluidSynth (or any DAW: MuseScore, Ardour, LMMS) can open, so an artist can re-orchestrate the AI's score.
:func:`read_notes` parses a file back (used by tests and by the score report).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

PPQ = 480
DRUM_CHANNEL = 9


@dataclass(frozen=True)
class Note:
    start: float  # beats
    dur: float  # beats
    pitch: int
    vel: int = 80


@dataclass
class Track:
    name: str
    channel: int
    program: int  # General MIDI program, 0-based (ignored on the drum channel)
    notes: list[Note] = field(default_factory=list)
    volume: int = 100  # CC7
    pan: int = 64  # CC10
    reverb: int = 50  # CC91
    chorus: int = 0  # CC93
    entries: list[float] = field(default_factory=list)  # composer: start beats of each motif statement


def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def _chunk(kind: bytes, data: bytes) -> bytes:
    return kind + struct.pack(">I", len(data)) + data


def _ticks(beats: float) -> int:
    return int(round(beats * PPQ))


def write_midi(path: str | Path, tracks: list[Track], bpm: float, beats_per_bar: int = 4) -> Path:
    """Write a type-1 SMF: a conductor track (tempo, metre) and one track per instrument."""
    path = Path(path)
    tempo_us = int(round(60_000_000 / bpm))
    conductor = (
        b"\x00\xff\x51\x03"
        + tempo_us.to_bytes(3, "big")
        + b"\x00\xff\x58\x04"
        + bytes([beats_per_bar, 2, 24, 8])
        + b"\x00\xff\x2f\x00"
    )
    chunks = [_chunk(b"MTrk", conductor)]
    for tr in tracks:
        ch = tr.channel & 0x0F
        name = tr.name.encode("ascii", "replace")[:64]
        head = b"\x00\xff\x03" + _vlq(len(name)) + name
        if ch != DRUM_CHANNEL:
            head += bytes([0x00, 0xC0 | ch, tr.program & 0x7F])
        for cc, val in ((7, tr.volume), (10, tr.pan), (91, tr.reverb), (93, tr.chorus)):
            head += bytes([0x00, 0xB0 | ch, cc, max(0, min(127, val))])
        events: list[tuple[int, int, bytes]] = []  # (tick, order: offs before ons, bytes)
        for n in tr.notes:
            t0 = _ticks(n.start)
            t1 = max(t0 + 1, _ticks(n.start + n.dur))
            p = max(0, min(127, n.pitch))
            events.append((t0, 1, bytes([0x90 | ch, p, max(1, min(127, n.vel))])))
            events.append((t1, 0, bytes([0x80 | ch, p, 0])))
        events.sort(key=lambda e: (e[0], e[1]))
        body = bytearray(head)
        last = 0
        for tick, _, msg in events:
            body += _vlq(tick - last) + msg
            last = tick
        body += b"\x00\xff\x2f\x00"
        chunks.append(_chunk(b"MTrk", bytes(body)))
    header = _chunk(b"MThd", struct.pack(">HHH", 1, len(chunks), PPQ))
    path.write_bytes(header + b"".join(chunks))
    return path


def _read_vlq(data: bytes, i: int) -> tuple[int, int]:
    n = 0
    while True:
        b = data[i]
        i += 1
        n = (n << 7) | (b & 0x7F)
        if not b & 0x80:
            return n, i


def read_notes(path: str | Path) -> dict:
    """Parse an SMF back into ``{"bpm", "tracks": [{"name", "channel", "program", "notes": [...]}]}``."""
    data = Path(path).read_bytes()
    assert data[:4] == b"MThd", "not a MIDI file"
    _fmt, ntrk, ppq = struct.unpack(">HHH", data[8:14])
    i = 14
    bpm = 120.0
    tracks = []
    for _ in range(ntrk):
        assert data[i : i + 4] == b"MTrk"
        (ln,) = struct.unpack(">I", data[i + 4 : i + 8])
        j, end = i + 8, i + 8 + ln
        tick, status = 0, 0
        tr = {"name": "", "channel": None, "program": None, "notes": []}
        open_notes: dict[tuple[int, int], tuple[int, int]] = {}
        while j < end:
            dt, j = _read_vlq(data, j)
            tick += dt
            b = data[j]
            if b == 0xFF:
                kind = data[j + 1]
                mlen, j = _read_vlq(data, j + 2)
                payload = data[j : j + mlen]
                j += mlen
                if kind == 0x51:
                    bpm = 60_000_000 / int.from_bytes(payload, "big")
                elif kind == 0x03:
                    tr["name"] = payload.decode("ascii", "replace")
                continue
            if b & 0x80:
                status = b
                j += 1
            hi, ch = status & 0xF0, status & 0x0F
            if hi in (0xC0, 0xD0):
                if hi == 0xC0:
                    tr["program"] = data[j]
                j += 1
                continue
            a, v = data[j], data[j + 1]
            j += 2
            if hi in (0x80, 0x90):
                tr["channel"] = ch
                if hi == 0x90 and v > 0:
                    open_notes[(ch, a)] = (tick, v)
                elif (ch, a) in open_notes:
                    t0, vel = open_notes.pop((ch, a))
                    tr["notes"].append(Note(t0 / ppq, (tick - t0) / ppq, a, vel))
        tr["notes"].sort(key=lambda n: (n.start, n.pitch))
        tracks.append(tr)
        i = end
    return {"bpm": bpm, "tracks": tracks}
