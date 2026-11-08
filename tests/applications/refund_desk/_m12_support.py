"""Shared support for the Refund Desk M1-2 developer checks (Amendment M2).

DEVELOPMENT ONLY / SYNTHETIC / test-owner developer checks, NOT independent qualification.
Expectations are frozen in applications/refund_desk/CONTRACT_AND_EXPECTATIONS.md (Amendment M2); nothing here weakens them.

Builds on the predecessor `_support.py` (counters, independent read-only SQLite reads, CLI runner) and adds the M2 case specs, the expected F1
profile identities and the test-owned use of the F1 TEST-TREE fault fixture for the high profile (never through the application).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("_refund_desk_test_support", _HERE / "_support.py")
S = sys.modules.get("_refund_desk_test_support") or importlib.util.module_from_spec(_spec)
sys.modules["_refund_desk_test_support"] = S
if not hasattr(S, "REPO"):
    _spec.loader.exec_module(S)

ROUTINE, HIGH = "refund-routine-v1", "refund-high-v1"
REGISTRY_VERSION = "refund-profiles/0.1.0-dev"
MANIFEST_ID, MANIFEST_VERSION = "refund-integration-pilot-v1", "1.1"
MANIFEST_DIGEST = "sha256:4d1ad6c96bc242c63998231b4df3ad7c86dc2e5e59cdae63afe7bff86e60f6ac"
IDENTITY = {
    ROUTINE: {"profile_id": ROUTINE, "registry_version": REGISTRY_VERSION, "manifest_id": MANIFEST_ID, "manifest_version": MANIFEST_VERSION,
              "manifest_digest": MANIFEST_DIGEST, "action_id": "urn:cognous:action:refund-issue-routine-v1",
              "requirement_id": "urn:cognous:authority-requirement:refund-routine-v1"},
    HIGH: {"profile_id": HIGH, "registry_version": REGISTRY_VERSION, "manifest_id": MANIFEST_ID, "manifest_version": MANIFEST_VERSION,
           "manifest_digest": MANIFEST_DIGEST, "action_id": "urn:cognous:action:refund-issue-high-v1",
           "requirement_id": "urn:cognous:authority-requirement:refund-high-v1"},
}
IDENTITY_KEYS = set(IDENTITY[ROUTINE])

# The two F1 high-profile disclosures, verbatim (F1 owns them; asserted as frozen in M2.2).
HIGH_DISCLOSURES = (
    "the reviewer role of this profile is a synthetic fact alias, not authenticated institutional reviewer authority (authenticated=false)",
    "the manifest's evidence obligations are not evaluated natively (requirement evidence is empty); authorization is not verified supporting evidence",
)
# The three historical application notes, byte-for-byte as shipped before M1-2.
LEGACY_APP_NOTES = (
    "Application note: everything here is synthetic and nonproduction; the destination is a local SQLite file only.",
    "Application note: the evaluation time is a fixed synthetic clock read from the facts fixture, not the wall clock.",
    "Application note: the action manifest is bound by F1 (one allowed synthetic customer, maximum 100.00 USD); "
    "the application cannot widen it.",
)

TENANT, C1, C2 = S.TENANT, "customer-001", "customer-002"
A1 = dict(case_id="HV-M12-A1", tenant_id=TENANT, customer_account=C1, amount=64.25, reason="damaged_item", authority="valid")
A2 = dict(case_id="HV-M12-A2", tenant_id=TENANT, customer_account=C2, amount=150.00, reason="damaged_item", authority="valid",
          profile=HIGH, case_reference="CASE-M12-0001")
A2_BOUNDARY = dict(A2, case_id="HV-M12-A2-MAX", amount=1000.00)
CASE_C_HIGH = dict(case_id="HV-M12-C1", tenant_id=TENANT, customer_account=C2, amount=150.00, reason="damaged_item", authority="valid",
                   profile=HIGH, case_reference="CASE-M12-0002")

# Check B (frozen B1..B7)
B1 = dict(A1, case_id="HV-M12-B1", profile="refund-ghost-v1")
B2 = dict(A2, case_id="HV-M12-B2", customer_account=C1, case_reference="CASE-M12-0003")
B3 = dict(A1, case_id="HV-M12-B3", customer_account=C2)
B4 = dict(A2, case_id="HV-M12-B4", amount=1000.01, case_reference="CASE-M12-0004")
B5 = dict(A2, case_id="HV-M12-B5", case_reference=None)
B6 = dict(A1, case_id="HV-M12-B6", profile=ROUTINE, case_reference="CASE-M12-0005")
B6_OMITTED = dict(A1, case_id="HV-M12-B6O", case_reference="CASE-M12-0005")
B7_ROUTINE = dict(A1, case_id="HV-M12-B7R", authority="revoked")
B7_HIGH = dict(A2, case_id="HV-M12-B7H", authority="revoked", case_reference="CASE-M12-0006")


def make_case(spec: dict):
    """RefundCase from a spec; the new optional fields are passed only when present (omitting them is the legacy construction)."""
    return S.make_case({k: v for k, v in spec.items() if not (k in ("profile", "case_reference") and v is None)})


def cli_args(command: str, spec: dict, state_dir: Path) -> list[str]:
    out = S.cli_args(command, spec, state_dir)
    if spec.get("profile") is not None:
        out += ["--profile", spec["profile"]]
    if spec.get("case_reference") is not None:
        out += ["--case-reference", spec["case_reference"]]
    return out


def load_fault_fixture():
    """Load the F1 TEST-TREE fault fixture by file path under a unique module name (avoids colliding with that directory's own `_support`)."""
    name = "_m12_f1_fault_injection"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, S.F1_TESTS / "_fault_injection.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def build_f1_request(spec: dict, root: Path, state_dir: Path):
    """F1 request via the application's private builder (test-owned use of an application internal)."""
    from refund_desk import desk

    return desk._build_request(make_case(spec), S.make_config(root, state_dir))


def f1_unknown_high(case, root: Path, state_dir: Path, spec: dict = CASE_C_HIGH):
    """Genuine F1 UNKNOWN for the high profile via the F1 TEST-TREE fault fixture (never the application); asserts `unknown` first."""
    F = load_fault_fixture()
    u = F.dispose_with_lost_ack_unavailable_observation(build_f1_request(spec, root, state_dir))
    case.assertEqual(u.disposition, "unknown", u)
    return u
