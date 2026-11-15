#!/usr/bin/env bash
# Downloads the optional open-source tools/models Animatica uses into ~/.cache/animatica.
#   * Kokoro-82M ONNX model + voices (Apache-2.0 weights) from the kokoro-onnx GitHub release — default TTS
#   * Piper voices (rhasspy/piper GitHub release v0.0.2): en-us-libritts-high (CC BY 4.0 dataset),
#     en-us-kathleen-low (CC0 dataset). HuggingFace may be blocked in sandboxes; GitHub releases work.
#   * Rhubarb Lip Sync 1.14.0 (MIT) Linux binary.
# Everything is optional: without them Animatica falls back to espeak-ng / a synth voice and an
# amplitude-based lip sync, so the pipeline always runs.
set -euo pipefail
CACHE="${ANIMATICA_CACHE:-$HOME/.cache/animatica}"
mkdir -p "$CACHE/voices" "$CACHE/rhubarb" "$CACHE/kokoro"
KREL=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  [ -f "$CACHE/kokoro/$f" ] || { echo "downloading $f"; curl -fsSL -o "$CACHE/kokoro/$f" "$KREL/$f"; }
done
for v in en-us-libritts-high en-us-kathleen-low; do
  if [ ! -f "$CACHE/voices/$v/$v.onnx" ]; then
    echo "downloading voice $v"
    mkdir -p "$CACHE/voices/$v"
    curl -fsSL "https://github.com/rhasspy/piper/releases/download/v0.0.2/voice-$v.tar.gz" | tar xz -C "$CACHE/voices/$v"
  fi
done
if [ ! -x "$CACHE/rhubarb/Rhubarb-Lip-Sync-1.14.0-Linux/rhubarb" ]; then
  echo "downloading rhubarb"
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/r.zip" https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/Rhubarb-Lip-Sync-1.14.0-Linux.zip
  unzip -q "$tmp/r.zip" -d "$CACHE/rhubarb"
  rm -rf "$tmp"
fi
echo "assets ready in $CACHE"
