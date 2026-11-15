# Research 01: 3D Asset Creation, Scene Building and Blender Automation

*Animatica research series. Compiled 2026-11-15. Scope: open-source tools that would reduce our work on the Blender film track (and, through glTF, the Godot track). Each license below was read from the project's LICENSE file, model card or terms page as of the compile date, unless marked **unverified**.*

**Method and limits.** I read license files straight from `raw.githubusercontent.com` and package metadata from the PyPI and npm JSON APIs. Model cards, terms pages and secondary sources came through web fetch. This session could not reach the GitHub REST API, so **star counts are missing**. Activity is measured by the latest PyPI or npm release, or the latest dated release I could find. In this sandbox, Hugging Face (from curl), blender.org, polyhaven.com, ambientcg.com, kenney.nl, poly.pizza and sketchfab.com were all blocked by the egress proxy (see §4.0). I also ran **hands-on tests** of the `bpy` wheel in this container: 2 vCPU, 7 GB RAM, no GPU, Mesa EGL (§4.1).

---

## 1. Executive summary: top 10 recommendations (ranked by impact)

1. **ADOPT the `bpy` 5.3.0 PyPI wheel (released 2026-11-10, Python 3.13 only, GPL-3.0) as the headless Blender engine, inside `adapters/blender` only.** I installed it in this container and ran it. Workbench, EEVEE and Cycles-CPU all rendered non-black frames headless, with no GPU and no X server, through Mesa's EGL software path. The wheel is GPL, so the Apache core must **never `import bpy`**. Run it in a subprocess (`python -m animatica_blender_runner`) or inside a `blender -b` process, which matches PLAN §7.
2. **ADOPT this render strategy, based on measurements on 2 CPU cores:**
   - Use **Workbench for every critic preview**: about 0.09 s per frame once warm at 480×270.
   - Use **Cycles on the CPU with low samples and the OIDN denoiser for finals**: about 2.3 s per frame at 480×270 with 32 spp, and about 8.6 s at 960×540, on the default scene.
   - Use **EEVEE only when a GPU is present**. On llvmpipe it took about 9 s per frame at 480×270 with 8 samples, plus 11 s or more of shader warm-up. That is about 70 minutes for a 20 s short.
3. **ADOPT Blender's built-in glTF exporter (Khronos glTF-Blender-IO, Apache-2.0) and its built-in USD exporter, plus `trimesh` (MIT, 5.2.1) and `pygltflib` (MIT, 1.16.5) in the core.** With these, the Apache core can inspect, validate and measure assets (bounds, triangle counts, materials) without touching GPL code. I tested all of them on Python 3.13.
4. **ADOPT Poly Haven (CC0, free keyless API) as the first asset source, with ambientCG (CC0, API v2/v3) for PBR materials.** Bundle a small vendored starter set of **Kenney / Quaternius CC0** low-poly packs, plus Blender's **Human Base Meshes (CC0)**. Poly Haven's API terms require two things: a unique User-Agent, and a visible "Powered by Poly Haven" style credit wherever we show live API content. Because the sandbox blocks these hosts, asset search must **degrade gracefully to procedural primitives**.
5. **ADOPT cheap geometric critic checks, reimplemented in our own code.** Use Blender's `bpy_extras.object_utils.world_to_camera_view` for frustum coverage, `mathutils.bvhtree.BVHTree` for overlap and floor penetration, and `object.bound_box` for bounds. Add image statistics for black or blown-out frames. Run the Blender-side checks in the GPL adapter and return compact numbers to the core. Mirror the same checks core-side with `trimesh` on exported GLB files.
6. **TRIAL `mcp-for-blender` (formerly `blender-mcp`; MIT; v2.0.0 released 2026-09-16) as the reference for live add-on mode.** Its socket-server pattern (port 9876, JSON commands), "look" multi-view verification and Poly Haven importer are the closest prior art. It is MIT, so we may copy and adapt code into our GPL add-on with attribution. Leave out its telemetry and premium/proprietary generator paths. Also study the **official Blender Lab MCP server** (GPL-3.0, v1.0.3, 2026-09-11) for its API-doc search tools. Being GPL, it can only inform the adapter, never the core.
7. **REFERENCE-ONLY: reimplement ideas from the LLM-to-3D research.** The papers are LL3M, BlenderGym, BlenderAlchemy, SceneCraft, 3D-GPT and SceneWeaver. The ideas to take are:
   - RAG over the Blender API docs
   - code-plus-render self-critique
   - a VLM verifier choosing among N candidate edits
   - library learning of reusable functions
   - procedural-parameter control

   Most of these repos have **no license file**, and LL3M's license is a demonstration licence that **forbids modification**. Do not copy any of their code.
8. **TRIAL Infinigen (BSD-3-Clause, `infinigen` 1.26.0 released 2026-11-11) and its new ProcFunc API (BSD-style, arXiv 2604.26943) for terrain, vegetation and indoor set dressing.** Both pin **`bpy==4.2.0` / Python 3.11**, which conflicts with our bpy 5.3 on Python 3.13. Run them as an offline asset baker in a separate virtual environment. Cache the resulting `.blend`/`.glb` files and import them through `import_asset`. ProcFunc's geometry-nodes-to-Python transpiler is also a strong idea for our knowledge base.
9. **Image-to-3D is optional and GPU-only. Hook it up behind a license gate.**
   - Best fully permissive choices: **TripoSG** (MIT code and weights, more than 8 GB VRAM, geometry only), **Step1X-3D** (Apache-2.0 weights; its texture stage builds on SDXL, which carries OpenRAIL++-M use restrictions) and **TripoSR** (MIT, about 6 GB VRAM, CPU fallback possible).
   - **TRELLIS.2** has MIT weights and is the best quality, but needs 24 GB VRAM. Its reference pipeline also depends on **nvdiffrast**, which is non-commercial, and on **DINOv3**, which has a custom Meta licence. Use a re-implementation without nvdiffrast (for example the ComfyUI-native path, GPL-3) or keep it as an opt-in, user-installed plugin.
   - **AVOID Hunyuan3D** (its licence excludes the EU, UK and South Korea), **InstantMesh** (depends on Zero123++ weights, which are CC-BY-NC), **SF3D/SPAR3D** (free only below US$1M revenue) and **LLaMA-Mesh** (non-commercial).
10. **ADOPT `usd-core` 26.11 (released 2026-10-21; licence TOST-1.0, which is Apache-2.0 with a changed trademark clause) for the USD-shaped scene model export.** Run it in the core process without bpy. Validate with Blender's USD importer. I tested importing `bpy` and `pxr` together, and it works, but keep them in separate processes for licence hygiene anyway.

