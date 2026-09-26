import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from focusos_api.main import app
from focusos_api.profiles import ProfileInput


class ProfileValidationTests(unittest.TestCase):
    def test_valid_preferences_keep_iso_weekdays_and_minutes(self):
        profile = ProfileInput(
            timezone="Asia/Jakarta",
            working_hours={
                "days": [5, 1, 2, 3, 4],
                "start_minute": 540,
                "end_minute": 1020,
            },
        )
        self.assertEqual(profile.working_hours.days, [1, 2, 3, 4, 5])

    def test_invalid_zone_is_rejected(self):
        with self.assertRaises(ValidationError):
            ProfileInput(
                timezone="Not/A_Zone",
                working_hours={"days": [1], "start_minute": 540, "end_minute": 1020},
            )

    def test_inverted_time_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            ProfileInput(
                timezone="Asia/Jakarta",
                working_hours={"days": [1], "start_minute": 600, "end_minute": 540},
            )

    def test_duplicate_weekdays_are_rejected(self):
        with self.assertRaises(ValidationError):
            ProfileInput(
                timezone="Asia/Jakarta",
                working_hours={"days": [1, 1], "start_minute": 540, "end_minute": 1020},
            )


class ProfileRouteTests(unittest.TestCase):
    def test_anonymous_profile_read_is_rejected(self):
        with TestClient(app) as client:
            response = client.get("/profile")
        self.assertEqual(response.status_code, 401)

    def test_server_controlled_flag_is_not_in_save_contract(self):
        with patch("focusos_api.main.save_profile") as save:
            with TestClient(app) as client:
                response = client.put(
                    "/profile",
                    headers={"Authorization": "Bearer user-token"},
                    json={
                        "timezone": "Asia/Jakarta",
                        "working_hours": {
                            "days": [1, 2, 3, 4, 5],
                            "start_minute": 540,
                            "end_minute": 1020,
                        },
                        "is_allowlisted": True,
                    },
                )
        self.assertEqual(response.status_code, 422)
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
