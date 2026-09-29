"""Integration tests against the real public endpoints.

These are skipped unless F1_LIVE_TESTS=1, because they need the network and
they touch a third-party service. They are the check that the protocol has not
moved underneath us, so they are worth running before a release even though
they are not part of a normal test run.

    F1_LIVE_TESTS=1 python3 -m unittest tests.test_live
"""

from __future__ import annotations

import os
import time
import unittest

from f1.live.decoder import decode_topic_payload
from f1.live.signalr import SignalRClient
from f1.live.state import LiveState

RUN_LIVE = os.environ.get("F1_LIVE_TESTS") == "1"


@unittest.skipUnless(RUN_LIVE, "set F1_LIVE_TESTS=1 to run live network tests")
class TestLiveEndpoint(unittest.TestCase):
    def test_connect_handshake_and_subscribe(self):
        client = SignalRClient()
        client.connect()
        try:
            self.assertIsNotNone(client.ws)
            self.assertFalse(client.ws.closed)
            client.subscribe(["DriverList", "SessionInfo", "LapCount"])
            self.assertIn("DriverList", client.subscribed)
        finally:
            client.close()

    def test_reconnect_after_an_explicit_close(self):
        first = SignalRClient()
        first.connect()
        first.close()
        second = SignalRClient()
        second.connect()
        try:
            self.assertFalse(second.ws.closed)
        finally:
            second.close()

    def test_jolpica_serves_a_calendar_and_standings(self):
        from f1.jolpica import client as jolpica

        races = jolpica.races()
        self.assertTrue(races, "no races in the calendar")
        self.assertTrue(all(r.get("date") for r in races))
        drivers = jolpica.driver_standings()
        self.assertTrue(drivers)
        self.assertEqual(drivers[0]["position"], 1)


@unittest.skipUnless(RUN_LIVE, "set F1_LIVE_TESTS=1 to run live network tests")
class TestLiveSession(unittest.TestCase):
    """Only meaningful while a session is actually running."""

    def test_topics_decode_during_a_session(self):
        client = SignalRClient()
        client.connect()
        client.subscribe(["DriverList", "SessionInfo", "LapCount", "TimingData", "Position.z"])
        state = LiveState()
        seen = {}
        deadline = time.time() + 25
        try:
            for topic, payload in client.messages():
                seen[topic] = payload
                if topic == "DriverList":
                    state.apply_driver_list(decode_topic_payload(payload))
                elif topic == "SessionInfo":
                    state.apply_session_info(decode_topic_payload(payload))
                elif topic == "LapCount":
                    state.apply_lap_count(decode_topic_payload(payload))
                if time.time() > deadline:
                    break
        finally:
            client.close()

        if not seen:
            self.skipTest("no session in progress; the feed is idle")
        for topic in seen:
            self.assertIsNotNone(decode_topic_payload(seen[topic]), f"{topic} failed to decode")


if __name__ == "__main__":
    unittest.main()