---

## 2. Tables per subtopic

Legend:
- **Verdict:** ADOPT = depend on it now; TRIAL = prototype behind a flag; REFERENCE-ONLY = read for ideas, don't copy code; AVOID.
- **Activity:** latest release found, with its date.
- **GPU?:** whether inference or rendering needs a GPU.

### 2.1 Blender automation and AI bridges

| Tool | What it does | Code license | Weights/asset license | Activity | Install (headless Linux) | GPU? | Verdict |
|---|---|---|---|---|---|---|---|
| [`bpy` wheel](https://pypi.org/project/bpy/) | Blender as a Python module | GPL-3.0 | n/a | 5.3.0, 2026-11-10 | `pip install bpy` (needs CPython 3.13 exactly; Linux x86-64 wheel 427 MB; glibc 2.28+). No Linux ARM64 wheel | No (tested: Mesa EGL CPU) | **ADOPT**: works headless here; keep it inside the GPL adapter process |
| Blender binary (`blender -b`) | Full Blender CLI | GPL-3.0 | n/a | 5.3 (matches the wheel) | Official tarball from download.blender.org (**blocked in this sandbox**); apt versions lag | No | **ADOPT as fallback**: needed for add-ons/extensions that expect a full install |
| [mcp-for-blender (ahujasid)](https://github.com/ahujasid/mcp-for-blender), formerly blender-mcp | MCP server plus Blender add-on socket bridge; multi-view "look"; Poly Haven/Sketchfab/Poly Pizza import; paid generator hooks | MIT ([LICENSE](https://raw.githubusercontent.com/ahujasid/mcp-for-blender/HEAD/LICENSE)) | n/a | PyPI `mcp-for-blender`/`blender-mcp` 2.0.0, 2026-09-16 | `uvx mcp-for-blender`; add-on `addon.py` | No | **TRIAL**: best reference for live mode; MIT code can be adapted into our GPL add-on. Has telemetry (opt-out) and an unauthenticated socket |
| [Official Blender Lab MCP](https://www.strayspark.studio/blog/official-blender-mcp-server-comparison-2026) (`projects.blender.org/lab/blender_mcp`) | 26 tools: run code, scene/object summaries, API-doc and manual search, screenshots, renders; CLI variants run in background Blender | GPL-3.0 (per [aiwiki summary](https://aiwiki.ai/wiki/blender_mcp); repo **not reachable from this sandbox**) | n/a | v1.0.3, 2026-09-11; needs Blender ≥5.1 | Blender extension plus MCP bundle | No | **REFERENCE-ONLY** (for the core); copying into the GPL adapter is legally possible. Its bundled API-doc search is the idea to copy for `knowledge/` |
| [CommonSenseMachines/blender-mcp](https://mcpservers.org/servers/CommonSenseMachines/blender-mcp) | MCP bridge to the CSM.ai cloud (asset search, Mixamo animation) | **None found**; repo returns 404 on raw GitHub as of 2026-11-15 | Proprietary CSM API | Unknown / possibly removed | n/a | Cloud | **AVOID**: no licence, vendor lock-in, repo gone |
| [fake-bpy-module](https://github.com/nutti/fake-bpy-module) | Type stubs for bpy (IDE, ruff, mypy, LLM context) | MIT | n/a | 20261031, 2026-10-31 | `pip install fake-bpy-module` | No | **ADOPT (dev-only)**: lets the core type-check generated scripts without GPL bpy |
| [bpy-helper](https://github.com/iamNCJ/bpy-helper) | Small render/camera/IO helpers | MIT | n/a | 0.0.13, 2025-12-25 | pip | No | **REFERENCE-ONLY**: too small to justify a dependency |
| [BlenderSynth](https://github.com/OllieBoyne/BlenderSynth) | Synthetic-data rendering harness (multi-camera, passes) | MIT | n/a | 0.3.3, 2025-08-27 | pip | No | **REFERENCE-ONLY**: pass/AOV recipes |
| [bpycv](https://github.com/DIYer22/bpycv) | Instance segmentation and depth from Blender | MIT | n/a | 1.0.0, 2025-07-31 | pip | No | **REFERENCE-ONLY**: idea for object-coverage masks in the critic |
| [Kubric](https://github.com/google-research/kubric) | Synthetic dataset generator (Blender + PyBullet) | Apache-2.0 | n/a | PyPI 0.1.1, 2021-08-25 (stale) | Docker | No | **AVOID** (stale); read its scene-randomisation ideas |
| [`mathutils` standalone](https://gitlab.com/ideasman42/blender-mathutils) | Blender maths outside Blender | GPL-3.0+ | n/a | 5.1.0, 2026-02-25 | pip | No | **AVOID in core** (GPL); use numpy in the core |

### 2.2 Procedural generation

| Tool | What it does | Code license | Asset license | Activity | Install | GPU? | Verdict |
|---|---|---|---|---|---|---|---|
| Blender Geometry Nodes (built in) | Node-based procedural modelling; scriptable via `bpy.types.GeometryNodeTree` | GPL-3.0 (Blender) | n/a | Ships with 5.3 | Comes with bpy | No | **ADOPT**: build node groups from script mode; store recipes in `knowledge/` |
| [Infinigen](https://github.com/princeton-vl/infinigen) (Princeton) | Procedural nature, terrain and indoor scenes; Infinigen-Indoors; Articulated | BSD-3-Clause | Generated output belongs to the user | `infinigen` 1.26.0, 2026-11-11 | `pip install infinigen` (**pins `bpy==4.2.0`, Python 3.11**); heavy | CPU OK (slow); GPU helps Cycles | **TRIAL**: offline asset baker in a separate venv; cache the outputs |
| [ProcFunc](https://github.com/princeton-vl/procfunc) ([paper](https://arxiv.org/abs/2604.26943)) | Functional Python API for procedural 3D; **transpiles geometry node trees into Python** | BSD-style (Princeton 2026) | n/a | Pre-1.0 (0.x); 2026 | `uv pip install procfunc` (bpy 4.2 / Py 3.11) | No | **TRIAL**: use the transpiler to turn artist geometry nodes into agent-readable recipes |
| [Sverchok](https://github.com/nortikin/sverchok) | Parametric node add-on (architecture, math geometry) | GPL-3.0 | n/a | `bl_info` 1.4.0 (min Blender 3.5); **no extension manifest; current activity unverified** | GitHub zip into add-ons | No | **REFERENCE-ONLY**: native geometry nodes cover our needs; avoid an extra add-on dependency |
| [tree-gen](https://github.com/friggog/tree-gen) | Weber-Penn style tree generator add-on | GPL-3.0 | n/a | GitHub releases; **activity unverified** | Add-on zip | No | **REFERENCE-ONLY / TRIAL in adapter**: a simple geometry-nodes tree recipe is likely enough for stylised films |
| [Blender Human Base Meshes](https://www.cgchannel.com/2023/06/download-blender-studios-free-human-base-meshes) | Realistic and stylised human base meshes (asset bundle) | n/a | **CC0** | 2023 bundle | Download from blender.org asset bundles | No | **ADOPT**: legal character bases for the Asset agent |
| [SceneWeaver](https://github.com/Scene-Weaver/SceneWeaver) ([paper](https://arxiv.org/abs/2509.20414)) | Self-reflective agent for indoor scene synthesis (on Infinigen) | BSD-3-Clause | Depends on the asset sources used | 2025 | GitHub | Varies | **REFERENCE-ONLY**: copying is legally possible, but the stack is heavy. Take the reflect-and-repair tool loop |
| [Holodeck](https://github.com/allenai/Holodeck) (AI2) | LLM-driven house layout using Objaverse assets | Apache-2.0 | **Objaverse: mixed licences, including about 77K NC objects** | 2024 | GitHub + objathor assets | GPU for retrieval | **REFERENCE-ONLY**: the layout-constraint solver idea; its asset pool is a licence trap |
| [LayoutGPT](https://github.com/weixi-feng/LayoutGPT) | LLM writes CSS-like layouts for 2D/3D scenes | MIT | n/a | 2023 | GitHub | No | **REFERENCE-ONLY**: a compact numeric layout format for the Director/Asset agents |
| [BlenderGIS](https://github.com/domlysz/BlenderGIS) | GIS/terrain import | GPL-3.0 | Data licences vary | — | Add-on | No | **AVOID for now** (out of scope) |

### 2.3 Text/image-to-3D models (code and weight licences checked separately)

| Model | What it does | Code license | **Weights license** | Activity | Install | GPU / VRAM | Verdict |
|---|---|---|---|---|---|---|---|
| [TRELLIS.2-4B](https://huggingface.co/microsoft/TRELLIS.2-4B) (Microsoft) | Image→textured PBR GLB, 4B params, O-Voxel | MIT ([LICENSE](https://raw.githubusercontent.com/microsoft/TRELLIS.2/HEAD/LICENSE)) | **MIT** (model card) | Released Dec 2025 (arXiv 2512.14692) | GitHub `setup.sh` with CUDA extensions (flash-attn, nvdiffrast, nvdiffrec, cumesh, flexgemm) | **NVIDIA ≥24 GB**, Linux, CUDA 12.4 | **TRIAL (opt-in plugin)**: top quality, but the reference pipeline needs **nvdiffrast (NVIDIA non-commercial)** and DINOv3 (custom Meta licence). Prefer a path without nvdiffrast |
| [TRELLIS (v1)](https://github.com/microsoft/TRELLIS) | Image/text→3D (GS, RF, mesh) | MIT, but submodules differ | MIT | 2025 | GitHub `setup.sh` | NVIDIA ≥16 GB | **REFERENCE-ONLY**: superseded; diffoctreerast is derived from Inria diff-gaussian-rasterization (research-only, not re-verified) and nvdiffrast is NC |
| [TripoSG](https://huggingface.co/VAST-AI/TripoSG) (VAST) | Image→high-quality mesh (rectified flow) | MIT | **MIT** | 2025 | GitHub + HF | CUDA, >8 GB | **TRIAL**: cleanest permissive licence; geometry only, so pair with our own materials |
| [TripoSR](https://huggingface.co/stabilityai/TripoSR) | Fast feed-forward image→mesh (LRM) | MIT | **MIT** | 2024 (mature) | GitHub, pip requirements | About 6 GB VRAM; can fall back to CPU (torchmcubes CPU) | **TRIAL (low-end fallback)**: weak quality, but permissive and small |
| [Step1X-3D](https://huggingface.co/stepfun-ai/Step1X-3D) (StepFun) | Geometry + SDXL-based texture stage | Apache-2.0 | **Apache-2.0** per card (texture stage builds on SDXL, **OpenRAIL++-M** use restrictions; not re-verified) | Weights 2025-05-13 | GitHub + HF | CUDA, large (VRAM not stated) | **TRIAL**: permissive; check transitive SDXL terms |
| [Pixal3D](https://comfy.org/pixal3d-trellis2.md) | Pixel-aligned image→3D on the TRELLIS.2 backbone | Reported MIT (**unverified**; no repo LICENSE read) | Reported MIT; HF `Comfy-Org/Pixal3D` | 2026-05 | ComfyUI native (ComfyUI itself is **GPL-3.0**) | GPU | **REFERENCE-ONLY** until the licence is verified. The ComfyUI re-implementation reportedly removes nvdiffrast/nvdiffrec |
| [Hunyuan3D-2 / 2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1) (Tencent) | Image/text→shape + PBR texture | **Tencent Hunyuan 3D Community License** (covers code too) | Same | 2.1: 2025-06-13; 2.5/3.x are **API-only** ([timeline](https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026)) | GitHub + HF | CUDA, high VRAM | **AVOID**: excludes EU/UK/South Korea, 1M-MAU cap, bars using outputs to improve other models |
| [Stable Fast 3D (SF3D)](https://huggingface.co/stabilityai/stable-fast-3d) / [SPAR3D](https://github.com/Stability-AI/stable-point-aware-3d) | Fast image→UV-textured mesh | **Stability AI Community License** | Same; gated HF; free only under **US$1M annual revenue**; registration required | 2024–2025 | GitHub; CUDA/MPS/CPU | GPU recommended; CPU possible | **AVOID** for a default open-source tool (revenue-capped, not OSI); OK for a user-installed plugin |
| [InstantMesh](https://huggingface.co/TencentARC/InstantMesh) | Multi-view diffusion → sparse-view LRM | Apache-2.0 | Card says Apache-2.0, **but it relies on a fine-tuned [Zero123++](https://github.com/SUDO-AI-3D/zero123plus) UNet; Zero123++ weights are CC-BY-NC-4.0** | 2024 | GitHub | CUDA | **AVOID**: inherits non-commercial terms through Zero123++ |
| [SAM 3D Objects](https://huggingface.co/facebook/sam-3d-objects) (Meta) | Masked object in a photo → 3D | **SAM License** (custom Meta, 2025-11-19) | Same; gated (legal name, date of birth) | 2025-11 | GitHub + gated HF | GPU | **REFERENCE-ONLY**: not OSI, trade-control/ITAR clauses; built for real-photo reconstruction rather than our stylised use |
| [LLaMA-Mesh](https://github.com/nv-tlabs/LLaMA-Mesh) (NVIDIA) | LLM emitting OBJ text | **NVIDIA License, non-commercial** | Non-commercial | 2024 | GitHub | GPU | **AVOID** (copying); idea only (meshes as text tokens) |
| Hi3D v1.0 | Image→3D | "Hi3D Open License Agreement" (**unverified**) | Unverified | 2026-10-23 per timeline | — | GPU | **REFERENCE-ONLY** until read |

### 2.4 LLM-to-3D research (for ideas)

| Work | Core idea worth reimplementing | Code license | Activity | Verdict |
|---|---|---|---|---|
| [LL3M](https://arxiv.org/abs/2508.08228) ([repo](https://github.com/threedle/ll3m)) | Multi-agent team (planner, retrieval, coder, critic/verifier, refiner) writing Blender Python; **BlenderRAG** over API docs; code- and render-based self-critique; shared code context; user-editable code | **Demonstration License: non-commercial academic/evaluation only, and modification is forbidden** | 2025, Blender 4.4 add-on | **REFERENCE-ONLY**: the architecture closest to ours; do not even fork it |
| [BlenderGym](https://blendergym.github.io) ([code](https://github.com/richard-guyunqi/BlenderGym-Open), [data](https://huggingface.co/datasets/richard-guyunqi/BG_bench_data)) | Benchmark of start/goal Blender edit tasks; **VLM verifier picks among N candidate edits**; there is a best ratio of compute between generation and verification | **No LICENSE file** (all rights reserved by default); the site is CC BY-SA 4.0 | CVPR 2025 | **REFERENCE-ONLY**: copy the evaluation methodology into our own tests, using our own tasks |
| [BlenderAlchemy](https://arxiv.org/abs/2404.17672) ([repo](https://github.com/ianhuang0630/BlenderAlchemyOfficial)) | Visual program refinement: propose edits to procedural materials/lighting, render, and keep the best by VLM comparison; "visual imagination" from a text-to-image reference | **No LICENSE file** | ECCV 2024 | **REFERENCE-ONLY**: the edit→render→compare loop maps onto our Critic |
| [SceneCraft](https://proceedings.mlr.press/v235/hu24g.html) | LLM writes a scene graph of spatial constraints, then Blender code; library learning of reusable functions across scenes | **No official code release found** | ICML 2024 | **REFERENCE-ONLY**: use a relation graph as an intermediate layer for the Director/Asset agents |
| [3D-GPT](https://github.com/Chuny1/3DGPT) | Task-dispatch, conceptualisation and modelling agents that fill Infinigen function parameters | **No LICENSE file** | 3DV 2025 | **REFERENCE-ONLY**: the idea of LLMs setting parameters of procedural generators |
| [SceneWeaver](https://github.com/Scene-Weaver/SceneWeaver) | Extensible tool-using agent with reflect-and-repair over scene quality metrics | BSD-3-Clause | 2025 | **REFERENCE-ONLY** (copying allowed, but heavy); take its physics/semantic quality metrics |
| [BlenderLLM](https://github.com/FreedomIntelligence/BlenderLLM) | Fine-tuned code LLM for Blender CAD scripts | Apache-2.0 (code); weights licence **unverified** | 2024–25 | **REFERENCE-ONLY**: its dataset ideas |
| [MeshCoder](https://github.com/InternRobotics/MeshCoder) | Point cloud → structured Blender Python | MIT | 2025 | **REFERENCE-ONLY** (optional later) |
| [CAD-Recode](https://github.com/filaPro/cad-recode) | Point cloud → CadQuery code | **CC-BY-NC-4.0** | 2025 | **AVOID** (code); idea only |

### 2.5 Free asset libraries

| Library | Content | License (exact) | API? | Attribution / terms | Reachable from sandbox? | Verdict |
|---|---|---|---|---|---|---|
| [Poly Haven](https://polyhaven.com/license) | About 2.4K HDRIs, PBR textures, models | **CC0** for all assets (site logos, renders and text are not CC0) | **Yes**, keyless: `https://api.polyhaven.com` ([README](https://github.com/Poly-Haven/Public-API)); API server code is AGPL but we only call it | [API ToS](https://github.com/Poly-Haven/Public-API/blob/master/ToS.md): free including commercial use; send a **unique User-Agent/Referer**; show a "Powered by Poly Haven" style credit when presenting live API content; site ToS bars scraping or data mining without permission | **No** (blocked) | **ADOPT**: first source for HDRIs, textures and hero props |
| [ambientCG](https://docs.ambientcg.com/license/) | PBR materials, HDRIs, some models | **CC0 1.0** | **Yes**: [v1/v2/v3 endpoints](https://docs.ambientcg.com/api/); the author warns it is a hobby service, not enterprise-grade | Credit optional | **No** | **ADOPT**: material source; cache locally |
| [Kenney](https://kenney.nl/support) | 2D/3D game kits (third-party count: 60K+ assets, 200+ packs) | **CC0** | No (zip downloads) | Credit optional | **No** | **ADOPT**: vendor a few small 3D kits into a downloadable starter pack (CC0, so redistribution is fine) |
| [Quaternius](https://quaternius.com/faq.html) | Stylised low-poly characters (many rigged and animated), props, nature | **CC0** (FAQ: all models) | No | Credit optional | **No** | **ADOPT**: rigged CC0 characters are a large shortcut for the Animator |
| [Poly Pizza](https://tessl.io/registry/skills/github/jasonkneen/tiny-world-builder/poly-pizza-api) | Low-poly models, including the Google Poly archive and Quaternius/Kenney mirrors | **Mixed: CC0 and CC-BY 4.0 per model** | Yes: `api.poly.pizza/v1`, `X-Auth-Token` key; free for hobbyists, **commercial use pay-as-you-go** | CC-BY requires credit; store the licence per asset | **No** | **TRIAL**: filter to CC0 and record attribution |
| [Blender Studio](https://studio.blender.org/terms-and-conditions/) | Open-movie production files, characters, rigs | **CC BY 4.0** by default "unless notified otherwise"; logos and trademarks excluded | No public API; much of it sits behind the paid subscription for *access* | Attribution required; record it in `THIRD_PARTY.md` | **No** | **ADOPT (reference and characters)**: check per-file notices |
| Blender asset bundles (e.g. [Human Base Meshes](https://www.cgchannel.com/2023/06/download-blender-studios-free-human-base-meshes)) | Base meshes | CC0 | No | — | No | **ADOPT** |
| [Sketchfab](https://sketchfab.com/developers/download-api/guidelines) | Huge catalogue, licences vary | Per model: CC0, CC-BY, CC-BY-NC, etc. | Data API + Download API; **downloads require end-user OAuth login**; the app must show licence and author and credit Sketchfab | Ownership reportedly moved from Epic to KitBash in Aug 2026 ([source](https://app.cinevva.com/guides/sketchfab-polyhaven-kenney), unverified) | **No** | **TRIAL (user-initiated only)**: never auto-download; CC0/CC-BY filter plus an attribution ledger |
| [Objaverse](https://huggingface.co/datasets/allenai/objaverse) | About 800K objects | Dataset ODC-By; objects: ~721K CC-BY, **~25K CC-BY-NC, ~52K CC-BY-NC-SA**, ~16K CC-BY-SA, ~3.5K CC0 | HF download | Per-object licence in metadata | No (HF blocked) | **AVOID as a default** (NC contamination); only with a strict per-object licence filter |

### 2.6 Scene formats and mesh processing

| Tool | What it does | Code license | Activity | Install | GPU? | Verdict |
|---|---|---|---|---|---|---|
| [usd-core](https://pypi.org/project/usd-core/) (OpenUSD) | USD read/write (`pxr`) | **TOST-1.0** (Apache-2.0 with Section 6, trademarks, changed; [LICENSE](https://raw.githubusercontent.com/PixarAnimationStudios/OpenUSD/HEAD/LICENSE.txt)) | 26.11, 2026-10-21 | `pip install usd-core` (Py 3.11–3.14), tested | No | **ADOPT**: USD export of the scene model (PLAN §2.7) |
| Blender glTF IO ([glTF-Blender-IO](https://github.com/KhronosGroup/glTF-Blender-IO)) | glTF/GLB import and export | Apache-2.0 | Bundled with Blender 5.3 | Built in (`io_scene_gltf2`, tested) | No | **ADOPT**: Blender→Godot bridge |
| Blender USD IO | USD import and export | GPL (Blender) | Built in | `bpy.ops.wm.usd_export` (tested) | No | **ADOPT** |
| [trimesh](https://github.com/mikedh/trimesh) | Load GLB/OBJ/STL; bounds, ray tests, convex hulls, scene graph | MIT | 5.2.1, 2026-11-12 | pip (tested) | No | **ADOPT**: core-side asset QA and geometric checks |
| [pygltflib](https://gitlab.com/dodgyville/pygltflib) | Low-level glTF JSON/binary editing | MIT (PyPI classifier) | 1.16.5, 2025-07-24 | pip (tested) | No | **ADOPT**: metadata and attribution `extras` injection, node renames |
| [Open3D](https://github.com/isl-org/Open3D) | Mesh/point-cloud processing, offscreen rendering | MIT | 0.20.0, 2026-09-16 (`open3d-cpu` 2026-09-28) | pip (tested) | No | **TRIAL**: only if trimesh is not enough (large wheel) |
| [manifold3d](https://github.com/elalish/manifold) | Robust mesh booleans | Apache-2.0 | 3.5.5, 2026-11-13 | pip | No | **TRIAL**: core-side booleans for generated assets |
| [fast-simplification](https://github.com/pyvista/fast-simplification) / [pyfqmr](https://github.com/Kramer84/pyfqmr-Fast-quadric-Mesh-Reduction) | Quadric decimation | MIT / MIT | 0.2.0 2026-08 / 0.5.0 2025-08 | pip | No | **TRIAL**: LOD/decimation of AI-generated meshes for Godot |
| [xatlas-python](https://github.com/mworchel/xatlas-python) | UV unwrapping | MIT | 0.0.11, 2025-07 | pip | No | **TRIAL**: UVs for generated meshes outside Blender |
| [gltf-transform CLI](https://gltf-transform.dev) | Optimise, compress and inspect glTF | MIT | 4.5.1, 2026-09-28 | `npm i -g @gltf-transform/cli` | No | **TRIAL**: shrink Godot/web exports |
| [glTF-Validator](https://github.com/KhronosGroup/glTF-Validator) | Spec validation | Apache-2.0 | npm `gltf-validator` 2.0.0-dev.3.10 | npm | No | **ADOPT (CI)**: validate every exported GLB |
| [PyMeshLab](https://github.com/cnr-isti-vclab/PyMeshLab) | MeshLab filters | **GPL-3.0** | 2025.7.post1, 2026-01-30 | pip | No | **AVOID in core**; acceptable only in the GPL adapter if really needed |
| [pymeshfix](https://github.com/pyvista/pymeshfix) | Hole and self-intersection repair | **GPL-3.0 per LICENSE, AGPL-3 per PyPI classifier** (inconsistent) | 0.18.1, 2026-04-23 | pip | No | **AVOID** (copyleft, ambiguous) |
| [meshio](https://github.com/nschloe/meshio) | Many mesh formats (FEM-oriented) | MIT | 5.3.5, 2024-01 | pip | No | **REFERENCE-ONLY** (not needed) |

### 2.7 Rendering-verification helpers for the Critic

| Tool / technique | What it does | License | Where it runs | Verdict |
|---|---|---|---|---|
| Workbench engine (solid/flat, cavity, object-color) | Very fast previews; object-ID colouring gives instant coverage masks | GPL (Blender) | Adapter | **ADOPT**: 0.09 s/frame warm at 480×270 (measured) |
| `bpy_extras.object_utils.world_to_camera_view` | Project bounding-box corners into camera NDC → on-screen %, off-frame, too small | GPL (Blender) | Adapter | **ADOPT**: frustum check per object per keyframe sample |
| `mathutils.bvhtree.BVHTree` | Overlap and penetration tests between objects or with the floor; raycasts for occlusion | GPL (Blender) | Adapter | **ADOPT**: "robot clips floor by 0.1 m at frame 40" checks |
| Render passes: Object Index / Cryptomatte, Z | Per-object pixel coverage and occlusion from the final camera | GPL (Blender) | Adapter | **TRIAL** (idea from bpycv/BlenderSynth) |
| trimesh `bounds`, `ray`, `collision` (needs python-fcl) | The same checks on exported GLBs, without Blender | MIT | Core | **ADOPT** (bounds/ray); collision **TRIAL** |
| Image statistics (numpy/Pillow) | Black frame, blown out, low contrast, static shot (frame diff), jitter (centroid acceleration) | BSD/MIT-HPND | Core | **ADOPT** |
| [pyrender](https://github.com/mmatl/pyrender) | Offscreen GL renderer | MIT | Core | **AVOID**: last release 2021 |
| [PyVista](https://github.com/pyvista/pyvista) | VTK offscreen renders of GLB for a core-side thumbnail | MIT (0.49.2, 2026-10-28) | Core | **TRIAL**: only if we want previews without Blender |

---

## 3. License traps

The following look "open" but would contaminate an Apache-2.0 core or a commercial-friendly tool:

1. **`bpy` wheel and Blender itself are GPL-3.0.** Importing `bpy` in the core Python process creates a combined GPL work. Keep all `bpy`, `mathutils` and `bpy_extras` usage in `adapters/blender` (GPL) and talk to it over a subprocess or socket (PLAN §7). The same applies to the standalone `mathutils` PyPI package (GPL).
2. **TRELLIS / TRELLIS.2: MIT weights, but the dependencies are not MIT.**
   - **nvdiffrast** uses the NVIDIA Source Code License: use is limited to research or evaluation, and only NVIDIA may use it commercially. TRELLIS.2 needs it for rendering and texture baking in the reference pipeline.
   - TRELLIS v1's **diffoctreerast** is derived from Inria's diff-gaussian-rasterization, which is research-only (not re-verified).
   - TRELLIS.2 / Pixal3D condition on **DINOv3**, which uses the custom "DINOv3 License": not OSI, with trade-control and ITAR clauses.
3. **Hunyuan3D 2.0/2.1, HunyuanWorld 1.0 and the other Tencent community licences** do **not apply in the EU, UK or South Korea**. Use there is unlicensed. They also impose a 1M-MAU cap and forbid using outputs to improve other models. Hunyuan3D 2.5/3.x are API-only.
4. **InstantMesh**: the HF card says Apache-2.0, but it depends on a fine-tuned **Zero123++** UNet, and the Zero123++ weights are **CC-BY-NC-4.0**.
5. **Stable Fast 3D / SPAR3D**: Stability AI Community License. Commercial use is free only under US$1M annual revenue, registration is required, and downloads are gated. This is not open source.
6. **LL3M**: the "Demonstration License Agreement" allows only non-commercial academic or evaluation use **and forbids modification**. PLAN.md already flags it. Read the paper, not the code.
7. **BlenderGym-Open, BlenderAlchemyOfficial, 3D-GPT, CommonSenseMachines/blender-mcp**: **no LICENSE file**, which means all rights reserved. Ideas only.
8. **LLaMA-Mesh** (NVIDIA License) and **CAD-Recode** (CC-BY-NC-4.0): non-commercial.
9. **SAM 3D Objects** (SAM License) and **DINOv3**: custom Meta licences with gated access that collects personal data. Not OSI-approved, so don't make them a default dependency.
10. **Objaverse / Holodeck asset pool**: about 77K objects are NC or NC-SA. A per-object filter is mandatory.
11. **Sketchfab**: licences vary per model (including NC/ND). The Download API needs end-user OAuth plus licence and author display. Never bulk-download.
12. **Poly Pizza**: mixed CC0/CC-BY, and the API's commercial use is paid.
13. **Poly Haven**: the assets are CC0, but the **API ToS adds conditions** (unique User-Agent, a "Powered by Poly Haven" style credit when showing live API content), and the website ToS bars scraping or data mining. The API *server* code repo is **AGPL**: call it, don't copy it.
14. **PyMeshLab (GPL-3.0)** and **pymeshfix (GPL-3.0/AGPL-3.0, inconsistent metadata)**: keep them out of the core.
15. **ComfyUI is GPL-3.0.** Its native TRELLIS.2/Pixal3D path avoids NVIDIA's NC code, but it can only run as a separate process or service, never as an imported library in the core.
16. **Step1X-3D texture stage** builds on SDXL, whose CreativeML OpenRAIL++-M licence adds use-based restrictions (not re-verified here).
17. **OpenUSD** is *not* plain Apache-2.0. It uses TOST-1.0, whose trademark clause differs. That is harmless for us, but list it accurately in `THIRD_PARTY.md`.
18. **Blender Studio content** is CC-BY 4.0 "unless notified otherwise", so check each file's notice. Logos and trademarks are excluded, and attribution is mandatory.

---

## 4. Concrete integration notes for ADOPT tools

### 4.0 Environment facts (from this container)
- Python 3.13.18 is present, which matches the `bpy` 5.3 requirement. `uv` is installed. Mesa `libEGL_mesa` is present. There is no NVIDIA GPU and no Vulkan, and Blender logs a harmless Vulkan warning plus some EGL_BAD_MATCH lines before falling back to OpenGL/EGL.
- The egress proxy **blocks** huggingface.co (from curl), blender.org/download.blender.org, projects.blender.org, polyhaven.com, ambientcg.com, kenney.nl, poly.pizza and sketchfab.com. PyPI, npm and raw.githubusercontent.com work. Consequences:
  - Install Blender via `pip install bpy`. The tarball route is blocked.
  - Asset fetchers need an offline cache and a procedural fallback.
  - `docs/SETUP.md` should list the domains the owner must allowlist.

### 4.1 `bpy` 5.3 wheel → `adapters/blender/runner.py` (GPL)
- **Install:** `uv venv -p 3.13 .venv-blender && uv pip install bpy` (the core can live in a separate venv on any Python version).
- **Process model:** the core spawns `python -I -m animatica_blender.runner --project <dir>`, keeps it alive, and sends batches as JSON-lines over stdin/stdout or a local socket. A persistent process avoids paying start-up and shader warm-up on every batch.
- **Measured** (480×270, default scene, 2 vCPU, llvmpipe):

  | Engine | First render (cold, includes start-up) | Warm per frame | Other |
  |---|---|---|---|
  | Workbench | 1.5 s | 0.09 s | |
  | EEVEE (8 TAA samples) | 26.8 s | 9–11 s | |
  | Cycles CPU, 16 spp | 1.85 s | | |
  | Cycles CPU, 32 spp + denoise | | 2.3 s | 8.6 s at 960×540 |

- **Policy for `render_preview`:** default to Workbench, with `shading.color_type='MATERIAL'` or `'OBJECT'` and the studio light.
- **Policy for `render_final`:** use Cycles CPU with 16–64 spp, OIDN denoise and `use_adaptive_sampling`, unless the adapter detects a GPU, in which case EEVEE or Cycles-GPU. Record the choice in the production log.
- **Exit codes:** under `blender -b`, use `--python-exit-code 1` so CI fails on exceptions. Under the wheel, catch exceptions and return `{"ok": false}`.

### 4.2 Built-in glTF/USD IO + trimesh + pygltflib → `import_asset` op, `asset registry`, Godot bridge
- **Asset agent:** `import_asset` (glTF/OBJ/FBX/USD) calls `bpy.ops.import_scene.gltf` or `bpy.ops.wm.usd_import` in the adapter. It applies scale normalisation (fit to a target height) and pivot-to-base. It then reports a compact `{id, dims, tris, materials}`.
- **Core asset registry:** before import, the core runs `trimesh.load(path)` to get bounds, triangle count and watertightness. It rejects anything over budget, so the LLM never sees raw meshes.
- **Godot track:** `export_gltf` op → `bpy.ops.export_scene.gltf(export_format='GLB')` → then `gltf-validator` (CI) and optionally `gltf-transform optimize`.
- **Attribution:** `pygltflib` writes `extras.license`, `extras.source_url` and `extras.author` into each GLB node, so attribution travels with the asset. The registry mirrors it into `THIRD_PARTY.md`.

### 4.3 usd-core → `core/state` exporter
- `animatica export --usd` writes the internal scene model (prims, xforms, material bindings, time samples) with `pxr.Usd`/`UsdGeom` in the core process. No bpy is involved.
- Round-trip test: the adapter runs `bpy.ops.wm.usd_import` on that file and compares object ids and transforms. I tested importing both libraries in one process and it worked, but we still keep them in separate processes.

### 4.4 Asset libraries → `src/animatica/assets/` (core, Apache) + Asset agent tool `asset_search`
- **Provider interface:** `search(query, kind) -> [AssetHit{id, title, license, author, url, thumb, formats}]` and `fetch(hit) -> local path`. Every hit carries an SPDX-like licence. The registry **refuses anything not in the {CC0-1.0, CC-BY-4.0} allowlist** (PLAN §7).
- **Poly Haven provider:**
  - Calls `GET https://api.polyhaven.com/assets?t=models|textures|hdris`, `/info/{id}` and `/files/{id}`.
  - Sends the header `User-Agent: Animatica/<version> (+repo URL)`. Never put a personal email in it.
  - The log viewer shows a "Powered by Poly Haven" credit next to API-sourced items.
  - Prefer the `.blend` or glTF model file. Textures map onto `set_material` as image-texture PBR.
- **ambientCG provider:** API v2 `full_json` / v3 `assets`, downloading 1K–2K JPG material zips. Cache them under `~/.cache/animatica/assets/<provider>/<id>`.
- **Kenney / Quaternius:** no API. Ship a pinned manifest (name, URL, SHA-256, licence CC0) and an `animatica assets pull starter` command. Keep vendored files out of git if they total more than 10 MB (PLAN §10).
- **Blender Studio and Human Base Meshes:** manual or user-supplied download. Record CC-BY attribution.
- **Fallback:** if the network is blocked, the Asset agent builds stylised props from primitives and geometry-nodes recipes in `knowledge/recipes/`. This is the default path in the offline CI.

### 4.5 Critic geometric checks → adapter op `analyze_shot` (GPL) + core `critic/geom.py` (Apache)
- **Adapter op `analyze_shot{camera, frames:[...], targets:[...]}`.** For each sampled frame it:
  1. Calls `scene.frame_set(f)`.
  2. Projects the 8 world-space bounding-box corners with `world_to_camera_view`, giving the % of the box on screen, the screen area fraction, and the centre against rule-of-thirds points.
  3. Checks the lowest vertex z against the floor height, plus a `BVHTree.overlap` between the character and set meshes, giving the penetration depth.
  4. Raycasts from the camera to the target centre to detect occlusion.

  It returns a compact JSON list of findings, for example `{"obj":"robot","frame":40,"issue":"floor_penetration","depth_m":0.1}`.
- **Core `critic/image.py`:** mean luminance, clipped-pixel %, frame-to-frame difference (to catch static shots) and a mouth-region diff during dialogue frames. Uses numpy and Pillow on the Workbench/Cycles preview PNGs.
- The Critic agent receives **numbers plus one low-res image**, not scene dumps (PLAN §2.2).

### 4.6 Live add-on mode, informed by mcp-for-blender (MIT) → `adapters/blender/addon/` (GPL)
- Reuse the pattern: a Blender timer-driven socket server inside Blender, length-prefixed JSON, and command dispatch on the main thread. This is where our **batched protocol** goes instead of one-call-per-action.
- If we copy code, keep the MIT notice in `third_party/` and in `THIRD_PARTY.md`. MIT can be included in GPL.
- **Bind to localhost only and add a per-session token.** The upstream README notes its socket has no authentication.
- Do **not** port its telemetry or premium generator routes.

### 4.7 fake-bpy-module → dev dependency
- Add `fake-bpy-module` to `[project.optional-dependencies].dev` for ruff/mypy on adapter code and on agent-generated script-mode code: run a static `ast` plus type check before execution.
- Extract docstrings from it into `knowledge/blender_api/` as the BlenderRAG seed. This is the LL3M idea, reimplemented.

### 4.8 Geometry Nodes recipes → `knowledge/recipes/*.py` + script mode
- Write small parameterised functions (scatter trees on a terrain, junk piles, flowers, rocks) that build node groups via `bpy`. Agents call them through `{"op":"apply_recipe","recipe":"scatter","params":{...}}`, so a 200-tree scatter is one op.
- If ProcFunc passes its trial, use `procfunc transpile` offline to convert artist-made node trees into recipes. It runs in a separate Python 3.11 env because it pins bpy 4.2.

---

## 5. Sources

**Blender, automation and MCP**
- bpy on PyPI: https://pypi.org/project/bpy/ (JSON: https://pypi.org/pypi/bpy/json)
- mcp-for-blender: https://github.com/ahujasid/mcp-for-blender (README and LICENSE read via raw.githubusercontent.com)
- Official Blender Lab MCP (not reachable from the sandbox): https://projects.blender.org/lab/blender_mcp; summaries: https://aiwiki.ai/wiki/blender_mcp, https://www.strayspark.studio/blog/official-blender-mcp-server-comparison-2026 (vendor blog)
- MCP vs headless bpy notes: https://sumguy.com/blender-mcp-vs-headless-bpy/
- CSM blender-mcp listing: https://mcpservers.org/servers/CommonSenseMachines/blender-mcp
- EEVEE-Next headless caveats (vendor marketing, treat with care): https://irendering.net/eevee-next-headless-dilemma-cloud-render-farm-guide/
- Mesa EGL surfaceless in Docker: https://www.yrom.net/blog/2025/07/27/develop-opengl-apps-in-docker-without-gpu/
- fake-bpy-module: https://github.com/nutti/fake-bpy-module
- bpy-helper: https://github.com/iamNCJ/bpy-helper
- BlenderSynth: https://github.com/OllieBoyne/BlenderSynth
- bpycv: https://github.com/DIYer22/bpycv
- Kubric: https://github.com/google-research/kubric
- mathutils: https://gitlab.com/ideasman42/blender-mathutils

**Procedural generation**
- Infinigen: https://github.com/princeton-vl/infinigen; PyPI: https://pypi.org/project/infinigen/
- ProcFunc: https://github.com/princeton-vl/procfunc; paper: https://arxiv.org/abs/2604.26943
- Sverchok: https://github.com/nortikin/sverchok
- tree-gen: https://github.com/friggog/tree-gen
- BlenderGIS: https://github.com/domlysz/BlenderGIS
- SceneWeaver: https://github.com/Scene-Weaver/SceneWeaver; paper: https://arxiv.org/abs/2509.20414
- Holodeck: https://github.com/allenai/Holodeck
- LayoutGPT: https://github.com/weixi-feng/LayoutGPT
- Human Base Meshes (CC0): https://www.cgchannel.com/2023/06/download-blender-studios-free-human-base-meshes

**Image/text-to-3D**
- TRELLIS.2: https://github.com/microsoft/TRELLIS.2; weights: https://huggingface.co/microsoft/TRELLIS.2-4B
- TRELLIS: https://github.com/microsoft/TRELLIS
- nvdiffrast licence: https://github.com/NVlabs/nvdiffrast/blob/main/LICENSE.txt
- DINOv3 licence: https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md
- TripoSG: https://github.com/VAST-AI-Research/TripoSG; weights: https://huggingface.co/VAST-AI/TripoSG
- TripoSR: https://github.com/VAST-AI-Research/TripoSR; weights: https://huggingface.co/stabilityai/TripoSR
- Step1X-3D: https://github.com/stepfun-ai/Step1X-3D; weights: https://huggingface.co/stepfun-ai/Step1X-3D
- Hunyuan3D-2.1: https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1; Hunyuan3D-2: https://github.com/Tencent-Hunyuan/Hunyuan3D-2; HunyuanWorld-1.0: https://github.com/Tencent-Hunyuan/HunyuanWorld-1.0
- Release timeline: https://app.cinevva.com/guides/ai-3d-model-generation-timeline-2026
- Stable Fast 3D: https://github.com/Stability-AI/stable-fast-3d; weights: https://huggingface.co/stabilityai/stable-fast-3d
- SPAR3D: https://github.com/Stability-AI/stable-point-aware-3d
- InstantMesh: https://github.com/TencentARC/InstantMesh; weights: https://huggingface.co/TencentARC/InstantMesh
- Zero123++ (weights CC-BY-NC): https://github.com/SUDO-AI-3D/zero123plus
- SAM 3D Objects: https://huggingface.co/facebook/sam-3d-objects; licence: https://github.com/facebookresearch/sam-3d-objects/blob/main/LICENSE
- Pixal3D (ComfyUI notes): https://comfy.org/pixal3d-trellis2.md
- ComfyUI (GPL-3.0): https://github.com/comfyanonymous/ComfyUI
- LLaMA-Mesh: https://github.com/nv-tlabs/LLaMA-Mesh

**LLM-to-3D research**
- LL3M: https://arxiv.org/abs/2508.08228; repo and licence: https://github.com/threedle/ll3m
- BlenderGym: https://blendergym.github.io; https://arxiv.org/abs/2504.01786; code: https://github.com/richard-guyunqi/BlenderGym-Open
- BlenderAlchemy: https://arxiv.org/abs/2404.17672; code: https://github.com/ianhuang0630/BlenderAlchemyOfficial
- SceneCraft: https://proceedings.mlr.press/v235/hu24g.html; https://arxiv.org/abs/2403.01248
- 3D-GPT: https://github.com/Chuny1/3DGPT
- BlenderLLM: https://github.com/FreedomIntelligence/BlenderLLM
- MeshCoder: https://github.com/InternRobotics/MeshCoder
- CAD-Recode: https://github.com/filaPro/cad-recode

**Asset libraries**
- Poly Haven licence: https://polyhaven.com/license; API: https://github.com/Poly-Haven/Public-API; API ToS: https://github.com/Poly-Haven/Public-API/blob/master/ToS.md
- ambientCG licence: https://docs.ambientcg.com/license/; API: https://docs.ambientcg.com/api/
- Kenney: https://kenney.nl/support, https://kenney.nl/assets
- Quaternius FAQ: https://quaternius.com/faq.html
- Poly Pizza API (third-party doc): https://tessl.io/registry/skills/github/jasonkneen/tiny-world-builder/poly-pizza-api
- Asset-site comparison (secondary): https://app.cinevva.com/guides/sketchfab-polyhaven-kenney
- Blender Studio terms: https://studio.blender.org/terms-and-conditions/
- Sketchfab Download API guidelines: https://sketchfab.com/developers/download-api/guidelines; API terms: https://sketchfab.com/developers/terms
- Objaverse: https://huggingface.co/datasets/allenai/objaverse

**Formats, mesh processing and verification**
- OpenUSD: https://github.com/PixarAnimationStudios/OpenUSD; usd-core: https://pypi.org/project/usd-core/
- glTF-Blender-IO: https://github.com/KhronosGroup/glTF-Blender-IO
- glTF-Validator: https://github.com/KhronosGroup/glTF-Validator
- gltf-transform: https://gltf-transform.dev (npm `@gltf-transform/cli`)
- trimesh: https://github.com/mikedh/trimesh
- pygltflib: https://gitlab.com/dodgyville/pygltflib
- Open3D: https://github.com/isl-org/Open3D
- PyMeshLab: https://github.com/cnr-isti-vclab/PyMeshLab
- pymeshfix: https://github.com/pyvista/pymeshfix
- manifold: https://github.com/elalish/manifold
- fast-simplification: https://github.com/pyvista/fast-simplification
- pyfqmr: https://github.com/Kramer84/pyfqmr-Fast-quadric-Mesh-Reduction
- xatlas-python: https://github.com/mworchel/xatlas-python
- meshio: https://github.com/nschloe/meshio
- pyrender: https://github.com/mmatl/pyrender
- PyVista: https://github.com/pyvista/pyvista
