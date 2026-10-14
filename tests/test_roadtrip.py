"""Fast checks for the generator's logic (no network, no rendering).

    python3 -m unittest discover tests
"""

import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from roadtrip import describe, route as R, scenes, timeline, voice

ROUTE = Path(__file__).resolve().parent.parent / "routes" / "denver-to-ouray.toml"


def built_route():
    return R.load_route(ROUTE).build(terrain=None)  # no terrain: elevations interpolate between stops


class RouteTests(unittest.TestCase):
    def test_parse_minutes(self):
        self.assertEqual(R.parse_minutes("1 hr 15 min"), 75)
        self.assertEqual(R.parse_minutes("50 min"), 50)
        self.assertEqual(R.parse_minutes("2h"), 120)
        with self.assertRaises(ValueError):
            R.parse_minutes("soon")

    def test_spline_passes_through_control_points(self):
        pts = np.array([[0.0, 0.0], [1.0, 2.0], [3.0, 1.0], [4.0, 4.0]])
        xs, ys, idx = R.catmull_rom(pts, samples=10)
        for k, i in enumerate(idx):
            self.assertAlmostEqual(xs[i], pts[k, 0])
            self.assertAlmostEqual(ys[i], pts[k, 1])

    def test_legs_add_up_to_road_miles(self):
        route = built_route()
        for prev, stop in zip(route.stops, route.stops[1:]):
            self.assertAlmostEqual(stop.mile - prev.mile, stop.miles, places=6)
        self.assertAlmostEqual(route.total_miles, sum(s.miles for s in route.stops[1:]))
        self.assertTrue(np.all(np.diff(route.mi) >= 0))

    def test_readouts_match_stop_elevations(self):
        route = built_route()
        for stop in route.stops:
            self.assertAlmostEqual(route.elevation_at(stop.mile), stop.elevation_ft, places=3)
        high, name = route.high_point()
        self.assertEqual((round(high), name), (11312, "Monarch Pass"))

    def test_returning_to_the_start_keeps_stop_order(self):
        # A loop (Durango -> ... -> Durango) must not confuse the last stop with the first.
        text = ROUTE.read_text()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loop.toml"
            path.write_text(text + '\n[[stops]]\nname = "Denver again"\nlat = 39.7392\nlon = -104.9903\nmiles = 300\n')
            route = R.load_route(path).build(terrain=None)
        self.assertGreater(route.stops[-1].mile, route.stops[-2].mile)

    def test_unknown_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.toml"
            path.write_text('[[stops]]\nname="A"\nlat=1\nlon=1\nmils=3\n[[stops]]\nname="B"\nlat=2\nlon=2\n')
            with self.assertRaisesRegex(ValueError, "mils"):
                R.load_route(path)


class TimelineTests(unittest.TestCase):
    def test_segments_cover_every_stop_and_leg(self):
        route = built_route()
        ids = [s.id for s in timeline.build_segments(route)]
        n = len(route.stops)
        for i in range(n):
            self.assertIn(f"stop-{i}", ids)
        for i in range(1, n):
            self.assertLess(ids.index(f"drive-{i}"), ids.index(f"stop-{i}"))
        self.assertEqual(ids[-3:], ["finale", "planner", "end"])

    def test_spoken_text(self):
        self.assertEqual(timeline.spoken("11,312 ft · mile 160 & up"), "11,312 feet, mile 160 and up")

    def test_youtube_chapters_rules(self):
        route = built_route()
        segs, total, _ = timeline.layout(route, use_voiceover=False)
        marks = describe.chapters(route, segs, offset=2.6)
        self.assertEqual(marks[0][0], 0.0)
        self.assertGreaterEqual(len(marks), 3)
        for (a, _), (b, _) in zip(marks, marks[1:]):
            self.assertGreaterEqual(b - a, 10)
        self.assertGreaterEqual(2.6 + total - marks[-1][0], 10)

    def test_drive_progress_is_smooth_and_monotonic(self):
        p = [scenes.drive_progress(t) for t in np.linspace(0, 1, 501)]
        self.assertAlmostEqual(p[0], 0)
        self.assertAlmostEqual(p[-1], 1)
        self.assertTrue(all(b >= a for a, b in zip(p, p[1:])))
        self.assertLess(max(np.diff(p)), 0.004)


class VoiceTests(unittest.TestCase):
    def test_long_pauses_are_capped(self):
        sr = 48000
        tone = 0.5 * np.sin(2 * np.pi * 220 * np.arange(sr) / sr)
        audio = np.concatenate([tone, np.zeros(2 * sr), tone])  # 1 s talk, 2 s pause, 1 s talk
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "line.wav"
            with wave.open(str(src), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes((audio * 32767).astype(np.int16).tobytes())
            old_cache = voice.CACHE
            voice.CACHE = Path(tmp) / "cache"
            try:
                out = voice.tighten(src, max_pause=0.4)
            finally:
                voice.CACHE = old_cache
            dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                        "csv=p=0", str(out)], capture_output=True, text=True).stdout)
        self.assertAlmostEqual(dur, 2.0 + 0.4, delta=0.06)  # two 1 s lines and one capped pause


if __name__ == "__main__":
    unittest.main()
