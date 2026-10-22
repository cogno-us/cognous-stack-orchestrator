"""Developer tests for the lock-driven evidence handoff. Not independent acceptance cases."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "development/acceptance/lock-driven-handoff/handoff.py"
spec = importlib.util.spec_from_file_location("lock_driven_handoff", SCRIPT)
assert spec and spec.loader
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

A, B, C, D = ("a" * 40, "b" * 40, "c" * 40, "d" * 40)
HUB = "e" * 40
PRODUCER = {"component": "cognous-stack-orchestrator", "revision": "f" * 40}


def make_lock() -> dict:
    """Synthetic lock with the key shapes of the real hub lock (sha; accepted_sha + core_interop_sha)."""
    return {
        "lock_version": "1.0",
        "components": {
            "control_plane": {"repository": "cogno-us/control-plane", "sha": A,
                              "interfaces": ["Decision 1.0"]},
            "moltbot_safe": {"repository": "cogno-us/runtime", "accepted_sha": B, "core_interop_sha": B,
                             "interfaces": ["Envelope 0.2"], "note": "x"},
            "bitrep": {"repository": "cogno-us/bitrep", "sha": C, "licensing_head": D},
            "gax_imx_transport": {"repository": "cogno-us/exchange", "sha": D, "accepted_sha": D,
                                  "reviewed_source_sha": D, "merged_pr": 61,
                                  "previous_acceptance": {"sha": A, "accepted_sha": A}},
            "prp": {"repository": "cogno-us/prp", "sha": D, "optional": True},
        },
    }


def dump(lock: dict) -> bytes:
    return json.dumps(lock, indent=2).encode()


def evidence_for(lock_bytes: bytes) -> list:
    _, tup = h.read_lock(lock_bytes)
    return [{"kind": "engineering_ci", "producing_commit": "1" * 40, "run_id": 42,
             "result_digest": "sha256:" + "2" * 64, "tuple_digest": h.tuple_digest(tup),
             "artifact_refs": ["run:42/log"]}]


def make_envelope(lock_bytes: bytes | None = None, **over) -> tuple[dict, bytes]:
    lock_bytes = lock_bytes or dump(make_lock())
    args = dict(lock_bytes=lock_bytes, hub_repository="cogno-us/cognous-open-control-stack", hub_sha=HUB,
                producer=PRODUCER, evidence=evidence_for(lock_bytes),
                claim_scope={"claim": "engineering evidence at this exact tuple only",
                             "exclusions": ["no operational trust", "no release selection"]})
    args.update(over)
    return h.build_envelope(**args), lock_bytes


def refused(code, envelope, lock_bytes, **kw):
    with pytest.raises(h.HandoffRefused) as ctx:
        h.check_envelope(envelope, lock_bytes=lock_bytes, hub_head=kw.pop("hub_head", HUB), **kw)
    assert ctx.value.code == code


def redigest(env):
    env["digest"] = h.envelope_digest(env)
    return env


def test_valid_envelope_is_checked_and_always_held():
    env, lock = make_envelope()
    result = h.check_envelope(env, lock_bytes=lock, hub_head=HUB)
    assert result["status"] == "hold" and result["release_admission"] == "not_authorized"
    assert result["selection"] == "unchanged" and result["effects"] == "disabled"
    assert result["envelope_digest"] == env["digest"]


def test_tuple_comes_from_the_supplied_lock_with_both_key_shapes():
    env, _ = make_envelope()
    assert env["tuple"]["moltbot_safe"]["sha"] == B and env["tuple"]["control_plane"]["sha"] == A
    assert env["tuple"]["bitrep"]["interfaces"] == []


def test_equal_sha_and_accepted_sha_is_one_revision_and_history_is_ignored():
    env, _ = make_envelope()
    assert env["tuple"]["gax_imx_transport"] == {"repository": "cogno-us/exchange", "sha": D, "interfaces": []}


def test_a_different_lock_does_not_inherit_the_evidence():
    env, lock = make_envelope()
    other = make_lock()
    other["components"]["bitrep"]["sha"] = "9" * 40
    refused("lock_digest_mismatch", env, dump(other))


@pytest.mark.parametrize("name", ["control_plane", "moltbot_safe", "bitrep", "prp", "gax_imx_transport"])
def test_tuple_differing_in_any_component_is_refused(name):
    env, lock = make_envelope()
    changed = copy.deepcopy(env)
    changed["tuple"][name]["sha"] = "9" * 40
    refused("tuple_differs_from_lock", redigest(changed), lock)


def test_lock_digest_mismatch_even_for_a_reformatted_lock():
    env, lock = make_envelope()
    reformatted = json.dumps(json.loads(lock), indent=4).encode()
    refused("lock_digest_mismatch", env, reformatted)


def test_digest_altered_after_issue():
    env, lock = make_envelope()
    env["claim_scope"]["claim"] = "wider claim"
    refused("digest_mismatch", env, lock)
    env2, lock = make_envelope()
    env2["digest"] = "sha256:" + "0" * 64
    refused("digest_mismatch", env2, lock)


@pytest.mark.parametrize("key,value", [
    ("effects", "enabled"), ("release_selection", "advanced"), ("intent", "promote"),
    ("operational_trust", {"state": "established", "independent_operator_evidence": None}),
    ("operational_trust", {"state": "not_established", "independent_operator_evidence": "claimed"}),
    ("qualification_reference", "run-1"),
])
def test_fixed_fields_cannot_change_even_with_a_valid_digest(key, value):
    env, lock = make_envelope()
    env[key] = value
    refused("fixed_field_changed", redigest(env), lock)


@pytest.mark.parametrize("member", ["verdict", "pin", "expectation", "pass", "hold_override"])
def test_verdict_pin_or_expectation_members_are_refused(member):
    env, lock = make_envelope()
    env[member] = "PASS"
    refused("unknown_or_missing_member", redigest(env), lock)


def test_missing_member_refused():
    env, lock = make_envelope()
    del env["predecessor"]
    refused("unknown_or_missing_member", env, lock)


def test_evidence_citing_a_different_tuple_is_refused():
    env, lock = make_envelope()
    env["evidence"][0]["tuple_digest"] = "sha256:" + "7" * 64
    refused("evidence_tuple_mismatch", redigest(env), lock)
    with pytest.raises(h.HandoffRefused) as ctx:
        make_envelope(evidence=[{**evidence_for(lock)[0], "tuple_digest": "sha256:" + "7" * 64}])
    assert ctx.value.code == "evidence_tuple_mismatch"


def test_evidence_and_claim_scope_must_be_explicit():
    lock = dump(make_lock())
    for bad in ([], None, [{"kind": "x"}]):
        with pytest.raises(h.HandoffRefused):
            make_envelope(lock, evidence=bad)
    for bad in ({}, {"claim": "x", "exclusions": []}, {"claim": " ", "exclusions": ["y"]}):
        with pytest.raises(h.HandoffRefused) as ctx:
            make_envelope(lock, claim_scope=bad)
        assert ctx.value.code == "claim_scope_invalid"


def test_hub_head_must_match():
    env, lock = make_envelope()
    refused("hub_sha_mismatch", env, lock, hub_head="0" * 40)


def test_superseded_envelope_is_reported_not_accepted():
    first, lock = make_envelope()
    second, _ = make_envelope(lock, predecessor=first["digest"])
    assert h.check_envelope(second, lock_bytes=lock, hub_head=HUB)["status"] == "hold"
    refused("superseded", first, lock, superseded=frozenset({first["digest"]}))


def test_predecessor_form():
    with pytest.raises(h.HandoffRefused):
        make_envelope(predecessor="not-a-digest")


@pytest.mark.parametrize("mutate,code", [
    (lambda c: c["components"]["control_plane"].update(accepted_sha=B), "lock_revision_conflict"),
    (lambda c: c["components"]["gax_imx_transport"].update(accepted_sha=A), "lock_revision_conflict"),
    (lambda c: c["components"]["control_plane"].update(accepted_sha="short"), "unknown_lock_shape"),
    (lambda c: c["components"]["control_plane"].pop("sha"), "unknown_lock_shape"),
    (lambda c: c["components"]["control_plane"].update(sha="short"), "unknown_lock_shape"),
    (lambda c: c["components"]["control_plane"].pop("repository"), "unknown_lock_shape"),
    (lambda c: c["components"]["control_plane"].update(interfaces="Decision"), "unknown_lock_shape"),
    (lambda c: c["components"]["moltbot_safe"].update(core_interop_sha=A), "lock_interop_drift"),
    (lambda c: c.update(components={}), "unknown_lock_shape"),
    (lambda c: c.pop("lock_version"), "unknown_lock_shape"),
    (lambda c: c.update(components=[]), "unknown_lock_shape"),
])
def test_unknown_lock_shapes_fail_closed(mutate, code):
    lock = make_lock()
    mutate(lock)
    with pytest.raises(h.HandoffRefused) as ctx:
        h.read_lock(dump(lock))
    assert ctx.value.code == code


def test_non_strict_lock_refused():
    for raw in (b'{"lock_version":"1.0","lock_version":"2","components":{}}', b'{"a": 1.5}', b"not json",
                b"\xff"):
        with pytest.raises(h.HandoffRefused) as ctx:
            h.read_lock(raw)
        assert ctx.value.code == "lock_not_strict_json"


def test_canonical_json_vectors():
    assert h.jcs_dumps({"b": 1, "a": [True, None, "x"]}) == '{"a":[true,null,"x"],"b":1}'
    assert h.jcs_dumps({"דּ": 1, "\U0001f600": 2}) == '{"\U0001f600":2,"דּ":1}'
    assert h.jcs_dumps('a"\\\n\x01') == '"a\\"\\\\\\n\\u0001"'
    for bad in (1.5, 2 ** 60, (1,), {1: 2}):
        with pytest.raises(ValueError):
            h.jcs_dumps(bad)


def test_digest_is_independent_of_member_order():
    env, _ = make_envelope()
    assert h.envelope_digest(env) == h.envelope_digest(dict(reversed(list(env.items()))))


def test_module_exposes_no_promotion_or_pin_writing_api():
    names = {n.lower() for n in dir(h) if not n.startswith("_")}
    assert not [n for n in names if any(w in n for w in ("promote", "select", "write", "advance", "authorize"))]


def test_historical_o6_q5_constants_are_untouched():
    text = (ROOT / "development/acceptance/o6-q5/admission.py").read_text()
    assert 'HUB_SHA = "2a23a2fbb3f5469872170c07a11b57656c6c3d2f"' in text
