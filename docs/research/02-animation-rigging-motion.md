# 02 — Character Animation, Rigging, Motion, Lip Sync & Facial Animation

**Research date:** 2026-11-15
**Scope:** Open-source tools, models and datasets that can cut work for the Animator and Voice & Sound agents (PLAN.md §3–§5), checked against the licensing rules in PLAN.md §7.

## How this was checked

- I fetched licenses straight from each repo's `LICENSE` file on `raw.githubusercontent.com`, not from READMEs or memory. Where the README and the LICENSE file disagree, the table says so.
- Dataset and model licenses come from the official license pages or model cards (MPI SMPL/AMASS, CMU, Zenodo, Hugging Face, Quaternius, Adobe).
- **What I ran myself in this container (CPU only, no GPU), 2026-11-15:**
  - `pip install bpy==5.3.0` (the PyPI wheel, uploaded 2026-11-10; Python 3.13).
  - Headless runs of:
    - Rigify human metarig + `rigify_generate`: 706-bone rig in 6.4 s.
    - Automatic weights with `parent_set(type='ARMATURE_AUTO')`.
    - Bulk keyframes through the Blender 5.x *channelbag* API: 500 keys in 0.02 s.
    - F-curve NOISE and CYCLES modifiers.
    - Confirming the BVH importer operator is available.
    - Creating a stroke through the Grease Pencil v3 API.
  - The Rhubarb Lip Sync 1.14.0 Linux binary: downloaded, ran it (no dependencies beyond glibc/libstdc++), produced JSON cues, and turned those into shape-key keyframes.
  - The probe script lives outside the repo; the recipes it proved are written out in §4.
- **Limits:**
  - The GitHub API was not reachable from this session, so "Activity" comes from release notes, README news, PyPI upload dates and web pages, not commit graphs.
  - I did not run any GPU model.
  - I am not a lawyer. Each "verdict" is an engineering call under PLAN §7 ("never copy code from AGPL, non-commercial, academic-only or unlicensed projects").

---

## 1. Executive summary — top 10 recommendations (ranked by impact)

1. **ADOPT Rhubarb Lip Sync (MIT) as the lip-sync engine.**
   - The Linux binary works out of the box on CPU and is fast (about 0.75 s for 2 s of audio).
   - Always pass `--dialogFile`, because our script text is known. Use `-r pocketSphinx` for English and `-r phonetic` for other languages.
   - Output is JSON `mouthCues` (shapes A–H, X), which map one-to-one onto shape keys. Output data belongs to the user.
2. **ADOPT Blender's built-in rigging stack:**
   - Rigify (core add-on, GPL, part of Blender) for humanoids/quadrupeds.
   - Automatic (bone-heat) weights for organic meshes.
   - **Rigid bone parenting for hard-surface characters** (our robot). Skip skinning entirely there.
   - All of this is verified headless in bpy 5.3.
3. **ADOPT a procedural animation library written by us (Apache core plus a GPL add-on executor).** Agents should set parameters, not keys. It covers:
   - easing/anticipation/overshoot curves;
   - parametric walk/hop/idle-breath cycles (CYCLES modifier);
   - NOISE F-modifiers for secondary motion;
   - baked damped-spring "jiggle" bones;
   - look-at/IK constraints, then baking.
4. **ADOPT the Blender 5.x channelbag keyframe path for `insert_keyframes`.**
   - Use `bpy_extras.anim_utils.action_ensure_channelbag_for_slot` → `fcurves.ensure()` → `keyframe_points.add(n)` + `foreach_set("co", …)`.
   - It is about 100× faster than per-key `keyframe_insert`.
   - Blender 5.0 **removed** `action.fcurves`. Any snippet using it in our knowledge base or in LLM memory will break.
5. **ADOPT CC0/CC-BY motion libraries as the "stock motion" layer:**
   - Quaternius Universal Animation Library 1 & 2 (CC0, 120+ and 130+ clips, free Standard tier).
   - Mesh2Motion (MIT code, CC0 rigs and animations).
   - CMU Graphics Lab Mocap (free for all uses, including inside sold products; no resale of the data).
   - 100STYLE (CC BY 4.0, BVH, 100 locomotion styles).
   - Retarget them with our own small retargeter (constraints + bake) inside the GPL add-on.
6. **ADOPT Grease Pencil v3 (Blender) for the 2D path and Godot's skeleton stack for games:**
   - Godot: Skeleton2D/Bone2D, RetargetModifier3D (4.4), SpringBoneSimulator3D (4.5), the new IK family (TwoBoneIK3D/FABRIK3D/CCDIK3D…, 4.6). Godot is MIT.
   - In 5.0 the Grease Pencil types were renamed (`bpy.data.grease_pencils`, `bpy.types.GreasePencil`). Verified.
7. **TRIAL MediaPipe Pose Landmarker (Apache-2.0 code; BlazePose GHUM model card Apache-2.0) for video-to-mocap from *user-supplied* clips on CPU.**
   - It gives 33 world landmarks, which we turn into bone rotations with our own solver.
   - This is the only video-mocap path with no SMPL, AMASS or non-commercial strings attached.
8. **TRIAL GPU auto-rigging for arbitrary generated meshes:**
   - UniRig: MIT code, and the Hugging Face model card is tagged MIT.
   - Puppeteer / MagicArticulate: Apache-2.0 code.
   - SkinTokens/TokenRig (MIT) is the successor, but read the data-provenance traps in §3 first.
   - Keep it behind an optional `rig.auto_ml` provider with a fallback to Rigify or bone heat.
9. **TRIAL, opt-in only, behind a license gate: HY-Motion 1.0 (Tencent) for text-to-motion.**
   - It is the only strong text-to-motion model whose license allows commercial use of *outputs*.
   - The catch: the license **does not apply in the EU, UK and South Korea**, has a 1M-MAU clause, forbids using outputs to train other models, and needs about 24 GB of VRAM.
   - Every academic text-to-motion model (MDM, MoMask, T2M-GPT, MotionGPT, MotionLCM) is **REFERENCE-ONLY** for us. Their weights are trained on HumanML3D, which is built from AMASS (non-commercial) and SMPL (non-commercial).
10. **TRIAL NVIDIA Audio2Face-3D (SDK MIT, training framework Apache-2.0, weights under the NVIDIA Open Model License, "ready for commercial use") as the GPU facial-animation upgrade.**
    - Needs an NVIDIA GPU with CUDA ≥ 12.8 and TensorRT.
    - **AVOID Wav2Lip** (research/personal use only; trained on LRS2) and other NC face models (EmoTalk, MeshTalk, EMOCA, Sapiens).

Plus a hard **AVOID list for the automated pipeline:**
- Mixamo: no raw-file redistribution, no ML training, Adobe ID web service only.
- AccuRig: Windows-only freeware, export needs an ActorCore account.
- Spine runtimes: every end user needs a Spine Editor license.
- FreeMoCap: AGPL.
- Bandai Namco dataset (CC BY-NC) and Ubisoft LaFAN1 (CC BY-NC-ND).

---

## 2. Tables per subtopic

Verdict legend:
- **ADOPT**: use now in the default pipeline.
- **TRIAL**: optional or provider plugin; evaluate.
- **REFERENCE-ONLY**: read papers and ideas, reimplement only from the idea, never copy code or ship weights.
- **AVOID**: don't integrate.

