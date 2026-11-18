"""Render a standard character design sheet (DESIGN_STAGE.md §3) and score it (§4).

    python scripts/design_sheet.py kiki                         # the current design
    python scripts/design_sheet.py kiki --morph '{"head": 1.1}'  # a candidate
    python scripts/design_sheet.py --all --out output/design     # the whole cast

Fixed lights and cameras so sheets compare across candidates and characters: front, side (facing left),
3/4, back, a black silhouette (from the side view's alpha), a 96 px thumbnail (from the 3/4 view) and a face
close-up with three expressions. Cycles on the configured device (CPU is fine: ~10 s per view at 512 px);
the neutral backdrop is the world, and frames are RGBA so silhouettes are exact.

Writes ``<out>/<character>/<tag>/``: ``views/*.png``, ``silhouette.png``, ``thumb96.png``, ``sheet.png`` and
``score.json`` (rubric result with the image checks and, when available, the vision critique).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import textwrap
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from animatica.core.engine import BlenderSession  # noqa: E402
from animatica.creatures.build import build_creature  # noqa: E402
from animatica.creatures.face import BROW_COLOR, face_keys, face_ops, refresh_rest  # noqa: E402
from animatica.creatures.gait import GAITS, Waypoint  # noqa: E402
from animatica.creatures.perform import walk_keys  # noqa: E402
from animatica.creatures.qa import outline_probe, outline_summary  # noqa: E402
from animatica.creatures.species import SPECIES, Species  # noqa: E402
from animatica.design.brief import Brief, all_briefs, load_brief  # noqa: E402
from animatica.design.critic import critique_for  # noqa: E402
from animatica.design.image_checks import (  # noqa: E402
    expression_change,
    floating_parts,
    load_mask,
    sheet_metrics,
)
from animatica.design.measure import describe  # noqa: E402
from animatica.design.rubric import score  # noqa: E402
from animatica.design.variants import Morph, apply_morph, morph_from_dict  # noqa: E402

BACKDROP = (222, 219, 212)
LENS = 85.0
VIEWS = {  # camera direction from the subject (unit-ish), the animal faces -Y
    "front": (0.0, -1.0, 0.12),
    "side": (1.0, 0.0, 0.08),  # from the animal's left: head on the image's left
    "three_quarter": (0.72, -0.72, 0.2),
    "back": (0.0, 1.0, 0.15),
}
FACE_DIR = (0.5, -1.0, 0.1)  # the face close-up's camera direction
FACE_TRACK = [(0.0, "neutral"), (0.6, "happy"), (1.6, "surprised")]
FACE_FRAMES = {"neutral": 8, "happy": 35, "surprised": 59}


def _run(eng: BlenderSession, bid: str, ops: list[dict]) -> dict:
    r = eng.run_batch({"batch_id": bid, "ops": ops})
    if not r.ok:
        raise SystemExit(json.dumps({"batch": bid, "errors": r.errors[:6]}, indent=1))
    return r.data


def extents(sp: Species, meta: Any) -> tuple[tuple[float, float, float], float]:
    """World-space centre of the figure and a framing radius (the figure stands at the origin, yaw 0)."""
    hl, hh = sp.head_size[1], sp.head_size[2]
    nose = min(sp.head_at[1] - hl / 2, sp.trunk.tip[1] if sp.trunk else 0.0)
    tail = max(sp.tail.tip[1], sp.torso[1] / 2, sp.shell[0][1] / 2 if sp.shell else 0.0)
    top = max(meta.head_height + hh * 0.9, sp.body_z + sp.torso[2] / 2)
    for ex in sp.extras:
        if ex.bone == "head":
            top = max(top, meta.head_height + ex.loc[2] + ex.size[2])
    cy, cz = (nose + tail) / 2, top / 2
    r = 0.5 * max(tail - nose, top) * 1.12
    return (0.0, cy, cz), r


def _cam(
    eng: BlenderSession, tag: str, aim: tuple[float, float, float], direction: tuple[float, ...], r: float
) -> None:
    n = math.sqrt(sum(c * c for c in direction))
    d = r / math.tan(math.atan(18.0 / LENS)) * 1.04
    loc = [round(aim[i] + direction[i] / n * d, 4) for i in range(3)]
    _run(
        eng,
        f"cam_{tag}",
        [
            {"op": "create_empty", "id": f"aim_{tag}", "location": [round(v, 4) for v in aim]},
            {"op": "add_camera", "id": f"cam_{tag}", "location": loc, "lens": LENS, "look_at": f"aim_{tag}"},
            {"op": "set_camera_active", "id": f"cam_{tag}"},
        ],
    )


def _render(eng: BlenderSession, tag: str, frame: int, out: Path) -> Path:
    d = out / "_frames" / tag
    _run(
        eng,
        f"r_{tag}",
        [{"op": "render_final", "output_dir": str(d), "frame_start": frame, "frame_end": frame}],
    )
    src = next(d.glob("*.png"))
    dst = out / "views" / f"{tag}.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dst)
    return dst


def render_views(
    cid: str, sp: Species, out: Path, res: int = 512, samples: int = 16, device: str = "auto"
) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    ops, meta = build_creature(cid, sp, at=(0.0, 0.0), yaw=0.0)
    fops, face = face_ops(sp.name, sp, meta.root, meta.rig, BROW_COLOR[sp.name])
    n = 64
    paths: dict[str, Path] = {}
    with BlenderSession(workdir=out) as eng:
        _run(
            eng,
            "stage",
            [
                {"op": "set_world", "zenith": "#C9C6BF", "horizon": "#E2DED6", "strength": 0.9},
                {
                    "op": "add_light",
                    "id": "key",
                    "light_type": "sun",
                    "energy": 3.2,
                    "color": "#FFF1DC",
                    "rotation": [50, 0, 30],
                    "size": 3.0,
                },
                {
                    "op": "add_light",
                    "id": "rim",
                    "light_type": "sun",
                    "energy": 1.2,
                    "color": "#DCE6FF",
                    "rotation": [60, 0, 200],
                    "size": 4.0,
                },
            ],
        )
        _run(eng, "creature", ops + fops)
        q = _run(
            eng,
            "q",
            [{"op": "query", "ids": [b["id"] for b in face["brows"].values()], "fields": ["transform"]}],
        )
        refresh_rest(face, q["objects"])
        _run(
            eng,
            "anim",
            face_keys(face, FACE_TRACK, None, 24, 1, n)
            + [{"op": "set_frame_range", "start": 1, "end": n, "fps": 24}],
        )
        _run(
            eng,
            "render",
            [
                {
                    "op": "set_render",
                    "engine": "cycles",
                    "resolution": [res, res],
                    "samples": samples,
                    "device": device,
                    "look": "AgX - Medium High Contrast",
                    "transparent": True,
                }
            ],
        )
        aim, r = extents(sp, meta)
        # the eyes and brows against the head's outline, from the sheet's own directions (face close-up included)
        brows = [b["id"] for b in face["brows"].values()]
        # (not the back view: there the ears, neck or shell stand in front of the head, and nobody reads a face)
        ol_views = {k: v for k, v in VIEWS.items() if k != "back"} | {"face": FACE_DIR}
        q = _run(eng, "outline", [outline_probe(meta, brows, ol_views, FACE_FRAMES["neutral"])])
        outline = outline_summary(q["inspect"], list(ol_views), list(meta.eyes), brows)
        for tag, direction in VIEWS.items():
            _cam(eng, tag, aim, direction, r)
            paths[tag] = _render(eng, tag, FACE_FRAMES["neutral"], out)
        head = (0.0, sp.head_at[1], meta.head_height + sp.head_size[2] * 0.12)
        hr = max(sp.head_size) * 0.8 + (0.12 * max(sp.head_size) if sp.ear[0] == "disc" else 0.0)
        _cam(eng, "face", head, FACE_DIR, hr)
        for expr, f in FACE_FRAMES.items():
            paths[f"face_{expr}"] = _render(eng, f"face_{expr}", f, out)
        if sp.default_pose != "stand":  # the signature pose (the meerkat's sentinel), side on
            pts = [Waypoint(0.0, 0.0, 0.0), Waypoint(n / 24, 0.0, 0.0)]
            keys, _plan = walk_keys(meta, GAITS[sp.name]["walk"], pts, 24, 1, seed=1, yaw0=0.0)
            _run(eng, "pose", keys)
            q = _run(
                eng, "c", [{"op": "inspect", "subjects": [meta.root], "frames": [FACE_FRAMES["neutral"]]}]
            )
            c = q["inspect"]["frames"][str(FACE_FRAMES["neutral"])]["subjects"][meta.root]["center"]
            _cam(eng, "pose", (0.0, c[1], c[2]), VIEWS["side"], r * 1.3)
            q = _run(
                eng,
                "outline_pose",
                [outline_probe(meta, brows, {"pose": VIEWS["side"]}, FACE_FRAMES["neutral"])],
            )
            pose = outline_summary(q["inspect"], ["pose"], list(meta.eyes), brows)
            outline["views"]["pose"] = pose["views"]["pose"]
            for k in ("eye", "brow"):
                if pose[k] > outline[k]:
                    outline[k], outline[f"{k}_view"] = pose[k], "pose"
            paths["pose"] = _render(eng, "pose", FACE_FRAMES["neutral"], out)
    # written next to the views, so --rescore scores the same render with the same measurement
    (out / "outline.json").write_text(json.dumps(outline, indent=1) + "\n", encoding="utf-8")
    return paths


def _on_backdrop(p: Path) -> Image.Image:
    im = Image.open(p).convert("RGBA")
    bg = Image.new("RGBA", im.size, (*BACKDROP, 255))
    return Image.alpha_composite(bg, im).convert("RGB")


def silhouette(side: Path, out: Path, name: str = "silhouette.png") -> Path:
    a = Image.open(side).convert("RGBA").getchannel("A")
    sil = Image.new("RGB", a.size, (255, 255, 255))
    sil.paste((0, 0, 0), mask=a.point(lambda v: 255 if v > 127 else 0))
    p = out / name
    sil.save(p)
    return p


def thumbnail(src: Path, out: Path) -> Path:
    im = _on_backdrop(src)
    im.thumbnail((96, 96), Image.Resampling.LANCZOS)
    p = out / "thumb96.png"
    im.save(p)
    return p


def compose(
    character: str,
    views: dict[str, Path],
    sil: Path,
    thumb: Path,
    result: dict[str, Any],
    out: Path,
    label: str,
) -> Path:
    tile = Image.open(views["front"]).size[0]
    pad, head = 12, 46
    top = ["front", "side", "three_quarter", "back"] + (["pose"] if "pose" in views else [])
    w = pad + len(top) * (tile + pad)
    face_t = tile // 2
    h = head + tile + pad + tile + pad + 140
    sheet = Image.new("RGB", (w, h), (246, 244, 239))
    dr = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=22)
    small = ImageFont.load_default(size=15)
    # Pillow's built-in font has no em dash (it drew a box): plain ASCII separators only
    dr.text((pad, 12), f"{character}: {label}", fill=(30, 30, 30), font=font)
    for i, tag in enumerate(top):
        x = pad + i * (tile + pad)
        sheet.paste(_on_backdrop(views[tag]), (x, head))
        dr.text((x + 6, head + 4), tag.replace("_", " "), fill=(60, 60, 60), font=small)
    y2 = head + tile + pad
    sheet.paste(Image.open(sil).convert("RGB"), (pad, y2))
    dr.text((pad + 6, y2 + 4), "silhouette", fill=(120, 120, 120), font=small)
    x = pad + tile + pad
    for j, expr in enumerate(FACE_FRAMES):
        im = _on_backdrop(views[f"face_{expr}"]).resize((face_t, face_t), Image.Resampling.LANCZOS)
        sheet.paste(im, (x + (j % 2) * face_t, y2 + (j // 2) * face_t))
        dr.text((x + (j % 2) * face_t + 4, y2 + (j // 2) * face_t + 2), expr, fill=(60, 60, 60), font=small)
    tx = x + 2 * face_t + pad
    th = Image.open(thumb)
    sheet.paste(th, (tx, y2))
    dr.text((tx, y2 + th.size[1] + 4), "96 px", fill=(60, 60, 60), font=small)
    # score panel
    px = tx + 110
    dr.text(
        (px, y2),
        f"score {result['score']:.1f}/10  {'READY' if result['ready'] else 'not ready'}",
        fill=(20, 20, 20),
        font=font,
    )
    yy = y2 + 32
    fails = [c for c in result["checks"] if not c["passed"]]
    chars = max(40, (w - px - pad) // 8)  # wrap the messages instead of cutting them off mid-word
    for c in fails[:12]:
        text = ("HARD " if c["hard"] else "") + c["message"]
        for line in textwrap.wrap(text, chars)[:3]:
            dr.text((px, yy), line, fill=(170, 40, 30) if c["hard"] else (150, 100, 20), font=small)
            yy += 19
    if result["pending"]:
        dr.text((px, yy), "pending: " + ", ".join(result["pending"]), fill=(90, 90, 90), font=small)
        yy += 19
    if not fails:
        dr.text((px, yy), "all checks pass", fill=(30, 120, 40), font=small)
    p = out / "sheet.png"
    sheet.save(p)
    return p


def sheet_for(
    brief: Brief,
    morph: Morph,
    out: Path,
    res: int = 512,
    samples: int = 16,
    device: str = "auto",
    label: str = "",
    rescore: bool = False,
) -> dict[str, Any]:
    """Render and score one sheet. ``rescore`` reuses the views already in ``out/views`` (no rendering): the
    composed sheet is then byte-identical, so a critique recorded for it (``critique.json``) is picked up.
    Cycles noise differs run to run, so a fresh render never matches a recorded critique's hash."""
    sp = apply_morph(SPECIES[brief.species], morph, brief.dark_ok)
    if rescore:
        views = {p.stem: p for p in sorted((out / "views").glob("*.png"))}
        if "side" not in views:
            raise SystemExit(f"--rescore: no rendered views in {out / 'views'}")
    else:
        views = render_views(sp.name, sp, out, res, samples, device)  # face ids are keyed by species
    side_sil = silhouette(views["side"], out, "side_silhouette.png")
    # the species-read silhouette is the signature pose when the species has one (the meerkat's sentinel)
    sil = silhouette(views.get("pose", views["side"]), out)
    thumb = thumbnail(views["three_quarter"], out)
    img = sheet_metrics(side_sil, views["side"])
    if "pose" in views:  # a detached part in the signature pose counts too (Kiki's sentinel tail, v2-v3)
        img["floating_parts"] = max(img["floating_parts"], floating_parts(load_mask(sil)))
    ol_path = out / "outline.json"
    if ol_path.exists():  # renders made before the outline check have none: the check is then not scored
        img["outline"] = json.loads(ol_path.read_text(encoding="utf-8"))
    for expr in ("happy", "surprised"):
        img[f"expression_{expr}"] = expression_change(views["face_neutral"], views[f"face_{expr}"])
    pre = score(brief, sp, img, None).as_dict()
    sheet = compose(brief.character, views, sil, thumb, pre, out, label or f"morph {morph.as_dict()}")
    crit = critique_for(brief, out)
    # the rig stress test's checks (scripts/rig_stress_test.py, copied to design/<char>/rig_stress.json) join the
    # final score; the sheet itself is composed without them, so a recorded critique's hash still matches
    stress_path = ROOT / "design" / brief.character / "rig_stress.json"
    stress = json.loads(stress_path.read_text(encoding="utf-8")) if stress_path.exists() else None
    result = score(brief, sp, img, crit, stress).as_dict()
    if crit:  # redraw the panel with the species read included
        compose(brief.character, views, sil, thumb, result, out, label or f"morph {morph.as_dict()}")
    doc = {
        "morph": morph.as_dict(),
        "image_metrics": img,
        "design": describe(sp),
        "critique": crit,
        "rig_stress": str(stress_path) if stress else None,
        **result,
        "sheet": str(sheet),
    }
    (out / "score.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("characters", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--morph", default="{}")
    ap.add_argument("--tag", default="current")
    ap.add_argument("--out", default=str(ROOT / "output" / "design"))
    ap.add_argument("--res", type=int, default=512)
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--device", default="auto")
    ap.add_argument(
        "--rescore", action="store_true", help="re-score the views already rendered in <out>/<char>/<tag>"
    )
    a = ap.parse_args()
    names = list(all_briefs()) if a.all else a.characters
    if not names:
        ap.error("name a character or pass --all")
    for ch in names:
        brief = load_brief(ch)
        doc = sheet_for(
            brief,
            morph_from_dict(json.loads(a.morph)),
            Path(a.out) / ch / a.tag,
            a.res,
            a.samples,
            a.device,
            rescore=a.rescore,
        )
        print(
            json.dumps(
                {
                    "character": ch,
                    "score": doc["score"],
                    "ready": doc["ready"],
                    "hard": doc["hard_failures"],
                    "image": doc["image_metrics"],
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
