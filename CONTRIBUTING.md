# Contributing

Thanks for helping build Animatica!

1. **Sign off your commits** (Developer Certificate of Origin): `git commit -s` adds
   `Signed-off-by: Your Name <you@example.com>`. By signing off you certify that you wrote the change or
   have the right to submit it under the project's licenses (https://developercertificate.org).
2. **Licensing:** the core (`src/animatica`) is Apache-2.0; `adapters/blender` and `adapters/tts_worker` are
   GPL-3.0-or-later. Never import `bpy` or GPL TTS code from `src/animatica` — talk to them over the JSON
   protocol. Do not copy code from AGPL, non-commercial, academic-only or unlicensed projects (see
   `docs/LICENSE_AUDIT.md`). Record every new dependency or asset in `THIRD_PARTY.md`.
3. **Tests:** `pytest -q` (unit) and `pytest -q -m blender` (needs `bpy`). `ruff check src tests adapters` must pass.
4. **Batches over calls:** new engine features go into the protocol (`core/protocol.py`) as validated ops,
   implemented in the adapter, documented in `docs/PROTOCOL.md`, and tested both for valid and invalid input.
5. **Log decisions** that others would otherwise have to rediscover in `docs/DECISIONS.md` (one line).
