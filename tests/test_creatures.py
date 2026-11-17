"""Savannah creatures: gait planner (foot-lock, footfall order, duty factor, reach) and body-plan builder."""

import math

import pytest

from animatica.core.protocol import validate_batch
from animatica.creatures.build import build_creature
from animatica.creatures.gait import GAITS, LEGS, Waypoint, foot_slide, plan_locomotion
from animatica.creatures.perform import walk_keys
from animatica.creatures.species import SPECIES


def walk(species: str, gait: str = "walk", seconds: float = 8.0):
    ops, meta = build_creature(species, SPECIES[species])
    g = GAITS[species][gait]
    v = g.nominal_speed(meta.leg)
    pts = [
        Waypoint(0, 0, 0),
        Waypoint(1, 0, 0),
        Waypoint(1 + seconds, v * seconds * 0.8, 0),
        Waypoint(seconds + 2.5, v * seconds * 0.8, 0),
    ]
    plan = plan_locomotion(pts, g, meta.feet, meta.leg, meta.body_z, meta.foot_z, joints=meta.joints)
    return ops, meta, g, plan


def touchdowns(plan, leg):
    return [i for i in range(1, len(plan)) if plan[i].stance[leg] and not plan[i - 1].stance[leg]]


@pytest.mark.parametrize("species", sorted(SPECIES))
def test_feet_never_slide_and_the_animal_ends_standing(species):
    _, meta, g, plan = walk(species)
    assert foot_slide(plan) == 0.0  # a planted foot does not move at all
    assert all(plan[-1].stance.values())  # it stops on four planted feet
    travelled = plan[-1].root[0] - plan[0].root[0]
    assert travelled > meta.leg  # and it really went somewhere


@pytest.mark.parametrize("species", sorted(SPECIES))
def test_stance_feet_stay_within_leg_reach(species):
    _, meta, g, plan = walk(species)
    for p in plan:
        a = math.radians(p.yaw)
        for leg in LEGS:
            jx, jy, jz, chain = meta.joints[leg]
            wx = p.root[0] + jx * math.cos(a) - jy * math.sin(a)
            wy = p.root[1] + jx * math.sin(a) + jy * math.cos(a)
            d = math.dist((wx, wy, p.root[2] + jz), p.feet[leg])
            assert d <= chain * 1.001, (species, leg, d, chain)


def test_lateral_sequence_walk_footfall_order():
    # zebra (equid) walk: LH -> LF -> RH -> RF, evenly spaced; duty factor ~0.62 (Muybridge, equine gait reviews)
    _, _, g, plan = walk("zebra")
    mid = [i for i in range(len(plan)) if plan[i].speed > 0.9 * max(p.speed for p in plan)]
    a, b = mid[0], mid[-1]
    events = sorted((i, leg) for leg in LEGS for i in touchdowns(plan, leg) if a <= i <= b)
    order = [leg for _, leg in events]
    start = order.index("LH")
    assert order[start : start + 4] == ["LH", "LF", "RH", "RF"]
    # measured duty factor in the steady part of the walk
    st = [plan[i].stance["LF"] for i in range(a, b)]
    assert sum(st) / len(st) == pytest.approx(g.duty, abs=0.06)


def test_elephant_never_leaves_the_ground_and_giraffe_uses_lateral_couplets():
    # Hutchinson 2006: elephants keep >= 2 feet down, never an aerial phase
    _, _, _, plan = walk("elephant")
    assert min(sum(p.stance.values()) for p in plan) >= 2
    # Basu 2019: the same-side fore lands soon after the hind (lateral couplets, limb phase ~0.12)
    _, _, g, plan = walk("giraffe")
    lh, lf = touchdowns(plan, "LH"), touchdowns(plan, "LF")
    gaps = [min((f - h for f in lf if f > h), default=99) for h in lh[1:-1]]
    period = (lh[-1] - lh[1]) / max(1, len(lh) - 2)
    assert gaps and all(gap / period < 0.2 for gap in gaps)


