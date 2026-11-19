"""The film's hand-off files (CHALLENGE-SAVANNAH "Output"): captions, the edit, the production log and the poster.

Everything here is built from the scene reports ``savannah_scene.py`` writes (``report.json``: the scene's
seconds, its shots with their subjects and frames, its lines with their exact text and timings, the voice engine
and Whisper's word error, continuity findings and render time) and the film/trailer reports of
``savannah_film.py``. Nothing is transcribed: captions carry the screenplay's words at the times the takes were
placed. The scenes are joined end to end (the title and end cards are drawn over the first and last shots, they
add no time), so a scene starts in the film at the sum of the scenes before it.

* ``caption_cues`` / ``write_srt`` / ``write_vtt``: one cue per line, at most two lines of ``MAX_CHARS``
  characters, split at sentence ends when a line is longer than that; held ``HOLD_S`` after the speech and at
  least ``MIN_S`` on screen when there is room, never overlapping the next cue (``GAP_S`` between them). The
  narrator is in italics, and a speaker who isn't in the shot is named (``ZURI: ...``), as in SDH captions.
  Cues read faster than ``MAX_CPS`` characters a second are listed (timing follows the voices, so they are
  reported, not changed).
* ``write_mlt``: an MLT timeline (Shotcut / Kdenlive / ``melt``) of the scene renders, one entry per shot, so
  the cuts are visible and every shot can be trimmed or re-ordered.
* ``production_log``: Markdown, deterministic (no wall-clock time of its own).
* ``poster_time`` / ``write_poster``: a frame from the first daytime medium shot of the lead with a friend, the title
  set in a band at the bottom.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from ..audio.delivery import plain

MAX_CHARS = 42  # per caption line (broadcast and web norm)
MAX_LINES = 2
MIN_S = 1.0  # a cue stays at least this long when the next one allows it
HOLD_S = 0.3  # held after the voice ends
GAP_S = 2 / 24  # two frames between cues, so a reader sees the change
MAX_CPS = 17.0  # reading speed for children 4-9 (adult norm is ~20)
NARRATOR = "narrator"
MEDIUM = {"ms": 3, "mcu": 2, "ws": 1}  # poster preference by shot type


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str  # caption lines joined by "\n", markup applied (italics, speaker label)
    who: str
    scene: str

    @property
    def chars(self) -> int:
        return len(re.sub(r"<[^>]+>", "", self.text).replace("\n", " "))

    @property
    def cps(self) -> float:
        return self.chars / max(1e-6, self.end - self.start)


def display_name(cid: str) -> str:
    return " ".join(w.capitalize() for w in cid.split("_"))


def offsets(reports: list[dict[str, Any]]) -> list[float]:
    """Each scene's start in the film (scenes are joined end to end)."""
    out, t = [], 0.0
    for r in reports:
        out.append(t)
        t += float(r["seconds"])
    return out


def wrap(text: str, width: int = MAX_CHARS) -> list[str]:
    """One line if it fits, else two lines broken at the space that balances them best (never a lone word
    hanging if a balanced break exists). Longer text is the caller's job (``split_sentences``)."""
    text = " ".join(text.split())
    if len(text) <= width:
        return [text]
    spaces = [i for i, c in enumerate(text) if c == " "]
    if not spaces:
        return [text]
    best = min(spaces, key=lambda i: (max(i, len(text) - i - 1) > width, abs(len(text) - 2 * i)))
    return [text[:best], text[best + 1 :]]


