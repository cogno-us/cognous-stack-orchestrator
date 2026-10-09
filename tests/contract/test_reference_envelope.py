import copy
import json
import pathlib
import unittest

from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "development/schemas/orchestration-reference-v0.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA)
SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


def candidate():
    return {
        "schema_version": "cso-ref/0.1-draft",
        "workflow_id": "wf:demo",
        "correlation_id": "corr:demo",
        "step_id": "step:proposal",
        "source": {
            "repository": "cogno-us/cognous-evidence-registry",
            "revision": SHA,
            "schema_id": "index-lifecycle/1",
        },
        "artifact": {
            "kind": "claim_event",
            "reference": "claim:1",
            "digest": DIGEST,
        },
        "recorded_state": "source_unverified",
        "loss": ["verification_not_established"],
    }


class EnvelopeShapeTests(unittest.TestCase):
    def test_schema_itself_is_valid(self):
        Draft202012Validator.check_schema(SCHEMA)

    def test_minimal_candidate(self):
        VALIDATOR.validate(candidate())

    def test_nullable_fields_are_allowed(self):
        obj = candidate()
        obj.update(tenant_binding_ref=None, effect_ref=None, independent_verification_ref=None)
        VALIDATOR.validate(obj)

    def test_separate_attempt_namespaces(self):
        obj = candidate()
        obj["transport_attempt_ref"] = "delivery:1"
        obj["executor_attempt_ref"] = "effect-attempt:3"
        VALIDATOR.validate(obj)
        self.assertNotEqual(obj["transport_attempt_ref"], obj["executor_attempt_ref"])

    def assert_rejected(self, mutate):
        obj = copy.deepcopy(candidate())
        mutate(obj)
        self.assertFalse(VALIDATOR.is_valid(obj), obj)

    def test_wrong_schema_generation(self):
        self.assert_rejected(lambda x: x.update(schema_version="cso-ref/0.2"))

    def test_missing_source_revision(self):
        self.assert_rejected(lambda x: x["source"].pop("revision"))

    def test_branch_name_not_immutable_sha(self):
        self.assert_rejected(lambda x: x["source"].update(revision="main"))

    def test_wrong_digest(self):
        self.assert_rejected(lambda x: x["artifact"].update(digest="unhashed"))

    def test_fabricated_authorized_field_forbidden(self):
        self.assert_rejected(lambda x: x.update(authorized=True))

    def test_invented_effect_verified_field_forbidden(self):
        self.assert_rejected(lambda x: x.update(effect_verified=True))

    def test_unknown_generic_verdict_forbidden(self):
        self.assert_rejected(lambda x: x.update(verification_status="verified"))

    def test_tenant_whitespace_invalid(self):
        self.assert_rejected(lambda x: x.update(tenant_binding_ref="someone else"))

    def test_unknown_loss_status_invalid(self):
        self.assert_rejected(lambda x: x.update(loss=["everything_verified"]))

    def test_duplicate_loss_status_invalid(self):
        self.assert_rejected(lambda x: x.update(loss=["observation_missing", "observation_missing"]))

    def test_unknown_source_repository_invalid(self):
        self.assert_rejected(lambda x: x["source"].update(repository="unknown-owner/repo"))

    def test_unknown_payload_kind_invalid(self):
        self.assert_rejected(lambda x: x["artifact"].update(kind="execution_grant"))

    def test_unknown_recorded_state_invalid(self):
        self.assert_rejected(lambda x: x.update(recorded_state="authorized"))


if __name__ == "__main__":
    unittest.main()