def test_zebra_trot_moves_diagonal_pairs_together():
    _, _, _, plan = walk("zebra", "trot")
    lh, rf = touchdowns(plan, "LH"), touchdowns(plan, "RF")
    assert lh and all(any(abs(a - b) <= 1 for b in rf) for a in lh[1:-1])


def test_a_foot_caught_mid_swing_lands_when_the_animal_stops():
    _, meta, g, plan = walk("zebra")
    stop = max(i for i, p in enumerate(plan) if p.speed > 0.02)
    # within 0.3 s of stopping every foot is down, and nothing is left hanging in the air
    later = plan[stop + int(0.3 * 24) + 1 :]
    assert later and all(all(p.stance.values()) for p in later)
    assert all(abs(p.feet[leg][2] - meta.foot_z) < 1e-9 for p in later for leg in LEGS)


@pytest.mark.parametrize("species", sorted(SPECIES))
def test_build_and_walk_ops_validate(species):
    ops, meta = build_creature(species, SPECIES[species], at=(1.0, 2.0), yaw=90)
    keys, plan = walk_keys(meta, GAITS[species]["walk"], [Waypoint(0, 1, 2), Waypoint(3, 1 + meta.leg, 2)])
    validate_batch({"batch_id": "c", "ops": ops})
    names = {b["name"] for o in ops if o["op"] == "create_armature" for b in o["bones"]}
    assert (
        {"hips", "chest", "head", "leg_LF_up", "leg_RH_lo"} <= names and meta.neck_bones and meta.tail_bones
    )
    assert sum(o["op"] == "add_bone_constraint" for o in ops) == 4  # IK on every leg
    if species == "elephant":
        assert len(meta.trunk_bones) == 5
    assert all(k[2] == "LINEAR" for o in keys if o["target"].endswith(("_ik_LF", "_root")) for k in o["keys"])


def test_faces_mouth_brows_and_expressions():
    from animatica.audio.lipsync import Cue
    from animatica.creatures.face import (
        BROW_COLOR,
        EXPRESSIONS,
        expression_at,
        face_keys,
        face_ops,
        mouth_mesh,
    )

    v, f, keys = mouth_mesh(0.05)
    assert set(keys) == {"open", "wide", "round", "smile", "frown"}
    corner = max(range(1, len(v)), key=lambda i: v[i][0])  # the right-hand corner vertex
    assert keys["smile"][corner][2] > v[corner][2] > keys["frown"][corner][2]  # smile curls up, frown down
    for sp_name in SPECIES:
        sp = SPECIES[sp_name]
        ops, face = face_ops(sp_name, sp, f"{sp_name}_root", f"{sp_name}_rig", BROW_COLOR[sp_name])
        validate_batch(
            {"batch_id": "f", "ops": ops},
            existing_ids={
                f"{sp_name}_root",
                f"{sp_name}_rig",
                f"{sp_name}_body",
                f"{sp_name}_head",
                f"{sp_name}_muzzle",
            },
        )
        assert any(o["op"] == "snap_to_surface" and o["target"] == face["mouth"] for o in ops)
    # expressions ease in, sad brows tilt inner-up, determined inner-down
    track = [(0.0, "neutral"), (1.0, "sad")]
    assert expression_at(track, 0.9).brow_tilt == pytest.approx(0.0)
    assert expression_at(track, 1.5).brow_tilt == pytest.approx(EXPRESSIONS["sad"].brow_tilt)
    assert EXPRESSIONS["determined"].brow_tilt < 0 < EXPRESSIONS["worried"].brow_tilt
    fk = face_keys(face, track, [Cue(0.0, 0.3, "D"), Cue(0.3, 0.6, "X")], 24, 1, 48, line_start=0.5)
    props = {(o["target"], o["property"]) for o in fk}
    assert (face["mouth"], "shape_key:open") in props and (face["mouth"], "shape_key:frown") in props
    opens = next(o for o in fk if o["property"] == "shape_key:open")["keys"]
    assert opens[0][0] == 1 + 12  # lip sync starts where the line starts


