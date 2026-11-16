#!/usr/bin/env bash
# Downloads the optional open-source tools/models Animatica uses into ~/.cache/animatica.
#   * Kokoro-82M ONNX model + voices (Apache-2.0 weights) from the kokoro-onnx GitHub release — default TTS
#   * Piper voices (rhasspy/piper GitHub release v0.0.2): en-us-libritts-high (CC BY 4.0 dataset),
#     en-us-kathleen-low (CC0 dataset). HuggingFace may be blocked in sandboxes; GitHub releases work.
#   * Rhubarb Lip Sync 1.14.0 (MIT) Linux or Windows binary.
#   * GeneralUser GS 2.0.3 SoundFont (S. Christian Collins; free for any music use, incl. commercial, and for
#     use in software) for the Composer's FluidSynth renders. Pinned to a commit of the author's GitHub repo
#     and checked by SHA-256. FluidSynth itself (LGPL-2.1) comes from the OS: `apt install fluidsynth`.
# On Windows run it from Git Bash (curl + unzip ship with Git for Windows); it fetches the Windows builds.
# Everything is optional: without them Animatica falls back to espeak-ng / a synth voice and an
# amplitude-based lip sync, so the pipeline always runs.
set -euo pipefail
CACHE="${ANIMATICA_CACHE:-$HOME/.cache/animatica}"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) OS=windows ;;
  *) OS=linux ;;
esac
mkdir -p "$CACHE/voices" "$CACHE/rhubarb" "$CACHE/kokoro" "$CACHE/soundfonts"
KREL=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  [ -f "$CACHE/kokoro/$f" ] || { echo "downloading $f"; curl -fsSL --retry 3 -o "$CACHE/kokoro/$f" "$KREL/$f"; }
done
for v in en-us-libritts-high en-us-kathleen-low; do
  if [ ! -f "$CACHE/voices/$v/$v.onnx" ]; then
    echo "downloading voice $v"
    mkdir -p "$CACHE/voices/$v"
    curl -fsSL "https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-$v.tar.gz" | tar xz -C "$CACHE/voices/$v"
  fi
done
if [ "$OS" = windows ]; then RHU=Windows; RHU_EXE=rhubarb.exe; else RHU=Linux; RHU_EXE=rhubarb; fi
if [ ! -f "$CACHE/rhubarb/Rhubarb-Lip-Sync-1.14.0-$RHU/$RHU_EXE" ]; then
  echo "downloading rhubarb ($RHU)"
  tmp=$(mktemp -d)
  curl -fsSL --retry 3 -o "$tmp/r.zip" "https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/Rhubarb-Lip-Sync-1.14.0-$RHU.zip"
  unzip -q "$tmp/r.zip" -d "$CACHE/rhubarb"
  rm -rf "$tmp"
fi
if [ "$OS" = windows ]; then GD=Godot_v4.5.1-stable_win64.exe; GD_BIN=Godot_v4.5.1-stable_win64_console.exe
else GD=Godot_v4.5.1-stable_linux.x86_64; GD_BIN=$GD; fi
if [ "${1:-}" = "--godot" ] && [ ! -f "$CACHE/godot/$GD_BIN" ]; then
  echo "downloading Godot 4.5.1"
  mkdir -p "$CACHE/godot"; tmp=$(mktemp -d)
  curl -fsSL --retry 3 -o "$tmp/g.zip" "https://github.com/godotengine/godot/releases/download/4.5.1-stable/$GD.zip"
  unzip -q "$tmp/g.zip" -d "$CACHE/godot"; rm -rf "$tmp"
fi
GUGS_COMMIT=684543d5e5efaef08d02be50dcda8d552478fa60
GUGS_SHA256=9575028c7a1f589f5770fccc8cff2734566af40cd26ed836944e9a5152688cfe
SF2="$CACHE/soundfonts/GeneralUser-GS.sf2"
if [ ! -f "$SF2" ]; then
  echo "downloading GeneralUser GS 2.0.3 SoundFont (32 MB)"
  curl -fsSL --retry 3 -o "$SF2.part" \
    "https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/$GUGS_COMMIT/GeneralUser-GS.sf2"
  if command -v sha256sum >/dev/null; then
    echo "$GUGS_SHA256  $SF2.part" | sha256sum -c --quiet - || { rm -f "$SF2.part"; echo "SoundFont checksum mismatch" >&2; exit 1; }
  fi
  mv "$SF2.part" "$SF2"
fi
command -v fluidsynth >/dev/null || echo "note: fluidsynth not on PATH; the Composer will use its numpy fallback synth"
echo "assets ready in $CACHE"
