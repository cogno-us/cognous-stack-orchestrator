import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "orchestration/adapters/attestation/verifier.py"
spec = importlib.util.spec_from_file_location("o4cb_attestation_verifier", MODULE_PATH)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

NOW = 2_000_000_000


def _trust_file(directory: str, payload=None) -> str:
    path = Path(directory) / "trust.json"
    if payload is None:
        payload = {
            "registry_version": "bitrep-trust/1",
            "audience": "deployment:test",
            "published_at": NOW - 100,
            "valid_until": NOW + 100,
            "keys": [],
        }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _expected(statement, statement_digest="sha256:" + "1" * 64):
    return {
        "statement": copy.deepcopy(statement),
        "statement_digest": statement_digest,
        "content_digest": statement["content_digest"],
        "audience": statement["audience"],
        "subject": statement["subject"],
    }


class BoundaryTests(unittest.TestCase):
    def test_unsupported_revision_rejected_before_execution(self):
        got = bridge.verify_attestation_binding(
            verifier_checkout="/unused",
            verifier_revision="0" * 40,
            trust_snapshot_path="/unused",
            trusted_time=NOW,
            attestation={},
            expected={},
        )
        self.assertEqual(
            (got["status"], got["reason"]),
            ("rejected", "unsupported_verifier_revision"),
        )

    def test_absent_trust_snapshot_is_unknown(self):
        got = bridge.verify_attestation_binding(
            verifier_checkout="/unused",
            verifier_revision=bridge.ATTESTATION_REVISION,
            trust_snapshot_path=None,
            trusted_time=NOW,
            attestation={},
            expected={},
        )
        self.assertEqual(
            (got["status"], got["reason"]),
            ("unknown", "trusted_snapshot_absent"),
        )

    def test_missing_independent_reference_is_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            got = bridge.verify_attestation_binding(
                verifier_checkout="/unused",
                verifier_revision=bridge.ATTESTATION_REVISION,
                trust_snapshot_path=_trust_file(td),
                trusted_time=NOW,
                attestation={},
                expected={},
            )
        self.assertEqual(
            (got["status"], got["reason"]),
            ("unknown", "independent_reference_absent_or_invalid"),
        )

    def test_pinned_source_mismatch_is_failure(self):
        statement = {
            "content_digest": "sha256:" + "2" * 64,
            "audience": "deployment:test",
            "subject": "claim:1",
        }
        with (
            tempfile.TemporaryDirectory() as td,
            mock.patch.object(
                bridge,
                "_copy_pinned_source",
                side_effect=RuntimeError("pinned_source_mismatch"),
            ),
        ):
            got = bridge.verify_attestation_binding(
                verifier_checkout=td,
                verifier_revision=bridge.ATTESTATION_REVISION,
                trust_snapshot_path=_trust_file(td),
                trusted_time=NOW,
                attestation={"statement": statement, "signature": "x" * 88},
                expected=_expected(statement),
            )
        self.assertEqual(
            (got["status"], got["reason"]),
            ("failure", "pinned_source_mismatch"),
        )

    def test_pinned_source_copy_uses_the_bytes_that_were_hashed(self):
        pinned = b"PINNED = True\n"
        relative = "models/__init__.py"
        expected_blob = "7266cb3244194f21e3e91e3d482562749a20be05"  # git hash-object
        with tempfile.TemporaryDirectory() as td:
            checkout = Path(td) / "checkout"
            destination = Path(td) / "isolated"
            (checkout / "models").mkdir(parents=True)
            destination.mkdir()
            source = checkout / relative
            source.write_bytes(pinned)

            def swap_during_hash(*args, **kwargs):
                # The checkout changes after the pinned bytes were observed.
                source.write_bytes(b"import os; os.system('evil')\n")
                return expected_blob

            with (
                mock.patch.object(bridge, "PINNED_SOURCE_BLOBS", {relative: expected_blob}),
                mock.patch.object(bridge, "_git_blob_id", side_effect=swap_during_hash),
            ):
                bridge._copy_pinned_source(checkout, destination)
            self.assertEqual((destination / relative).read_bytes(), pinned)

    def test_in_process_blob_id_matches_git(self):
        self.assertEqual(
            bridge._git_blob_id(b""), "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
        )

    def test_caller_verification_json_has_no_input_slot(self):
        self.assertNotIn("verification", bridge.verify_attestation_binding.__annotations__)


