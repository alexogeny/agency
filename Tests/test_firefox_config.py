import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICIES = ROOT / "firefox/policies.json"


class FirefoxPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policies = json.loads(POLICIES.read_text())["policies"]

    def test_strict_tracking_protection_uses_current_policy(self):
        self.assertEqual(
            self.policies["EnableTrackingProtection"],
            {
                "Category": "strict",
                "BaselineExceptions": True,
                "ConvenienceExceptions": True,
            },
        )

    def test_local_network_access_is_guarded(self):
        self.assertEqual(
            self.policies["LocalNetworkAccess"],
            {
                "Enabled": True,
                "BlockTrackers": True,
                "EnablePrompting": True,
            },
        )

    def test_remote_suggestion_features_are_disabled(self):
        self.assertEqual(
            self.policies["FirefoxSuggest"],
            {
                "WebSuggestions": False,
                "SponsoredSuggestions": False,
                "ImproveSuggest": False,
            },
        )
        self.assertFalse(self.policies["SearchSuggestEnabled"])
        self.assertFalse(self.policies["VisualSearchEnabled"])
        preferences = self.policies["Preferences"]
        self.assertNotIn("browser.urlbar.quicksuggest.enabled", preferences)
        self.assertNotIn(
            "browser.urlbar.suggest.quicksuggest.nonsponsored", preferences
        )
        self.assertNotIn(
            "browser.urlbar.suggest.quicksuggest.sponsored", preferences
        )

    def test_ai_features_are_blocked(self):
        self.assertEqual(
            self.policies["AIControls"],
            {"Default": {"Value": "blocked", "Locked": True}},
        )

    def test_firefox_labs_messaging_is_hidden(self):
        self.assertFalse(self.policies["UserMessaging"]["FirefoxLabs"])


if __name__ == "__main__":
    unittest.main()