def test_savannah_set_ops_validate_for_every_time_of_day():
    from animatica.sets.savannah import SKY, Layout, grass_tuft, savannah_set

    v, f = grass_tuft()
    assert len(f) == 9 * 4 and all(len(face) == 4 for face in f)
    for tod in SKY:
        ops = savannah_set(Layout(water=(3.0, 8.0, 3.0)), tod)
        validate_batch({"batch_id": "s", "ops": ops})
        kinds = {o["op"] for o in ops}
        assert {"scatter", "create_metaball_mesh", "set_world", "add_light"} <= kinds
        grass = next(o for o in ops if o["op"] == "scatter" and o["id"] == "grass")
        assert grass["clear"] and grass["short"]  # water kept clear, action area short
        world = next(o for o in ops if o["op"] == "set_world")
        assert (world["stars"] > 0) == (tod == "night")


@pytest.mark.parametrize("name", ["elephant", "giraffe", "zebra", "meerkat", "tortoise"])
def test_eye_frame_and_lids(name):
    import math

    from animatica.creatures import eyes
    from animatica.creatures.species import SPECIES

    sp = SPECIES[name]
    for sx in (1, -1):
        fr = eyes.eye_frame(sp, sx)
        dot = sum(a * b for a, b in zip(fr.look, fr.socket))
        assert math.degrees(math.acos(min(1.0, dot))) <= eyes.MAX_LOOK_DEG + 1e-6  # iris on the visible cap
        assert abs(sum(a * b for a, b in zip(fr.up, fr.look))) < 1e-6 and fr.up[2] > 0  # lids open upward
        assert fr.socket[0] * sx > 0  # each socket faces out of its own side of the head
        for upper in (True, False):
            v, f, keys = eyes.lid_mesh(fr.radius, fr, upper)
            assert all(len(k) == len(v) for k in keys.values())
            assert max(i for face in f for i in face) == len(v) - 1
            r = [math.sqrt(sum(c * c for c in p)) / fr.radius for p in v]
            assert min(r) >= eyes.LID_INNER - 1e-3  # never cuts into the eyeball
        assert eyes.IRIS_AT + 0.24 < eyes.LID_INNER  # a closed lid covers the iris


def test_rig_checks_thresholds():
    from animatica.creatures.qa import rig_checks

    def rep(embed, gap, swim):
        return {
            "frames": {
                "1": {
                    "seating": {"e": {"embed": 0.65}, "b": {"gap": 0.0, "size": 0.1}},
                    "swim": {"m": {"p95": 0.0}},
                },
                "7": {
                    "seating": {"e": {"embed": embed}, "b": {"gap": gap, "size": 0.1}},
                    "swim": {"m": {"p95": swim}},
                },
            }
        }

    assert rig_checks(rep(0.66, 0.001, 0.0))[0] == []
    checks = sorted(i.check for i in rig_checks(rep(0.3, 0.05, 0.02))[0])
    assert checks == ["eye_socket", "lid_float", "texture_swim"]
    assert [i.message for i in rig_checks(rep(0.78, 0.0, 0.0))[0]][0].endswith("of its diameter")


