import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import aurora_alert


class ParseKpRecordTests(unittest.TestCase):
    def test_current_observed_dictionary(self):
        record = {
            "time_tag": "2026-08-09T12:00:00",
            "Kp": 1.33,
            "a_running": 5,
            "station_count": 8,
        }

        self.assertEqual(aurora_alert.parse_kp_record(record), (1.33, "2026-08-09T12:00:00"))

    def test_current_forecast_dictionary(self):
        record = {
            "time_tag": "2026-08-12T00:00:00",
            "kp": 3.67,
            "observed": "predicted",
            "noaa_scale": None,
        }

        self.assertEqual(aurora_alert.parse_kp_record(record), (3.67, "2026-08-12T00:00:00"))

    def test_legacy_row(self):
        self.assertEqual(
            aurora_alert.parse_kp_record(["2026-08-09 12:00:00", "4.33"]),
            (4.33, "2026-08-09 12:00:00"),
        )

    def test_missing_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "time_tag"):
            aurora_alert.parse_kp_record({"station_count": 8})


class NoaaFeedTests(unittest.TestCase):
    @patch("aurora_alert.fetch_json")
    def test_kp_now_uses_latest_dictionary_record(self, fetch_json):
        fetch_json.return_value = [
            {"time_tag": "2026-08-09T09:00:00", "Kp": 2.0},
            {"time_tag": "2026-08-09T12:00:00", "Kp": 3.33},
        ]

        self.assertEqual(aurora_alert.kp_now(), (3.33, "2026-08-09T12:00:00"))

    @patch("aurora_alert.fetch_json")
    def test_forecast_selects_highest_kp_in_window_from_dictionaries(self, fetch_json):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        in_3h = (now + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
        in_6h = (now + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S")
        outside = (now + timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%S")
        fetch_json.return_value = [
            {"time_tag": in_3h, "kp": 4.0, "observed": "predicted"},
            {"time_tag": in_6h, "kp": 6.67, "observed": "predicted"},
            {"time_tag": outside, "kp": 8.0, "observed": "predicted"},
        ]

        kp, time_tag, peak_dt = aurora_alert.kp_forecast_max_next_hours(24)

        self.assertEqual(kp, 6.67)
        self.assertEqual(time_tag, in_6h)
        self.assertEqual(peak_dt, aurora_alert.parse_noaa_time_utc(in_6h))

    @patch("aurora_alert.fetch_json")
    def test_forecast_still_supports_legacy_header_and_rows(self, fetch_json):
        in_3h = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
        fetch_json.return_value = [
            ["time_tag", "kp", "observed", "noaa_scale"],
            [in_3h, "5.33", "predicted", None],
        ]

        kp, time_tag, peak_dt = aurora_alert.kp_forecast_max_next_hours(24)

        self.assertEqual(kp, 5.33)
        self.assertEqual(time_tag, in_3h)
        self.assertIsNotNone(peak_dt)

    @patch("aurora_alert.fetch_json", return_value=[])
    def test_empty_feed_has_clear_error(self, _fetch_json):
        with self.assertRaisesRegex(ValueError, "pustą"):
            aurora_alert.kp_now()


if __name__ == "__main__":
    unittest.main()
