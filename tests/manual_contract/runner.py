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
from typing import Callable, Mapping, NamedTuple

SCHEMA = "cognous.orchestrator.manual-contract-result/0-candidate"
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


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _msg(exc):
    try:
        return str(exc)[:200]
    except Exception:
        return "<unprintable>"


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
    result["producer_output_sha256"] = result["consumer_input_sha256"] = _sha(output)

    result["invocation_status"] = "INVOKED"
    try:
        native = consumer.call(output)  # the same immutable bytes object the producer returned
    except Exception as exc:
        result["consumer_error"] = {"type": type(exc).__name__, "message": _msg(exc)}
        observed, why = "ERROR", "consumer raised %s" % type(exc).__name__
    else:
        observed, why = "UNKNOWN", "no native admission verdict observed (return value or acknowledgment is not acceptance)"
        snap = None
        if isinstance(native, Mapping):
            try:  # one snapshot: the evidence recorded is exactly the data the verdict is read from
                snap = dict(native)
                digest = _sha(_canonical(snap))
            except Exception:
                snap, why = None, "native response is not JSON-serializable; no verdict observed"
        if snap is not None:
            result["native_response"], result["native_response_sha256"] = snap, digest
            received = snap.get("received_sha256")
            reported = received if type(received) is str else None
            result["consumer_reported_input_sha256"] = reported
            verdict = snap.get(consumer.admission_field)
            mapped = consumer.admission_map.get(verdict) if type(verdict) is str else None
            if reported is not None and reported != result["consumer_input_sha256"]:
                why = "consumer reported a different input hash than was routed; evidence inconsistent"
            elif mapped in ("ACCEPTED", "REFUSED"):
                observed, why = mapped, "native %s=%r" % (consumer.admission_field, verdict)
    result["observed_outcome"] = observed
    if observed == "UNKNOWN":
        result["status"], result["reason"] = "BLOCKED", why
    elif observed == expected:
        result["status"], result["reason"] = "PASS", why
    else:
        result["status"], result["reason"] = "FAIL", "expected %s, observed %s: %s" % (expected, observed, why)
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
    if args.case not in mock_cases.REGISTRY.cases:
        print("refused: case id is not allowlisted", file=sys.stderr)
        return 2
    result = run_case(args.case, mock_cases.REGISTRY)
    text = result_json(result)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