def test_savannah_set_dense_grass_canopy_clumps_and_warm_haze():
    from animatica.core.protocol import validate_batch
    from animatica.sets.savannah import Layout, dense_regions, savannah_set

    lay = Layout(action=[(0.0, 2.0, 4.0)])
    ((x, y, r, m),) = dense_regions(lay)
    assert y < 2.0 - 4.0 and m > 1  # in front of the action, on the camera side
    ops = savannah_set(lay, "midday")
    validate_batch({"batch_id": "set", "ops": ops})
    grass = next(o for o in ops if o["op"] == "scatter" and o["id"] == "grass")
    assert grass["dense"] == [[x, y, r, m]]
    canopy = next(o for o in ops if o["op"] == "create_metaball_mesh" and o["id"].endswith("_canopy"))
    assert len(canopy["elements"]) >= 10  # many clumps, not one cushion
    hills = next(o for o in ops if o["op"] == "set_material" and o["material"].get("name") == "mountains")
    r_, g_, b_ = (int(hills["material"]["base_color"][i : i + 2], 16) for i in (1, 3, 5))
    assert r_ > b_ and hills["material"]["fade_glow"] < 0.5  # warm, and not blown out by the haze glow


def test_happy_pushes_the_lower_lids_up_and_the_sentinel_keeps_the_head_level():
    """Review 11-17 12:36: happy barely changed the face (lower lids now rise: "smiling eyes"); Kiki v3 carries
    her head forward on all fours, so the sentinel splits its forward bend between neck and head."""
    from animatica.creatures.eyes import eye_frame, lid_mesh
    from animatica.creatures.face import BROW_COLOR, EXPRESSIONS, expression_at, face_keys, face_ops
    from animatica.creatures.perform import (
        SENTINEL_HEAD_UP,
        SENTINEL_NECK_UP,
        SENTINEL_PITCH,
        sentinel_bends,
    )

    assert EXPRESSIONS["happy"].cheek > 0.5 and EXPRESSIONS["neutral"].cheek == 0.0
    assert expression_at([(0.0, "neutral"), (1.0, "happy")], 2.0).cheek == pytest.approx(
        EXPRESSIONS["happy"].cheek
    )
    sp = SPECIES["meerkat"]
    _ops, face = face_ops("k", sp, "k_root", "k_rig", BROW_COLOR["meerkat"])
    fk = face_keys(face, [(0.0, "neutral"), (0.5, "happy")], None, 24, 1, 48)
    cheek = [o for o in fk if o["property"] == "shape_key:cheek"]
    assert {o["target"] for o in cheek} == {"k_lid_L_lo", "k_lid_R_lo"}
    assert cheek[0]["keys"][0][1] == 0.0 and cheek[0]["keys"][-1][1] == pytest.approx(0.85)
    _v, _f, keys = lid_mesh(0.01, eye_frame(sp, 1), upper=False)
    assert "cheek" in keys and "droop" not in keys
    # the sentinel: the neck ends SENTINEL_NECK_UP above horizontal and the head SENTINEL_HEAD_UP nose-up,
    # whatever the neck's angle on all fours
    _ops, meta = build_creature("k", sp)
    neck, head = sentinel_bends(meta)
    dy = sum(meta.bone_dirs[b][1] for b in meta.neck_bones)
    dz = sum(meta.bone_dirs[b][2] for b in meta.neck_bones)
    rest = math.degrees(math.atan2(dz, -dy))
    assert rest < 45  # v3: head carried forward on all fours, not raised like a dog's
    assert rest + SENTINEL_PITCH - neck == pytest.approx(SENTINEL_NECK_UP)
    assert SENTINEL_PITCH - neck - head == pytest.approx(SENTINEL_HEAD_UP)
    assert sp.snout_tip is not None and sp.jaw > 0 and sp.belly_tuck > 0


