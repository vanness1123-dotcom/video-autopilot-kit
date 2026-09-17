"""Sprint 10.2 deterministic music arrangement contracts."""
import copy
import subprocess
import unittest
from pathlib import Path

from travel_reel.config import MusicConfig
from travel_reel.music import effective_beat_grid, interpret_tempo, negotiate_duration
from travel_reel.music_arrangement import build_assembly_command, generate_strategies


def analysis(duration=20, bpm=60, confidence=.8, energy=.5):
    beats=[{"time":float(x),"type":"detected_beat","confidence":confidence} for x in range(0,int(duration),1)]
    return {"version":"1.0","duration_seconds":float(duration),"tempo":{"bpm":bpm,"confidence":confidence},
            "beats":beats,"phrases":[{"index":0,"start":0.0,"end":float(duration),"energy":energy,"confidence":.6}],
            "energy_curve":[{"time":0,"end":duration,"energy":energy}],"structure":[{"type":"peak"}],"sync_anchors":[]}


def candidate(name,duration=20,score=70,energy=.5):
    a=analysis(duration,energy=energy)
    return {"track":{"track_id":name,"file_name":name+".mp3","fingerprint":name,"path":name+".mp3",
                     "production_ready":False,"metadata_status":"local_only"},"analysis":a,
            "alignment":{"music_aligned_duration":40 if duration>=40 else None,"usable_for_planning":duration>=40},
            "music_match_score":score,"components":{},"reasons":[]}


def direction(style="beat_montage"):
    return {"style":style,"duration_strategy":{"resolved_seconds":40,"minimum_seconds":38,"maximum_seconds":42,
            "flexibility_seconds":2,"safe_shot_bounds_seconds":{"minimum":38,"maximum":42}}}


PROFILE={"preferred_tempo_bpm":{"minimum":105,"maximum":165}}
STORY={"sequence":[{"section":x} for x in ("hook","exploration","highlight","closing")]}


class MusicArrangementTests(unittest.TestCase):
    def test_short_single_is_ineligible_and_alignment_is_not_fake(self):
        aligned=negotiate_duration(direction(),analysis(18.5))
        self.assertFalse(aligned["usable_for_planning"]); self.assertIsNone(aligned["music_aligned_duration"])
        result=generate_strategies([candidate("short",18.5)],PROFILE,direction(),STORY,MusicConfig())
        self.assertFalse(result["single_track_candidates"]); self.assertTrue(result["validation"])

    def test_two_and_three_short_tracks_form_exact_feasible_arrangements(self):
        for tracks in ([candidate("a",20),candidate("b",22)],
                       [candidate("a",15),candidate("b",15),candidate("c",15)]):
            result=generate_strategies(tracks,PROFILE,direction(),STORY,MusicConfig())
            self.assertTrue(result["multi_track_candidates"])
            strategy=result["multi_track_candidates"][0]
            self.assertEqual(strategy["timeline_duration_seconds"],40)
            self.assertEqual(len({s["fingerprint"] for s in strategy["segments"]}),strategy["track_count"])
            for segment in strategy["segments"]:
                self.assertGreaterEqual(segment["source_start_seconds"],0)
                self.assertLessEqual(segment["source_end_seconds"],segment["source_duration_seconds"])

    def test_insufficient_combined_duration_is_infeasible(self):
        result=generate_strategies([candidate("a",10),candidate("b",10)],PROFILE,direction(),STORY,MusicConfig())
        self.assertFalse(result["multi_track_candidates"])

    def test_tempo_interpretation_is_separate_bounded_and_deterministic(self):
        source=analysis(20,60,.8); original=copy.deepcopy(source["tempo"])
        result=interpret_tempo(source,PROFILE)
        self.assertEqual(result["detected_bpm"],60); self.assertEqual(result["effective_bpm"],120)
        self.assertLessEqual(result["tempo_interpretation_confidence"],.8); self.assertEqual(source["tempo"],original)
        grid=effective_beat_grid(source,result)
        self.assertEqual([x["time"] for x in grid],sorted(set(x["time"] for x in grid)))
        self.assertIn("heuristic_subdivision",{x["provenance"] for x in grid})

    def test_low_confidence_does_not_fabricate_tempo(self):
        result=interpret_tempo(analysis(20,60,.01),PROFILE)
        self.assertIsNone(result["effective_bpm"]); self.assertFalse(result["alternate_bpm_candidates"])

    def test_crossfade_math_and_command_filters(self):
        result=generate_strategies([candidate("a",20),candidate("b",22)],PROFILE,direction(),STORY,MusicConfig())
        strategy=result["multi_track_candidates"][0]
        gross=sum(s["source_end_seconds"]-s["source_start_seconds"] for s in strategy["segments"])
        overlap=sum(t["duration_seconds"] for t in strategy["transitions"])
        self.assertAlmostEqual(gross-overlap,strategy["timeline_duration_seconds"],places=3)
        command=[str(x) for x in build_assembly_command("ffmpeg",strategy,Path("out.m4a"))]
        filters=command[command.index("-filter_complex")+1]
        self.assertIn("atrim=start=",filters); self.assertIn("acrossfade=d=",filters); self.assertIn("asetpts=PTS-STARTPTS",filters)

    def test_deterministic_generation_and_complexity_rule(self):
        tracks=[candidate("a",60,95),candidate("b",22,65),candidate("c",22,65)]
        first=generate_strategies(copy.deepcopy(tracks),PROFILE,direction(),STORY,MusicConfig())
        second=generate_strategies(copy.deepcopy(tracks),PROFILE,direction(),STORY,MusicConfig())
        self.assertEqual(first,second); self.assertEqual(first["winner"]["strategy_type"],"single_track")


if __name__ == "__main__": unittest.main()
