"""O5-D-A actual-source qualification helpers.

This module only wires exact pinned upstream Action Manifest and Control Plane
source into the synthetic customer-refund qualification. It does not issue
authority or dispatch an effect.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ACTION_MANIFEST_PIN = "ff5490828b2bf7f6a976da209f3f533701855687"
CONTROL_PLANE_PIN = "2bac7875391cad0a431fa0d75208b7ade39743e3"


def _head(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f"upstream source unavailable at {path}: {exc}") from exc


def require_pinned_sources() -> tuple[Path, Path]:
    manifest = Path(os.environ["COGNOUS_ACTION_MANIFEST_SRC"]).resolve()
    control = Path(os.environ["COGNOUS_CONTROL_PLANE_SRC"]).resolve()
    actual = {"action_manifest": _head(manifest), "control_plane": _head(control)}
    expected = {"action_manifest": ACTION_MANIFEST_PIN, "control_plane": CONTROL_PLANE_PIN}
    if actual != expected:
        raise RuntimeError(f"upstream pin mismatch: expected={expected} actual={actual}")
    for path in (manifest / "src", control / "src"):
        sys.path.insert(0, str(path))
    return manifest, control


def load_upstream():
    manifest_repo, control_repo = require_pinned_sources()

    from agent_action_manifest.binding import manifest_digest, payload_digest, proposal_digest, proposal_mismatches
    from agent_action_manifest.models import AgentActionManifest, RuntimeActionProposalV12

    helper_path = control_repo / "tests" / "test_bounded_authorization.py"
    spec = importlib.util.spec_from_file_location("pinned_control_refund_tests", helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("pinned Control Plane refund helper cannot be loaded")
    helper = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = helper
    spec.loader.exec_module(helper)

    manifest_path = manifest_repo / "examples" / "refund_integration_v1_1.manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("pinned Action Manifest refund example is unavailable")

    # Validate through the actual Action Manifest model, then make the pinned
    # Control Plane helper consume that canonical model projection. This avoids
    # treating the Control Plane repository's copied fixture bytes as proof of
    # cross-repository integration.
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    model = AgentActionManifest.model_validate(raw)
    canonical_manifest = model.model_dump(mode="json", exclude_none=False)

    def actual_manifest():
        return json.loads(json.dumps(canonical_manifest))

    helper.manifest = actual_manifest

    return {
        "manifest_repo": manifest_repo,
        "control_repo": control_repo,
        "helper": helper,
        "manifest_raw": raw,
        "manifest_model": model,
        "ManifestProposal": RuntimeActionProposalV12,
        "manifest_digest": manifest_digest,
        "payload_digest": payload_digest,
        "proposal_digest": proposal_digest,
        "proposal_mismatches": proposal_mismatches,
    }


def decide_with_trusted_owner(flow, proposal, *, now):
    """Call the real pinned decision handler only behind an authenticated owner resolver."""
    if getattr(flow.resolver, "authenticated", False) is not True:
        raise PermissionError("trusted owner resolver required")
    return flow.decide(proposal, now=now)
