import copy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = (
    ROOT
    / "orchestration/adapters/attestation/trust_qualification/qualification.py"
)
spec = importlib.util.spec_from_file_location("o4db_trust_qualification", MODULE_PATH)
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)

NOW = 2_000_000_000


def _snapshot(*, key_id="key:1", issuer="issuer:test", audience="deployment:test",
              revoked_at=None, key_valid_until=NOW + 100):
    return {
        "registry_version": "bitrep-trust/1",
        "audience": audience,
        "published_at": NOW - 100,
        "valid_until": NOW + 100,
        "keys": [
            {
                "issuer": issuer,
                "key_id": key_id,
                "public_key": "A" * 44,
                "valid_from": NOW - 100,
                "valid_until": key_valid_until,
                "revoked_at": revoked_at,
            }
        ],
    }


def _write_snapshot(directory, payload, name="trust.json"):
    path = Path(directory) / name
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return path, "sha256:" + hashlib.sha256(raw).hexdigest()


def _config(path, digest, *, key_id="key:1", issuer="issuer:test",
            audience="deployment:test", **updates):
    config = {
        "config_version": qualification.CONFIG_VERSION,
        "verifier_repository": qualification.accepted_bridge.ATTESTATION_REPOSITORY,
        "verifier_revision": qualification.accepted_bridge.ATTESTATION_REVISION,
        "trust_snapshot_path": str(path.resolve()),
        "trust_snapshot_sha256": digest,
        "trust_source": qualification.TRUST_SOURCE,
        "trusted_time_source": qualification.TRUSTED_TIME_SOURCE,
        "expected_issuer": issuer,
        "expected_key_id": key_id,
        "expected_audience": audience,
    }
    config.update(updates)
    return config


def _attestation(*, key_id="key:1", issuer="issuer:test",
                 audience="deployment:test", subject="claim:test",
                 content_digest="sha256:" + "ab" * 32):
    return {
        "statement": {
            "protocol_version": "bitrep-attestation/1",
            "algorithm": "Ed25519",
            "attestation_id": "att:test:1",
            "issuer": issuer,
            "key_id": key_id,
            "subject": subject,
            "statement_type": "supports",
            "audience": audience,
            "content_digest": content_digest,
            "issued_at": NOW - 10,
            "not_before": NOW - 10,
            "expires_at": NOW + 50,
        },
        "signature": "x" * 88,
    }


def _expected(attestation):
    statement = attestation["statement"]
    return {
        "statement": copy.deepcopy(statement),
        "statement_digest": "sha256:" + "1" * 64,
        "content_digest": statement["content_digest"],
        "audience": statement["audience"],
        "subject": statement["subject"],
    }


class BridgeStub:
    def __init__(self, *, status="verified", reason="issuer_signature_and_binding_verified"):
        self.status = status
        self.reason = reason
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        result = {
            "result_version": "cognous-orchestrator-attestation-bridge/1",
            "status": self.status,
            "reason": self.reason,
            "verifier_repository": qualification.accepted_bridge.ATTESTATION_REPOSITORY,
            "verifier_revision": qualification.accepted_bridge.ATTESTATION_REVISION,
            "authority": "not_established",
            "independent_authenticity": "not_claimed",
        }
        if self.status == "verified":
            result.update(
                {
                    "issuer_authenticity": "verified_under_configured_snapshot_and_time",
                    "upstream_verification": {
                        "outcome": "verified",
                        "assurance": "issuer_signature_only",
                        "reason": "ok",
                    },
                }
            )
        return result


