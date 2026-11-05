"""Minimal local producer-to-consumer contract-test runner (ORCH-00 / O0B-1).

Synthetic, non-effecting engineering test mechanism. CANDIDATE schema: not an adopted component contract, not an
issuer, grant checker, policy owner, verifier or release selector. It routes one producer output, unmodified, to one
consumer taken from a static registry (no import paths, commands or code from inputs) and compares the consumer's own
native admission verdict with a separately specified expectation. A function return, an ack or a transport status
never establishes ACCEPTED: only the consumer's mapped native verdict does.
"""
import argparse
import hashlib
import json
import os
import sys
from types import MappingProxyType
from typing import Callable, Mapping, NamedTuple

SCHEMA = "cognous.orchestrator.manual-contract-result/0-candidate"
FANOUT_SCHEMA = "cognous.orchestrator.manual-contract-fanout-result/0-candidate"
OBSERVED = ("ACCEPTED", "REFUSED", "ERROR", "UNKNOWN")
STATUSES = ("PASS", "FAIL", "BLOCKED")


class Consumer(NamedTuple):
    call: Callable[[bytes], Mapping]
    admission_field: str
    admission_map: Mapping[str, str]


class Registry(NamedTuple):
    producers: Mapping[str, Callable[[bytes], bytes]]
    consumers: Mapping[str, Consumer]
    cases: Mapping[str, tuple]
    expectations: Mapping[str, str]
    fanout_cases: Mapping[str, tuple] = MappingProxyType({})  # case_id -> (producer_id, fixture, (consumer_id, consumer_id))
    fanout_expectations: Mapping[str, Mapping[str, str]] = MappingProxyType({})  # case_id -> {consumer_id: expected}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _msg(exc):
    try:
        return str(exc)[:200]
    except Exception:
        return "<unprintable>"


def _consume(consumer, output, input_sha, expected):
    """Deliver `output` to one consumer and classify its own native response. Consumer behaviour (exception, odd response) is
    recorded, never raised, so it cannot affect anything outside this one consumer's result."""
    res = {
        "invocation_status": "INVOKED", "consumer_input_sha256": input_sha, "native_response": None,
        "native_response_sha256": None, "consumer_error": None, "consumer_reported_input_sha256": None,
        "expected_outcome": expected, "observed_outcome": "UNKNOWN", "status": "BLOCKED", "reason": "",
    }
    try:
        native = consumer.call(output)  # the same immutable bytes object the producer returned
    except Exception as exc:
        res["consumer_error"] = {"type": type(exc).__name__, "message": _msg(exc)}
        observed, why = "ERROR", "consumer raised %s" % type(exc).__name__
    else:
        observed, why = "UNKNOWN", "no native admission verdict observed (return value or acknowledgment is not acceptance)"
        snap = None
        if isinstance(native, Mapping):
            try:  # one snapshot: the evidence recorded is exactly the data the verdict is read from
                snap = dict(native)
                canonical = _canonical(snap)
                digest = _sha(canonical)
                snap = json.loads(canonical)  # detached deep copy of exactly the hashed data; later mutation cannot alter the evidence
            except Exception:
                snap, why = None, "native response is not JSON-serializable; no verdict observed"
        if snap is not None:
            res["native_response"], res["native_response_sha256"] = snap, digest
            received = snap.get("received_sha256")
            reported = received if type(received) is str else None
            res["consumer_reported_input_sha256"] = reported
            verdict = snap.get(consumer.admission_field)
            mapped = consumer.admission_map.get(verdict) if type(verdict) is str else None
            if reported is not None and reported != input_sha:
                why = "consumer reported a different input hash than was routed; evidence inconsistent"
            elif mapped in ("ACCEPTED", "REFUSED"):
                observed, why = mapped, "native %s=%r" % (consumer.admission_field, verdict)
    res["observed_outcome"] = observed
    if observed == "UNKNOWN":
        res["status"], res["reason"] = "BLOCKED", why
    elif observed == expected:
        res["status"], res["reason"] = "PASS", why
    else:
        res["status"], res["reason"] = "FAIL", "expected %s, observed %s: %s" % (expected, observed, why)
    return res


