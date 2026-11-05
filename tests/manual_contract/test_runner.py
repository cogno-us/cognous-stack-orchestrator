"""Unit tests for the O0B-1 manual-contract runner (stdlib unittest only)."""
import hashlib
import json
import math
import unittest
from collections.abc import Mapping

import mock_cases
import runner

FIXTURE = b'{"fixture":"synthetic-1"}\n'
PRODUCER_OUTPUT = b'{"synthetic_producer_output":"v1"}\n' + FIXTURE


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(case_id):
    return runner.run_case(case_id, mock_cases.REGISTRY)


def run_native(call):
    """Run the real runner on one case whose consumer returns whatever `call` returns (expectation: ACCEPTED)."""
    consumer = runner.Consumer(call, "verdict", {"ADMITTED": "ACCEPTED", "REJECTED": "REFUSED"})
    registry = mock_cases.REGISTRY._replace(
        consumers={"c": consumer},
        cases={"x": ("mock_producer", mock_cases.FIXTURE, "c")},
        expectations={"x": "ACCEPTED"})
    result = runner.run_case("x", registry)
    runner.result_json(result)  # a structured, serializable result must always come back
    return result


class RunnerCases(unittest.TestCase):
    def test_expected_acceptance_passes(self):
        r = run("mock_accept_expected_accept")
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["expected_outcome"], "ACCEPTED")
        self.assertEqual(r["observed_outcome"], "ACCEPTED")
        self.assertEqual(r["invocation_status"], "INVOKED")
        self.assertEqual(r["effect_status"], "NOT_ATTEMPTED")
        self.assertEqual(r["fixture_sha256"], sha(FIXTURE))
        expected = sha(PRODUCER_OUTPUT)
        self.assertEqual(r["producer_output_sha256"], expected)
        self.assertEqual(r["consumer_input_sha256"], expected)
        self.assertEqual(r["consumer_reported_input_sha256"], expected)
        # deterministic serialisation
        text = runner.result_json(r)
        self.assertEqual(json.loads(text), r)
        self.assertEqual(text, runner.result_json(run("mock_accept_expected_accept")))

    def test_expected_refusal_passes(self):
        r = run("mock_refuse_expected_refuse")
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["observed_outcome"], "REFUSED")
        self.assertEqual(r["native_response"]["reason"], "synthetic_refusal")

    def test_unexpected_refusal_fails(self):
        r = run("mock_unexpected_refusal")
        self.assertEqual(r["status"], "FAIL")
        self.assertEqual(r["expected_outcome"], "ACCEPTED")
        self.assertEqual(r["observed_outcome"], "REFUSED")

    def test_missing_observable_response_blocked(self):
        r = run("mock_no_observable_response")
        self.assertEqual(r["status"], "BLOCKED")
        self.assertEqual(r["observed_outcome"], "UNKNOWN")
        self.assertNotEqual(r["observed_outcome"], "ACCEPTED")
        self.assertIs(r["native_response"]["ack"], True)
        self.assertIsNone(r["consumer_reported_input_sha256"])

    def test_non_allowlisted_case_is_refused_without_invoking_anything(self):
        calls = []

        def counting(consumer):
            def call(data):
                calls.append(data)
                return consumer.call(data)
            return consumer._replace(call=call)

        consumers = {k: counting(v) for k, v in mock_cases.REGISTRY.consumers.items()}
        registry = mock_cases.REGISTRY._replace(consumers=consumers)
        for bad in ("no_such_case", "mock_accept_expected_accept; rm -rf /"):
            with self.assertRaises(KeyError):
                runner.run_case(bad, registry)
        self.assertEqual(len(calls), 0)

    def test_untrustworthy_verdict_cannot_yield_acceptance_from_different_evidence(self):
        class Liar(Mapping):  # .get() claims ADMITTED, but the mapping's own content has no verdict
            def get(self, key, default=None):
                return "ADMITTED" if key == "verdict" else default
            def __getitem__(self, key):
                return {"x": 1}[key]
            def __iter__(self):
                return iter({"x": 1})
            def __len__(self):
                return 1

        class Slippery(str):  # equals and hashes like "ADMITTED" but is not the recorded value
            def __eq__(self, other):
                return True
            __hash__ = lambda self: hash("ADMITTED")

        for name, native in (("mapping subclass", Liar()), ("str subclass verdict", {"verdict": Slippery("zzz")})):
            with self.subTest(name):
                r = run_native(lambda data, native=native: native)
                self.assertEqual((r["status"], r["observed_outcome"]), ("BLOCKED", "UNKNOWN"))
                recorded_verdict = (r["native_response"] or {}).get("verdict")
                self.assertNotEqual(str(recorded_verdict), "ADMITTED")  # nothing recorded justifies ACCEPTED

    def test_non_json_native_response_is_blocked_without_crash(self):
        cases = (("bytes value", {"verdict": "ADMITTED", "blob": b"a"}), ("set value", {"verdict": "ADMITTED", "s": {1}}),
                 ("NaN value", {"verdict": "ADMITTED", "n": math.nan}), ("mixed key types", {1: 2, "verdict": "ADMITTED"}))
        for name, native in cases:
            with self.subTest(name):
                r = run_native(lambda data, native=native: native)
                self.assertEqual((r["status"], r["observed_outcome"]), ("BLOCKED", "UNKNOWN"))
                self.assertEqual(r["invocation_status"], "INVOKED")
                self.assertIsNone(r["native_response"])
                self.assertIn("not JSON-serializable", r["reason"])

    def test_received_hash_mismatch_is_blocked_as_inconsistent_evidence(self):
        wrong = sha(b"some other bytes")
        r = run_native(lambda data: {"verdict": "ADMITTED", "received_sha256": wrong})
        self.assertEqual((r["status"], r["observed_outcome"]), ("BLOCKED", "UNKNOWN"))
        self.assertEqual(r["consumer_input_sha256"], sha(PRODUCER_OUTPUT))
        self.assertEqual(r["consumer_reported_input_sha256"], wrong)  # the inconsistent claim is preserved, not corrected
        self.assertIn("evidence inconsistent", r["reason"])


if __name__ == "__main__":
    unittest.main()
