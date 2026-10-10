"""O6-Q3: synthetic composition using actual, explicitly pinned O6 source classes.

This test has a test-owned policy gate; it does not authenticate institutional authority.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest


def _source(name: str, env: str, expected: str) -> Path:
    import subprocess
    root = Path(os.environ[env]).resolve()
    actual = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    assert actual == expected, f"{name}: expected {expected}; got {actual}"
    assert root.is_dir()
    return root


RUNTIME = _source("runtime", "COGNOUS_O6_RUNTIME_ROOT", "1b0a9e32d010797711004ae612051a277b07912a")
GAX = _source("gax", "COGNOUS_O6_GAX_ROOT", "814927dac65a2078d5efee6bbf07c46091844822")
ATTEST = _source("attestation", "COGNOUS_O6_ATTEST_ROOT", "5786b91696ffa276650c4f7b424c9662ebf96fac")

sys.path.insert(0, str(ATTEST))
sys.path.insert(0, str(GAX))
sys.path.insert(0, str(RUNTIME))

from engine.revocation_closeout import OrderingEvidence, RevocationCloseoutStore
from experiments.odex_gax_imx_reference.generation_fence import (
    GenerationFenceClaim, GenerationFenceRefusal, GenerationFencePersistenceError,
    LineageGenerationFence,
)
from profiles.authority_digest_custody import verify_authority_digest_custody

fixture_spec = importlib.util.spec_from_file_location(
    "o6_q3_actual_attestation_fixture", ATTEST / "tests/test_authority_digest_custody_profile.py"
)
assert fixture_spec and fixture_spec.loader
fixture_module = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixture_module)


class LocalSyntheticDestination:
    """Test-owned destination only; actual GAX fence performs the commit admission."""
    def __init__(self):
        self.effects = []

    def commit(self, snapshot, *, simulate=None):
        self.effects.append(snapshot.effect_id)
        return {"effect_id": snapshot.effect_id, "synthetic": True}


def _lineage(tmp_path, conversation="conversation:synthetic-refund"):
    path = tmp_path / "gax.sqlite3"
    fence = LineageGenerationFence(path, max_refusals_per_conversation=2)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE heads (conversation_id TEXT PRIMARY KEY, state_version INTEGER NOT NULL)")
        conn.execute("INSERT INTO heads VALUES (?, ?)", (conversation, 4))
    return path, fence, conversation


def _custody_evidence():
    values = fixture_module.fixture(kind="policy")
    raw, claim, publisher, publisher_trust, witness, witness_trust = values
    return raw, claim, publisher, publisher_trust, witness, witness_trust


def _authenticated_digest(values, raw_override=None):
    raw, claim, publisher, publisher_trust, witness, witness_trust = values
    return verify_authority_digest_custody(
        authority_bytes=raw if raw_override is None else raw_override,
        claim=claim,
        publisher_attestation=publisher,
        publisher_trust=publisher_trust,
        witness_attestation=witness,
        witness_trust=witness_trust,
        expected_epoch=claim.authority_epoch,
        now=fixture_module.NOW,
    )


def _commit_after_digest(values, fence, destination, conversation, effect, generation, raw_override=None):
    custody = _authenticated_digest(values, raw_override=raw_override)
    if not custody.accepted:
        return {"status": "hold", "reason": custody.reason, "custody": custody}
    # This is a test-owned gating decision, NOT institutional authorization.
    claim = GenerationFenceClaim(conversation_id=conversation, effect_id=effect, generation=generation)
    return fence.commit_if_current(destination, SimpleNamespace(effect_id=effect), claim)


def test_connected_synthetic_custody_generation_revocation_and_original_attempt(tmp_path):
    values = _custody_evidence()
    path, fence, conversation = _lineage(tmp_path)
    destination = LocalSyntheticDestination()
    effect = "effect:synthetic-refund-007"
    attempt = "attempt:synthetic-refund-007"
    grant = "grant:synthetic-refund"
    assert _authenticated_digest(values).assurance == "non_authorizing_digest_custody"

    # A changed authority document cannot be dispatched by the test-owned gate.
    rejected = _commit_after_digest(values, fence, destination, conversation, effect, 4, b"modified")
    assert rejected["status"] == "hold"
    assert rejected["reason"] == "authority_digest_mismatch"
    assert destination.effects == []

    # A v4 claimant is superseded by authoritative v5 at local commit.
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE heads SET state_version=5 WHERE conversation_id=?", (conversation,))
    with pytest.raises(GenerationFenceRefusal, match="superseded_lineage_generation"):
        _commit_after_digest(values, fence, destination, conversation, effect, 4)
    assert destination.effects == []
    assert fence.refusals(conversation)[0]["effect_id"] == effect

    # A new claim for v5 may reach only this synthetic destination, once here.
    result = _commit_after_digest(values, fence, destination, conversation, effect, 5)
    assert result["effect_id"] == effect
    assert destination.effects == [effect]

    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    ledger = RevocationCloseoutStore(tmp_path / "revocation", clock=lambda: now)
    ledger.record_item(
        effect_id=effect, attempt_id=attempt, decision_id="decision:synthetic-refund-007",
        grant_id=grant, grant_revision="1", state="executing",
        ordering=OrderingEvidence(5, "synthetic:pre-revocation"),
    )
    dispositions = ledger.record_revocation(
        grant_id=grant, grant_revision="1",
        revocation=OrderingEvidence(6, "synthetic:revocation"),
        owner="synthetic-reconciler", deadline=now + timedelta(hours=1),
        reconciliation_ref="synthetic:provider-reconciliation",
    )
    assert len(dispositions) == 1
    assert dispositions[0].effect_id == effect
    assert dispositions[0].status == "in_doubt"
    assert RevocationCloseoutStore(tmp_path / "revocation").dispositions()[0].status == "in_doubt"

    # Missing/unknown observation cannot turn a late response into retry authority.
    unknown = ledger.close_original_attempt(
        attempt_id=attempt, observation_state="unknown",
        observation=OrderingEvidence(7, "synthetic:unknown"),
        observation_ref="synthetic:unknown-ref",
    )
    assert not unknown.closed and not unknown.retry_eligible
    assert RevocationCloseoutStore(tmp_path / "revocation").closeout(attempt).retry_eligible is False
    # No replacement effect/attempt is minted: unresolved original attempt is preserved.
    assert destination.effects == [effect]


def test_connected_negative_mutations_and_refusal_flood(tmp_path):
    values = _custody_evidence()
    path, fence, conversation = _lineage(tmp_path)
    destination = LocalSyntheticDestination()
    effect = "effect:negative"
    wrong_epoch_values = list(values)
    wrong_epoch_values[1] = values[1].model_copy(update={"authority_epoch": 9})
    assert _authenticated_digest(tuple(wrong_epoch_values)).reason == "publisher_content_digest_mismatch"
    assert destination.effects == []

    with pytest.raises(GenerationFenceRefusal):
        _commit_after_digest(values, fence, destination, conversation, effect, 3)
    with pytest.raises(GenerationFenceRefusal):
        _commit_after_digest(values, fence, destination, conversation, effect, 2)
    with pytest.raises(GenerationFenceRefusal):
        _commit_after_digest(values, fence, destination, conversation, effect, 1)
    counters = LineageGenerationFence(path, max_refusals_per_conversation=2).counters(conversation)
    assert counters["total_refusals"] == 3
    assert counters["persisted_refusals"] == 2
    assert counters["suppressed_refusals"] == 1
    assert len(fence.refusals(conversation)) == 2
    assert destination.effects == []

    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    ledger = RevocationCloseoutStore(tmp_path / "disabled", clock=lambda: now)
    ledger.record_item(
        effect_id=effect, attempt_id="attempt:negative", decision_id="decision:negative",
        grant_id="grant:negative", grant_revision="3", state="executing",
        ordering=OrderingEvidence(4, "synthetic:order"),
    )
    broken = RevocationCloseoutStore(
        tmp_path / "disabled", clock=lambda: now, disposition_writer_enabled=False
    )
    with pytest.raises(RuntimeError, match="writer disabled"):
        broken.record_revocation(
            grant_id="grant:negative", grant_revision="3",
            revocation=OrderingEvidence(5, "synthetic:revoked"),
            owner="reconciler", deadline=now + timedelta(hours=1),
            reconciliation_ref="synthetic:reconcile",
        )
    assert broken.dispositions() == []
