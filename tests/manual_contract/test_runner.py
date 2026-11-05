"""Unit tests for the O0B-1 manual-contract runner (stdlib unittest only)."""
import hashlib
import json
import unittest

import mock_cases
import runner

FIXTURE = b'{"fixture":"synthetic-1"}\n'
PRODUCER_OUTPUT = b'{"synthetic_producer_output":"v1"}\n' + FIXTURE


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(case_id):
    return runner.run_case(case_id, mock_cases.REGISTRY)


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


if __name__ == "__main__":
    unittest.main()
