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


ADMIT = {"ADMITTED": "ACCEPTED", "REJECTED": "REFUSED"}


def fanout_registry(consumers, expectations, producer=None):
    """Registry with one fan-out case "x": two consumers (dict order = listed order) fed by one producer."""
    return mock_cases.REGISTRY._replace(
        producers={"mock_producer": producer or mock_cases.mock_producer},
        consumers=consumers,
        fanout_cases={"x": ("mock_producer", b'{"fixture":"synthetic-1"}\n', tuple(consumers))},
        fanout_expectations={"x": expectations})


def verdict_consumer(verdict, log=None):
    def call(data):
        if log is not None:
            log.append(data)
        return {"verdict": verdict, "received_sha256": sha(data)}
    return runner.Consumer(call, "verdict", ADMIT)


def raising_consumer():
    def call(data):
        raise RuntimeError("synthetic failure")
    return runner.Consumer(call, "verdict", ADMIT)


def ack_consumer():
    return runner.Consumer(lambda data: {"ack": True}, "verdict", ADMIT)


class FanoutCases(unittest.TestCase):
    def assert_consumer(self, c, cid, expected, observed, status, invoked=True):
        self.assertEqual((c["consumer_id"], c["expected_outcome"], c["observed_outcome"], c["status"]),
                         (cid, expected, observed, status))
        self.assertEqual(c["invocation_status"], "INVOKED" if invoked else "NOT_INVOKED")
        self.assertEqual(c["consumer_input_sha256"], sha(PRODUCER_OUTPUT) if invoked else None)

    def test_b_accepts_c_refuses_as_expected_is_aggregate_pass(self):
        r = runner.run_fanout(mock_cases.CASE_FANOUT_PASS, mock_cases.REGISTRY)
        self.assertEqual((r["status"], r["effect_status"], r["effect_mode"]),
                         ("PASS", "NOT_ATTEMPTED", "synthetic_non_effecting"))
        self.assertEqual(r["schema"], runner.FANOUT_SCHEMA)
        self.assertEqual(r["fixture_sha256"], sha(FIXTURE))
        self.assertEqual(r["producer_output_sha256"], sha(PRODUCER_OUTPUT))
        self.assertIsNone(r["producer_error"])
        with open(runner.__file__, "rb") as fh:  # source identity: independent hash of the runner that produced this result
            self.assertEqual(r["source_identity"]["runner_sha256"], sha(fh.read()))
        self.assertIn("git_commit", r["source_identity"])
        b, c = r["consumers"]
        self.assert_consumer(b, "mock_consumer_accepts", "ACCEPTED", "ACCEPTED", "PASS")
        self.assert_consumer(c, "mock_consumer_refuses", "REFUSED", "REFUSED", "PASS")
        for x in (b, c):
            self.assertEqual(x["consumer_reported_input_sha256"], sha(PRODUCER_OUTPUT))

    def test_unexpected_refusal_by_c_is_aggregate_fail(self):
        r = runner.run_fanout(mock_cases.CASE_FANOUT_FAIL, mock_cases.REGISTRY)
        self.assertEqual(r["status"], "FAIL")
        b, c = r["consumers"]
        self.assert_consumer(b, "mock_consumer_accepts", "ACCEPTED", "ACCEPTED", "PASS")
        self.assertEqual(b["native_response"]["verdict"], "ADMITTED")
        self.assertEqual(b["consumer_reported_input_sha256"], sha(PRODUCER_OUTPUT))
        self.assert_consumer(c, "mock_consumer_refuses", "ACCEPTED", "REFUSED", "FAIL")
        self.assertEqual(c["native_response"]["reason"], "synthetic_refusal")

    def test_consumer_failure_does_not_suppress_the_other(self):
        def go(b, c, exp_b, exp_c):
            r = runner.run_fanout("x", fanout_registry({"b": b, "c": c}, {"b": exp_b, "c": exp_c}))
            runner.result_json(r)
            return r, r["consumers"][0], r["consumers"][1]

        with self.subTest("(i) B ack-only is BLOCKED, C evidence kept"):
            r, b, c = go(ack_consumer(), verdict_consumer("REJECTED"), "ACCEPTED", "REFUSED")
            self.assert_consumer(b, "b", "ACCEPTED", "UNKNOWN", "BLOCKED")
            self.assert_consumer(c, "c", "REFUSED", "REFUSED", "PASS")
            self.assertEqual(c["consumer_reported_input_sha256"], sha(PRODUCER_OUTPUT))
            self.assertEqual(r["status"], "BLOCKED")
        with self.subTest("(ii) B raises: FAIL/ERROR, C still invoked"):
            r, b, c = go(raising_consumer(), verdict_consumer("ADMITTED"), "ACCEPTED", "ACCEPTED")
            self.assert_consumer(b, "b", "ACCEPTED", "ERROR", "FAIL")
            self.assertEqual(b["consumer_error"]["type"], "RuntimeError")
            self.assert_consumer(c, "c", "ACCEPTED", "ACCEPTED", "PASS")
            self.assertEqual(c["native_response"]["verdict"], "ADMITTED")
            self.assertEqual(r["status"], "FAIL")
        with self.subTest("(iii) C raises: B evidence intact"):
            r, b, c = go(verdict_consumer("ADMITTED"), raising_consumer(), "ACCEPTED", "REFUSED")
            self.assert_consumer(b, "b", "ACCEPTED", "ACCEPTED", "PASS")
            self.assertEqual(b["consumer_reported_input_sha256"], sha(PRODUCER_OUTPUT))
            self.assert_consumer(c, "c", "REFUSED", "ERROR", "FAIL")
            self.assertEqual(c["consumer_error"]["type"], "RuntimeError")
            self.assertEqual(r["status"], "FAIL")
        with self.subTest("(iv) BLOCKED plus FAIL is FAIL"):
            r, b, c = go(ack_consumer(), verdict_consumer("REJECTED"), "ACCEPTED", "ACCEPTED")
            self.assertEqual((b["status"], c["status"]), ("BLOCKED", "FAIL"))
            self.assertEqual(r["status"], "FAIL")
        with self.subTest("(v) producer raises: no consumer invoked"):
            seen = []

            def bad_producer(fixture):
                raise ValueError("synthetic producer failure")

            reg = fanout_registry({"b": verdict_consumer("ADMITTED", seen), "c": verdict_consumer("REJECTED", seen)},
                                  {"b": "ACCEPTED", "c": "REFUSED"}, producer=bad_producer)
            r = runner.run_fanout("x", reg)
            self.assertEqual(seen, [])
            self.assertEqual(r["status"], "BLOCKED")
            self.assertIsNone(r["producer_output_sha256"])
            self.assertEqual(r["producer_error"]["type"], "ValueError")
            for x, cid, exp in zip(r["consumers"], ("b", "c"), ("ACCEPTED", "REFUSED")):
                self.assert_consumer(x, cid, exp, "UNKNOWN", "BLOCKED", invoked=False)
                self.assertIsNone(x["native_response"])
        with self.subTest("(vi) C mutating a nested object B returned cannot alter B's recorded evidence"):
            shared = {"items": [1]}

            def b_call(data):
                return {"verdict": "ADMITTED", "received_sha256": sha(data), "x": shared}

            def c_call(data):
                shared["items"].append(2)
                return {"verdict": "REJECTED", "received_sha256": sha(data)}

            reg = fanout_registry({"b": runner.Consumer(b_call, "verdict", ADMIT), "c": runner.Consumer(c_call, "verdict", ADMIT)},
                                  {"b": "ACCEPTED", "c": "REFUSED"})
            r = runner.run_fanout("x", reg)
            b = r["consumers"][0]
            self.assertEqual(r["status"], "PASS")
            self.assertEqual(b["native_response"]["x"], {"items": [1]})  # as B returned it, not as C later changed it
            recomputed = sha(json.dumps(b["native_response"], sort_keys=True, separators=(",", ":")).encode())
            self.assertEqual(b["native_response_sha256"], recomputed)

    def test_both_consumers_receive_identical_original_bytes(self):
        produced, seen_b, seen_c = [], [], []

        def producer(fixture):
            out = mock_cases.mock_producer(fixture)
            produced.append(out)
            return out

        consumers = {"b": verdict_consumer("ADMITTED", seen_b), "c": verdict_consumer("REJECTED", seen_c)}
        reg = fanout_registry(consumers, {"b": "ACCEPTED", "c": "REFUSED"}, producer=producer)
        for bad in ("no_such_case", "x; rm -rf /"):  # allowlist: refused before anything is called
            with self.assertRaises(KeyError):
                runner.run_fanout(bad, reg)
        self.assertEqual((produced, seen_b, seen_c), ([], [], []))

        r = runner.run_fanout("x", reg)
        self.assertEqual(len(produced), 1)  # producer called exactly once
        self.assertEqual((seen_b, seen_c), ([PRODUCER_OUTPUT], [PRODUCER_OUTPUT]))
        expected = hashlib.sha256(b'{"synthetic_producer_output":"v1"}\n{"fixture":"synthetic-1"}\n').hexdigest()
        self.assertEqual(r["producer_output_sha256"], expected)
        self.assertEqual([c["consumer_input_sha256"] for c in r["consumers"]], [expected, expected])
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(reg.fanout_cases["x"][1], b'{"fixture":"synthetic-1"}\n')  # fixture unchanged
        text = runner.result_json(r)
        self.assertEqual(json.loads(text), r)
        self.assertEqual(text, runner.result_json(runner.run_fanout("x", reg)))


if __name__ == "__main__":
    unittest.main()