def split_sentences(text: str, limit: int = MAX_CHARS * MAX_LINES) -> list[str]:
    """Chunks of at most ``limit`` characters, cut after sentence ends (. ! ? ...), else at commas, else at
    spaces, filled greedily."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return [text]
    parts = [p for p in re.split(r"(?<=[.!?…])\s+", text) if p]
    out: list[str] = []
    for p in parts:
        pieces = [p] if len(p) <= limit else _split_long(p, limit)
        for q in pieces:
            if out and len(out[-1]) + 1 + len(q) <= limit:
                out[-1] += " " + q
            else:
                out.append(q)
    return out


def _split_long(p: str, limit: int) -> list[str]:
    for sep in (r"(?<=[,;:—])\s+", r"\s+"):
        bits = re.split(sep, p)
        if len(bits) > 1:
            out: list[str] = []
            for b in bits:
                if out and len(out[-1]) + 1 + len(b) <= limit:
                    out[-1] += " " + b
                else:
                    out.append(b)
            if all(len(x) <= limit for x in out):
                return out
    return [p]


def _shot_at(report: dict[str, Any], t: float) -> dict[str, Any] | None:
    shots = report.get("shots") or []
    hit = [s for s in shots if s["start"] <= t + 1e-6]
    return hit[-1] if hit else (shots[0] if shots else None)


def caption_cues(reports: list[dict[str, Any]], names: dict[str, str] | None = None) -> list[Cue]:
    names = names or {}
    raw: list[tuple[float, float, str, str, str]] = []  # start, speech end, text, who, scene
    for off, r in zip(offsets(reports), reports, strict=True):
        for ln in r.get("lines", []):
            who = ln["who"]
            words = plain(ln["text"]).strip()
            if not words:
                continue
            s0, s1 = off + float(ln["start"]), off + float(ln["end"])
            if who != NARRATOR:
                shot = _shot_at(r, float(ln["start"]))
                if shot is not None and who not in shot.get("subjects", []):
                    words = f"{names.get(who, display_name(who)).upper()}: {words}"
            chunks = split_sentences(words)
            total = sum(len(c) for c in chunks)
            t = s0
            for c in chunks:
                dt = (s1 - s0) * len(c) / total
                raw.append((t, t + dt, c, who, r["scene"]))
                t += dt
    film_end = sum(float(r["seconds"]) for r in reports)
    cues = []
    for i, (a, b, text, who, scene) in enumerate(raw):
        nxt = raw[i + 1][0] if i + 1 < len(raw) else film_end
        limit = max(a + 0.2, nxt - GAP_S)
        end = min(max(b + HOLD_S, a + MIN_S), limit, film_end)
        lines = wrap(text)
        if who == NARRATOR:
            lines = [f"<i>{x}</i>" for x in lines]
        cues.append(Cue(round(a, 3), round(end, 3), "\n".join(lines), who, scene))
    return cues


def _ts(t: float, sep: str) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def write_srt(cues: list[Cue], out: str | Path) -> Path:
    body = "\n".join(
        f"{i}\n{_ts(c.start, ',')} --> {_ts(c.end, ',')}\n{c.text}\n" for i, c in enumerate(cues, 1)
    )
    Path(out).write_text(body, encoding="utf-8")
    return Path(out)


def write_vtt(cues: list[Cue], out: str | Path, lang: str = "en") -> Path:
    blocks = [f"WEBVTT\nLanguage: {lang}\n"]
    blocks += [f"{_ts(c.start, '.')} --> {_ts(c.end, '.')}\n{c.text}\n" for c in cues]
    Path(out).write_text("\n".join(blocks), encoding="utf-8")
    return Path(out)


def caption_issues(cues: list[Cue]) -> list[str]:
    out = []
    for i, c in enumerate(cues):
        lines = re.sub(r"<[^>]+>", "", c.text).split("\n")
        if len(lines) > MAX_LINES or any(len(x) > MAX_CHARS for x in lines):
            out.append(f"{_ts(c.start, '.')} too long for {MAX_LINES}x{MAX_CHARS}: {c.text!r}")
        if c.cps > MAX_CPS:
            out.append(f"{_ts(c.start, '.')} {c.cps:.0f} chars/s ({c.who}, {c.scene}): {lines[0]!r}")
        if i + 1 < len(cues) and c.end > cues[i + 1].start - GAP_S + 1e-6:
            out.append(f"{_ts(c.start, '.')} overlaps the next cue")
    return out


# ---- the edit


def write_mlt(
    reports: list[dict[str, Any]],
    clips: list[str],
    out: str | Path,
    title: str,
    fps: int = 24,
    resolution: tuple[int, int] = (1280, 720),
) -> Path:
    """One avformat producer per scene render (``clips``, written as given: relative paths resolve from the
    .mlt's folder), one playlist entry per shot (in/out in the scene's frames), picture and sound together.
    The title and end cards and the -14 LUFS master are applied after the edit (``savannah_film.py``)."""
    w, h = resolution
    x = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<mlt LC_NUMERIC="C" version="7.0.0" title={quoteattr(title)} producer="main_bin">',
        f'  <profile description="Animatica {w}x{h} {fps}fps" width="{w}" height="{h}" progressive="1" '
        f'sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="{w}" display_aspect_den="{h}" '
        f'frame_rate_num="{fps}" frame_rate_den="1" colorspace="709"/>',
    ]
    total = 0
    for r, clip in zip(reports, clips, strict=True):
        n = int(round(float(r["seconds"]) * fps))
        total += n
        x.append(
            f'  <producer id="{escape(r["scene"])}" in="0" out="{n - 1}">'
            f'<property name="resource">{escape(clip)}</property>'
            '<property name="mlt_service">avformat</property>'
            f'<property name="shotcut:caption">{escape(r["scene"] + " " + r.get("title", ""))}</property>'
            "</producer>"
        )
    x.append('  <playlist id="V1">')
    for r in reports:
        n = int(round(float(r["seconds"]) * fps))
        shots = r.get("shots") or [{"shot": 0, "type": "", "start": 0.0, "end": float(r["seconds"])}]
        for k, s in enumerate(shots):
            f0 = int(round(float(s["start"]) * fps))
            f1 = n if k + 1 == len(shots) else int(round(float(shots[k + 1]["start"]) * fps))
            if f1 <= f0:
                continue
            label = f"{r['scene']} shot {s['shot']} {s.get('type', '')}".strip()
            x.append(
                f'    <entry producer="{escape(r["scene"])}" in="{f0}" out="{f1 - 1}">'
                f'<property name="shot">{escape(label)}</property></entry>'
            )
    x.append("  </playlist>")
    x.append(f'  <tractor id="edit" in="0" out="{total - 1}">')
    x.append('    <track producer="V1"/>')
    x.append("  </tractor>")
    x.append("</mlt>")
    Path(out).write_text("\n".join(x) + "\n", encoding="utf-8")
    return Path(out)


# ---- the production log


def _mmss(t: float) -> str:
    return f"{int(t // 60)}:{t % 60:04.1f}"


def production_log(
    reports: list[dict[str, Any]],
    title: str,
    film: dict[str, Any] | None = None,
    trailer: dict[str, Any] | None = None,
    cues: list[Cue] | None = None,
) -> str:
    offs = offsets(reports)
    total = sum(float(r["seconds"]) for r in reports)
    lines_all = [ln for r in reports for ln in r.get("lines", [])]
    shots_all = [s for r in reports for s in r.get("shots", [])]
    render_s = [r.get("render_seconds") or 0.0 for r in reports]
    out = [
        f"# Production log: {title}",
        "",
        f"* Runtime **{_mmss(total)}** ({total:.1f} s), {len(reports)} scenes, {len(shots_all)} shots, "
        f"{len(lines_all)} lines.",
    ]
    qualities = sorted({str(r.get("quality")) for r in reports})
    out.append(
        f"* Render quality: {', '.join(qualities)}; render time {sum(render_s) / 3600:.1f} h in total."
    )
    if film:
        out.append(
            f"* Master: {film.get('lufs', film.get('target_lufs'))} LUFS integrated, true peak "
            f"{film.get('true_peak_dbtp', '?')} dBTP (web copy {film.get('web_true_peak_dbtp', '?')} dBTP); web copy "
            f"{film.get('web_mb', '?')} MB."
        )
    if trailer:
        out.append(f"* Trailer: {trailer.get('seconds', '?')} s, {len(trailer.get('cuts', []))} cuts.")
    out += [
        "",
        "## Scenes",
        "",
        "| Scene | Title | Starts | Length | Shots | Longest shot | Lines | Render |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for off, r in zip(offs, reports, strict=True):
        shots = r.get("shots", [])
        longest = max((s["end"] - s["start"] for s in shots), default=0.0)
        rs = r.get("render_seconds")
        out.append(
            f"| {r['scene']} | {r.get('title', '')} | {_mmss(off)} | {float(r['seconds']):.1f} s | {len(shots)} | "
            f"{longest:.1f} s | {len(r.get('lines', []))} | {f'{rs / 60:.0f} min' if rs else '-'} |"
        )
    engines: dict[str, int] = {}
    for ln in lines_all:
        engines[ln.get("engine", "?")] = engines.get(ln.get("engine", "?"), 0) + 1
    wers = [float(ln["wer"]) for ln in lines_all if ln.get("wer") is not None]
    out += ["", "## Voices", ""]
    out.append("* Engines: " + ", ".join(f"{k} {v}" for k, v in sorted(engines.items())) + ".")
    if wers:
        out.append(
            f"* Whisper word error (heard vs. written): mean {sum(wers) / len(wers):.2f}, worst {max(wers):.2f}."
        )
    fallbacks = [(r["scene"], ln) for r in reports for ln in r.get("lines", []) if ln.get("fallback")]
    if fallbacks:
        out.append(f"* Fallbacks ({len(fallbacks)}):")
        out += [f'  * {sc} {ln["who"]}: "{plain(ln["text"])}"' for sc, ln in fallbacks]
    else:
        out.append("* No fallbacks.")
    out += ["", "## Music", ""]
    for r in reports:
        c = r.get("cue") or {}
        if c:
            moods = ", ".join(c.get("moods", [])) if isinstance(c.get("moods"), list) else c.get("moods", "")
            out.append(f"* {r['scene']}: cue `{c.get('id', '?')}`, {c.get('bpm', '?')} bpm, {moods}.")
    found = [(r["scene"], v) for r in reports for v in r.get("continuity", [])]
    warns = [(r["scene"], w) for r in reports for w in r.get("warnings", [])]
    out += ["", "## Continuity and warnings", ""]
    out += [f"* {sc}: {v}" for sc, v in found] or ["* Continuity: none found."]
    out += [f"* {sc} (warning): {w}" for sc, w in warns]
    if cues is not None:
        issues = caption_issues(cues)
        out += ["", "## Captions", "", f"* {len(cues)} cues; reading speed limit {MAX_CPS:.0f} chars/s."]
        out += [f"* {i}" for i in issues] or ["* No caption issues."]
    return "\n".join(out) + "\n"


# ---- the poster


def lead(reports: list[dict[str, Any]]) -> str:
    """The character with the most lines (the narrator aside)."""
    n: dict[str, int] = {}
    for r in reports:
        for ln in r.get("lines", []):
            if ln["who"] != NARRATOR:
                n[ln["who"]] = n.get(ln["who"], 0) + 1
    return max(sorted(n), key=lambda k: n[k]) if n else ""


def poster_time(reports: list[dict[str, Any]], hero: str | None = None) -> float:
    """Film time of the poster frame: the middle of the first daytime medium shot of the lead with one or two
    friends. Wides are a last resort: with the whole cast in them every animal is a few pixels tall at
    poster size (a night scene's title starts with "Night")."""
    hero = lead(reports) if hero is None else hero
    best: tuple[tuple[int, ...], float] | None = None
    for off, r in zip(offsets(reports), reports, strict=True):
        day = 0 if str(r.get("title", "")).lower().startswith("night") else 1
        for s in r.get("shots", []):
            subj = s.get("subjects", [])
            key = (
                day,
                int(hero in subj),
                int(2 <= len(subj) <= 3),
                MEDIUM.get(s.get("type", ""), 0),
                -round((off + s["start"]) * 1000),
            )
            t = off + (float(s["start"]) + float(s["end"])) / 2
            if best is None or key > best[0]:
                best = (key, t)
    return best[1] if best else 0.0


def write_poster(
    video: str | Path, t: float, out: str | Path, title: str, tagline: str = "", width: int = 1280
) -> Path:
    """The frame at ``t`` (scaled to ``width``), a dark band fading up from the bottom and the title on it."""
    from PIL import Image, ImageDraw

    from ..audio.mux import _font

    out = Path(out)
    frame = out.with_suffix(".frame.png")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1"]
        + ["-vf", f"scale={width}:-2:flags=lanczos", str(frame)],
        check=True,
        timeout=120,
    )
    im = Image.open(frame).convert("RGB")
    frame.unlink()
    w, h = im.size
    band = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(band)
    top = int(h * 0.62)
    for y in range(top, h):
        d.line([(0, y), (w, y)], fill=int(190 * ((y - top) / (h - top)) ** 1.4))
    im = Image.composite(Image.new("RGB", (w, h), (20, 14, 8)), im, band)
    d = ImageDraw.Draw(im)
    f1 = _font(int(h * 0.085))
    tw = d.textlength(title, font=f1)
    ty = int(h * (0.80 if tagline else 0.84))
    for dx, dy, col in ((3, 3, (0, 0, 0)), (0, 0, (255, 236, 200))):
        d.text(((w - tw) / 2 + dx, ty + dy), title, font=f1, fill=col, anchor="lm")
    if tagline:
        f2 = _font(int(h * 0.036))
        sw = d.textlength(tagline, font=f2)
        d.text(((w - sw) / 2, int(h * 0.90)), tagline, font=f2, fill=(235, 220, 190), anchor="lm")
    im.save(out, quality=90)
    return out
