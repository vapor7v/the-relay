"""Unit tests for results.csv and report.md validation script (Part 11)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "relay")))

from validate_results import validate_results_data, REQUIRED_COLUMNS, validate_file


class TestResultsValidator(unittest.TestCase):

    def _sample_valid_row(self, req_id: str = "req-001", scenario: str = "steady") -> dict:
        return {
            "request_id": req_id,
            "scenario": scenario,
            "source": "stand-in",
            "start_time": "1731542400.123",
            "first_token_ms": "120.5",
            "total_ms": "350.2",
            "status": "ok",
            "retries": "0",
            "tokens_in": "150",
            "tokens_out": "45",
            "retrieval_setting": "small-5-no",
            "answer_grade": "correct",
        }

    def test_valid_fixture_passes(self):
        rows = [self._sample_valid_row("req-1"), self._sample_valid_row("req-2")]
        errors = validate_results_data(rows, REQUIRED_COLUMNS, check_manifest_counts=False)
        self.assertEqual(errors, [])

    def test_rule1_missing_column(self):
        rows = [self._sample_valid_row("req-1")]
        cols = [c for c in REQUIRED_COLUMNS if c != "tokens_out"]
        errors = validate_results_data(rows, cols, check_manifest_counts=False)
        self.assertTrue(any("Rule 1 Failure: Invalid CSV header schema" in e for e in errors))

    def test_rule2_duplicate_request_id(self):
        rows = [self._sample_valid_row("dup-id"), self._sample_valid_row("dup-id")]
        errors = validate_results_data(rows, REQUIRED_COLUMNS, check_manifest_counts=False)
        self.assertTrue(any("Rule 2 Failure: Duplicated request IDs" in e for e in errors))

    def test_rule3_invalid_status_grade_source(self):
        bad_row = self._sample_valid_row("bad-1")
        bad_row["status"] = "bogus_status"
        bad_row["answer_grade"] = "semi-correct"
        bad_row["source"] = "magic-provider"
        errors = validate_results_data([bad_row], REQUIRED_COLUMNS, check_manifest_counts=False)
        self.assertTrue(any("Rule 3 Failure" in e for e in errors))
        self.assertTrue(any("Rule 4 Failure" in e for e in errors))
        self.assertTrue(any("Rule 3/11 Failure" in e for e in errors))

    def test_rule5_negative_tokens(self):
        bad_row = self._sample_valid_row("neg-tok")
        bad_row["tokens_in"] = "-10"
        errors = validate_results_data([bad_row], REQUIRED_COLUMNS, check_manifest_counts=False)
        self.assertTrue(any("Rule 5 Failure" in e for e in errors))

    def test_rule9_first_token_exceeds_total(self):
        bad_row = self._sample_valid_row("impossible-ttft")
        bad_row["first_token_ms"] = "500.0"
        bad_row["total_ms"] = "200.0"  # Impossible!
        errors = validate_results_data([bad_row], REQUIRED_COLUMNS, check_manifest_counts=False)
        self.assertTrue(any("Rule 9 Failure" in e for e in errors))

    def test_rule14_credential_leak_in_results(self):
        leaky_row = self._sample_valid_row("leak-req")
        # Construct synthetic credential test token dynamically to avoid triggering static secret scanners
        prefix = "gsk_"
        dummy_secret = prefix + "dummy" * 8
        leaky_row["request_id"] = f"req_{dummy_secret}"
        errors = validate_results_data([leaky_row], REQUIRED_COLUMNS, check_manifest_counts=False)
        self.assertTrue(any("Rule 14 Failure: Live API credentials detected in results.csv" in e for e in errors))

    def test_rule14_credential_leak_in_report(self):
        rows = [self._sample_valid_row("req-1")]
        prefix = "gsk_"
        dummy_secret = prefix + "secret" * 8
        report_with_key = f"Groq key was {dummy_secret} during testing."
        errors = validate_results_data(rows, REQUIRED_COLUMNS, check_manifest_counts=False, report_text=report_with_key)
        self.assertTrue(any("Rule 14 Failure: Live API credentials detected in report.md" in e for e in errors))

    def test_official_dataset_and_report_pass_all_14_rules(self):
        success = validate_file()
        self.assertTrue(success, "Official validation failed.")


if __name__ == "__main__":
    unittest.main()