@unittest.skipUnless(
    os.environ.get("COGNOUS_EVIDENCE_ATTESTATION_ROOT"),
    "set COGNOUS_EVIDENCE_ATTESTATION_ROOT to pinned upstream source checkout",
)
class PinnedUpstreamIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.checkout = Path(
            os.environ["COGNOUS_EVIDENCE_ATTESTATION_ROOT"]
        ).resolve()
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
        if sys.path and sys.path[0] == str(cls.checkout):
            sys.path.pop(0)

    def fixture(
        self,
        *,
        trust_update=None,
        statement_update=None,
        signature_override=None,
    ):
        key = self.Ed25519PrivateKey.generate()
        public = base64.b64encode(
            key.public_key().public_bytes(
                self.serialization.Encoding.Raw,
                self.serialization.PublicFormat.Raw,
            )
        ).decode()
        statement = {
            "protocol_version": "bitrep-attestation/1",
            "algorithm": "Ed25519",
            "attestation_id": "att:test:1",
            "issuer": "issuer:test",
            "key_id": "key:1",
            "subject": "claim:test",
            "statement_type": "supports",
            "audience": "deployment:test",
            "content_digest": "sha256:" + "ab" * 32,
            "issued_at": NOW - 10,
            "not_before": NOW - 10,
            "expires_at": NOW + 50,
        }
        if statement_update:
            statement.update(statement_update)
        model = self.SignedStatement(**statement)
        signature = base64.b64encode(
            key.sign(self.canonical_bytes(model))
        ).decode()
        if signature_override is not None:
            signature = signature_override
        trust = {
            "registry_version": "bitrep-trust/1",
            "audience": "deployment:test",
            "published_at": NOW - 100,
            "valid_until": NOW + 100,
            "keys": [
                {
                    "issuer": "issuer:test",
                    "key_id": "key:1",
                    "public_key": public,
                    "valid_from": NOW - 100,
                    "valid_until": NOW + 100,
                    "revoked_at": None,
                }
            ],
        }
        if trust_update:
            trust["keys"][0].update(trust_update)
        expected = _expected(statement, self.statement_digest(model))
        return {"statement": statement, "signature": signature}, trust, expected

    def run_bridge(self, attestation, trust, expected):
        with tempfile.TemporaryDirectory() as td:
            return bridge.verify_attestation_binding(
                verifier_checkout=self.checkout,
                verifier_revision=bridge.ATTESTATION_REVISION,
                trust_snapshot_path=_trust_file(td, trust),
                trusted_time=NOW,
                attestation=attestation,
                expected=expected,
            )

    def test_valid_signature_and_exact_binding(self):
        att, trust, expected = self.fixture()
        got = self.run_bridge(att, trust, expected)
        self.assertEqual(got["status"], "verified")
        self.assertEqual(
            got["upstream_verification"]["assurance"],
            "issuer_signature_only",
        )
        self.assertEqual(got["authority"], "not_established")
        self.assertNotIn("grant", got)

    def test_revoked_key_rejected(self):
        att, trust, expected = self.fixture(
            trust_update={"revoked_at": NOW}
        )
        got = self.run_bridge(att, trust, expected)
        self.assertEqual(
            (got["status"], got["reason"]),
            ("rejected", "key_revoked"),
        )

    def test_expired_key_rejected(self):
        att, trust, expected = self.fixture(
            trust_update={"valid_until": NOW}
        )
        got = self.run_bridge(att, trust, expected)
        self.assertEqual(
            (got["status"], got["reason"]),
            ("rejected", "key_expired"),
        )

    def test_malformed_signature_rejected(self):
        att, trust, expected = self.fixture(
            signature_override="!" * 88
        )
        got = self.run_bridge(att, trust, expected)
        self.assertEqual(
            (got["status"], got["reason"]),
            ("rejected", "invalid_signature"),
        )

    def test_unsupported_statement_revision_rejected(self):
        att, trust, expected = self.fixture(
            statement_update={"protocol_version": "bitrep-attestation/2"}
        )
        got = self.run_bridge(att, trust, expected)
        self.assertEqual(
            (got["status"], got["reason"]),
            ("rejected", "unsupported_version"),
        )

    def test_wrong_statement_digest_reference_rejected(self):
        att, trust, expected = self.fixture()
        expected["statement_digest"] = "sha256:" + "0" * 64
        got = self.run_bridge(att, trust, expected)
        self.assertEqual(
            (got["status"], got["reason"]),
            ("rejected", "statement_digest_mismatch"),
        )

    def test_wrong_content_digest_reference_rejected(self):
        att, trust, expected = self.fixture()
        expected["content_digest"] = "sha256:" + "0" * 64
        got = self.run_bridge(att, trust, expected)
        self.assertEqual(
            (got["status"], got["reason"]),
            ("rejected", "content_digest_mismatch"),
        )

    def test_wrong_audience_reference_rejected(self):
        att, trust, expected = self.fixture()
        expected["audience"] = "deployment:other"
        got = self.run_bridge(att, trust, expected)
        self.assertEqual(
            (got["status"], got["reason"]),
            ("rejected", "audience_mismatch"),
        )

    def test_wrong_subject_reference_rejected(self):
        att, trust, expected = self.fixture()
        expected["subject"] = "claim:other"
        got = self.run_bridge(att, trust, expected)
        self.assertEqual(
            (got["status"], got["reason"]),
            ("rejected", "subject_mismatch"),
        )

    def test_exact_statement_difference_rejected(self):
        att, trust, expected = self.fixture()
        expected["statement"]["statement_type"] = "denies"
        got = self.run_bridge(att, trust, expected)
        self.assertEqual(
            (got["status"], got["reason"]),
            ("rejected", "statement_mismatch"),
        )


if __name__ == "__main__":
    unittest.main()
