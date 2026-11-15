"""Film plan data model: the Director's output and the contract every other agent reads."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

HEX = r"#[0-9A-Fa-f]{6}"
ShotType = Literal["wide", "medium", "closeup"]
CameraMove = Literal["static", "dolly_in", "dolly_out", "pan", "orbit", "crane_up", "track"]
Beat = Literal["enter", "discover", "approach", "speak", "react", "celebrate", "settle", "exit", "idle"]
TimeOfDay = Literal["dawn", "day", "sunset", "night"]
SettingKind = Literal["junkyard", "forest", "meadow", "beach", "desert", "snow", "city", "space", "room"]
CharacterKind = Literal["robot", "critter"]
PropKind = Literal["flower", "lantern", "ball", "crystal", "mushroom", "star", "egg", "book"]


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Palette(_M):
    primary: str = "#D9822B"
    secondary: str = "#3E4A59"
    accent: str = "#7FE7FF"
    ground: str = "#6B5A4A"
    sky_zenith: str = "#3B4E8C"
    sky_horizon: str = "#F4A259"
    sun: str = "#FFB36B"

    @field_validator("*")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not re.fullmatch(HEX, v):
            raise ValueError(f"bad colour {v!r}")
        return v.upper()


class StyleBible(_M):
    palette: Palette = Field(default_factory=Palette)
    mood: str = "warm"  # music mood key, see audio.music.MOODS
    shape_language: str = "rounded, chunky, friendly; bevelled edges, no sharp spikes"
    lighting: str = "low warm key light with cool fill"
    notes: list[str] = Field(default_factory=list)


class Setting(_M):
    kind: SettingKind = "junkyard"
    time_of_day: TimeOfDay = "sunset"
    density: float = Field(1.0, ge=0, le=3)


class VoiceChoice(_M):
    voice: str = "am_puck"  # Kokoro voice id (stock voices only; no cloning)
    speaker: int = 20  # Piper multi-speaker fallback
    pitch: float = Field(1.12, ge=0.5, le=2.0)
    rate: float = Field(0.9, ge=0.5, le=2.0)
    robot: float = Field(0.2, ge=0, le=1)


class Character(_M):
    id: str = "hero"
    kind: CharacterKind = "robot"
    name: str = "Bolt"
    color: str = "#D9822B"
    eye_color: str = "#7FE7FF"
    scale: float = Field(1.0, ge=0.3, le=3)
    voice: VoiceChoice = Field(default_factory=VoiceChoice)


class Prop(_M):
    id: str = "prop"
    kind: PropKind = "flower"
    color: str = "#FF5C8A"
    location: tuple[float, float, float] = (1.3, 0.0, 0.0)


class DialogueLine(_M):
    id: str = "line1"
    character: str = "hero"
    text: str
    shot: str = "s3"
    at: float = Field(1.0, ge=0, description="seconds after the shot starts")


class Shot(_M):
    id: str
    type: ShotType = "wide"
    duration: float = Field(5.0, ge=1.5, le=20)
    beat: Beat = "idle"
    description: str = ""
    camera_move: CameraMove = "static"
    subject: Literal["hero", "prop", "both"] = "hero"


class FilmPlan(_M):
    title: str
    logline: str = ""
    prompt: str = ""
    style: StyleBible = Field(default_factory=StyleBible)
    setting: Setting = Field(default_factory=Setting)
    characters: list[Character] = Field(default_factory=lambda: [Character()], min_length=1, max_length=1)
    props: list[Prop] = Field(default_factory=lambda: [Prop()], max_length=3)
    shots: list[Shot] = Field(min_length=1, max_length=8)
    dialogue: list[DialogueLine] = Field(default_factory=list, max_length=6)
    fps: int = Field(24, ge=12, le=60)

    @property
    def duration(self) -> float:
        return sum(s.duration for s in self.shots)

    def shot_frames(self) -> dict[str, tuple[int, int]]:
        """Inclusive frame range per shot, starting at frame 1."""
        out, f = {}, 1
        for s in self.shots:
            n = int(round(s.duration * self.fps))
            out[s.id] = (f, f + n - 1)
            f += n
        return out

    @property
    def frame_end(self) -> int:
        return max(e for _, e in self.shot_frames().values())

    @property
    def hero(self) -> Character:
        return self.characters[0]

    @property
    def prop(self) -> Prop | None:
        return self.props[0] if self.props else None
