# Research 03 — Voice, Music, Sound Effects, Mixing and Final Assembly

Status: research note, compiled 2026-11-15. Scope: open tools Animatica can run **headless on CPU in a Linux container** to turn a script into the soundtrack of the final MP4 (dialogue, lip-sync data, music bed, SFX, mix, loudness, mux, captions).

How this was checked: README, LICENSE and model-card pages were read for each tool (URLs in §5). PyPI JSON metadata was pulled on 2026-11-15 to get latest version, upload date and declared license. The GitHub API was not reachable from this session, so "activity" comes from the latest PyPI or GitHub release date and the repo README, not commit graphs. Anything marked *(unverified)* is my own estimate or recollection and has not been checked against a primary source. This is engineering triage, not legal advice.

Legend for verdicts: **ADOPT** = use in the default pipeline now. **TRIAL** = optional, behind a flag or extra, worth testing. **REFERENCE-ONLY** = read for ideas, don't depend on it. **AVOID** = license or practical blocker.

---

## 1. Executive summary — top 10 recommendations (ranked by impact)

1. **Default TTS is Kokoro-82M** (Apache-2.0 weights, 54 voices, 8 languages, 82M params), run through `kokoro-onnx` (MIT) for CPU. It sounds best among the truly permissive CPU models. Trap: its phonemizer falls back to **espeak-ng (GPL-3.0+)**. Run TTS in a **separate worker process** behind the `VoiceEngine` interface, not as an import inside the Apache core.
2. **Fallback TTS is Piper** (`piper-tts` 1.8.0, Sept 2026). It now lives at **OHF-Voice/piper1-gpl and is GPL-3.0-or-later**. The old MIT `rhasspy/piper` was archived in Oct 2025. Call it only as a CLI subprocess, and **only use voices from Piper's COMMERCIAL_USE list**. The popular `en_US-lessac-*` voices are research-only through the Lessac Blizzard corpus.
3. **Use Rhubarb Lip Sync v1.14.0 (MIT) for visemes.** Always pass the known dialogue text (`-d`) and export JSON. It gives Preston-Blair-style mouth shapes A–H plus X, which map directly onto 9 shape keys in Blender. It's a single static binary, CPU only, and fast.
4. **Make the music bed procedural by default.** Generate MIDI with `mido`/`pretty_midi` (MIT) from an LLM-written chord plan and render it with **FluidSynth (LGPL-2.1, CLI)** plus **GeneralUser GS** (free for any use, including commercial software). This avoids every music-model weight-license problem and is deterministic and testable.
5. **Mix with ffmpeg filtergraphs**: `adelay` to place clips, `sidechaincompress` to duck music under dialogue, `amix normalize=0`, then a **two-pass `loudnorm` to -14 LUFS integrated and -1 dBTP** (YouTube's playback reference is -14 LUFS). Keep `pyloudnorm` (MIT) for verification in tests.
6. **Get SFX from CC0 libraries, in this order**: Kenney audio packs (CC0) vendored as a small starter set, then `jsfxr` (Unlicense) for procedural UI and retro sounds, then a Freesound CC0-only fetcher (`filter=license:"Creative Commons 0"`) with a cached manifest. **Do not ship** BBC (RemArc, non-commercial) or Sonniss GDC files in the repo.
7. **Generate captions from the script, not from ASR.** We already know the text and the TTS timing. Use **faster-whisper (MIT; Whisper weights are permissive)** as a *critic*: transcribe the rendered dialogue and compare it with the script to catch garbled TTS. That's cheap on CPU with `tiny` or `base` int8.
8. **Treat Chatterbox (MIT, 0.5B, emotion "exaggeration" knob, Perth watermark built in) as the expressive TRIAL engine** for a future "quality" tier. It's slow on CPU and is a zero-shot cloner, so keep it behind the consent-gated `voice_clone` hook from PLAN §7. Also TRIAL **Kyutai Pocket TTS** (MIT code, CC-BY-4.0 gated weights, about 6× real-time on a laptop CPU), but **exclude its Expresso and EARS voices (CC-BY-NC)**.
9. **Stable Audio Open (small or 1.0) and ACE-Step 1.5 (MIT) are optional "generative music/SFX" extras only.** SAO is under the Stability Community License (free below $1M annual revenue, gated, AUP). ACE-Step is genuinely MIT but practical only on GPU. **Never ship** MusicGen, AudioLDM2, Tango, TangoFlux, MMAudio, YuE, F5-TTS or XTTS weights: they are non-commercial or research-only.
10. **Keep a machine-readable `audio_manifest.json` per film.** Each audio asset gets source URL, license SPDX, author, attribution string, generator and model. Feed it into `THIRD_PARTY.md` and the end credits. Most license bugs in this domain are attribution bugs (CC-BY voices, Freesound CC-BY, Hi-Fi TTS-derived Piper voices).

---

## 2. Tool tables

### 2.1 Text-to-speech (stock voices)

| Tool | What it does | Code license | Weights / data license | Activity | Headless Linux install | CPU-feasible? | Verdict |
|---|---|---|---|---|---|---|---|
| **Kokoro-82M** (hexgrad) | 82M StyleTTS2-derived TTS; 54 voices, 8 langs (v1.0); 24 kHz | Apache-2.0 (`kokoro` pkg); G2P `misaki` Apache-2.0 | **Apache-2.0** weights; trained on permissive, public-domain and synthetic audio (incl. CC-BY Koniwa/SIWIS) | `kokoro` 0.9.4 (Apr 2025), stable; model card active | `apt install espeak-ng; pip install kokoro soundfile` (Python **<3.13**) | Yes. Small model, faster than real time on modern x86 *(unverified figure)* | **ADOPT**: best permissive quality per CPU-second. Isolate the espeak-ng (GPL) fallback in a worker process. |
| **kokoro-onnx** (thewh1teagle) | ONNX Runtime wrapper for Kokoro; ~300 MB, ~80 MB quantized | MIT | Kokoro Apache-2.0 | 0.6.1 (Aug 2026) | `pip install kokoro-onnx soundfile` + download `kokoro-v1.0.onnx` and `voices-v1.0.bin` | Yes, no torch needed | **ADOPT** as the runtime for Kokoro (smaller image, Python 3.10–3.13) |
| **Piper** (OHF-Voice/piper1-gpl) | Fast VITS-based TTS, many languages, ONNX | **GPL-3.0-or-later** (relicensed; old `rhasspy/piper` MIT repo archived 2025-10-06) | **Per voice.** Piper grants nothing; check each MODEL_CARD's training chain. Lessac-derived voices are research-only. | `piper-tts` 1.8.0 (2026-09-04); maintainers wanted | `pip install piper-tts`; voices from HF `rhasspy/piper-voices` | Yes, very fast, Raspberry-Pi class | **ADOPT as fallback, via subprocess only**, and only voices on COMMERCIAL_USE.md (e.g. `en_US-ljspeech-high`, `en_US-norman-medium`, `en_US-joe-medium`, `en_GB-cori-high`) |
| **Kyutai Pocket TTS** | ~100M CPU-first TTS with voice cloning; 7 langs | MIT | **CC-BY-4.0**, HF-gated; voices per-file: VCTK CC-BY, voice-donations CC0, **Expresso and EARS CC-BY-NC** | `pocket-tts` 4.0.1 (2026-10-21), very active | `pip install pocket-tts` (use the CPU torch index to avoid CUDA wheels) or standalone binary | Yes. README: ~6× real-time on M4 Air with 2 cores; small English variants up to 25× | **TRIAL**. Strong CPU option; gating plus per-voice licensing needs an allow-list (CC0/CC-BY voices only). |
| **Chatterbox** (Resemble AI) | 0.5B TTS with emotion-exaggeration and CFG controls; multilingual V3 (23+ langs); zero-shot cloning | MIT | MIT | `chatterbox-tts` 0.1.7 (Mar 2026) | `pip install chatterbox-tts` (pulls torch) | Slow. Runs on CPU but examples target CUDA; expect slower than real time *(unverified)* | **TRIAL** for the expressive "quality" tier. Perth watermark is on by default (good). |
| **Parler-TTS** (HF) | Text-described voice ("a calm female voice, close mic…"); Mini 880M, Large 2.3B | Apache-2.0 | Apache-2.0 (mini-v1 card) | `parler-tts` 0.2.3 (Jan 2025), effectively dormant | `pip install parler-tts` or git | Marginal: 880M autoregressive on CPU is slow | **REFERENCE-ONLY**. The description-prompt idea is useful for the Voice agent. Too slow and stale to default to. |
| **MeloTTS** (MyShell) | Multi-accent EN, ES, FR, ZH, JA, KO | MIT | MIT (per README) | `melotts` 0.1.1 (Feb 2024), stale | git install; heavy deps (MeCab, unidic) | Yes, README claims CPU real-time | **REFERENCE-ONLY**. License fine, but stale and has awkward deps. |
| **StyleTTS2** | Research TTS (Kokoro's ancestor) | MIT | Pretrained models carry a condition: tell listeners the audio is synthetic unless the speaker consented. Inference relies on a GPL phonemizer. | Dormant research repo | git | Yes-ish | **REFERENCE-ONLY**. Use Kokoro instead. |
| **NeuTTS Air / Nano** (Neuphonic) | 0.5B-class on-device LM TTS with 3 s cloning; Perth watermark | Repo LICENSE (see repo) | Air **Apache-2.0**; Nano and 2E under "NeuTTS Open License 1.0" (custom) | Active 2026 | `pip install neutts` (+ llama.cpp GGUF) | Yes. Q4 GGUF ~110–120 tok/s on Ryzen 9 / M4 CPU (README) | **TRIAL** (Air only). Cloning-centric, so consent hook required. |
| **Zonos v0.1** (Zyphra) | Expressive TTS with emotion, rate and pitch controls; 5 langs | Apache-2.0 | "open-weight" (Apache tag on repo) | 2025, slowing | git + docker | Technically runs on CPU, slowly (README says not interactive) | **REFERENCE-ONLY** |
| **Kyutai TTS 1.6B** | Streaming EN and FR TTS | MIT/Apache *(repo)* | CC-BY-4.0 | 2025 | `moshi` pkg | No, GPU-oriented (1.8B) | **REFERENCE-ONLY** |
| **Orpheus TTS** (Canopy) | 3B Llama-based emotive TTS with `<laugh>`, `<sigh>` tags | Apache-2.0 | HF card says Apache-2.0, **but fine-tuned from Llama-3.2-3B**, so Llama Community License terms likely attach; gated | 2025 | vLLM / llama.cpp | Only via llama.cpp quant, slow | **AVOID** for default (licence ambiguity plus 3B). REFERENCE-ONLY for tag-style emotion. |
| **Dia / Dia2** (Nari Labs) | 1.6B dialogue TTS with nonverbals (laughs, coughs) | Apache-2.0 | Apache-2.0 | Dia2 released | pip/git | **No**: README says CPU support not yet added | **REFERENCE-ONLY** (great for multi-speaker banter if a GPU tier exists) |
| **KittenTTS** | 15–80M ONNX TTS, 8 voices | Apache-2.0 | Apache-2.0 (HF card) | Developer preview; APIs change | `pip install` from GitHub release | Yes, CPU-only design | **TRIAL** as a tiny-footprint CI/test voice; quality below Kokoro *(unverified)* |
| **Supertonic 3** (Supertone) | Fast ONNX TTS, 31 langs | MIT (sample code) | **OpenRAIL-M** (use-based restrictions) | **Repo to be archived** | ONNX | Yes (RTF 0.3 on an e-reader) | **AVOID**: archived, and OpenRAIL-M adds use-restriction pass-through obligations |
| **F5-TTS** | Flow-matching zero-shot cloning TTS | MIT | **CC-BY-NC** (Emilia training data) | Active (1.1.22, Jul 2026) | pip | GPU-oriented | **AVOID** (NC weights) |
| **XTTS-v2** (Coqui) / `coqui-tts` (idiap fork) | 17-lang cloning TTS / toolkit | MPL-2.0 (idiap fork, active, 0.28.0 Oct 2026) | XTTS weights: **Coqui Public Model License, non-commercial** | Coqui the company is defunct; fork maintained | `pip install coqui-tts` | Slow on CPU | **AVOID** XTTS weights. The toolkit is REFERENCE-ONLY (some bundled models have their own dataset licenses). |
| **IndexTTS-2 / 2.5** (bilibili) | Emotion and duration-controllable cloning TTS | bilibili Model Use License | same (custom; commercial by inquiry) | Active | GPU (CUDA 12.8) | No | **AVOID** (custom licence, GPU) |
| **Fish-Speech / OpenAudio** | Cloning TTS | Fish Audio Community License | Community / **Research License (S2-Pro)** | Active | GPU | No | **AVOID** |
| **OpenVoice V1/V2** (MyShell) | Tone-color converter (voice conversion) on top of a base TTS | MIT | MIT (since Apr 2024) | Low activity | git | Yes-ish | **REFERENCE-ONLY**. It's a cloning tool, so consent-gated future use only. |

### 2.2 Voice cloning and consent safeguards

Cloning-capable and permissively licensed: Chatterbox (MIT), Pocket TTS (CC-BY), NeuTTS Air (Apache), OpenVoice (MIT). Non-commercial: F5-TTS, XTTS-v2. PLAN §7 forbids cloning real people for now. What the field treats as standard practice, which we should copy into the hook design:

- **Explicit consent record.** Pocket TTS and Dia both prohibit cloning without explicit, lawful consent. StyleTTS2 requires telling listeners the audio is synthetic unless the speaker consented. Our hook should demand a `consent` object (speaker identity, signed statement or recording hash, scope, expiry) before a reference clip can be used.
- **Read-aloud consent phrase.** The voice owner records a dated sentence that we generate, which proves they are live and agreed. This is common in commercial cloning services *(industry practice, unverified per vendor)*.
- **Watermarking.** Resemble's **Perth** (MIT) is embedded by default in Chatterbox and NeuTTS and has an extract API. We can apply it to *all* Animatica TTS output, stock voices included, as a provenance signal. Perth's README says it works on generic audio arrays; we'd need to test it on Kokoro output.
- **Disclosure.** Put "voices are synthetic" in credits and video metadata.
- **No reference clips from the internet.** Only user-supplied files with consent, or CC0 voice-donation datasets.

| Tool | Role | Code | Weights | Verdict |
|---|---|---|---|---|
| Perth (resemble-ai) | Neural audio watermark embed/extract | MIT | MIT (bundled) | **TRIAL**: watermark all generated speech |
| Chatterbox / Pocket TTS / NeuTTS Air | Zero-shot cloning | MIT / MIT / Apache | MIT / CC-BY (gated) / Apache | **Future, consent-gated only** |
| OpenVoice | Voice conversion | MIT | MIT | REFERENCE-ONLY |

### 2.3 Music

| Tool | What it does | Code license | Weights / data license | Activity | Headless install | CPU-feasible? | Verdict |
|---|---|---|---|---|---|---|---|
| **MIDI composition**: `mido`, `pretty_midi`, `music21` | Write and edit MIDI from an LLM-produced chord, melody and drum plan | MIT / MIT / BSD-3 | n/a | pretty_midi 0.2.11.post0 (Jul 2026), music21 10.5.2 (Oct 2026) | `pip install mido pretty_midi` | Trivial | **ADOPT** |
| **FluidSynth** | SoundFont synth; renders MIDI to WAV offline (`-F out.wav`, `-ni`) | LGPL-2.1 | n/a | Very active | `apt install fluidsynth` | Yes, faster than real time | **ADOPT** (call the CLI as a subprocess; `pyfluidsynth` MIT 1.4.0 optional) |
| **GeneralUser GS** v2.0.x SoundFont | ~30 MB General MIDI bank | — | Custom permissive licence: free for any music use including commercial; may be used and modified in software; self-host it, don't hot-link | Updated 2024–25 | download from GitHub `mrbumpy409/GeneralUser-GS` | n/a | **ADOPT** (download at setup; record licence in THIRD_PARTY.md) |
| **FluidR3_GM** SoundFont | 140 MB GM bank | — | MIT (as packaged by Debian `fluid-soundfont-gm`) *(verify package copyright file)* | stable | `apt install fluid-soundfont-gm` | n/a | **ADOPT** as an apt-installable alternative |
| **Numpy/scipy synthesis** (our own) | Pads, drones and ambience: additive/subtractive synth plus noise, filtered and reverbed | ours (Apache) | n/a | — | already deps | Trivial | **ADOPT** for ambient beds and the offline CI path |
| **SuperCollider** (`sclang`/`scsynth` NRT mode) | Pro algorithmic synthesis; non-real-time render to file | GPL-3.0 | n/a | Active | `apt install supercollider-server` | Yes | **TRIAL**. Powerful but heavy; only via subprocess (GPL). |
| **Csound** | Classic synthesis language, offline render | LGPL-2.1 | n/a | Active | `apt install csound` | Yes | **TRIAL** (alternative to SC) |
| **Magenta RealTime** (Google) | Streaming text/audio-prompted instrumental music model | Apache-2.0 | **CC-BY-4.0** plus Terms of Use; Google claims no rights in outputs | 2025 | JAX/TPU-oriented | Unclear; designed for TPU/GPU | **TRIAL** (rare permissive music model; needs attribution) |
| **ACE-Step 1.5** | Full songs with lyrics in 50+ langs, LoRA fine-tune | MIT | **MIT** (HF card); data said to be licensed, royalty-free and synthetic MIDI-rendered | Very active (XL series Apr 2026) | git; Python 3.11–3.12; CPU guide exists | Technically yes, but slow; designed for ≥4 GB VRAM | **TRIAL** (GPU tier). Best permissive song generator found. |
| **DiffRhythm** v1.2 | Full-song latent diffusion | Apache-2.0 | DiT weights Apache-2.0; **VAE licence not stated** | Last news May 2025 | git (needs espeak) | ≥8 GB VRAM | **REFERENCE-ONLY** (VAE licence gap) |
| **Stable Audio Open 1.0 / Small** | Text-to-audio, 44.1 kHz stereo; 1.0: 1B params, ≤47 s; small: 0.5B, ≤11 s, Arm-optimized | `stable-audio-tools` MIT | **Stability AI Community License**: free below $1M annual revenue, gated, AUP; outputs owned by user; data is Freesound/FMA CC0, CC-BY, Sampling+ | tools 0.0.20 (May 2026, Python <3.11) | `pip install stable-audio-tools` + gated HF download | Small: plausible on CPU *(unverified)*; 1.0: slow | **TRIAL** (opt-in extra; better at SFX/ambience than music per its card) |
| **MusicGen / AudioCraft** (Meta) | Text-to-music | MIT | **CC-BY-NC 4.0** | `audiocraft` 1.3.0 (Jun 2024), stale | pip | Slow | **AVOID** (NC weights) |
| **YuE / YuE2** | Lyrics-to-song | Apache-2.0 | **CC-BY-NC-4.0** plus a creator permission (individuals may monetize; companies need a licence) | Active (Oct 2026) | git | No (24 GB VRAM) | **AVOID** for the project default (company-use ambiguity, GPU) |
| **AudioLDM2 music** | Text-to-music/audio | — | **CC-BY-NC-SA-4.0** | stale | diffusers | Slow | **AVOID** |

### 2.4 Sound effects (generation and libraries)

| Source / tool | What it is | Code licence | Content licence | Activity | Install / access | CPU? | Verdict |
|---|---|---|---|---|---|---|---|
| **Kenney audio packs** (Interface, Impact, RPG, Digital, Casino…) | Hundreds of game SFX | — | **CC0** (confirmed on the Interface Sounds page) | Ongoing | direct zip download; also on OpenGameArt and the Godot asset library | n/a | **ADOPT**. Vendor a curated subset (<10 MB) into `assets/sfx/kenney/`. |
| **Freesound (CC0 filter)** | ~600k+ community sounds | API | Per sound: CC0 / CC-BY / CC-BY-NC / legacy Sampling+ | Active | APIv2 token for search and previews; **original-quality download needs OAuth2**; filter `license:"Creative Commons 0"` | n/a | **ADOPT (CC0 only by default; CC-BY opt-in with attribution)**. Store license and author in the manifest; never auto-use NC or Sampling+. |
| **jsfxr** (sfxr port) | Procedural retro SFX from presets (jump, coin, laser, explosion, hit…) | **Unlicense** | outputs ours | Maintained | `npm i jsfxr` (Node, headless `toBuffer`/`toWave`) | Trivial | **ADOPT** for games and UI. Also easy to port the sfxr algorithm to numpy. |
| Own numpy foley (wind, rain, hum, whoosh = filtered noise + envelopes) | Procedural ambience | ours | ours | — | — | Trivial | **ADOPT** (offline CI path, zero licence risk) |
| **Stable Audio Open (1.0/small)** | Text-to-SFX | MIT tools | Stability Community License | see above | gated HF | small: maybe | **TRIAL** (opt-in) |
| **AudioLDM / AudioLDM2** | Text-to-audio | MIT-ish code | **CC-BY-NC-SA-4.0** | stale | diffusers | slow | **AVOID** |
| **Tango / Tango 2** | Text-to-audio | see repo | **CC-BY-NC-SA-4.0** | stale | — | slow | **AVOID** |
| **TangoFlux** | Fast text-to-audio | see repo | **Non-commercial research only**; Stability Community License plus WavCaps academic-only | 2025 | — | GPU | **AVOID** |
| **MMAudio** | Video-to-audio (Foley synced to video frames) | MIT | **CC-BY-NC-4.0** | 2025 | — | GPU (~6 GB) | **AVOID** (but REFERENCE-ONLY for the "Foley from render" idea) |
| **Sonniss GDC bundles** | Pro SFX (tens of GB) | — | Royalty-free custom licence: commercial use OK, no attribution, can't sell raw files; **not CC0**; OSS-repo redistribution not addressed | Yearly | manual download | n/a | **REFERENCE-ONLY**. Users may point Animatica at a local copy; never vendor or redistribute. |
| **BBC Sound Effects (RemArc)** | 30k+ archive SFX | — | **RemArc licence: personal, educational, research only; commercial needs a paid licence; AI training/data-mining excluded** | — | — | n/a | **AVOID** |

### 2.5 Audio processing and mixing

| Tool | What it does | Licence | Activity | Install | CPU | Verdict |
|---|---|---|---|---|---|---|
| **ffmpeg filters** (`adelay`, `afade`, `apad`, `amix`, `sidechaincompress`, `loudnorm`, `aresample`, `alimiter`) | Whole mix in one filtergraph | LGPL-2.1+ (GPL if built with `--enable-gpl`, e.g. Debian/Ubuntu builds with x264) | Very active | `apt install ffmpeg` | Yes | **ADOPT** (subprocess; don't bundle binaries) |
| **soundfile** (libsndfile) + **numpy** | WAV I/O, sample-accurate edits | BSD-3 / BSD | 0.14.0 (Jun 2026) | pip | Yes | **ADOPT** (primary Python audio layer) |
| **pyloudnorm** | ITU-R BS.1770 loudness meter and normalize | MIT | 0.2.0 (Jan 2026) | pip | Yes | **ADOPT** (assertions in tests, Python-side normalization) |
| **librosa** | Analysis: onset/beat tracking, RMS, resampling, time-stretch | ISC | 1.0.1 (2026-11-12; Python ≥3.12) | pip | Yes | **ADOPT** (beat-sync cuts, music analysis) |
| **pydub** | Convenience wrapper over ffmpeg | MIT | **0.25.1, last release 2021**; Python 3.13 removed `audioop`, so it needs `audioop-lts` | pip | Yes | **AVOID** as a core dependency (stale, 3.13 breakage). Use soundfile, numpy and ffmpeg directly. |
| **pedalboard** (Spotify) | Studio effects (compressor, reverb, limiter, EQ), VST3 hosting | **GPL-3.0** (JUCE) | 0.9.26 (Oct 2026), active | pip | Yes, fast | **TRIAL, out-of-core only**: GPL. Usable from the GPL Blender adapter or a separate worker, not imported by the Apache core. |
| **SoX** | Classic CLI effects (reverb, EQ) | GPL-2+ (CLI) | Low activity | apt | Yes | **REFERENCE-ONLY** (ffmpeg covers it) |
| **Demucs** (Meta) | Stem separation | MIT | Archived 2025 *(unverified)* | pip | Slow | **REFERENCE-ONLY** (not needed for synthetic stems) |

### 2.6 Video assembly and captions

| Tool | What it does | Licence | Activity | Install | CPU | Verdict |
|---|---|---|---|---|---|---|
| **ffmpeg** | Mux audio into Blender's rendered video; encode H.264/AAC; burn or soft-sub captions | LGPL/GPL (see above) | Active | apt | Yes | **ADOPT** |
| **Blender VSE (bpy)** | Sound strips placed by frame inside the .blend (editable by artists); can render audio mixdown | GPL (Blender); our adapter is GPL | Active | in the Blender adapter | Yes | **ADOPT for *placement*** (artists see dialogue, music and SFX on the timeline). Do the final loudness pass in ffmpeg. API: `scene.sequence_editor.strips.new_sound(...)` in 4.4+/5.x (`sequences` renamed to `strips`; verify against the installed version). |
| **MoviePy** v2 | Python video compositing | MIT | 2.2.1 (May 2025) | pip | Yes, slow | **REFERENCE-ONLY** (adds nothing over ffmpeg for muxing; slow frame-by-frame) |
| **faster-whisper** (CTranslate2) | ASR on CPU, int8, word timestamps | MIT; Whisper weights MIT (repo) / Apache-2.0 tag on HF | 1.2.1 (Oct 2025) | pip | Yes (`tiny`/`base` int8 many times faster than real time) | **ADOPT as QA critic** (TTS intelligibility round-trip) and for user-supplied audio |
| **openai-whisper** | Reference implementation | MIT | 20250625 | pip | Slow on CPU | REFERENCE-ONLY |
| **whisper.cpp** | C++ Whisper, no Python | MIT | Active | build or package | Very fast CPU | **TRIAL** (lean container) |
| **Script-derived SRT/WebVTT** (ours) | Captions from script text plus TTS/Rhubarb timings | ours | — | — | Trivial | **ADOPT** (exact text, no ASR errors) |

### 2.7 Phoneme / forced alignment and lip sync

| Tool | What it does | Licence | Activity | Install | CPU | Verdict |
|---|---|---|---|---|---|---|
| **Rhubarb Lip Sync** | Audio (+ optional transcript) to timed mouth shapes A–H, X; TSV/JSON/XML/DAT | MIT (bundled deps BSD/MIT/Boost) | v1.14.0 (latest release) | static Linux binary from GitHub Releases | Yes, seconds per line | **ADOPT**. Run `-f json -d dialog.txt`; English recognizer is PocketSphinx, `--recognizer phonetic` for other languages. |
| **Montreal Forced Aligner** 3.x | Kaldi-based phone/word alignment (TextGrid) | MIT; pretrained models in a separate repo (licence per model, english_mfa believed CC-BY-4.0 *(verify)*) | 3.4.3 (Oct 2026), active | `conda install -c conda-forge montreal-forced-aligner` (pip alone isn't enough: needs Kaldi binaries) | Yes | **TRIAL**: precise phonemes for a future phoneme-to-viseme mapper (better than Rhubarb for non-English, and for jaw/lip curves) |
| **whisperX** | Whisper ASR plus wav2vec2 forced alignment (word/char timestamps) | BSD-2-Clause; align models from torchaudio/HF (check each; pyannote diarization CC-BY-4.0, gated) | 3.8.6 (May 2026) | pip (Python <3.14) | Yes with `--device cpu --compute_type int8` | **TRIAL** (word-level timing for captions and beat cuts; heavier than needed) |
| **Gentle** | Kaldi forced aligner, REST/Docker | MIT | Effectively unmaintained | `docker run lowerquality/gentle` | Yes | **REFERENCE-ONLY** (superseded by MFA and whisperX) |
| **TTS-native timings** | Kokoro's English pipeline returns tokens with start/end timestamps *(reported in kokoro ≥0.9; verify)* | Apache | — | — | Yes | **TRIAL**: free word timings for captions without any aligner |

---

## 3. License traps (read before wiring anything)

1. **Piper is GPL now.** `rhasspy/piper` (MIT) was archived 2025-10-06. The maintained `OHF-Voice/piper1-gpl` and `piper-tts` ≥1.3 on PyPI are **GPL-3.0-or-later**. Importing `piper` inside the Apache-2.0 core would make the distributed combination GPL. **Mitigation:** invoke the `piper` CLI as a separate process, keep it an optional extra, and document it in THIRD_PARTY.md.
2. **Piper voices are not licensed by Piper.** Rights follow each voice's training chain. **`en_US-lessac-*`, the voice used in most tutorials, is Lessac Blizzard 2013 data, research-only.** Many voices were retrained in late 2026 to remove a lessac base, so *an older file with the same name may not qualify*. Read the `Training` section of the bundled MODEL_CARD. CC-BY voices (hifi_tts_92 family, libritts, mls, serena) need attribution, and CC-BY-SA voices have unresolved share-alike questions.
3. **espeak-ng is GPL-3.0+**, and it sits under Kokoro's `misaki` fallback, Piper, StyleTTS2, phonemizer and DiffRhythm. `kokoro` itself is Apache, but its default English G2P path loads espeak-ng for out-of-vocabulary words. **Mitigation:** run every TTS engine in a `voice_worker` subprocess with a JSON contract (text, voice, out.wav, timings.json), so the Apache core never links GPL code. If we ever ship a binary bundle, ship the worker as a separately licensed component.
4. **"Open weights" ≠ commercial.** These are non-commercial or research-only: **MusicGen/AudioCraft (CC-BY-NC)**, **AudioLDM2 and Tango/Tango2 (CC-BY-NC-SA)**, **TangoFlux (research-only)**, **MMAudio (CC-BY-NC)**, **F5-TTS (CC-BY-NC via the Emilia data)**, **XTTS-v2 (Coqui Public Model License, non-commercial)**, **YuE (CC-BY-NC plus creator permission; companies must license)**, **Fish-Speech S2-Pro (research licence)**. The code is MIT or Apache in most of these cases. *The code licence is not the weight licence.*
5. **Gated and "community" licences.** Stable Audio Open is free only for organizations under $1M annual revenue, needs an HF click-through, and binds outputs to Stability's AUP. Pocket TTS is CC-BY but gated, with prohibited-use terms. Orpheus is tagged Apache but fine-tuned from **Llama-3.2**, so the Llama Community License likely flows through. Supertonic uses **OpenRAIL-M**, whose use restrictions must be passed downstream. Treat all of these as opt-in extras the *user* downloads and accepts, never defaults, and never mirror their weights.
6. **Per-voice NC inside permissive models.** Pocket TTS's preset voices from **Expresso and EARS are CC-BY-NC**, while VCTK and CML-TTS are CC-BY and voice-donations are CC0. Keep an explicit voice allow-list in code.
7. **pedalboard is GPL-3.0** (JUCE, Rubber Band GPL option, LAME). The same goes for SoX and SuperCollider. Use them only from GPL-side processes.
8. **FFmpeg distro builds are GPL** (`--enable-gpl` for libx264). Calling the system ffmpeg as a subprocess is fine. Bundling an ffmpeg binary in a release or Docker image triggers source-offer and attribution duties. H.264/AAC patents are a separate, low-risk-for-OSS issue noted on ffmpeg's legal page.
9. **SFX libraries:** BBC RemArc is non-commercial, with AI training and data-mining excluded, so **don't use it**. Sonniss GDC is royalty-free but proprietary, and redistribution in an OSS repo isn't addressed, so **never vendor it**. Freesound licences are per sound: **CC-BY requires credit**, and CC-BY-NC and Sampling+ (retired, NC-like) must be filtered out. Original-quality downloads need OAuth2, and token access only gets lossy previews, so cache with provenance.
10. **SoundFont sample provenance.** GeneralUser GS permits commercial music *and* use in software, but its author can't vouch for every sample's origin. That's acceptable risk with no complaints since 2000, but record it in THIRD_PARTY.md. Avoid random SoundFonts from the web, since many contain ripped commercial samples.
11. **StyleTTS2-family pretrained models** require telling listeners the speech is synthetic unless the speaker consented. Add "Voices are AI-generated" to credits regardless; it's cheap and satisfies this class of clause.
12. **Attribution is the most common failure.** CC-BY voices, CC-BY Freesound clips, Magenta RT (CC-BY), Pocket TTS (CC-BY) and Hi-Fi TTS-based Piper voices all need credit. Auto-generate credits from `audio_manifest.json`.

---

## 4. Recommended audio pipeline

```
Script (lines, speakers, emotions, timing hints)
   │
   ├─► [1] Dialogue: voice_worker (subprocess) ─ Kokoro-ONNX default / Piper fallback
   │        out: line_NN.wav (24 kHz mono) + line_NN.json {text, voice, model, license, duration, word timings?}
   │        QA: faster-whisper tiny/base int8 → WER vs script; retry with alt voice/speed if WER > ~15%
   │
   ├─► [2] Alignment/visemes: rhubarb -f json -d line_NN.txt line_NN.wav
   │        → mouthCues [{start,end,value:A..H,X}] → Blender shape-key keyframes (GPL adapter)
   │        → captions.srt from script text + line start offsets
   │
   ├─► [3] Music bed: LLM writes {key, tempo, chord progression, sections, mood}
   │        → pretty_midi → bed.mid → fluidsynth + GeneralUser GS → music.wav (48k stereo)
   │        (offline CI path: numpy pad/drone synth)
   │
   ├─► [4] SFX: cue list {name, frame, gain} → resolve: Kenney CC0 → jsfxr/numpy procedural → Freesound CC0 cache
   │
   ├─► [5] Place + duck + mix: one ffmpeg filtergraph (adelay per clip, sidechaincompress music by dialogue, amix normalize=0)
   │        (also mirror strips into Blender VSE so artists see the timeline)
   │
   ├─► [6] Loudness: two-pass loudnorm → -14 LUFS integrated, -1 dBTP, LRA ≤ 11; verify with pyloudnorm in tests
   │
   └─► [7] Mux: Blender video (frames or lossless) + mix → H.264/AAC MP4, +faststart, optional soft subtitles
```

Frame↔time: `t = frame / fps` (use the scene fps, e.g. 24). Keep every intermediate file at **48 kHz** after step 1. Resample TTS once with `aresample=48000:resampler=soxr` (if ffmpeg is built with soxr; otherwise the default is fine).

### 4.1 Dialogue (Kokoro-ONNX in a worker)

```python
# voice_worker.py — runs as its own process; core calls: python -m animatica_voice_worker job.json
from kokoro_onnx import Kokoro
import soundfile as sf
k = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
samples, sr = k.create("Hello, little one.", voice="af_heart", speed=0.95, lang="en-us")
sf.write("line_01.wav", samples, sr)   # 24 kHz mono
```

Piper fallback (CLI, GPL kept out of process):

```bash
echo "Hello, little one." | piper --model en_US-ljspeech-high.onnx --output_file line_01.wav
```

### 4.2 Visemes

```bash
printf 'Hello, little one.\n' > line_01.txt
rhubarb -f json -d line_01.txt -o line_01.mouth.json line_01.wav
# non-English: add --recognizer phonetic
```

Map `A..H,X` to 9 shape keys or pose-library poses (A = closed M/B/P, B = slightly open/teeth, C = open E, D = wide AI, E = rounded O, F = puckered U/W, G = F/V teeth-on-lip, H = L tongue, X = rest). Key each cue at `round(start*fps)` with a short 1–2 frame blend.

### 4.3 Music bed (procedural, licence-clean)

```bash
fluidsynth -ni -g 0.6 -r 48000 -F music_raw.wav GeneralUser-GS.sf2 bed.mid
ffmpeg -y -i music_raw.wav -af "afade=t=in:d=2,afade=t=out:st=18:d=2,aformat=sample_rates=48000:channel_layouts=stereo" music.wav
```

### 4.4 Place, duck and mix (single filtergraph)

Example for a 20 s film: dialogue at 12.0 s, a "clank" SFX at 3.5 s and a "chime" at 12.8 s, music bed and ambience under everything.

```bash
ffmpeg -y \
  -i music.wav -i ambience.wav -i line_01.wav -i clank.wav -i chime.wav \
  -filter_complex "
    [0:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=-6dB[mus];
    [1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=-14dB[amb];
    [2:a]aresample=48000,aformat=channel_layouts=stereo,adelay=12000:all=1,apad=whole_dur=20[dlg];
    [3:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=3500:all=1,volume=-4dB[s1];
    [4:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=12800:all=1,volume=-8dB[s2];
    [dlg]asplit=2[dlg_mix][dlg_sc];
    [mus][dlg_sc]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=350:makeup=1[mus_duck];
    [mus_duck][amb][dlg_mix][s1][s2]amix=inputs=5:duration=first:normalize=0,
      alimiter=limit=0.95[mix]" \
  -map "[mix]" -t 20 -c:a pcm_s24le mix.wav
```

Notes: `normalize=0` keeps the gains we set (amix's default renormalizes per input count and makes the mix quiet and pumpy). `duration=first` ends at the music bed's length. Ducking depth is set by `threshold` and `ratio`; about 8–10 dB of reduction under speech is typical. Dialogue should land about 6–10 LU above the music bed *(rule of thumb)*.

### 4.5 Loudness normalize (two-pass loudnorm, YouTube target)

```bash
# pass 1: measure
ffmpeg -hide_banner -i mix.wav -af loudnorm=I=-14:TP=-1:LRA=11:print_format=json -f null - 2> ln.txt
# parse input_i, input_tp, input_lra, input_thresh, target_offset from the JSON block, then pass 2:
ffmpeg -y -i mix.wav -af "loudnorm=I=-14:TP=-1:LRA=11:measured_I=-21.3:measured_TP=-4.2:measured_LRA=6.1:measured_thresh=-31.9:offset=0.3:linear=true,aresample=48000" -c:a pcm_s24le mix_norm.wav
```

Test assertion (Python): `pyloudnorm.Meter(48000).integrated_loudness(x)` lands within ±1 LU of -14. Peak sample ≤ -1 dBFS (true peak via loudnorm). loudnorm's own default target is -24 LUFS (broadcast-ish), so always pass `I=-14` for web delivery.

### 4.6 Mux with Blender's video

```bash
# Blender renders video-only (or PNG frames). Mux, don't re-encode video if already H.264:
ffmpeg -y -i render.mp4 -i mix_norm.wav -map 0:v:0 -map 1:a:0 \
  -c:v copy -c:a aac -b:a 192k -ar 48000 -shortest -movflags +faststart output/film.mp4

# From PNG frames at 24 fps:
ffmpeg -y -framerate 24 -i frames/%04d.png -i mix_norm.wav \
  -c:v libx264 -pix_fmt yuv420p -crf 18 -preset medium \
  -c:a aac -b:a 192k -shortest -movflags +faststart output/film.mp4

# Optional soft subtitles (mov_text) from script-derived SRT:
ffmpeg -y -i output/film.mp4 -i captions.srt -map 0 -map 1 -c copy -c:s mov_text -metadata:s:s:0 language=eng output/film_subs.mp4
```

(`libx264` needs a GPL ffmpeg build. Distro ffmpeg has it. If only an LGPL build is available, use `libopenh264` or `mpeg4`.)

### 4.7 QA hooks for the Critic agent

- **Intelligibility:** faster-whisper `base.en` int8 on each line. Fail if normalized WER exceeds the threshold.
- **Loudness:** pyloudnorm integrated LUFS and max sample peak; there's an `ebur128` ffmpeg filter for LRA.
- **Sync:** first mouth cue start minus dialogue start, ≤ 1 frame.
- **Silence and clipping:** `silencedetect` and `astats` in ffmpeg for dropouts and clipping.
- **Licence:** every file in the mix has a manifest entry with an allowed SPDX (`CC0-1.0`, `CC-BY-4.0` + attribution, `Apache-2.0`, `MIT`, or `LicenseRef-Animatica-generated`).

---

## 5. Sources

TTS
- Kokoro-82M model card: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/README.md
- misaki G2P: https://github.com/hexgrad/misaki
- kokoro-onnx: https://github.com/thewh1teagle/kokoro-onnx
- Piper (current, GPL): https://github.com/OHF-Voice/piper1-gpl ; licensing: https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/LICENSING.md ; commercial-use voice list: https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/COMMERCIAL_USE.md
- Piper (archived MIT): https://github.com/rhasspy/piper ; voices: https://huggingface.co/rhasspy/piper-voices
- espeak-ng (GPL-3.0+): https://github.com/espeak-ng/espeak-ng
- Kyutai Pocket TTS: https://github.com/kyutai-labs/pocket-tts ; weights: https://huggingface.co/kyutai/pocket-tts ; voices: https://huggingface.co/kyutai/tts-voices
- Kyutai TTS 1.6B: https://huggingface.co/kyutai/tts-1.6b-en_fr
- Chatterbox: https://huggingface.co/ResembleAI/chatterbox/blob/main/README.md
- Perth watermarker: https://github.com/resemble-ai/Perth
- Parler-TTS: https://github.com/huggingface/parler-tts ; https://huggingface.co/parler-tts/parler-tts-mini-v1
- MeloTTS: https://github.com/myshell-ai/MeloTTS
- OpenVoice: https://github.com/myshell-ai/OpenVoice
- StyleTTS2: https://github.com/yl4579/StyleTTS2
- NeuTTS: https://github.com/neuphonic/neutts-air
- Zonos: https://github.com/Zyphra/Zonos
- Orpheus: https://github.com/canopyai/Orpheus-TTS ; https://huggingface.co/canopylabs/orpheus-3b-0.1-ft
- Dia: https://github.com/nari-labs/dia ; https://huggingface.co/nari-labs/Dia-1.6B-0626
- KittenTTS: https://github.com/KittenML/KittenTTS ; https://huggingface.co/KittenML/kitten-tts-mini-0.8
- Supertonic: https://github.com/supertone-inc/supertonic
- F5-TTS: https://github.com/SWivid/F5-TTS
- XTTS-v2: https://huggingface.co/coqui/XTTS-v2 ; CPML: https://coqui.ai/cpml (site unreachable at time of research) ; maintained toolkit fork: https://github.com/idiap/coqui-ai-TTS
- IndexTTS: https://github.com/index-tts/index-tts
- Fish-Speech: https://github.com/fishaudio/fish-speech

Music
- AudioCraft/MusicGen: https://github.com/facebookresearch/audiocraft ; https://huggingface.co/facebook/musicgen-small
- Stable Audio Open 1.0: https://huggingface.co/stabilityai/stable-audio-open-1.0 ; Small: https://huggingface.co/stabilityai/stable-audio-open-small ; Community License: https://stability.ai/license ; tools: https://github.com/Stability-AI/stable-audio-tools
- ACE-Step 1.5: https://github.com/ace-step/ACE-Step-1.5 ; https://huggingface.co/ACE-Step/Ace-Step1.5
- YuE: https://github.com/multimodal-art-projection/YuE
- DiffRhythm: https://github.com/ASLP-lab/DiffRhythm
- Magenta RealTime: https://huggingface.co/google/magenta-realtime
- FluidSynth: https://github.com/FluidSynth/fluidsynth
- GeneralUser GS: https://github.com/mrbumpy409/GeneralUser-GS ; licence: https://github.com/mrbumpy409/GeneralUser-GS/blob/main/documentation/LICENSE.txt
- FluidR3_GM (Debian): https://packages.debian.org/sid/fluid-soundfont-gm
- SuperCollider: https://github.com/supercollider/supercollider ; Csound: https://github.com/csound/csound
- mido: https://github.com/mido/mido ; pretty_midi: https://github.com/craffel/pretty-midi ; music21: https://github.com/cuthbertLab/music21

SFX
- Kenney Interface Sounds (CC0): https://kenney.nl/assets/interface-sounds ; all audio: https://kenney.nl/assets/category:Audio
- Freesound licences/FAQ: https://freesound.org/help/faq/ ; API resources (OAuth2 for original download, licence filter): https://freesound.org/docs/api/resources_apiv2.html ; auth: https://freesound.org/docs/api/authentication.html
- jsfxr: https://github.com/chr15m/jsfxr
- AudioLDM2: https://huggingface.co/cvssp/audioldm2
- Tango: https://github.com/declare-lab/tango ; Tango 2 weights: https://huggingface.co/declare-lab/tango2 ; TangoFlux: https://github.com/declare-lab/TangoFlux
- MMAudio: https://github.com/hkchengrex/MMAudio
- Sonniss GDC licence: https://sonniss.com/gdc-bundle-license/
- BBC Sound Effects (RemArc) summary: https://www.diyphotography.net/the-bbc-sound-effects-archive-is-now-free-to-download-with-over-33000-files/ ; site: https://sound-effects.bbcrewind.co.uk/licensing (blocked from this session)

Processing, mixing, assembly
- FFmpeg filters (loudnorm, sidechaincompress, amix, adelay, apad, afade): https://ffmpeg.org/ffmpeg-filters.html
- FFmpeg licence: https://ffmpeg.org/legal.html
- pedalboard: https://github.com/spotify/pedalboard
- pyloudnorm: https://github.com/csteinmetz1/pyloudnorm ; https://pypi.org/project/pyloudnorm/
- librosa: https://github.com/librosa/librosa
- pydub: https://github.com/jiaaro/pydub ; audioop-lts: https://pypi.org/project/audioop-lts/ ; PEP 594 (audioop removal): https://peps.python.org/pep-0594/
- soundfile: https://github.com/bastibe/python-soundfile
- MoviePy: https://github.com/Zulko/moviepy
- Blender SequenceEditor API: https://docs.blender.org/api/current/bpy.types.SequenceEditor.html
- YouTube -14 LUFS reference: https://productionadvice.co.uk/youtube-loudness/
- Whisper: https://github.com/openai/whisper ; https://huggingface.co/openai/whisper-large-v3 ; faster-whisper: https://github.com/SYSTRAN/faster-whisper ; whisper.cpp: https://github.com/ggml-org/whisper.cpp

Alignment and lip sync
- Rhubarb Lip Sync: https://github.com/DanielSWolf/rhubarb-lip-sync ; licence: https://github.com/DanielSWolf/rhubarb-lip-sync/blob/master/LICENSE.md ; release v1.14.0: https://github.com/DanielSWolf/rhubarb-lip-sync/releases/tag/v1.14.0
- Montreal Forced Aligner: https://github.com/MontrealCorpusTools/Montreal-Forced-Aligner ; models: https://github.com/MontrealCorpusTools/mfa-models
- whisperX: https://github.com/m-bain/whisperX
- Gentle: https://github.com/lowerquality/gentle

Package metadata (versions and dates in tables): PyPI JSON API, `https://pypi.org/pypi/<package>/json`, queried 2026-11-15.