def run_case(case_id, registry):
    """Run one allowlisted case. KeyError if case_id is not in registry.cases; nothing else is ever resolved."""
    producer_id, fixture, consumer_id = registry.cases[case_id]
    expected = registry.expectations[case_id]
    if expected not in OBSERVED:
        raise ValueError("expectation outside the outcome vocabulary: %r" % (expected,))
    consumer = registry.consumers[consumer_id]
    result = {
        "schema": SCHEMA, "case_id": case_id, "producer_id": producer_id, "consumer_id": consumer_id,
        "effect_mode": "synthetic_non_effecting", "effect_status": "NOT_ATTEMPTED",
        "fixture_sha256": _sha(fixture), "producer_output_sha256": None, "consumer_input_sha256": None,
        "invocation_status": "NOT_INVOKED", "native_response": None, "native_response_sha256": None,
        "consumer_error": None, "consumer_reported_input_sha256": None,
        "expected_outcome": expected, "observed_outcome": "UNKNOWN", "status": "BLOCKED", "reason": "",
    }
    try:
        output = registry.producers[producer_id](fixture)
        if type(output) is not bytes:
            raise TypeError("producer output is not bytes")
    except Exception as exc:  # a producer failure stops the edge; never fake output
        result["reason"] = "producer failed (%s); consumer not invoked" % type(exc).__name__
        return result
    result["producer_output_sha256"] = _sha(output)
    result.update(_consume(consumer, output, result["producer_output_sha256"], expected))
    return result


def run_fanout(case_id, registry, identity=None):
    """Run one allowlisted fan-out case: ONE producer call, the same output bytes delivered independently to exactly two
    consumers, one result per consumer, one aggregate. KeyError if case_id is not in registry.fanout_cases."""
    producer_id, fixture, consumer_ids = registry.fanout_cases[case_id]
    expectations = registry.fanout_expectations[case_id]
    ids = tuple(consumer_ids)
    if len(ids) != 2 or len(set(ids)) != 2:
        raise ValueError("fan-out takes exactly two distinct consumers")
    for cid in ids:
        if expectations[cid] not in OBSERVED:
            raise ValueError("expectation outside the outcome vocabulary: %r" % (expectations[cid],))
    consumers = [(cid, registry.consumers[cid]) for cid in ids]  # resolve everything before producing anything
    with open(__file__, "rb") as fh:
        source = {**(identity or {}), "runner_sha256": _sha(fh.read()), "git_commit": os.environ.get("GITHUB_SHA")}
    result = {
        "schema": FANOUT_SCHEMA, "case_id": case_id, "producer_id": producer_id,
        "effect_mode": "synthetic_non_effecting", "effect_status": "NOT_ATTEMPTED",
        "fixture_sha256": _sha(fixture), "producer_output_sha256": None, "producer_error": None,
        "consumers": [], "status": "BLOCKED", "reason": "", "source_identity": source,
    }
    try:
        output = registry.producers[producer_id](fixture)  # exactly once
        if type(output) is not bytes:
            raise TypeError("producer output is not bytes")
    except Exception as exc:  # never fake output: no consumer is invoked
        result["producer_error"] = {"type": type(exc).__name__, "message": _msg(exc)}
        for cid, _ in consumers:
            result["consumers"].append({
                "consumer_id": cid, "invocation_status": "NOT_INVOKED", "consumer_input_sha256": None, "native_response": None,
                "native_response_sha256": None, "consumer_error": None, "consumer_reported_input_sha256": None,
                "expected_outcome": expectations[cid], "observed_outcome": "UNKNOWN", "status": "BLOCKED",
                "reason": "producer failed (%s); consumer not invoked" % type(exc).__name__})
    else:
        result["producer_output_sha256"] = _sha(output)
        for cid, consumer in consumers:  # each consumer gets the original bytes; nothing from the other consumer
            row = _consume(consumer, output, result["producer_output_sha256"], expectations[cid])
            result["consumers"].append(dict(row, consumer_id=cid))
    statuses = [row["status"] for row in result["consumers"]]
    result["status"] = "FAIL" if "FAIL" in statuses else "BLOCKED" if "BLOCKED" in statuses else "PASS"
    result["reason"] = ", ".join("%s=%s" % (row["consumer_id"], row["status"]) for row in result["consumers"])
    return result


def result_json(result):
    return json.dumps(result, indent=2, sort_keys=True) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one allowlisted synthetic producer->consumer case.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I omits the script dir
    import mock_cases  # static synthetic registry; no component code
    registry = mock_cases.REGISTRY
    if args.case in registry.fanout_cases:
        with open(mock_cases.__file__, "rb") as fh:
            result = run_fanout(args.case, registry, {"mock_cases_sha256": _sha(fh.read())})
    elif args.case in registry.cases:
        result = run_case(args.case, registry)
    else:
        print("refused: case id is not allowlisted", file=sys.stderr)
        return 2
    text = result_json(result)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