class OperatorTrustQualificationTests(unittest.TestCase):
    def run_qualified(self, config, att=None, expected=None, bridge=None, trusted_time=NOW):
        att = att or _attestation()
        expected = expected or _expected(att)
        bridge = bridge or BridgeStub()
        return qualification.qualify_attestation_trust(
            deployment_config=config,
            verifier_checkout="/accepted/pinned/upstream",
            trusted_time=trusted_time,
            attestation=att,
            expected=expected,
            bridge_verify=bridge,
        )

    def test_missing_configuration_fails_closed_without_bridge(self):
        bridge = BridgeStub()
        got = self.run_qualified(None, bridge=bridge)
        self.assertEqual(
            (got["status"], got["reason"]),
            ("unknown", "operator_trust_configuration_absent"),
        )
        self.assertEqual(bridge.calls, [])

    def test_missing_trusted_time_fails_closed_without_bridge(self):
        with tempfile.TemporaryDirectory() as td:
            path, digest = _write_snapshot(td, _snapshot())
            bridge = BridgeStub()
            got = self.run_qualified(_config(path, digest), bridge=bridge, trusted_time=None)
        self.assertEqual(
            (got["status"], got["reason"]),
            ("unknown", "trusted_time_absent_or_invalid"),
        )
        self.assertEqual(bridge.calls, [])

    def test_untrusted_time_source_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            path, digest = _write_snapshot(td, _snapshot())
            bridge = BridgeStub()
            got = self.run_qualified(
                _config(path, digest, trusted_time_source="attestation-wire-time"),
                bridge=bridge,
            )
        self.assertEqual((got["status"], got["reason"]), ("unknown", "untrusted_time_source"))
        self.assertEqual(bridge.calls, [])

    def test_verifier_revision_must_equal_accepted_bridge_pin(self):
        with tempfile.TemporaryDirectory() as td:
            path, digest = _write_snapshot(td, _snapshot())
            bridge = BridgeStub()
            got = self.run_qualified(
                _config(path, digest, verifier_revision="0" * 40),
                bridge=bridge,
            )
        self.assertEqual(
            (got["status"], got["reason"]),
            ("unknown", "verifier_revision_pin_mismatch"),
        )
        self.assertEqual(bridge.calls, [])

    def test_snapshot_is_raw_digest_pinned_before_bridge_use(self):
        with tempfile.TemporaryDirectory() as td:
            path, digest = _write_snapshot(td, _snapshot())
            config = _config(path, digest)
            path.write_text(json.dumps(_snapshot(key_id="key:2")), encoding="utf-8")
            bridge = BridgeStub()
            got = self.run_qualified(config, bridge=bridge)
        self.assertEqual(
            (got["status"], got["reason"]),
            ("unknown", "trust_snapshot_pin_mismatch"),
        )
        self.assertEqual(bridge.calls, [])

    def test_rotation_requires_explicit_new_snapshot_pin_and_key_identity(self):
        with tempfile.TemporaryDirectory() as td:
            path, old_digest = _write_snapshot(td, _snapshot(key_id="key:1"))
            old_config = _config(path, old_digest, key_id="key:1")
            old_bridge = BridgeStub()
            old = self.run_qualified(old_config, bridge=old_bridge)
            self.assertEqual(old["status"], "verified")

            path, new_digest = _write_snapshot(td, _snapshot(key_id="key:2"))
            stale = self.run_qualified(old_config, bridge=BridgeStub())
            self.assertEqual(
                (stale["status"], stale["reason"]),
                ("unknown", "trust_snapshot_pin_mismatch"),
            )

            new_att = _attestation(key_id="key:2")
            new_config = _config(path, new_digest, key_id="key:2")
            new_bridge = BridgeStub()
            rotated = self.run_qualified(
                new_config,
                att=new_att,
                expected=_expected(new_att),
                bridge=new_bridge,
            )
            self.assertEqual(rotated["status"], "verified")
            self.assertEqual(rotated["operator_trust"]["key_id"], "key:2")

            old_att = _attestation(key_id="key:1")
            old_after_rotation = self.run_qualified(
                new_config,
                att=old_att,
                expected=_expected(old_att),
                bridge=BridgeStub(),
            )
            self.assertEqual(
                (old_after_rotation["status"], old_after_rotation["reason"]),
                ("rejected", "key_identity_mismatch"),
            )

    def test_revoked_key_rejection_from_accepted_bridge_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            path, digest = _write_snapshot(td, _snapshot(revoked_at=NOW))
            bridge = BridgeStub(status="rejected", reason="key_revoked")
            got = self.run_qualified(_config(path, digest), bridge=bridge)
        self.assertEqual((got["status"], got["reason"]), ("rejected", "key_revoked"))
        self.assertEqual(got["authority"], "not_established")
        self.assertEqual(got["grant"], "not_inferred")

    def test_expired_key_rejection_from_accepted_bridge_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            path, digest = _write_snapshot(td, _snapshot(key_valid_until=NOW))
            bridge = BridgeStub(status="rejected", reason="key_expired")
            got = self.run_qualified(_config(path, digest), bridge=bridge)
        self.assertEqual((got["status"], got["reason"]), ("rejected", "key_expired"))

    def test_issuer_and_key_identity_are_bound_before_bridge(self):
        with tempfile.TemporaryDirectory() as td:
            path, digest = _write_snapshot(td, _snapshot())
            config = _config(path, digest)
            for att, reason in (
                (_attestation(issuer="issuer:attacker"), "issuer_identity_mismatch"),
                (_attestation(key_id="key:attacker"), "key_identity_mismatch"),
            ):
                with self.subTest(reason=reason):
                    bridge = BridgeStub()
                    got = self.run_qualified(
                        config, att=att, expected=_expected(att), bridge=bridge
                    )
                    self.assertEqual((got["status"], got["reason"]), ("rejected", reason))
                    self.assertEqual(bridge.calls, [])

    def test_audience_subject_and_content_are_independently_bound(self):
        with tempfile.TemporaryDirectory() as td:
            path, digest = _write_snapshot(td, _snapshot())
            config = _config(path, digest)
            att = _attestation()
            cases = []
            wrong_audience = _expected(att)
            wrong_audience["audience"] = "deployment:other"
            cases.append((wrong_audience, "independent_audience_mismatch"))
            wrong_subject = _expected(att)
            wrong_subject["subject"] = "claim:other"
            cases.append((wrong_subject, "independent_subject_mismatch"))
            wrong_content = _expected(att)
            wrong_content["content_digest"] = "sha256:" + "00" * 32
            cases.append((wrong_content, "independent_content_digest_mismatch"))
            for expected, reason in cases:
                with self.subTest(reason=reason):
                    bridge = BridgeStub()
                    got = self.run_qualified(
                        config, att=att, expected=expected, bridge=bridge
                    )
                    self.assertEqual((got["status"], got["reason"]), ("rejected", reason))
                    self.assertEqual(bridge.calls, [])

    def test_attacker_supplied_trust_path_cannot_replace_operator_path(self):
        signature = inspect.signature(qualification.qualify_attestation_trust)
        self.assertNotIn("trust_snapshot_path", signature.parameters)
        with tempfile.TemporaryDirectory() as td:
            operator_path, digest = _write_snapshot(td, _snapshot(), "operator.json")
            attacker_path, _ = _write_snapshot(
                td, _snapshot(key_id="key:attacker"), "attacker.json"
            )
            att = _attestation()
            att["trust_snapshot_path"] = str(attacker_path)
            bridge = BridgeStub()
            got = self.run_qualified(
                _config(operator_path, digest),
                att=att,
                expected=_expected(att),
                bridge=bridge,
            )
        self.assertEqual(got["status"], "verified")
        self.assertEqual(len(bridge.calls), 1)
        self.assertEqual(
            bridge.calls[0]["trust_snapshot_path"],
            str(operator_path.resolve()),
        )

    def test_verified_result_records_operator_provenance_but_no_authority(self):
        with tempfile.TemporaryDirectory() as td:
            path, digest = _write_snapshot(td, _snapshot())
            got = self.run_qualified(_config(path, digest), bridge=BridgeStub())
        self.assertEqual(got["status"], "verified")
        self.assertEqual(got["operator_trust"]["trust_snapshot_sha256"], digest)
        self.assertEqual(got["operator_trust"]["trusted_time_source"],
                         qualification.TRUSTED_TIME_SOURCE)
        self.assertEqual(got["authority"], "not_established")
        self.assertEqual(got["grant"], "not_inferred")
        self.assertEqual(got["effect"], "not_observed")


