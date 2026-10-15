"""Small offline tests for the demo wrapper."""
import unittest
from main import analyze_sentiment


class SentimentDemoTests(unittest.TestCase):
    def test_returns_label_and_float_score(self):
        def fake_classifier(text):
            self.assertEqual(text, "This is great!")
            return [{"label": "POSITIVE", "score": 0.999}]

        result = analyze_sentiment("  This is great!  ", classifier=fake_classifier)
        self.assertEqual(result["label"], "POSITIVE")
        self.assertIsInstance(result["score"], float)

    def test_rejects_empty_input(self):
        with self.assertRaises(ValueError):
            analyze_sentiment("   ", classifier=lambda _: [])

if __name__ == "__main__":
    unittest.main()
