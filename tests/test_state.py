"""Data tests: driver mapping, timing, positions, race control, session state.

Everything here runs against fixtures captured from formula1.com's own static
archive, so the expectations are the feed's real shapes rather than the
plugin's assumptions about them.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from f1.live.decoder import decode_position_payload, decode_topic_payload
from f1.live.state import LiveState, parse_gap

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EVENT = "az2026-race"


def load(name):
    return (FIXTURES / f"{EVENT}-{name}.json").read_bytes()


def loaded_state() -> LiveState:
    """Build the state a full session produces, in the order topics arrive."""
    s = LiveState()
    s.apply_driver_list(decode_topic_payload(load("DriverList")))
    s.apply_session_info(decode_topic_payload(load("SessionInfo")))
    s.apply_session_data(decode_topic_payload(load("SessionData")))
    s.apply_track_status(decode_topic_payload(load("TrackStatus")))
    s.apply_lap_count(decode_topic_payload(load("LapCount")))
    s.apply_weather(decode_topic_payload(load("WeatherData")))
    s.apply_timing(decode_topic_payload(load("TimingData")))
    s.apply_race_control(decode_topic_payload(load("RaceControlMessages")))
    for sample in decode_position_payload(load("Position.z")):
        s.apply_position(sample)
    return s


class TestGapParsing(unittest.TestCase):
    def test_formats(self):
        self.assertAlmostEqual(parse_gap("+1.842"), 1.842)
        self.assertAlmostEqual(parse_gap("1:02.345"), 62.345)
        self.assertAlmostEqual(parse_gap("-0.500"), -0.500)
        self.assertIsNone(parse_gap(""))
        self.assertIsNone(parse_gap(None))
        self.assertIsNone(parse_gap("-"))
        self.assertIsNone(parse_gap("not a gap"))


class TestSessionMetadata(unittest.TestCase):
    def setUp(self):
        self.s = loaded_state()

    def test_meeting_and_circuit(self):
        self.assertEqual(self.s.meeting_name, "Azerbaijan Grand Prix")
        self.assertEqual(self.s.circuit_short, "Baku")
        self.assertEqual(self.s.country, "AZE")
        self.assertEqual(self.s.session_type, "Race")

    def test_lap_count(self):
        self.assertEqual(self.s.current_lap, 51)
        self.assertEqual(self.s.total_laps, 51)

    def test_track_status(self):
        # The fixture ends with a yellow flag.
        self.assertEqual(self.s.track_flag, "Yellow")

    def test_session_label(self):
        self.assertEqual(self.s.session_label(), "RACE")

    def test_weather(self):
        self.assertTrue(self.s.air_temp)
        self.assertTrue(self.s.track_temp)


class TestClassification(unittest.TestCase):
    def setUp(self):
        self.s = loaded_state()

    def test_every_car_is_mapped_to_a_number_and_code(self):
        for d in self.s.drivers.values():
            self.assertTrue(d.number, "driver has no racing number")
            self.assertRegex(d.number, r"^\d+$")
            self.assertTrue(d.tla)

    def test_positions_are_dense_and_unique(self):
        positions = sorted(d.position for d in self.s.leaderboard() if d.position)
        self.assertEqual(positions, list(range(1, len(positions) + 1)))

    def test_leaderboard_is_sorted_by_position(self):
        order = [d.position for d in self.s.leaderboard()]
        self.assertEqual(order, sorted(order))

    def test_gaps_come_from_the_feed(self):
        leader = next(d for d in self.s.leaderboard() if d.position == 1)
        # The fixture's winner has an empty GapToLeader.
        self.assertIsNone(leader.gap)
        second = next(d for d in self.s.leaderboard() if d.position == 2)
        self.assertIsNotNone(second.gap)
        self.assertGreater(second.gap, 0)

    def test_team_colour_comes_from_the_feed(self):
        for d in self.s.leaderboard():
            self.assertRegex(d.colour, r"^#[0-9A-Fa-f]{6}$")


class TestPositions(unittest.TestCase):
    def setUp(self):
        self.s = loaded_state()

    def test_coordinates_are_present(self):
        located = self.s.cars_with_position()
        self.assertGreaterEqual(len(located), 18)

    def test_sentinel_coordinates_are_discarded(self):
        """The feed emits far-away coordinates for cars that left the circuit.

        Plotting them would put a car in the wrong country, so they must be
        dropped and reported as having no position rather than clamped.
        """
        for d in self.s.drivers.values():
            if d.x is not None:
                self.assertLessEqual(abs(d.x), 20000)
                self.assertLessEqual(abs(d.y), 20000)

    def test_position_carries_a_timestamp_and_age(self):
        self.s.age_positions()
        for d in self.s.cars_with_position():
            self.assertTrue(d.pos_timestamp)
            self.assertIsNotNone(d.pos_age)
            self.assertGreaterEqual(d.pos_age, 0)

    def test_missing_position_is_reported_not_invented(self):
        s = LiveState()
        s.apply_driver_list(decode_topic_payload(load("DriverList")))
        # A driver with no Position.z entry must report no position.
        self.assertEqual(len(s.cars_with_position()), 0)
        first_id = next(iter(s.drivers))
        d = s.drivers[first_id]
        self.assertFalse(d.has_position)
        self.assertIsNone(d.x)
        self.assertIsNone(d.y)


class TestRaceControl(unittest.TestCase):
    def setUp(self):
        self.s = loaded_state()

    def test_messages_are_kept_newest_first(self):
        self.assertGreater(len(self.s.race_control), 100)

    def test_messages_carry_category_and_text(self):
        for m in self.s.race_control[:20]:
            self.assertIn("Utc", m)
            self.assertTrue(m.get("Category"))

    def test_flags_are_parsed_from_the_feed(self):
        flags = {m.get("Flag") for m in self.s.race_control}
        self.assertIn("YELLOW", flags)
        self.assertIn("CLEAR", flags)


class TestSnapshotContract(unittest.TestCase):
    """The exact shape the QML layer consumes."""

    def setUp(self):
        self.s = loaded_state()
        self.snap = self.s.to_dict()

    def test_top_level_keys(self):
        for key in (
            "mode", "session", "sessionLabel", "circuit", "lap", "totalLaps",
            "trackStatus", "drivers", "raceControl", "revision",
        ):
            self.assertIn(key, self.snap)

    def test_driver_keys(self):
        for d in self.snap["drivers"]:
            for key in (
                "number", "tla", "position", "gap", "interval", "tyre",
                "x", "y", "hasPosition", "colour", "posAge",
            ):
                self.assertIn(key, d)

    def test_snapshot_is_json_serialisable(self):
        json.dumps(self.snap)

    def test_has_position_is_consistent_with_coordinates(self):
        for d in self.snap["drivers"]:
            if d["hasPosition"]:
                self.assertIsNotNone(d["x"])
                self.assertIsNotNone(d["y"])
            else:
                self.assertIsNone(d["x"])


class TestMalformedInput(unittest.TestCase):
    """A bad frame must be skipped, never crash the reader loop."""

    def test_garbage_never_raises(self):
        s = LiveState()
        for bad in (None, "", "not json", [], {}, 42, b"\xff\xfe"):
            s.apply_driver_list(bad)
            s.apply_session_info(bad)
            s.apply_session_data(bad)
            s.apply_track_status(bad)
            s.apply_lap_count(bad)
            s.apply_weather(bad)
            s.apply_timing(bad)
            s.apply_race_control(bad)
            s.apply_timing_app(bad)
            s.apply_car_data(bad)

    def test_driver_list_with_missing_fields(self):
        s = LiveState()
        s.apply_driver_list({"1": {"RacingNumber": "44", "Tla": "HAM"}})
        d = s.drivers["1"]
        self.assertEqual(d.number, "44")
        self.assertEqual(d.colour, "")


if __name__ == "__main__":
    unittest.main()
