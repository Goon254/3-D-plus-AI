"""Voice & Sound: dialogue -> WAV per line (local TTS) -> visemes (Rhubarb) -> mouth keys; music bed."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..audio import lipsync, music, tts
from .base import Agent

if TYPE_CHECKING:
    from ..core.orchestrator import Context


class VoiceSound(Agent):
    role = "voice"
    task = "voice"
    system_prompt = "Voice & sound designer."

    def run(self, ctx: Context) -> dict[str, Any]:
        plan = ctx.plan
        audio_dir = ctx.state.root / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        frames = plan.shot_frames()
        fps = plan.fps
        lines: dict[str, Any] = {}
        mouth: dict[str, list] = {k: [] for k in lipsync.SHAPE_KEYS}
        hero = plan.hero
        engine = ctx.options.get("tts_engine", "auto")
        for d in plan.dialogue:
            v = hero.voice
            spec = tts.VoiceSpec(engine=engine, voice=v.voice, speaker=v.speaker, pitch=v.pitch, rate=v.rate, robot=v.robot)
            res = tts.synthesize(d.text, audio_dir / f"{d.id}.wav", spec)
            cues, ls_engine = lipsync.lipsync(res["path"], d.text)
            start_frame = frames[d.shot][0] + int(round(d.at * fps))
            keys = lipsync.cues_to_keyframes(cues, fps, start_frame)
            for k in mouth:
                last = mouth[k][-1][0] if mouth[k] else -1
                mouth[k] += [kf for kf in keys[k] if kf[0] > last]
            lines[d.id] = {"path": res["path"], "engine": res["engine"], "duration": res["duration"], "lipsync": ls_engine,
                           "start_s": round((start_frame - 1) / fps, 3), "cues": len(cues)}
            ctx.log.event("audio", self.role, f"{d.id} '{d.text}' -> {res['engine']} {res['duration']:.2f}s, "
                          f"{len(cues)} mouth cues via {ls_engine}, starts frame {start_frame}", line=d.id)
        dur = plan.duration
        bed = music.generate_bed(dur + 0.5, plan.style.mood, seed=plan.title,
                                 ambience="wind" if plan.setting.kind not in ("room", "space") else "")
        music_path = tts.write_wav(audio_dir / "music_bed.wav", bed, music.SR)
        mix_path = music.mix(dur, bed, [(v["start_s"], v["path"]) for v in lines.values()], audio_dir / "mix.wav")
        ctx.log.event("audio", self.role, f"music bed: mood '{plan.style.mood}', {dur:.1f}s; mixed with dialogue "
                      f"ducking -9 dB -> {mix_path.name}")
        ctx.state.artifacts.update({"lines": lines, "mouth_keys": mouth, "music": str(music_path), "mix": str(mix_path)})
        return {"lines": lines, "mix": str(mix_path)}
