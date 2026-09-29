"""Track tests: coordinate handling, outline reconstruction, and the cache.

The outline pipeline's contract is that it either produces a plausible lap or
produces nothing. A half-traced circuit drawn as if it were complete is worse
than an honest empty state, so the rejection paths are tested as carefully as
the happy path.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from f1 import cache, curve
from f1.live.state import LiveState


def sample_ring(n=400, radius=700.0, cx=2000.0, cy=1000.0, jitter=0.0, seed=7):
    """A closed loop sampled the way the feed samples a real circuit."""
    import random

    rnd = random.Random(seed)
    pts = []
    for i in range(n):
        t = (i / n) * math.pi * 2
        r = radius * (1.0 + 0.12 * math.sin(3 * t) + 0.05 * math.cos(5 * t))
        jx = rnd.uniform(-jitter, jitter)
        jy = rnd.uniform(-jitter, jitter)
        pts.append((cx + r * math.cos(t) + jx, cy + 0.6 * r * math.sin(t) + jy))
    return pts


class TestDensityFilter(unittest.TestCase):
    def test_near_duplicates_merge_into_a_centroid(self):
        pts = [(100.0, 100.0), (100.4, 99.6), (99.8, 100.3)]
        out = curve.density_filter(pts, cell=6.0)
        self.assertEqual(len(out), 1)
        # The result is an average of observations, not a new location.
        self.assertAlmostEqual(out[0][0], sum(p[0] for p in pts) / 3, places=6)

    def test_empty_input(self):
        self.assertEqual(curve.density_filter([]), [])


class TestLargestComponent(unittest.TestCase):
    def test_a_distant_blob_is_discarded(self):
        ring = sample_ring(120)
        stray = [(9000.0, 9000.0), (9100.0, 9050.0), (9050.0, 9100.0)]
        kept = curve.largest_component(ring + stray, radius=120.0)
        self.assertLess(len(kept), len(ring) + len(stray))
        for x, y in kept:
            self.assertLess(x, 5000.0)

    def test_tiny_input_is_passed_through(self):
        self.assertEqual(len(curve.largest_component([(0, 0), (1, 1)])), 2)


class TestOrdering(unittest.TestCase):
    def test_tour_follows_the_ring_rather_than_crossing_it(self):
        pts = sample_ring(160)
        tour = curve.two_opt(curve.greedy_tour(pts), pts)
        path = [pts[i] for i in tour] + [pts[tour[0]]]
        length = sum(
            math.dist(path[i], path[i + 1]) for i in range(len(path) - 1)
        )
        # The circumference of the sampled ring (a few km for the default
        # radius), not something wildly longer or shorter. A tangled tour would
        # either cut straight across the infield or double back on itself.
        self.assertGreater(length, 2000.0)
        self.assertLess(length, 30000.0)

    def test_tour_visits_every_point_exactly_once(self):
        pts = sample_ring(90)
        tour = curve.two_opt(curve.greedy_tour(pts), pts)
        self.assertEqual(sorted(tour), list(range(len(pts))))


class TestOutlineReconstruction(unittest.TestCase):
    def test_clean_ring_produces_a_closed_outline(self):
        out = curve.build_outline(sample_ring(400, radius=700.0))
        self.assertIsNotNone(out)
        self.assertGreaterEqual(len(out), curve.MIN_POINTS)
        # Closed: the last point returns to the first.
        self.assertLess(math.dist(out[0], out[-1]), 30.0)

    def test_outlier_samples_are_absorbed(self):
        # What the feed does when a car leaves the circuit: a far-away sentinel.
        pts = sample_ring(400, radius=700.0) + [(20000.0, 20000.0)] * 6
        out = curve.build_outline(pts)
        self.assertIsNotNone(out)
        xs = [p[0] for p in out]
        self.assertLess(max(xs), 3000.0)

    def test_too_few_samples_is_refused(self):
        self.assertIsNone(curve.build_outline([(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]))

    def test_empty_input_is_refused(self):
        self.assertIsNone(curve.build_outline([]))

    def test_a_blob_with_no_lap_shape_is_refused(self):
        # A tight clump has no lap length, so it must not become an outline.
        blob = [(1000.0 + (i % 3), 1000.0 + (i % 4)) for i in range(300)]
        self.assertIsNone(curve.build_outline(blob))

    def test_a_giant_outlier_loop_is_refused(self):
        # Length bounds are the guard against a tangled tour being mistaken for
        # a circuit. The longest current lap is Austin at 5.513 km.
        pts = sample_ring(300, radius=100000.0)
        self.assertIsNone(curve.build_outline(pts))

    def test_outline_survives_being_stored_and_reloaded(self):
        out = curve.build_outline(sample_ring(400, radius=700.0))
        self.assertIsNotNone(out)
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["XDG_CACHE_HOME"] = tmp
            try:
                cache.ensure_dirs()
                payload = {
                    "key": "Test",
                    "points": [[round(x, 2), round(y, 2)] for x, y in out],
                    "length": round(curve.path_length(out), 1),
                    "samples": 400,
                    "learnedAt": 1,
                }
                self.assertTrue(cache.save_outline("Test", payload))
                back = cache.load_outline("Test")
                self.assertIsNotNone(back)
                self.assertEqual(back["key"], "Test")
                # Same number of vertices and the same shape after a round trip.
                self.assertEqual(len(back["points"]), len(payload["points"]))
                self.assertAlmostEqual(back["length"], payload["length"], places=1)
            finally:
                os.environ.pop("XDG_CACHE_HOME", None)


class TestMapProjection(unittest.TestCase):
    """The arithmetic TrackMap.qml uses, mirrored so it can be asserted.

    The whole point of deriving geometry from the feed is that track and cars
    share one frame, so the projection must be the identity-plus-scale, with no
    rotation, no offset per marker and no per-marker correction.
    """

    def _project(self, geom, pt, size):
        return (
            size / 2 + (pt[0] - geom["cx"]) / geom["side"] * size,
            size / 2 - (pt[1] - geom["cy"]) / geom["side"] * size,
        )

    def test_center_maps_to_center(self):
        geom = {"side": 100.0, "cx": 500.0, "cy": 250.0}
        x, y = self._project(geom, (500.0, 250.0), 400.0)
        self.assertAlmostEqual(x, 200.0)
        self.assertAlmostEqual(y, 200.0)

    def test_y_axis_is_inverted_for_the_screen(self):
        geom = {"side": 100.0, "cx": 0.0, "cy": 0.0}
        _x, high = self._project(geom, (0.0, 50.0), 400.0)
        _x, low = self._project(geom, (0.0, -50.0), 400.0)
        self.assertLess(high, low)

    def test_everything_stays_inside_the_box(self):
        pts = sample_ring(200)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        side = max(max(xs) - min(xs), max(ys) - min(ys))
        geom = {"side": side, "cx": (min(xs) + max(xs)) / 2, "cy": (min(ys) + max(ys)) / 2}
        for p in pts:
            x, y = self._project(geom, p, 360.0)
            self.assertGreaterEqual(x, -1.0)
            self.assertLessEqual(x, 361.0)
            self.assertGreaterEqual(y, -1.0)
            self.assertLessEqual(y, 361.0)

    def test_uniform_scale_preserves_relative_spacing(self):
        """No axis is stretched, so two cars keep their distance ratio."""
        geom = {"side": 100.0, "cx": 0.0, "cy": 0.0}
        a = self._project(geom, (0.0, 0.0), 200.0)
        b = self._project(geom, (50.0, 0.0), 200.0)
        c = self._project(geom, (0.0, 50.0), 200.0)
        self.assertAlmostEqual(math.dist(a, b), math.dist(a, c), places=6)


class TestStalePositions(unittest.TestCase):
    def test_age_is_reported_so_the_ui_can_dim_a_silent_car(self):
        s = LiveState()
        s.drivers["1"] = s._driver("1")
        s.drivers["1"].x, s.drivers["1"].y = 100, 200
        s.drivers["1"].pos_timestamp = "2020-01-01T00:00:00Z"
        s.age_positions()
        self.assertGreater(s.drivers["1"].pos_age, 0)
        self.assertTrue(s.drivers["1"].has_position)


class TestCache(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("XDG_CACHE_HOME")
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["XDG_CACHE_HOME"] = self.tmp.name
        cache.ensure_dirs()

    def tearDown(self):
        if self._old is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = self._old
        self.tmp.cleanup()

    def test_state_round_trip(self):
        snap = {"mode": "live", "lap": 12, "drivers": [{"number": "1", "x": 5, "y": 6, "hasPosition": True}]}
        self.assertTrue(cache.save_state(snap))
        back = cache.load_state()
        self.assertEqual(back["lap"], 12)

    def test_positions_file_only_carries_located_cars(self):
        snap = {
            "revision": 3,
            "circuit": "Baku",
            "drivers": [
                {"id": "1", "number": "1", "tla": "NOR", "colour": "#fff", "x": 10, "y": 20, "posAge": 0.2, "position": 1, "hasPosition": True},
                {"id": "2", "number": "2", "tla": "VER", "colour": "#000", "x": None, "y": None, "posAge": None, "position": 2, "hasPosition": False},
            ],
        }
        self.assertTrue(cache.save_positions(snap))
        back = cache.load_positions()
        self.assertEqual(len(back["drivers"]), 1)
        self.assertEqual(back["drivers"][0][1], "1")

    def test_corrupt_file_reads_as_absent(self):
        cache.state_path().write_text("{ this is not json")
        self.assertIsNone(cache.load_state())

    def test_missing_file_reads_as_absent(self):
        self.assertIsNone(cache.load_outline("nope"))

    def test_stale_state_is_rejected_by_age(self):
        cache.save_state({"lap": 1})
        self.assertIsNone(cache.load_state(max_age=0))
        self.assertIsNotNone(cache.load_state())

    def test_written_state_is_valid_json(self):
        cache.save_state({"lap": 7, "drivers": []})
        json.loads(cache.state_path().read_text())


if __name__ == "__main__":
    unittest.main()
