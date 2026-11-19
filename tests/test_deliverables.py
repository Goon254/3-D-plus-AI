"""The film's hand-off files: captions, the MLT edit, the production log, the poster (CHALLENGE "Output")."""

from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from animatica.production import deliverables as dlv


def _reports():
    return [
        {
            "scene": "sc01",
            "title": "Dawn - the old watering hole",
            "quality": "final",
            "seconds": 10.0,
            "render_seconds": 1200.0,
            "shots": [
                {"shot": 0, "type": "ews", "subjects": ["tembo", "zuri", "kiki"], "start": 0.0, "end": 4.0},
                {"shot": 1, "type": "ms", "subjects": ["tembo", "zuri"], "start": 4.0, "end": 10.0},
            ],
            "lines": [
                {
                    "who": "narrator",
                    "start": 1.0,
                    "end": 3.0,
                    "text": "Far away, where the grass grows *golden*...",
                    "engine": "chatterbox",
                    "wer": 0.0,
                },
                {
                    "who": "tembo",
                    "start": 5.0,
                    "end": 5.4,
                    "text": "Water!",
                    "engine": "chatterbox",
                    "wer": 0.0,
                },
                {
                    "who": "kiki",
                    "start": 5.5,
                    "end": 6.5,
                    "text": "Over here!",
                    "engine": "kokoro",
                    "fallback": "x",
                },
            ],
            "cue": {"id": "wonder", "bpm": 72, "moods": ["wonder"]},
            "continuity": [],
            "warnings": [],
        },
        {
            "scene": "sc02",
            "title": "Night - the dry riverbed",
            "quality": "final",
            "seconds": 8.0,
            "render_seconds": 600.0,
            "shots": [{"shot": 0, "type": "ms", "subjects": ["tembo", "kiki"], "start": 0.0, "end": 8.0}],
            "lines": [
                {
                    "who": "zuri",
                    "start": 0.5,
                    "end": 6.5,
                    "text": "We walked all day and all night under the stars. "
                    "Now we rest by the two old trees that bow to each other, and tomorrow we find the spring!",
                    "engine": "chatterbox",
                    "wer": 0.1,
                }
            ],
            "continuity": ["actor_overlap tembo+kiki at 3.0 s (0.10 m)"],
            "warnings": [],
        },
    ]


def test_cues_sit_at_film_time_with_italics_for_the_narrator_and_names_off_screen():
    cues = dlv.caption_cues(_reports())
    nar, tembo, kiki = cues[:3]
    assert nar.start == 1.0 and nar.text == "<i>Far away, where the grass grows golden...</i>"
    assert tembo.text == "Water!"  # Tembo is in the shot: no name
    assert kiki.text == "KIKI: Over here!"  # Kiki speaks from off screen
    assert tembo.end <= kiki.start - dlv.GAP_S + 2e-3  # the short line's minimum hold yields to the next cue
    later = [c for c in cues if c.scene == "sc02"]
    assert later[0].start == pytest.approx(10.5)  # sc02 starts after sc01's 10 s
    assert later[0].text.startswith("ZURI: ")


def test_a_long_line_is_split_at_sentences_into_two_line_cues_that_share_its_time():
    cues = [c for c in dlv.caption_cues(_reports()) if c.scene == "sc02"]
    assert len(cues) == 3  # two sentences; the second is too long for one cue and breaks at its comma
    for c in cues:
        lines = c.text.split("\n")
        assert len(lines) <= dlv.MAX_LINES and all(len(x) <= dlv.MAX_CHARS for x in lines)
    assert cues[0].text.replace("\n", " ").endswith("stars.")
    assert cues[1].text.replace("\n", " ").endswith("each other,")
    assert cues[0].end <= cues[1].start and cues[1].end <= cues[2].start
    assert cues[2].start < 16.5 and cues[2].end <= 18.0  # inside the line, held at most to the film's end


def test_wrap_balances_two_lines():
    assert dlv.wrap("Water!") == ["Water!"]
    a, b = dlv.wrap("Two trees, bowing! Right under the stars, just like the song said!")
    assert len(a) <= 42 and len(b) <= 42 and abs(len(a) - len(b)) < 12


