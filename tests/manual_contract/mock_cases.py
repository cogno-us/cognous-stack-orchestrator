"""Synthetic mocks for the O0B-1 manual-contract runner.
These mocks are synthetic only; they model nothing real.
The result schema and interface are a candidate (not adopted) contract.
Nothing here is a component contract of any Cognous component.
No OCS component code is included or imported.
Pure functions: no I/O, network, clock or randomness.
"""
import hashlib

from runner import Consumer, Registry

CASE_ACCEPT = "mock_accept_expected_accept"
CASE_REFUSE = "mock_refuse_expected_refuse"
CASE_UNEXPECTED_REFUSAL = "mock_unexpected_refusal"
CASE_NO_RESPONSE = "mock_no_observable_response"

FIXTURE = b'{"fixture":"synthetic-1"}\n'
PREFIX = b'{"synthetic_producer_output":"v1"}\n'
ADMISSION_MAP = {"ADMITTED": "ACCEPTED", "REJECTED": "REFUSED"}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def mock_producer(fixture):
    return PREFIX + fixture


def _accepts(data):
    return {"verdict": "ADMITTED", "reason": "synthetic_accept", "received_sha256": _sha(data)}


def _refuses(data):
    return {"verdict": "REJECTED", "reason": "synthetic_refusal", "received_sha256": _sha(data)}


def _ack_only(data):
    return {"ack": True, "transport_status": 200}


def _consumer(fn):
    return Consumer(fn, "verdict", ADMISSION_MAP)


REGISTRY = Registry(
    producers={"mock_producer": mock_producer},
    consumers={
        "mock_consumer_accepts": _consumer(_accepts),
        "mock_consumer_refuses": _consumer(_refuses),
        "mock_consumer_ack_only": _consumer(_ack_only),
    },
    cases={
        CASE_ACCEPT: ("mock_producer", FIXTURE, "mock_consumer_accepts"),
        CASE_REFUSE: ("mock_producer", FIXTURE, "mock_consumer_refuses"),
        CASE_UNEXPECTED_REFUSAL: ("mock_producer", FIXTURE, "mock_consumer_refuses"),
        CASE_NO_RESPONSE: ("mock_producer", FIXTURE, "mock_consumer_ack_only"),
    },
    expectations={
        CASE_ACCEPT: "ACCEPTED",
        CASE_REFUSE: "REFUSED",
        CASE_UNEXPECTED_REFUSAL: "ACCEPTED",
        CASE_NO_RESPONSE: "ACCEPTED",
    },
)
