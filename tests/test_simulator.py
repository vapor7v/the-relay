"""Unit tests for the calibrated stand-in simulator (Part 3 & 8)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "relay")))

from simulator import SimulatorState, DEFAULT_CALIBRATION, _extract_question_from_prompt, generate_response_text


class TestSimulator(unittest.TestCase):

    def setUp(self):
        self.cal = DEFAULT_CALIBRATION.copy()
        self.cal["rpm_limit"] = 5
        self.cal["tpm_limit"] = 1000
        self.cal["rpd_limit"] = 10
        self.cal["tpd_limit"] = 5000

    def test_seed_determinism(self):
        """Simulators initialized with identical seeds generate identical sequences."""
        sim1 = SimulatorState(self.cal, seed=42)
        sim2 = SimulatorState(self.cal, seed=42)

        ttft_1 = [sim1.sample_ttft() for _ in range(10)]
        ttft_2 = [sim2.sample_ttft() for _ in range(10)]
        self.assertEqual(ttft_1, ttft_2)

        tps_1 = [sim1.sample_tps() for _ in range(10)]
        tps_2 = [sim2.sample_tps() for _ in range(10)]
        self.assertEqual(tps_1, tps_2)

    def test_concurrency_accounting_and_release(self):
        """Concurrency slots increment on admission and decrement cleanly on release."""
        sim = SimulatorState(self.cal, seed=1)
        self.assertEqual(sim.concurrent, 0)

        # 3 admissions
        sim.check_rate_limit(100)
        sim.check_rate_limit(100)
        sim.check_rate_limit(100)
        self.assertEqual(sim.concurrent, 3)

        # Release 2
        sim.release()
        sim.release()
        self.assertEqual(sim.concurrent, 1)

        # Release more than existing (clamped to 0)
        sim.release()
        sim.release()
        self.assertEqual(sim.concurrent, 0)

    def test_rpm_limit_enforcement(self):
        """When RPM limit is hit, check_rate_limit returns a positive retry-after value."""
        sim = SimulatorState(self.cal, seed=1)  # rpm_limit = 5
        for _ in range(5):
            ra = sim.check_rate_limit(50)
            self.assertIsNone(ra)

        # 6th request must trigger rate limit
        ra = sim.check_rate_limit(50)
        self.assertIsNotNone(ra)
        self.assertGreater(ra, 0.0)

    def test_rpd_limit_enforcement(self):
        """When daily limit is hit, check_rate_limit returns a positive retry-after."""
        sim = SimulatorState(self.cal, seed=1)  # rpd_limit = 10
        sim.request_count_day = 10

        ra = sim.check_rate_limit(50)
        self.assertIsNotNone(ra)
        self.assertGreater(ra, 1.0)

    def test_ttft_and_tps_bounds(self):
        """Sampled TTFT and TPS must be strictly positive and obey physical constraints."""
        sim = SimulatorState(self.cal, seed=123)
        for _ in range(100):
            ttft = sim.sample_ttft()
            tps = sim.sample_tps()
            self.assertGreaterEqual(ttft, 50.0)
            self.assertGreaterEqual(tps, 15.0)

    def test_question_extraction_from_prompt(self):
        """Prompt parser extracts the exact question without matching on retrieved context."""
        prompt = (
            "CONTEXT:\nPassage about Moshi simultaneous speech-text dialogue.\n\n"
            "QUESTION: What is the embedding dimension d_model in Transformer?\n\n"
            "ANSWER:"
        )
        extracted = _extract_question_from_prompt(prompt)
        self.assertEqual(extracted, "What is the embedding dimension d_model in Transformer?")
        self.assertNotIn("simultaneous", extracted)

    def test_context_aware_response_generation(self):
        """Simulator generates appropriate responses across all 3 pipeline phases."""
        # 1. Query analysis
        messages = [{"role": "user", "content": "You are a research assistant. Analyze this question:\nQuestion: What is the capital of France?"}]
        resp, toks = generate_response_text(messages)
        self.assertIn('"answerable": false', resp)

        # 2. Answer drafting
        messages = [{"role": "user", "content": "QUESTION: How many attention heads in base model?\n\nANSWER:"}]
        resp, toks = generate_response_text(messages)
        self.assertIn("8 attention heads", resp)
        self.assertIn("[Attention Is All You Need", resp)

        # 3. Citation verification
        messages = [{"role": "user", "content": "You are a citation verifier.\n\nANSWER TO CHECK: Base model uses 8 heads [Attention Is All You Need, p.5]."}]
        resp, toks = generate_response_text(messages)
        self.assertIn('"valid": true', resp)

    def test_scenario_metadata_persistence_and_migration(self):
        """Test writing, updating, and migrating scenario metadata in dictionary format."""
        import tempfile
        import json
        from runner import _update_scenario_metadata

        with tempfile.TemporaryDirectory() as tmpdir:
            meta_path = os.path.join(tmpdir, "scenario_metadata.json")

            # 1. Test writing new scenario
            _update_scenario_metadata({"scenario": "burst", "duration_s": 24.0}, meta_path=meta_path)
            with open(meta_path, "r") as f:
                data = json.load(f)
            self.assertIsInstance(data, dict)
            self.assertIn("burst", data)
            self.assertEqual(data["burst"]["duration_s"], 24.0)

            # 2. Test adding second scenario
            _update_scenario_metadata({"scenario": "steady", "duration_s": 70.0}, meta_path=meta_path)
            with open(meta_path, "r") as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
            self.assertIn("steady", data)

            # 3. Test updating existing scenario
            _update_scenario_metadata({"scenario": "burst", "duration_s": 30.0}, meta_path=meta_path)
            with open(meta_path, "r") as f:
                data = json.load(f)
            self.assertEqual(len(data), 2)
            self.assertEqual(data["burst"]["duration_s"], 30.0)

            # 4. Test legacy list migration
            list_path = os.path.join(tmpdir, "legacy_list.json")
            with open(list_path, "w") as f:
                json.dump([{"scenario": "sc1", "val": 1}, {"scenario": "sc2", "val": 2}], f)
            _update_scenario_metadata({"scenario": "sc3", "val": 3}, meta_path=list_path)
            with open(list_path, "r") as f:
                migrated = json.load(f)
            self.assertIsInstance(migrated, dict)
            self.assertIn("sc1", migrated)
            self.assertIn("sc2", migrated)
            self.assertIn("sc3", migrated)


if __name__ == "__main__":
    unittest.main()