def test_srt_and_vtt_are_well_formed(tmp_path):
    cues = dlv.caption_cues(_reports())
    srt = dlv.write_srt(cues, tmp_path / "c.srt").read_text(encoding="utf-8")
    vtt = dlv.write_vtt(cues, tmp_path / "c.vtt").read_text(encoding="utf-8")
    assert srt.startswith("1\n00:00:01,000 --> ")
    assert vtt.startswith("WEBVTT") and "00:00:01.000 --> " in vtt
    assert srt.count(" --> ") == vtt.count(" --> ") == len(cues)


def test_caption_issues_flag_fast_reading_and_overlaps():
    fast = dlv.Cue(0.0, 0.5, "A very long sentence in half a second", "zuri", "sc01")
    slow = dlv.Cue(0.4, 2.0, "Ok.", "kiki", "sc01")
    issues = dlv.caption_issues([fast, slow])
    assert any("chars/s" in i for i in issues) and any("overlaps" in i for i in issues)
    assert dlv.caption_issues([dlv.Cue(0.0, 2.0, "Water!", "tembo", "sc01")]) == []


def test_the_mlt_edit_has_a_producer_per_scene_and_an_entry_per_shot(tmp_path):
    rs = _reports()
    out = dlv.write_mlt(rs, ["../sc01.mp4", "../sc02.mp4"], tmp_path / "edit.mlt", "Tembo & the Spring")
    root = ET.parse(out).getroot()
    assert root.get("title") == "Tembo & the Spring"
    assert [p.get("id") for p in root.iter("producer")] == ["sc01", "sc02"]
    entries = list(root.find("playlist").iter("entry"))
    assert [(e.get("producer"), e.get("in"), e.get("out")) for e in entries] == [
        ("sc01", "0", "95"),
        ("sc01", "96", "239"),
        ("sc02", "0", "191"),
    ]
    assert root.find("tractor").get("out") == str(18 * 24 - 1)


def test_the_production_log_reports_scenes_voices_and_continuity():
    rs = _reports()
    log = dlv.production_log(rs, "Tembo", {"lufs": -14.0, "true_peak_dbtp": -1.2}, None, dlv.caption_cues(rs))
    assert "Runtime **0:18.0**" in log and "| sc02 | Night - the dry riverbed | 0:10.0 |" in log
    assert "Fallbacks (1)" in log and "kiki" in log and "actor_overlap" in log
    assert "## Captions" in log
    assert log == dlv.production_log(
        rs, "Tembo", {"lufs": -14.0, "true_peak_dbtp": -1.2}, None, dlv.caption_cues(rs)
    )


def test_the_poster_is_a_daytime_medium_shot_of_the_lead_with_a_friend():
    rs = _reports()
    assert dlv.lead(rs) == "kiki"  # one line each: the first name alphabetically
    rs[0]["lines"].append({"who": "tembo", "start": 8.0, "end": 9.0, "text": "Go!"})
    assert dlv.lead(rs) == "tembo"
    # the ews has the most of the cast, the night ms has Tembo too: the dawn ms wins
    assert dlv.poster_time(rs) == pytest.approx(7.0)
    assert dlv.poster_time(rs, hero="kiki") == pytest.approx(2.0)  # Kiki is only in the dawn ews by day


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_write_poster_grabs_the_frame_and_sets_the_title(tmp_path):
    from PIL import Image

    vid = tmp_path / "v.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x6688AA:s=320x180:r=24:d=2"]
        + ["-pix_fmt", "yuv420p", str(vid)],
        check=True,
    )
    out = dlv.write_poster(vid, 1.0, tmp_path / "poster.jpg", "Tembo", "tag", width=640)
    im = Image.open(out).convert("RGB")
    assert im.size == (640, 360)
    top, bottom = im.getpixel((10, 10)), im.getpixel((10, 355))
    assert abs(top[2] - 0xAA) < 12 and sum(bottom) < sum(top)  # untouched sky, darkened band
    assert not (tmp_path / "poster.frame.png").exists()
