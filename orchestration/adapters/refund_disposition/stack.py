"""Pin verification and lazy import of the native development components (DEVELOPMENT ONLY / SYNTHETIC).

Reads `source_pins.json` (a copy of the G3 development tuple; not a source lock). Only the components F1 imports are verified:
control_plane, runtime, replay and institutional_governance, each with HEAD == pin and no modified tracked files. Imports happen only
after verification and each imported module must live inside its pinned checkout. One stack root per process: the native packages are
imported by module name, so a second, different root is refused rather than mixed.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PINS_FILE = Path(__file__).resolve().parent / "source_pins.json"
PINS = json.loads(PINS_FILE.read_text(encoding="utf-8"))
USED = tuple(PINS["used_by_f1"])
IG_DRIVER_DIR = Path("process") / "implementation" / "g2-cp-resolver-dev"


class StackError(RuntimeError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _git(root: Path, *args: str) -> str:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "LC_ALL": "C"}
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env, timeout=60, check=True).stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        raise StackError("git_unavailable_or_not_a_checkout", f"{root}: {exc!r}") from exc


def verify_pins(stack_root: Path) -> dict[str, dict[str, str]]:
    identity: dict[str, dict[str, str]] = {}
    for key in USED:
        pin = PINS["components"][key]
        root = stack_root / key
        if not root.is_dir():
            raise StackError("component_missing", f"{key} not found under {stack_root}")
        head = _git(root, "rev-parse", "HEAD")
        if head != pin:
            raise StackError("component_not_pinned_revision", f"{key}: HEAD {head} != pin {pin}")
        if _git(root, "status", "--porcelain", "--untracked-files=no"):
            raise StackError("component_tree_modified", f"{key}: tracked files modified")
        identity[key] = {"head": head, "tree": _git(root, "rev-parse", "HEAD^{tree}")}
    return identity


@dataclass(frozen=True)
class NativeStack:
    root: Path
    identity: dict
    B: Any  # agent_control_plane.bounded
    RA: Any  # agent_control_plane.runtime_authority
    resolver_module: Any  # IG ig_root_resolver
    engine_effective_grant: Any
    engine_safe_executor: Any
    engine_adapter: Any
    engine_producer: Any
    replay_importers: Any
    cp_manifest_path: Path


_CACHE: NativeStack | None = None


def _inside(module: Any, root: Path, label: str) -> None:
    f = getattr(module, "__file__", None)
    if not f or not Path(f).resolve().is_relative_to(root.resolve()):
        raise StackError("module_outside_pinned_checkout", f"{label}: {f}")


def load_stack(stack_root: Path) -> NativeStack:
    global _CACHE
    stack_root = Path(stack_root).resolve()
    if _CACHE is not None:
        if _CACHE.root != stack_root:
            raise StackError("second_stack_root_refused", f"already loaded {_CACHE.root}; got {stack_root}")
        verify_pins(stack_root)  # cheap re-check: the tree must still be the pinned, clean one on every call
        return _CACHE
    identity = verify_pins(stack_root)
    for sub in (stack_root / "runtime", stack_root / "replay" / "src", stack_root / "institutional_governance" / IG_DRIVER_DIR,
                stack_root / "control_plane" / "src"):
        s = str(sub)
        if s in sys.path:
            sys.path.remove(s)
        sys.path.insert(0, s)  # the verified checkouts win module resolution
    try:
        resolver_module = importlib.import_module("ig_root_resolver")
        B, RA = resolver_module.load_pinned_control_plane(stack_root / "control_plane")
        eg = importlib.import_module("engine.effective_grant")
        se = importlib.import_module("engine.safe_executor")
        ad = importlib.import_module("engine.control_plane_adapter")
        pc = importlib.import_module("engine.producer_contract")
        rp = importlib.import_module("agent_replay_bundle.importers")
    except Exception as exc:  # noqa: BLE001 - surfaced as a structured configuration refusal by the caller
        raise StackError("native_import_failed", repr(exc)) from exc
    for mod, key in ((B, "control_plane"), (eg, "runtime"), (se, "runtime"), (ad, "runtime"), (pc, "runtime"), (rp, "replay"),
                     (resolver_module, "institutional_governance")):
        _inside(mod, stack_root / key, key)
    if not hasattr(rp, "_validate_operation_tenant"):
        raise StackError("replay_lacks_tenant_binding_correction", "imported Replay is not the pinned 7eb7d76e behavior")
    manifest = stack_root / "control_plane" / "tests" / "fixtures" / "refund_integration_v1_1.manifest.json"
    if not manifest.is_file():
        raise StackError("cp_manifest_fixture_missing", str(manifest))
    _CACHE = NativeStack(stack_root, identity, B, RA, resolver_module, eg, se, ad, pc, rp, manifest)
    return _CACHE