### 2.1 Auto-rigging & skinning

| Tool | What it does | Code license | Weights / data license | Activity | Install route (headless Linux) | GPU? | Verdict |
|---|---|---|---|---|---|---|---|
| **Rigify** (Blender core add-on) | Metarig templates (human, animals) → full production rig (706 bones for the human) | GPL (ships with Blender, `addons_core`) | n/a | Maintained with Blender; documented in the 5.2 manual | `addon_utils.enable("rigify")`, `bpy.ops.object.armature_human_metarig_add()`, `bpy.ops.pose.rigify_generate()`. **Verified, 6.4 s on CPU** | No | **ADOPT**. Free, headless, editable by artists, already GPL like our add-on. |
| **Blender automatic weights (bone heat)** | Skins a mesh to an armature | GPL (Blender) | n/a | Core feature | `bpy.ops.object.parent_set(type='ARMATURE_AUTO')`. **Verified** | No | **ADOPT**. Fails on non-manifold or multi-part meshes ("failed to find solution"). Fall back to rigid parenting or envelope weights. |
| **Rigid/bone parenting** (technique) | Each hard-surface part follows one bone at 100% | n/a | n/a | n/a | `obj.parent = arm; obj.parent_type='BONE'; obj.parent_bone=…` | No | **ADOPT**. Right choice for robots and props: no skinning artefacts. |
| **UniRig** (VAST-AI) | Autoregressive skeleton + skin-weight prediction for any mesh | MIT (LICENSE) | HF model card tagged MIT. Released checkpoint trained on **Articulation-XL2.0** (filtered from Objaverse-XL) | 2025; README points to successor SkinTokens | Conda/pip with `spconv`, `torch_scatter`, `torch_cluster`; checkpoint auto-downloads from HF | **Yes**, CUDA, >8 GB VRAM | **TRIAL**. Best permissive ML rigger. Training data is mixed-license Objaverse assets, so it is a provenance risk, not a license block. |
| **SkinTokens / TokenRig** (VAST-AI) | Rig as one token sequence (skeleton + skin), GRPO-refined | MIT | MIT on HF. **Trained on ArticulationXL 2.0 + VRoid Hub + ModelsResource** | 2025–26, active | Python + HF weights; Qwen3-0.6B config | **Yes**, ≥14 GB | **TRIAL (caution)**. ModelsResource hosts ripped commercial game models. Weights trained on them carry reputational/legal risk. Opt-in only. |
| **Puppeteer** (Seed3D, NeurIPS'25) | Skeleton + skinning + video-guided animation; FBX export | Apache-2.0 | Checkpoints on HF (license not separately verified); data Articulation-XL2.0 | Sep 2025 | Python/CUDA | **Yes** | **TRIAL**. Check the HF weights license before enabling. |
| **MagicArticulate** (Seed3D, CVPR'25) | Skeleton generation | Apache-2.0 | HF weights; Articulation-XL2.0 | Aug 2025 weight fix | Python/CUDA | **Yes** | **REFERENCE/TRIAL**. Superseded by Puppeteer. |
| **Make-It-Animatable** (CVPR'25) | Fast joints + weights + pose-to-T-pose | MIT | **Trained on a Mixamo-derived dataset** (`hf download jasongzy/Mixamo`) | v2 in 2025 | Python/CUDA | **Yes** | **AVOID (weights)**. Adobe staff's Mixamo FAQ forbids ML training on Mixamo content. The ideas are fine to reference. |
| **RigNet** (2020) | GNN joint + skin prediction | GPL-3.0 (README); no LICENSE file at repo root | Trained on ModelsResource-RigNetv1 | Last README update May 2023; CUDA 11.3 | Old PyTorch 1.12 stack | Yes | **REFERENCE-ONLY**. Dated; UniRig beats it. |
| **RigAnything** (Adobe) | Autoregressive rigging | **Adobe Research License, non-commercial** | NC | 2025 | — | Yes | **AVOID** |
| **Robust Skin Weights Transfer** (SIGGRAPH Asia'23) | Transfers weights from a template body to a new mesh, then inpaints the rest | MIT (rin-23 reference code); Blender add-on port is GPL-3 (sentfromspacevr) | n/a | 2024 | numpy/scipy (+libigl) | No | **TRIAL**. Good CPU fallback: skin a Rigify template body, then transfer weights to a generated character. |
| **Mesh2Motion** | Open "Mixamo-like" web app: fit a template skeleton, auto-skin, preview and export animations (GLB) | **MIT** | **CC0** rigs and animations | 2025–26, active | Node/three.js web app. For us, mainly the CC0 asset repo `Mesh2Motion/mesh2motion-assets` | No | **ADOPT assets / REFERENCE app**. |
| **Mixamo** (Adobe) | Web auto-rigger + animation library | Proprietary service | Royalty-free in your projects. **No raw-file redistribution, no ML training** (Adobe staff FAQ); needs an Adobe ID; no public API | Live, "technology preview" | Browser only | n/a | **AVOID** in the pipeline. Users may import their own Mixamo FBX by hand. |
| **AccuRig 2.0** (Reallusion) | Desktop auto-rigger + ActorCore motions | **Proprietary freeware, not open** | Export needs a free ActorCore account; ActorCore motions mostly paid | Jul 2025 (2.0) | **Windows 8+ only** | — | **AVOID**. Not open, not Linux, not automatable. |
| **Auto-Rig Pro** | Commercial Blender rigging/retarget add-on | Paid (GPL code, but sold) | — | Active | — | — | **AVOID** as a dependency. Don't require paid add-ons. |

### 2.2 Text-to-motion / motion generation

> **Key fact.** HumanML3D's *code and text annotations* are MIT. Its *motions* come from **AMASS**, and the README says it cannot redistribute them because of the AMASS distribution policy. AMASS's license is for non-commercial research/education/art only, forbids "train[ing] methods/algorithms/neural networks… for commercial use", and forbids redistribution. SMPL/SMPL-H body models have the same non-commercial terms (a commercial license is sold through Meshcapade). **Every model trained on HumanML3D therefore has non-commercial weights, whatever its code license says.**

| Tool | What it does | Code license | Weights / data license | Activity | Install route | GPU? | Verdict |
|---|---|---|---|---|---|---|---|
| **MDM** (Motion Diffusion Model) | Text/action → SMPL-skeleton motion (diffusion) | MIT | Trained on HumanML3D/AMASS → **NC**; needs SMPL downloads (NC) | 50-step model Apr 2024; follow-ups CLoSD/AnyTop (MIT code) 2024–25 | conda + Google Drive checkpoints + `download_smpl_files.sh` | Yes (CUDA) | **REFERENCE-ONLY** |
| **MoMask** (CVPR'24) | Masked residual-VQ text-to-motion; temporal inpainting | MIT | HumanML3D/KIT → **NC**; SMPL for meshes | Last news Aug 2024 (CPU WebUI demo claimed) | conda + checkpoints | CPU possible (slow) | **REFERENCE-ONLY**. Could be a user-installed "research mode" plugin; never bundled. |
| **T2M-GPT** (CVPR'23) | VQ-VAE + GPT text-to-motion | Apache-2.0 | HumanML3D → **NC** | 2023 | conda | Yes | **REFERENCE-ONLY** |
| **MotionGPT** (OpenMotionLab) | Motion-language LLM (T5); MotionGPT3 announced Jun 2025 | MIT | HumanML3D + SMPL → **NC** (README warns datasets keep their own licenses) | 2023; MotionGPT3 2025 | conda | Yes | **REFERENCE-ONLY** |
| **MotionLCM** | Real-time latent consistency model | **Non-commercial scientific research license (code itself)** | NC | 2024 | — | Yes | **AVOID** (even the code is NC) |
| **MLD** (motion-latent-diffusion) | Latent diffusion text-to-motion | MIT | HumanML3D → NC | 2023 | conda | Yes | REFERENCE-ONLY |
| **MotionDiffuse** | Diffusion text-to-motion | **S-Lab License 1.0 (non-commercial)** | NC | 2022 | — | Yes | **AVOID** |
| **HumanTOMATO / MotionLLM** (IDEA) | Whole-body text-to-motion / motion LLM | **Non-commercial research license** | NC | 2023–24 | — | Yes | **AVOID** |
| **STMC** (NVIDIA) | Multi-track timeline text-to-motion | **NVIDIA license, non-commercial only** | NC | 2024 | — | Yes | **AVOID** |
| **MotionStreamer** (ZJU3DV) | Streaming text-to-motion | **Project Registration License v1.0**: any organisational "project use" must be registered first, even non-commercial | — | 2026 relicense | — | Yes | **AVOID** (registration terms are incompatible with a permissive downstream) |
| **HY-Motion 1.0 / 1.0-Lite** (Tencent Hunyuan) | 1.0B / 0.46B DiT flow-matching text-to-motion; 3,000 h pretrain + 400 h fine-tune + RLHF | **Tencent HY-Motion 1.0 Community License** (code and weights) | Same license. **Territory excludes EU, UK, South Korea**; >1M MAU needs a separate license; **outputs may not be used to improve other AI models**; Tencent claims no rights in outputs | Released 2025-12-30; README updated Oct 2026 (FlowHMR video-to-motion built on it) | Python + HF weights | **Yes**, 26 GB (1.0) / 24 GB (Lite) minimum | **TRIAL (opt-in, gated)**. Never default. Show a license and territory prompt. Never use outputs to train our models. |
| **Motion Matching** (orangeduck, Holden) | Classic data-driven runtime motion matching (games) | MIT | Demo uses LaFAN1 (CC BY-NC-ND) | 2021 | C++ | No | **REFERENCE**. The algorithm is great for the Godot path; bring our own CC0/CC-BY data. |
| **ProtoMotions** (NVIDIA) | Physics-based humanoid control | Apache-2.0 | Typically AMASS-trained → NC | Active | Isaac stack | Yes | REFERENCE-ONLY |

**Bottom line:** in Nov 2026 no high-quality text-to-motion model exists that is fully permissive (code, weights and training data) and safe for an Apache-2.0 product shipped worldwide. Our default "text-to-motion" is **the LLM Animator choosing and composing CC0/CC-BY clips plus procedural generators** (§5).

### 2.3 Motion capture from video

| Tool | What it does | Code license | Weights / data license | Activity | Install route | GPU? | Verdict |
|---|---|---|---|---|---|---|---|
| **MediaPipe Pose Landmarker** (Google) | 33 2D + 3D "world" landmarks per frame (BlazePose GHUM; lite/full/heavy) | Apache-2.0 | BlazePose GHUM 3D model card: **Apache-2.0**. Single person, out of scope beyond ~4 m, depth up to scale | `mediapipe` 1.2.3 on PyPI (2026-11-11) | `pip install mediapipe` | **No** (CPU fine) | **TRIAL → ADOPT** for user-supplied video. Write our own landmarks→bone-rotation solver. |
| **BlendArMocap** | MediaPipe → Blender/Rigify transfer add-on | GPL-3.0 | MediaPipe | **Discontinued** by its author (README) | Blender add-on | No | **REFERENCE** (GPL-compatible with our add-on, but unmaintained). |
| **FreeMoCap** | Multi-camera markerless mocap + Blender export | **AGPL-3.0** (also the Blender add-on) | Uses MediaPipe/RTMPose trackers | Active (1.8.2, Apr 2026) | `pip install freemocap[cpu]` | Optional | **REFERENCE-ONLY**. PLAN §7 bans copying AGPL code. A user may run it separately and give us BVH/FBX. |
| **4D-Humans / HMR 2.0** | Monocular SMPL mesh recovery + tracking | MIT | **Needs SMPL neutral model (NC)**; trained on mixed datasets | 2023 | conda + SMPL registration | Yes | **REFERENCE-ONLY** |
| **WHAM** | World-grounded human motion from video | MIT | **SMPL (NC)**; stage-1 trained on **AMASS (NC)** | 2024 | conda + SMPL registration | Yes | **REFERENCE-ONLY** |
| **GVHMR** (ZJU) | Gravity-view world human motion | **Educational/research/non-profit only** | NC | 2024 | — | Yes | **AVOID** |
| **EasyMocap** (ZJU) | Multi-view mocap toolbox | **Project Registration License v1.0 (2026)** | — | Relicensed 2026 | — | Yes | **AVOID** |
| **Sapiens** (Meta) | Human foundation models (pose, seg, depth) | **CC BY-NC 4.0** | NC | 2024 | — | Yes | **AVOID** |
| **MMPose / ViTPose** | 2D/3D pose toolboxes | Apache-2.0 | Per-checkpoint; COCO-trained (annotations CC BY 4.0, images Flickr-mixed) | Maintained | `pip install mmpose` | Yes (CPU slow) | **TRIAL** (GPU upgrade for 2D keypoints) |
| **MotionBERT** | 2D→3D lifting | Apache-2.0 | Trained on H36M/AMASS → check per checkpoint (likely NC) | 2023 | conda | Yes | REFERENCE-ONLY |
| **FlowHMR** | Video→motion (.fbx) built on HY-Motion | Not verified | Presumably inherits HY-Motion terms | Oct 2026 | — | 12+ GB | REFERENCE (check before any trial) |

### 2.4 Free mocap / animation data we may ship or use

| Dataset | Content | License (exact terms, paraphrased) | Verdict |
|---|---|---|---|
| **CMU Graphics Lab Motion Capture DB** | ~2,600 clips, ASF/AMC (+ community BVH conversions, e.g. Bruce Hahn / cgspeed) | Site states the data is **free for all uses** and may be copied, modified or redistributed; **may be included in commercially sold products, but the data itself may not be resold, even converted**. Acknowledgement requested ("obtained from mocap.cs.cmu.edu", NSF EIA-0196217). Asks people not to crawl the whole DB | **ADOPT** (attribute in THIRD_PARTY.md; ship only a curated subset, not a mirror) |
| **100STYLE** (Mason et al.) | 100 locomotion styles, BVH, 4M+ frames | **CC BY 4.0** (Zenodo) | **ADOPT** with attribution. Ideal for stylised walk/run variety |
| **Quaternius Universal Animation Library 1 & 2** | 120+ and 130+ game animations on one humanoid rig; FBX/GLB (Blend in the paid Source tier) | **CC0**. Standard tier (~60–70% of the pack) free; Pro/Source tiers via Patreon credits, still CC0 | **ADOPT**. Ship the free Standard clips; they already target Godot/Unity/UE |
| **Mesh2Motion assets** | Rigs + animations | **CC0** | **ADOPT** |
| **Mixamo** | 2,000+ animations | Royalty-free use in projects; **no redistribution of raw files; no ML training**; Adobe ID | **AVOID** (cannot ship or bundle; cannot automate) |
| **Bandai Namco Research Motion Dataset 1 & 2** | 36,673 + 384,931 frames, stylised BVH | **CC BY-NC 4.0** (Blender visualiser script MIT) | **AVOID** for shipping; REFERENCE |
| **Ubisoft LaFAN1** | 4.6 h locomotion and in-betweening | **CC BY-NC-ND 4.0** | **AVOID** |
| **AMASS / HumanML3D motions** | Unified SMPL mocap / text-annotated | **Non-commercial; no redistribution; no commercial training** | **AVOID** |
| **ActorCore** (Reallusion) | Commercial mocap store | Proprietary | AVOID |

### 2.5 Retargeting & BVH in Blender

| Tool | What it does | Code license | Activity | Install route | GPU? | Verdict |
|---|---|---|---|---|---|---|
| **Built-in BVH importer** (`io_anim_bvh`) | Imports BVH as armature + action | GPL (Blender core) | Core | `bpy.ops.import_anim.bvh(...)`. **Operator verified present in 5.3** | No | **ADOPT** |
| **Own retargeter** (technique, our GPL add-on) | Bone-name map + rest-pose alignment → Copy Rotation / Copy Location constraints → `nla.bake` | Ours | — | — | No | **ADOPT**. 150–300 lines; full control; no dependency risk |
| **Rokoko Studio Live for Blender** | Live link + retargeting UI | **LICENSE.md is LGPL-3.0, but the README badge says MIT** (discrepancy; treat as LGPL-3) | Maintained by Rokoko | Blender add-on | No | **REFERENCE** (MoMask authors also report foot errors with it) |
| **KeeMap Rig Retargeting** | Bone-mapping retarget add-on (JSON maps) | GPL-3.0 | Older, community | Blender add-on | No | **REFERENCE/TRIAL**. GPL-compatible with our add-on; its JSON bone-map idea is worth copying as a concept |
| **"Retarget" by KBS-DEV** (Blender Extensions) | Retargeting extension | GPL-3.0-or-later | v5.2.0, 2026-08-23; Blender ≥ 5.0 | extensions.blender.org | No | **TRIAL** (GPL-compatible; verify headless operators) |
| **Retarget BVH** (Diffeomorphic/MakeHuman lineage) | BVH→rig retargeting | GPL | Bitbucket, sporadic | Add-on | No | REFERENCE |
| **bvhio** (PyPI) | Pure-Python BVH read/write/edit | MIT | 1.5.4, Oct 2025 | `pip install bvhio` | No | **ADOPT** in the core (Apache side) for BVH cleanup outside Blender |
| **Godot RetargetModifier3D + SkeletonProfileHumanoid** | Engine-side retargeting at import | MIT | 4.4+ | Godot | No | **ADOPT** (game path) |

### 2.6 Procedural animation (agents implement these as parameterised generators)

| Technique / tool | What it gives us | License | Headless? | Verdict |
|---|---|---|---|---|
| **F-curve modifiers**: NOISE, CYCLES, GENERATOR, STEPPED | Secondary jitter, loops, "on twos" stepping | Blender | **Verified** (NOISE + CYCLES) | **ADOPT** |
| **Keyframe interpolation/easing** (`BEZIER`, `BACK` overshoot, `ELASTIC`, `BOUNCE`, `easing`) | Ease-in/out, anticipation/overshoot without extra keys | Blender | Yes | **ADOPT** |
| **Constraints**: IK (chain length, pole), Spline IK, Damped Track, Locked Track, Child Of, Stretch To | Foot planting, look-at, tails/antennae, prop hand-offs | Blender | Yes; bake with `bpy.ops.nla.bake` | **ADOPT** |
| **Drivers** | Automatic squash and stretch, wheel rotation from distance | Blender | Yes (5.0: Python-created drivers get two keyframes, not an F-modifier) | **ADOPT** |
| **NLA strips / action slots** | Layer stock clips + procedural layers, blend in/out | Blender | Yes | **ADOPT** |
| **Our damped-spring bake** (technique) | Jiggle/overlap/follow-through for antennae, tails, ears; deterministic | Ours | Yes (simulate per frame in Python, write keys) | **ADOPT**. Deterministic and render-safe, unlike frame-change handlers |
| **Wiggle 2** (shteeve3d) | Spring/jiggle bones add-on | GPL-3.0 | Handler-based; has bake | **REFERENCE/TRIAL** (GPL-compatible) |
| **Procedural walk cycle** (technique) | Stride/period/bounce/arm-swing parameters → root bob (2× frequency), hip sway, foot arcs via IK targets | Ours | Yes | **ADOPT** |
| **Godot SpringBoneSimulator3D (4.5), LookAtModifier3D (4.4), IK family (4.6), Skeleton2D + SkeletonModification2D** | Runtime secondary motion and IK in games | MIT | n/a | **ADOPT** (game path) |

### 2.7 Lip sync & facial animation

| Tool | What it does | Code license | Weights / data license | Activity | Install route | GPU? | Verdict |
|---|---|---|---|---|---|---|---|
| **Rhubarb Lip Sync** | Audio (+ optional transcript) → timed mouth cues A–F basic + G, H, X extended; TSV/XML/JSON/Moho `.dat` | **MIT**. All dependencies MIT/BSD/Boost; bundled CMU Sphinx acoustic model under BSD-style terms. LICENSE states output data belongs to the user | Ships its own models | **1.14.0, 2025-04-03** (stable; slow cadence) | GitHub release `Rhubarb-Lip-Sync-1.14.0-Linux.zip` (87 MB). **Verified running** | **No** | **ADOPT** |
| **Rhubarb Lipsync NG** (Premik) | Blender add-on: cue capture, mapping to Actions/shape keys, baking to NLA | MIT (GitHub; also sold on Superhive) | wraps Rhubarb | Active, Blender 4.2+ | Blender extension | No | **REFERENCE/TRIAL**. We need our own batch op anyway; borrow its "cue → Action" mapping concept |
| scaredyfish/blender-rhubarb-lipsync | Older Blender add-on | **No license file** | — | README says not under active development | — | — | **AVOID** (unlicensed) |
| **Papagayo-NG** | GUI phoneme breakdown/timing for Moho | GPL (`gpl.txt`, version not stated on page) | — | Low activity; README says it now targets Moho only | Qt GUI, no CLI | No | **REFERENCE-ONLY** |
| **Preston Blair viseme set** | Classic 10-ish mouth chart (AI, E, O, U, etc., L, WQ, MBP, FV, rest) | Concept | — | — | Rhubarb maps A→MBP, B→etc, C→E, D→AI, E→O, F→U, G→FV, H→L, X→rest | — | **ADOPT** as naming convention |
| **NVIDIA Audio2Face-3D** (SDK + training framework + v3.0 models) | Audio → facial motion (skin, tongue, jaw, eyes); Audio2Emotion add-on | SDK **MIT**; training framework **Apache-2.0** | Weights: **NVIDIA Open Model License**, card says commercial use is fine. Audio2Emotion weights gated (click-through) | v3.0 weights 2025-09-24 | Build SDK (CUDA 12.8–12.9 + TensorRT) | **Yes** (NVIDIA only; 4 GB+) | **TRIAL** (GPU upgrade; we must map its output to our shape keys or ARKit-style set) |
| **Wav2Lip** | Video lip-sync (pixels) | **No LICENSE file; README says personal/research/non-commercial only; trained on LRS2; commercial use prohibited** | NC | Repo now advertises the commercial sync.so product | — | Yes | **AVOID** |
| **SadTalker** | Single image + audio → talking-head video | Apache-2.0 (relicensed, NC removed) **except listed third-party components** | Bundles `wav2lip.pth` (NC), Basel Face Model files, GFPGAN/facexlib weights | 2023 | conda | Yes | **AVOID** (bundled NC components; also 2D video, not 3D rig) |
| **MuseTalk** (MIT) / **LatentSync** (Apache-2.0) / **EchoMimic v2** (Apache-2.0) / **LivePortrait** (MIT) | Video/portrait lip-sync and reenactment | Permissive code | Weights depend on SD-VAE, Whisper, InsightFace (NC for some) and training data; **not verified** | 2024–26 | conda | Yes | **REFERENCE-ONLY** (pixel-space; doesn't drive our editable rig) |
| **FaceFormer / CodeTalker** | Audio → 3D face vertices | MIT | Trained on VOCASET/BIWI, FLAME-based → NC data | 2022–23 | — | Yes | **REFERENCE-ONLY** |
| **EmoTalk / MeshTalk / EMOCA** | Audio/3D face | **CC BY-NC 4.0 / CC BY-NC 4.0 / NC research license** | NC | — | — | Yes | **AVOID** |

### 2.8 2D animation

| Tool | What it does | Code license | Activity | Install route | GPU? | Verdict |
|---|---|---|---|---|---|---|
| **Blender Grease Pencil v3** | 2D strokes/fills in 3D space, layers, modifiers, rendered by EEVEE/Workbench | GPL (Blender) | 5.1 added direct fill control + boolean fill holes; 5.0 renamed API to `bpy.types.GreasePencil` / `bpy.data.grease_pencils` | bpy. **Verified** `layers.new` → `frames.new` → `drawing.add_strokes` | No | **ADOPT** (2D film path) |
| **Synfig Studio** | Vector/bone 2D animation; `.sif` XML scenes; CLI renderer `synfig` | GPL-3.0 | 1.5.4 released 2026-01-18 | apt/AppImage; run as separate process | No | **TRIAL** (agents can write `.sif` XML; GPL is fine as a separate program) |
| **OpenToonz** | Pro 2D (Studio Ghibli lineage) | BSD-3-Clause (copyright through 2026) | Active | apt/flatpak | No | **REFERENCE** (GUI-centric; Rhubarb `.dat` export exists) |
| **Spine runtimes** | Skeletal 2D runtime | **Spine Runtimes License: every user of the product needs their own Spine Editor license** | Active | — | — | **AVOID** |
| **DragonBones runtime** | Skeletal 2D runtime | MIT | Editor effectively abandoned | — | — | REFERENCE |
| **Godot Skeleton2D / Bone2D / Polygon2D skinning / SkeletonModification2D (CCDIK, FABRIK, TwoBoneIK, Jiggle, LookAt)** | 2D cut-out rigs in games | MIT | Active (Godot 4.x) | Godot | No | **ADOPT** (game path) |

---

## 3. License traps (read before integrating anything)

1. **"MIT code, non-commercial brain."**
   - MDM, MoMask, MotionGPT, MLD, 4D-Humans, WHAM, FaceFormer and CodeTalker all have permissive *code*. Their *weights* are trained on AMASS/HumanML3D, LRS2, VOCASET/FLAME, or need SMPL.
   - The AMASS and SMPL licenses forbid commercial use, redistribution, and training networks for commercial use.
   - Never bundle these weights. Never auto-download them in the default pipeline. Never ship their outputs in our showcase.
2. **SMPL is everywhere.**
   - Many repos tell you to run `download_smpl_files.sh` or register on smpl.is.tue.mpg.de. That download is non-commercial and cannot be redistributed; commercial use goes through Meshcapade.
   - Treat any dependency on `smplx` model files (`.pkl`/`.npz`) as a red flag.
3. **HumanML3D is "MIT" on GitHub.** That covers the scripts and text. The motions must be rebuilt from AMASS, which is NC.
4. **The license may cover the code itself.** MotionLCM, MotionDiffuse (S-Lab), HumanTOMATO/MotionLLM (IDEA), GVHMR, STMC (NVIDIA) and RigAnything (Adobe Research) are non-commercial at the *code* level. Don't even copy snippets (PLAN §7).
5. **New "registration" licenses.**
   - ZJU3DV relicensed EasyMocap and MotionStreamer in 2026 under a "Project Registration License". Any organisation must register *before* use, commercial or not, and the obligation passes to downstream recipients.
   - Incompatible with a frictionless Apache-2.0 tool. Avoid.
6. **Territory-limited community licenses.**
   - HY-Motion 1.0 does not apply in the EU, UK or South Korea, and use there is unlicensed.
   - It also has a 1M-MAU clause and bans using outputs to improve other models.
   - If offered at all, it must be a user-installed, user-accepted plugin. We never redistribute the weights and never train on its outputs.
7. **Mixamo:**
   - Royalty-free inside your project, per Adobe's FAQ.
   - Adobe staff FAQ: you may not distribute raw character/animation files (no repo, no asset pack) and may not train ML models on them.
   - So: no Mixamo files in our repo, no Mixamo-trained weights (that rules out Make-It-Animatable's released weights), and no scraping. The same reasoning applies to **ModelsResource**-trained weights (SkinTokens, RigNet): ripped game assets.
8. **AGPL (FreeMoCap and its Blender add-on).** Don't copy, import or vendor it. Only the user running it as a separate program and handing us BVH/FBX is clean.
9. **Wav2Lip ecosystem.** Wav2Lip is NC (LRS2). SadTalker's Apache-2.0 explicitly excludes its bundled third-party components, which include `wav2lip.pth`, Basel Face Model files and GFPGAN weights. Many "Apache" talking-head repos inherit NC sub-weights the same way.
10. **Spine.** The runtimes look open on GitHub, but their license requires every end user to own a Spine Editor license. Unusable for an open tool.
11. **README vs LICENSE mismatch.** Rokoko's Blender add-on README badge says MIT; `LICENSE.md` is LGPL-3.0. Trust the LICENSE file and record both in THIRD_PARTY.md.
12. **Unlicensed repos** (scaredyfish rhubarb add-on, several "mediapipe-to-blender" scripts): no license means no rights. Reference only.
13. **Proprietary "free" tools** (AccuRig, Mixamo, Rokoko Vision, Cascadeur free tier): free-as-in-beer, not automatable, not redistributable. Never put them on the critical path.
14. **GPL boundary.**
    - GPL-3 Blender add-ons (KeeMap, Wiggle 2, BlendArMocap, KBS Retarget, Rigify itself) may be reused **only inside `adapters/blender/` (GPL-3.0-or-later)**, never in the Apache core.
    - The core sends JSON ops; the add-on executes them. Keep it that way.
15. **Data attribution.** CMU (requested acknowledgement) and 100STYLE (CC BY 4.0) need credits in THIRD_PARTY.md and in the film credits / production log. Quaternius and Mesh2Motion are CC0, but credit anyway.

---

## 4. Integration notes for ADOPT tools

### 4.1 Where things live

```
src/animatica/audio/lipsync.py        (Apache)  run Rhubarb, parse JSON → VisemeTrack
src/animatica/animation/procedural/   (Apache)  generators → batches of ops (pure math, no bpy)
src/animatica/animation/retarget_maps/(Apache)  JSON bone maps (CMU, 100STYLE, Quaternius, Mesh2Motion → Rigify / simple biped / robot)
adapters/blender/ops_anim.py          (GPL)     executes insert_keyframes, apply_lipsync, create_rig, import_motion, bake_spring…
knowledge/animation/                  recipes: 12 principles → parameter presets; Blender 5.x API notes (channelbags!)
```

### 4.2 `insert_keyframes` (batched, columnar)

The columnar form cuts tokens about 3× compared with per-key objects:

```json
{"op": "insert_keyframes",
 "target": "robot_rig", "bone": "head",          // bone optional → pose.bones["head"]
 "path": "rotation_euler", "index": 2,
 "frames": [1, 12, 18, 30],
 "values": [0.0, -0.15, 0.35, 0.3],
 "interp": "BEZIER",                              // or per-key list; also CONSTANT, LINEAR, BACK, ELASTIC, BOUNCE
 "easing": "AUTO",                                // EASE_IN | EASE_OUT | EASE_IN_OUT
 "handles": "AUTO_CLAMPED",
 "modifiers": [{"type": "NOISE", "scale": 8, "strength": 0.03, "phase": 1.7}],
 "action": "shot02_robot", "slot": "OBRobot"}     // optional; default = active action/slot
```

**Executor (Blender ≥ 5.0)**, verified pattern:

```python
from bpy_extras import anim_utils
ad = id_.animation_data or id_.animation_data_create()
act = ad.action or bpy.data.actions.new(name); ad.action = act
slot = ad.action_slot or act.slots.new(id_type, slot_name); ad.action_slot = slot
cb = anim_utils.action_ensure_channelbag_for_slot(act, slot)
fc = cb.fcurves.ensure(data_path, index=index, group_name=bone or "Object")
start = len(fc.keyframe_points); fc.keyframe_points.add(len(frames))
fc.keyframe_points.foreach_set("co", flat_pairs)   # bulk write; set interpolation per point after
fc.update()
```

**Validation:**
- Frames must be strictly increasing and inside the scene range.
- Values must be finite and the right length for the path.
- The `path` must resolve with `id_.path_resolve()`.
- Reject `action.fcurves` usage in submitted scripts with a clear error that points to the channelbag API. Blender 5.0 removed `action.fcurves`, `action.groups` and `action.id_root`.

### 4.3 Lip sync: Voice agent → Animator

1. **Voice agent:**
   - Runs the TTS line to `audio/line01.wav` (16-bit PCM).
   - Writes the exact line to `audio/line01.txt`.
   - Runs:
     `rhubarb -q --machineReadable -r pocketSphinx --dialogFile audio/line01.txt --extendedShapes GHX -f json -o audio/line01.cues.json audio/line01.wav`
     Use `-r phonetic` for non-English.
   - Stores a compact `VisemeTrack {line_id, offset_sec, cues:[[start,end,shape],…]}` in the scene model and production log.
   - Optional shortcut: if the TTS engine exposes phoneme durations, map phonemes → Rhubarb shapes directly and skip recognition. Keep Rhubarb as the default because it is engine-agnostic.
2. **Animator** emits one op per line:

```json
{"op": "apply_lipsync", "target": "robot_face", "mode": "shape_keys",
 "cues": "audio/line01.cues.json", "audio_offset_frames": 48, "fps": 24,
 "mapping": {"A": "MBP", "B": "etc", "C": "E", "D": "AI", "E": "O", "F": "U", "G": "FV", "H": "L", "X": "rest"},
 "lead_frames": 1, "blend_frames": 2, "intensity": 0.9, "hold_min_frames": 2}
```

3. **The executor (GPL add-on):**
   - Converts seconds to frames: `round((start+offset)*fps) - lead_frames`. A 1-frame lead reads better, which is common animator practice.
   - Drops cues shorter than `hold_min_frames`, merging them into their neighbour.
   - For each cue, keys the target shape to `intensity` and the others to 0, with `blend_frames` cross-fades. Use BEZIER for organic mouths and CONSTANT for 2D/robot "swap" style.
   - Verified: keyframing 9 shape keys from a Rhubarb JSON takes 0.03 s.
4. **Mouth rigs supported via `mode`:**
   - `shape_keys`: one key per Preston Blair name.
   - `pose_library`: Action per shape, the same mechanism the Rhubarb-NG add-on uses.
   - `material_swap`: a texture-atlas index for screen-faced robots or 2D.
   - `gp_layer`: Grease Pencil frame swap.
   - `bone_param`: a *parametric* mouth with three channels (`jaw_open`, `lips_wide`, `lips_round`). This is the easiest one for agents to build procedurally on a robot:

| Rhubarb | Preston Blair | jaw_open | lips_wide | lips_round | notes |
|---|---|---|---|---|---|
| A | MBP | 0.0 | 0.3 | 0.0 | lips pressed |
| B | etc | 0.15 | 0.6 | 0.0 | teeth clenched, most consonants |
| C | E | 0.4 | 0.6 | 0.0 | |
| D | AI | 0.8 | 0.5 | 0.0 | wide open |
| E | O | 0.45 | 0.2 | 0.6 | |
| F | U | 0.2 | 0.0 | 1.0 | pucker (W, OO) |
| G | FV | 0.1 | 0.4 | 0.0 | lower lip under teeth (shape key if available) |
| H | L | 0.45 | 0.4 | 0.0 | tongue up (optional) |
| X | rest | 0.0 | 0.2 | 0.0 | relaxed |

(The amounts are our starting presets, not from a source; tune per character.)

5. **Critic check (cheap and geometric):** for every dialogue interval, the summed mouth-channel values must change at least N times per second. Flag "mouth not moving during dialogue" (PLAN Milestone 4) without a render.

### 4.4 Rigging ops

```json
{"op": "create_rig", "target_mesh": "hero", "template": "rigify_human",   // rigify_human | rigify_quadruped | simple_biped | robot_rigid | prop_single
 "fit": "auto_bbox", "skin": "auto_weights",                              // auto_weights | rigid_parts | envelope | none
 "generate": true, "name": "hero_rig"}
```

- **`robot_rigid`:** the executor builds a short FK chain (root → hips → spine → head, arms, wheels/legs) and bone-parents each named part. No skinning failures; ideal for the north-star robot.
- **`rigify_human`:**
  1. metarig add;
  2. scale/fit to the mesh bounding box (later: landmark fit by vision);
  3. `rigify_generate` (6.4 s on CPU);
  4. `ARMATURE_AUTO`.
  - If bone heat fails, the executor must catch the warning, fall back to envelope weights or rigid parts, and report it in the compact reply.
- The executor returns only `{rig, bones: N, control_bones: [...short list...], warnings}`. Never the full bone list unless queried with a filter.

### 4.5 Stock motion + retarget

```json
{"op": "import_motion", "source": "lib://quaternius_ual/Walk_Loop", "target_rig": "hero_rig",
 "map": "quaternius_to_rigify", "frame_start": 1, "speed": 1.0, "in_place": true,
 "bake": true, "nla_track": "base", "blend_in": 6, "blend_out": 6}
```

- `lib://` resolves to a local, license-tagged clip index (`assets/motion/index.json`). Each entry has license, source URL, attribution text, rig profile, loopable flag, and tags such as walk/happy/tired. The Animator searches the tags; the LLM never invents file paths.
- The executor:
  1. imports (BVH via `import_anim.bvh`, FBX/GLB via the importers);
  2. aligns rest poses;
  3. adds Copy Rotation (plus hips Copy Location, scaled by leg-length ratio);
  4. runs `nla.bake(visual_keying=True, clear_constraints=True)`;
  5. pushes the result to an NLA strip.
- Procedural layers (look-at, spring, noise) go on top as further strips.

### 4.6 Procedural generators (Apache core emits ops; no bpy needed)

- `walk_cycle(rig, stride, period_frames, bounce, sway, arm_swing, style)` returns `insert_keyframes` on IK foot targets + hips. A CYCLES modifier loops it, and the root is translated at `stride/period` speed to avoid foot sliding.
- `idle_breath(rig, amplitude, period)`, `blink(face, mean_interval, jitter)`, `look_at(rig, target, lead_frames)`.
- `principled_move(obj, from, to, frames, anticipation=0.15, overshoot=0.1, settle_frames=6)` returns 4–5 keys with BACK/BEZIER easing. This encodes anticipation, ease and follow-through.
- `bake_spring(rig, bones, stiffness, damping, gravity)`: the executor simulates a damped spring per frame in Python and writes keys. It is deterministic, so renders match previews.
- `noise_layer(target, path, scale, strength, seed)` returns a NOISE F-modifier op.

### 4.7 Godot (game path)

- Export glTF from Blender (Apache-2.0 glTF-Blender-IO is built in) with NLA tracks as animations.
- In Godot, use AnimationPlayer/AnimationTree, `RetargetModifier3D` + `SkeletonProfileHumanoid` for shared clips, and `SpringBoneSimulator3D` for antennae.
- For 2D: Skeleton2D + Bone2D + Polygon2D skinning, with Rhubarb cues mapped onto `AnimatedSprite2D` frames.

---

## 5. Pipelines

### 5.1 "No-GPU baseline": works tonight in a CPU-only container

| Step | Tool | Proven here? |
|---|---|---|
| Engine | `pip install bpy==5.3.0` (Python 3.13 manylinux wheel, 427 MB) or the official Blender Linux tarball | **Yes** |
| Character rig | Robot: `robot_rigid` bone parenting. Humanoids: Rigify metarig + generate, then automatic weights | **Yes** (Rigify 6.4 s; auto weights OK) |
| Body animation | Procedural generators (walk, idle, look-at, principled moves) + NOISE/CYCLES modifiers + spring bake | **Yes** (keys/modifiers) |
| Stock motion (optional) | Quaternius UAL (CC0), Mesh2Motion (CC0), CMU BVH subset, 100STYLE (CC BY) → `import_motion` + own retargeter | BVH importer present; retargeter to be written |
| Dialogue | TTS (see 03-voice report) → Rhubarb 1.14.0 Linux binary with `--dialogFile` → `apply_lipsync` | **Yes** (binary + JSON + shape keys) |
| 2D variant | Grease Pencil v3 API strokes + frame swaps; lip sync as GP frame swaps | **Yes** (stroke creation) |
| Video reference (user-supplied only) | MediaPipe Pose (CPU) → our landmark solver → keys | Not run here; `pip install mediapipe` |
| Verification | Critic: geometric checks (feet vs floor, mouth activity during dialogue, jitter = 2nd-derivative spikes in F-curves) + Workbench/EEVEE preview | — |

**Setup commands:**

```bash
pip install bpy==5.3.0 bvhio mediapipe
curl -L -o /opt/rhubarb.zip https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/Rhubarb-Lip-Sync-1.14.0-Linux.zip
unzip -q /opt/rhubarb.zip -d /opt && ln -s /opt/Rhubarb-Lip-Sync-1.14.0-Linux/rhubarb /usr/local/bin/rhubarb
```

Keep the whole `res/` folder next to the binary; it holds the Sphinx models.

### 5.2 "GPU upgrade" pipeline (later, all opt-in providers with license metadata)

| Capability | Provider | Gate |
|---|---|---|
| Auto-rig arbitrary generated meshes | UniRig (MIT) → SkinTokens/TokenRig (MIT, provenance warning) / Puppeteer (Apache, check weights) | `rig.provider=unirig`; fall back to Rigify/bone heat on failure; Critic checks deformation |
| Text-to-motion | HY-Motion-1.0-Lite (24 GB) | User must accept the Tencent license; blocked if the user declares EU/UK/KR; outputs flagged in the production log; never used for training |
| Research-mode text-to-motion | MoMask / MDM installed by the user | Explicit "non-commercial research mode" flag; outputs watermarked in the log as NC |
| Better video mocap | MMPose/ViTPose (Apache) 2D → our lifter, or MediaPipe heavy | Per-checkpoint license check |
| Facial animation from audio | NVIDIA Audio2Face-3D v3.0 (NVIDIA Open Model License) → solve to our shape keys/ARKit-style set | NVIDIA GPU + TensorRT; Audio2Emotion needs a separate gated click-through |
| Lip-sync refinement | Rhubarb cues + Audio2Face jaw/lip curves blended | — |

---

## 6. Sources

**Lip sync / facial**
- Rhubarb Lip Sync repo, LICENSE, README, CHANGELOG, releases: https://github.com/DanielSWolf/rhubarb-lip-sync · https://raw.githubusercontent.com/DanielSWolf/rhubarb-lip-sync/master/LICENSE.md · https://github.com/DanielSWolf/rhubarb-lip-sync/releases · Linux binary: https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/Rhubarb-Lip-Sync-1.14.0-Linux.zip
- Rhubarb Lipsync NG (Blender): https://github.com/Premik/blender_rhubarb_lipsync_ng
- scaredyfish blender-rhubarb-lipsync: https://github.com/scaredyfish/blender-rhubarb-lipsync
- Papagayo-NG: https://github.com/morevnaproject-org/papagayo-ng
- Wav2Lip: https://github.com/Rudrabha/Wav2Lip
- SadTalker: https://github.com/OpenTalker/SadTalker
- NVIDIA Audio2Face-3D SDK: https://github.com/NVIDIA/Audio2Face-3D-SDK · training framework: https://github.com/NVIDIA/Audio2Face-3D-training-framework · model card: https://huggingface.co/nvidia/Audio2Face-3D-v3.0
- FaceFormer: https://github.com/EvelynFan/FaceFormer · CodeTalker: https://github.com/Doubiiu/CodeTalker · EmoTalk: https://github.com/psyai-net/EmoTalk_release · MeshTalk: https://github.com/facebookresearch/meshtalk · EMOCA: https://github.com/radekd91/emoca
- MuseTalk: https://github.com/TMElyralab/MuseTalk · LatentSync: https://github.com/bytedance/LatentSync · LivePortrait: https://github.com/KwaiVGI/LivePortrait · EchoMimic v2: https://github.com/antgroup/echomimic_v2

**Rigging**
- Rigify manual: https://docs.blender.org/manual/en/latest/addons/rigging/rigify · generate.py: https://projects.blender.org/blender/blender-addons/src/tag/v4.1.0/rigify/generate.py
- UniRig: https://github.com/VAST-AI-Research/UniRig · HF: https://huggingface.co/VAST-AI/UniRig
- SkinTokens: https://github.com/VAST-AI-Research/SkinTokens
- Puppeteer: https://github.com/Seed3D/Puppeteer · MagicArticulate: https://github.com/Seed3D/MagicArticulate
- Make-It-Animatable: https://github.com/jasongzy/Make-It-Animatable
- RigNet: https://github.com/zhan-xu/RigNet · RigAnything: https://github.com/Isabella98Liu/RigAnything
- Robust Skin Weights Transfer: https://github.com/rin-23/RobustSkinWeightsTransferCode · Blender port: https://github.com/sentfromspacevr/robust-weight-transfer
- Mesh2Motion: https://github.com/scottpetrovic/mesh2motion-app · assets: https://github.com/Mesh2Motion/mesh2motion-assets
- AccuRig 2.0 coverage: https://www.cgchannel.com/2025/07/rig-and-animate-3d-characters-for-free-with-accurig-2-0/ · EULA thread: https://discussions.reallusion.com/t/question-about-accurig-2s-eula/15034
- Mixamo FAQ (Adobe): https://helpx.adobe.com/be_en/creative-cloud/faq/mixamo-faq.html · Adobe community licensing FAQ: https://community.adobe.com/questions-696/mixamo-faq-licensing-royalties-ownership-eula-and-tos-589400

**Motion generation**
- MDM: https://github.com/GuyTevet/motion-diffusion-model · MoMask: https://github.com/EricGuo5513/momask-codes · T2M-GPT: https://github.com/Mael-zys/T2M-GPT · MotionGPT: https://github.com/OpenMotionLab/MotionGPT · MotionLCM: https://github.com/Dai-Wenxun/MotionLCM · MLD: https://github.com/ChenFengYe/motion-latent-diffusion · MotionDiffuse: https://github.com/mingyuan-zhang/MotionDiffuse · HumanTOMATO: https://github.com/IDEA-Research/HumanTOMATO · STMC: https://github.com/nv-tlabs/stmc · MotionStreamer: https://github.com/zju3dv/MotionStreamer · AnyTop: https://github.com/Anytop2025/AnyTop · ProtoMotions: https://github.com/NVlabs/ProtoMotions
- HY-Motion 1.0: https://github.com/Tencent-Hunyuan/HY-Motion-1.0 · License: https://raw.githubusercontent.com/Tencent-Hunyuan/HY-Motion-1.0/master/License.txt · paper: https://arxiv.org/abs/2512.23464v1
- HumanML3D: https://github.com/EricGuo5513/HumanML3D
- Motion Matching: https://github.com/orangeduck/Motion-Matching

**Body models / datasets**
- SMPL license: https://smpl.is.tue.mpg.de/modellicense.html · AMASS license: https://amass.is.tue.mpg.de/license.html
- CMU Mocap: http://mocap.cs.cmu.edu/ · FAQ: http://mocap.cs.cmu.edu/faqs.php
- 100STYLE: https://zenodo.org/record/8127870 · https://ianxmason.github.io/100style
- Quaternius UAL: https://quaternius.com/packs/universalanimationlibrary.html · UAL 2: https://quaternius.com/packs/universalanimationlibrary2.html
- Bandai Namco dataset: https://github.com/BandaiNamcoResearchInc/Bandai-Namco-Research-Motiondataset
- Ubisoft LaFAN1: https://github.com/ubisoft/ubisoft-laforge-animation-dataset

**Video mocap**
- MediaPipe: https://github.com/google-ai-edge/mediapipe · Pose Landmarker guide: https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker · BlazePose GHUM 3D model card (mirror): https://dcmpx.remotevs.com/com/googleapis/storage/SL/mediapipe-assets/Model%20Card%20BlazePose%20GHUM%203D.pdf · open question thread: https://discuss.ai.google.dev/t/commercial-use-of-mediapipe-pose-landmarker-full/184033
- FreeMoCap: https://github.com/freemocap/freemocap · PyPI: https://pypi.org/project/freemocap
- BlendArMocap: https://github.com/cgtinker/BlendArMocap
- 4D-Humans: https://github.com/shubham-goel/4D-Humans · WHAM: https://github.com/yohanshin/WHAM · GVHMR: https://github.com/zju3dv/GVHMR · EasyMocap: https://github.com/zju3dv/EasyMocap · Sapiens: https://github.com/facebookresearch/sapiens · MMPose: https://github.com/open-mmlab/mmpose · ViTPose: https://github.com/ViTAE-Transformer/ViTPose · MotionBERT: https://github.com/Walter0807/MotionBERT

**Retargeting / procedural**
- Rokoko Blender add-on: https://github.com/Rokoko/rokoko-studio-live-blender · KeeMap: https://github.com/nkeeline/Keemap-Blender-Rig-ReTargeting-Addon · Retarget (KBS-DEV): https://extensions.blender.org/add-ons/retarget/versions/ · Retarget BVH: https://bitbucket.org/Diffeomorphic/retarget_bvh.git/wiki · bvhio: https://pypi.org/project/bvhio/ · Wiggle 2: https://github.com/shteeve3d/blender-wiggle-2

**Blender / Godot / 2D**
- bpy on PyPI: https://pypi.org/project/bpy/
- Blender 5.0 Python API notes (channelbags, GP renames): https://developer.blender.org/docs/release_notes/5.0/python_api/ · 5.0 animation & rigging: https://developer.blender.org/docs/release_notes/5.0/animation_rigging/ · 4.3 Python API: https://developer.blender.org/docs/release_notes/4.3/python_api/ · 5.1 overview: https://www.cgchannel.com/2026/03/discover-5-key-features-in-blender-5-1
- Godot IK in 4.6 (history of LookAtModifier3D/RetargetModifier3D 4.4, SpringBoneSimulator3D 4.5): https://godotengine.org/article/inverse-kinematics-returns-to-godot-4-6/ · SkeletonModifier3D docs: https://docs.godotengine.org/en/4.5/classes/class_skeletonmodifier3d.html · Godot license: https://github.com/godotengine/godot
- Synfig 1.5.4: https://www.synfig.org/2026/01/18/synfig-studio-1-5-4-released/ · repo: https://github.com/synfig/synfig
- OpenToonz: https://github.com/opentoonz/opentoonz
- Spine runtimes license: https://github.com/EsotericSoftware/spine-runtimes · DragonBones: https://github.com/DragonBones/DragonBonesJS
- glTF-Blender-IO: https://github.com/KhronosGroup/glTF-Blender-IO