def test_kiki_v4_rump_rides_the_hips_paws_only_darken_and_body_is_smoother():
    """Laptop GPU 11-17: in the sentinel the rump stayed with the planted thighs and the tail root hung ~3 cm
    below it (detached in the silhouette since v2). The rump end is now weighted rigidly to the hips, like the
    tail. Kiki v4 also darkens only the paws (v3 had dark socks) and packs her metaballs closer (lumpy barrel)."""
    from animatica.creatures.build import rump_rigid
    from animatica.creatures.organic import Graph, metaball_elements

    sp = SPECIES["meerkat"]
    ops, _meta = build_creature("k", sp)
    bind = next(o for o in ops if o["op"] == "bind_mesh_to_armature" and o.get("auto"))
    rump = [r for r in bind["rigid"] if r["bone"] == "hips"]
    assert len(rump) == 1
    # the region reaches the tail root (the rump surface behind the hips)
    assert rump[0]["center"][1] + rump[0]["radii"][1] * (1 - rump[0]["falloff"]) > sp.tail.base[1] - 0.01
    assert rump_rigid(SPECIES["zebra"]) == []  # only species that rise onto their hind legs
    paw = sp.mats["paw"]
    assert paw["base_color"] == sp.coat["base_color"] and paw["marks"][0]["at"][2] == pytest.approx(
        -sp.body_z
    )
    assert sp.patch_soft < 0.4  # crisp eye patches that carry at 96 px
    g = Graph()
    a, b = g.node((0.0, 0.0, 0.0), 0.02), g.node((0.0, 0.2, 0.0), 0.02)
    g.link(a, b)
    rough, res0 = metaball_elements(g)
    smooth, res1 = metaball_elements(g, 1.0)
    assert len(smooth) > len(rough) and res1 < res0


def test_zuri_stripes_wrap_as_chevrons_and_the_mane_stands_on_the_crest():
    """Baseline review 11-17 06:36: y-planes rang bullseyes on the chest, face and rump; the mane was a thin plate
    behind the neck and the muzzle a black clown-nose ball."""
    from animatica.core.protocol import parse_batch

    sp = SPECIES["zebra"]
    assert sp.coat["pattern_chevron"] > 1.0 and sp.coat["pattern_tilt"] < 0
    parse_batch(
        {
            "batch_id": "z",
            "ops": [{"op": "set_material", "targets": ["x"], "material": {**sp.coat, "name": "z"}}],
        }
    )
    mane = next(e for e in sp.extras if e.id == "mane")
    assert mane.size[1] >= 0.25 and mane.loc[1] < 0.1  # tall, and on the neck's crest, not behind it
    assert sp.muzzle[0][0] < sp.head_size[0] * 0.75  # narrower than the face


def test_bibi_carapace_is_a_dome_with_raised_scutes_not_a_ball():
    """Baseline review 11-17 06:36: the shell was a near-perfect ball with panel lines, spots that read as holes and
    a pale plastron disc. The carapace is now its own mesh (creatures.shell)."""
    from animatica.creatures.shell import PLASTRON, carapace, mark_colour, scute_centres, signed_volume

    v, f, c = carapace(0.25, 0.3, 0.33, -0.12, -0.19, rings=40, seg=96)
    assert len(c) == len(v) and signed_volume(v, f) > 0  # closed, normals out
    zs = [p[2] for p in v]
    width = max(p[0] for p in v) - min(p[0] for p in v)
    assert (max(zs) - min(zs)) / width < 0.85  # a dome on a flat plastron, not a ball (1.0)
    assert min(zs) == pytest.approx(-0.19)
    cs = scute_centres()
    assert len(cs) == 5 + 8 + 24
    # a plate's centre stands higher than its seam; the centre is pale (no dark "hole")
    centre, r_c = mark_colour(*cs[2], cs)
    mid = ((cs[2][0] + cs[3][0]) / 2, (cs[2][1] + cs[3][1]) / 2)
    seam, r_s = mark_colour(*mid, cs)
    assert r_c > r_s and sum(centre) > 3 * sum(seam)
    assert sum(PLASTRON) < 0.5  # the underside is dark, never a pale disc
    sp = SPECIES["tortoise"]
    ops, _m = build_creature("b", sp)
    shell = next(o for o in ops if o.get("id") == "b_shell")
    assert shell["op"] == "create_mesh" and shell["colors"]
    assert not any(e.id == "plastron" for e in sp.extras)
    from animatica.design.measure import features, materials

    assert "pattern:scutes" in features(sp) and materials(sp)["pattern_contrast"]["shell"] >= 4.0
