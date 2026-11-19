"""Mastering (cloud review 11-19): the web film was -14.0 LUFS but peaked at +0.5 dBTP after a second AAC
pass. Delivery is now limited and measured on the encoded file."""

import shutil
import subprocess

import pytest

from animatica.audio.mux import TP_CEILING_DB, loudness, master, parse_ebur128, true_peak_limiter

SUMMARY = """[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -14.0 LUFS
    Threshold: -24.4 LUFS

  Loudness range:
    LRA:         7.1 LU
    Threshold: -34.3 LUFS

  True peak:
    Peak:        0.5 dBFS
"""


def test_parse_ebur128_summary():
    assert parse_ebur128("noise\n" + SUMMARY) == {"i": -14.0, "lra": 7.1, "tp": 0.5}


def test_the_limiter_oversamples_and_returns_to_the_rate():
    f = true_peak_limiter(-2.0)
    assert f.startswith("aresample=192000,alimiter=limit=0.7943") and f.endswith("aresample=48000")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_master_holds_the_true_peak_on_the_encoded_file(tmp_path):
    """A peaky mix (a quiet bed with hard 3 kHz clicks, like footsteps and the gush): plain loudnorm + AAC
    lands over 0 dBTP; master() measures the encoded file and lowers the limiter until it is under -1."""
    src = tmp_path / "mix.wav"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.05:d=12",
            "-f", "lavfi", "-i", "aevalsrc='0.9*sin(2*PI*3000*t)*lt(mod(t,1),0.03)':d=12",
            "-filter_complex", "[0][1]amix=inputs=2:normalize=0,aformat=channel_layouts=stereo",
            "-ar", "48000", str(src),
        ],
        check=True,
    )  # fmt: skip
    got = master(src, tmp_path / "out.m4a", lufs=-14.0)
    assert got["tp"] <= TP_CEILING_DB
    assert abs(got["i"] - -14.0) <= 1.0
    assert loudness(tmp_path / "out.m4a")["tp"] == got["tp"]