@unittest.skipUnless(
    os.environ.get("COGNOUS_EVIDENCE_ATTESTATION_ROOT"),
    "set COGNOUS_EVIDENCE_ATTESTATION_ROOT for live pinned-upstream qualification",
)
class LiveAcceptedBridgeLifecycleTests(unittest.TestCase):
    """Optional live check: cryptography remains wholly in the accepted upstream."""

    @classmethod
    def setUpClass(cls):
        cls.checkout = Path(os.environ["COGNOUS_EVIDENCE_ATTESTATION_ROOT"]).resolve()
        import sys
        sys.path.insert(0, str(cls.checkout))
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        from models.verification import SignedStatement
        from utils.verification import canonical_bytes, statement_digest

        cls.Ed25519PrivateKey = Ed25519PrivateKey
        cls.serialization = serialization
        cls.SignedStatement = SignedStatement
        cls.canonical_bytes = staticmethod(canonical_bytes)
        cls.statement_digest = staticmethod(statement_digest)

    @classmethod
    def tearDownClass(cls):
        import sys
        if sys.path and sys.path[0] == str(cls.checkout):
            sys.path.pop(0)

    def _fixture(self, *, revoked_at=None, key_valid_until=NOW + 100):
        import base64
        key = self.Ed25519PrivateKey.generate()
        public = base64.b64encode(
            key.public_key().public_bytes(
                self.serialization.Encoding.Raw,
                self.serialization.PublicFormat.Raw,
            )
        ).decode()
        att = _attestation()
        model = self.SignedStatement(**att["statement"])
        att["signature"] = base64.b64encode(
            key.sign(self.canonical_bytes(model))
        ).decode()
        trust = _snapshot(revoked_at=revoked_at, key_valid_until=key_valid_until)
        trust["keys"][0]["public_key"] = public
        expected = _expected(att)
        expected["statement_digest"] = self.statement_digest(model)
        return att, trust, expected

    def _run_live(self, *, revoked_at=None, key_valid_until=NOW + 100):
        att, trust, expected = self._fixture(
            revoked_at=revoked_at, key_valid_until=key_valid_until
        )
        with tempfile.TemporaryDirectory() as td:
            path, digest = _write_snapshot(td, trust)
            return qualification.qualify_attestation_trust(
                deployment_config=_config(path, digest),
                verifier_checkout=self.checkout,
                trusted_time=NOW,
                attestation=att,
                expected=expected,
            )

    def test_live_revoked_key(self):
        got = self._run_live(revoked_at=NOW)
        self.assertEqual((got["status"], got["reason"]), ("rejected", "key_revoked"))

    def test_live_expired_key(self):
        got = self._run_live(key_valid_until=NOW)
        self.assertEqual((got["status"], got["reason"]), ("rejected", "key_expired"))


if __name__ == "__main__":
    unittest.main()
