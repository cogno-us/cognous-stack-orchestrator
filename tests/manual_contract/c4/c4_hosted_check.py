"""Hosted C4 frozen-literal checker for the manual workflow (orchestrator-owned; NOT independent) (stdlib only; run as `python -I -B`).

Development-only and fixture-scoped. NOT independent qualification, release evidence or an authenticated-authority claim.
Subcommands (the workflow passes everything else through the environment, never through shell text):
  verify   exact-source and context check before any component code runs (no component import); writes sources.txt and context.json.
  check    comparison of the retained files with the frozen C4 literals. It does not trust the harness's own status/all_ok; it
           re-derives hashes from the retained files and re-observes the Pack-side zero counts and the hold/held semantics directly
           from the retained native Pack dumps. It is orchestrator-owned and is NOT an independent verifier. Writes the checker-derived
           slices, oracle.txt and evidence-manifest.json. Exit 1 on any mismatch or missing/corrupt artifact.
  summary  job summary from the step outcomes and the files that exist; never raises.
Every expected literal below is the frozen contract (Hub #273 comment 6674059997; freeze: Architect decision A1-A9), restated here
independently of the harness; no per-run value (record/bundle/Pack hashes, bundle_id, generated_at, pack_id, decision_id) is ever a golden literal.
The focused-suite counts are NOT literals here: the lead fixes them in the workflow and passes C4_EXPECTED_FUNCTIONAL / C4_EXPECTED_INTEGRITY.
"""
import hashlib
import importlib.metadata as md
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

CASE_GROUP = "c4_manifest_to_pack_one_action_hosted_group"
CASE_P1, CASE_N1, CASE_N2 = ("c4_p1_authorized_chain", "c4_n1_hold_revoked_grant", "c4_n2_flip_hold_to_authorized")
CASES = (CASE_P1, CASE_N1, CASE_N2)
# key -> (repository, sha, tree, env prefix, root env var)
PINS = {
    "action_manifest": ("cogno-us/cognous-action-manifest", "fa170815ef96a54c233d0dd9da821b60debabf8b", "3b0e3772e944aa668c8f4b879588c7cc3e2c32be", "C4_AM", "COGNOUS_C4_ACTION_MANIFEST_ROOT"),
    "control_plane": ("cogno-us/cognous-control-plane", "484fdbd297235dd24148ddb0703f2055a31eabff", "c182939882103015f12c5360fccf377c54e2c4f9", "C4_CP", "COGNOUS_C4_CONTROL_PLANE_ROOT"),
    "replay_bundle": ("cogno-us/cognous-replay-bundle", "93a76e281fcae6a65d2cd1d35376f87442dafb95", "aca6e6b8bdd33d51db3b34bc0c75eff93b9ff88f", "C4_RB", "COGNOUS_C4_REPLAY_BUNDLE_ROOT"),
    "evidence_pack": ("cogno-us/cognous-governance-evidence-pack", "065150852cc2a8abeb748777bb69d72ccd0e03d8", "fe428a89da2e74346648cdfe014462ddc8624c77", "C4_PACK", "COGNOUS_C4_EVIDENCE_PACK_ROOT"),
}
AM_SHA, CP_SHA, RB_SHA, PACK_SHA = (PINS[k][1] for k in ("action_manifest", "control_plane", "replay_bundle", "evidence_pack"))
SUITES = (("test_real_c4.py", "C4_EXPECTED_FUNCTIONAL"), ("test_real_c4_integrity.py", "C4_EXPECTED_INTEGRITY"))
PROPOSAL_PATH = "tests/manual_contract/c1/fixtures/proposal.tenant-alpha.json"
PROPOSAL_SHA = "1033c73e7dbe677cc71520711d3aaacb182952e5c12c8eaa489f24be0014cfe2"
MANIFEST_PATH = "examples/refund_integration_v1_1.manifest.json"  # inside the Action Manifest root
MANIFEST_FILE_SHA = "789ad39596b9e1ef84a726a671883e1cb6b83343da3a31db0a1120906d68c074"
MANIFEST_DIGEST = "sha256:4d1ad6c96bc242c63998231b4df3ad7c86dc2e5e59cdae63afe7bff86e60f6ac"
C2_PRODUCER_SHA = "7c4f2595d7939e4a373586faafc0de86469dc03b791d893d7b27fb328a02a895"
EFFECT_AUTH = "sha256:4e5844d6d53ab6f8694e9c76cb6238ec4110137dd35de73cb0b22963961ecde8"
EFFECT_HOLD = "sha256:d0e4afe09cdf3a52aa3b530b822411b1dff35031973660fbbf9b707415f18465"
PROPOSAL_COMMITMENT = "sha256:becaea3f10b5edf56ea181e0cd62793ebe8262238f948fb72dc5c0389c7f8c53"
TENANT, GENERATION = "tenant-alpha", "bounded-authorization-effect/0.3-strict-tenant"
ACTION_ID = "urn:cognous:action:refund-issue-routine-v1"
PROFILE = "runtime-authority/0.1"
VOCAB = "runtime-authority-reasons/0.1"
DECIDED_AT = "2026-10-05T19:00:00+00:00"
CONFIG_ID = "C4-CP-RUNTIME-PROFILE-STRICT-TENANT-DECIDE-ONLY"
TRANSFORMATION = "agep-manifest-reconstruction-import/0.3.10-strict-tenant-candidate"
VALIDATOR = "agent_replay_bundle.importers.import_bounded_workflow"
ZERO_COUNT_KEYS = ("control_plane_attempt_count", "executor_attempt_count", "attempt_transition_record_count", "destination_effect_count",
                   "effect_observation_count", "reconciliation_count")
PARTIAL_RECORD_TYPES = ["input_time_floors", "resolution_check", "resolution_check_event", "runtime_decision", "runtime_proposal"]
EVIDENCE_SCHEMA = "cognous.orchestrator.c4-evidence/0-candidate"
MANIFEST_SCHEMA = "cognous.orchestrator.c4-hosted-evidence-manifest/0-candidate"
LOCKED = {"pydantic": "2.14.1", "cryptography": "50.0.2", "pytest": "8.4.2"}
LOCK_PATH = ".github/locks/cryptography-pydantic-pytest-513753.txt"
HOSTED_SOURCES = ("tests/manual_contract/real_c4.py", "tests/manual_contract/c4_producer.py", "tests/manual_contract/c2_producer.py",
                  "tests/manual_contract/real_c3.py", "tests/manual_contract/c4/test_real_c4.py", "tests/manual_contract/c4/test_real_c4_integrity.py",
                  "tests/manual_contract/c4/c4_hosted_check.py", LOCK_PATH)
BOUNDARIES = ("action_manifest", "control_plane", "replay_bundle", "evidence_pack")
FOUND = ("sources.txt", "context.json")
RAW_P1 = tuple("c4.p1.%s.json" % n for n in ("cp-record", "destination", "reconstruction-bundle", "evidence-pack"))
RAW_N1 = tuple("c4.n1.%s.json" % n for n in ("cp-record", "destination", "reconstruction-bundle", "evidence-pack"))
RAW_OTHER = ("c4.inputs.am-manifest.json", "c4.inputs.proposal.json", "c4.n2.mutated-bundle.json")
INPUTS = ("tests.json", "cases.json", "tests.log", "c4.result.json") + RAW_OTHER + RAW_P1 + RAW_N1
SLICES = (("p1.result.json", CASE_P1), ("n1-hold.result.json", CASE_N1), ("n2-flip.result.json", CASE_N2))
DERIVED = ("p1.pack-validation-report.json", "n1.pack-validation-report.json", "c4-crosswalk.json", "limits-L1-L27.json", "boundary-verdicts.json")
LIMIT_STATUS = "DEVELOPMENT_TESTED_NOT_INDEPENDENTLY_QUALIFIED_FIXTURE_SCOPED"
LIMIT_FLAGS = {"decision_semantics_only": True, "effect_executed": False, "non_authorizing": True,
               "no_certification_clearance_or_production_readiness": "HOLD", "hub_280_digest_basis": "OPEN"}
# L1-L19: the C3 contract section 9 text as carried by the C3 harness (comment 6671327666), restated here verbatim.
LIMIT_TEXT_L1_L19 = {
    1: "Replay is reconstruction_partial with exactly B004 (a decision-only run); never complete.",
    2: "Authority is synthetic and unauthenticated (test-only public Ed25519 key); authorization: authorized in the pack is a retained "
       "historical record, not current permission.",
    3: "Journal association is proposal-level only; event_decision_linkage NOT_ESTABLISHED; decision_id is null on all events.",
    4: "Zero executor attempts and zero destination effects; no effect is inferred and none is verified.",
    5: "The C1 original-record incompatibility with Replay is preserved.",
    6: "Lineage to C1/C2 is identity/proposal-level, not decision-exact.",
    7: "signed=false; no signature is verified; HMAC/digest is not issuer identity.",
    8: "No custody chain; embedded retention is not custody.",
    9: "No freshness; generated_at is uncompared.",
    10: "Provenance labels (CP/RB revision, generation, manifest revision) are caller-asserted; input_artifacts[*].trusted_revision is a "
        "field name, not a trust finding: its values are Pack constants / the verifier's installed Replay, nothing verifies where the supplied "
        "files came from, and the Pack's recorded Replay revision is the verifier's, not the producer's.",
    11: "Pack valid=True means internally consistent, not reviewer approval, compliance or audit.",
    12: "semantically_valid and valid_bundle_count=1 on a partial pack are not completeness.",
    13: "Tenant is verified by Replay only, not by the Pack (the Pack has no tenant field).",
    14: "Replay, redelivery and substitution are not defended.",
    15: "Hub #280 digest-basis divergence is OPEN.",
    16: "The Pack's Replay pin (its CP-2 row) is a PROVISIONAL DEVELOPMENT PIN, UNQUALIFIED, and not the Pack-selected pair.",
    17: "Developer-scope only: not independently qualified, not production, no certification or clearance (HOLD).",
    18: "Engineering Constitution adoption is UNVERIFIED.",
    19: "The Pack carries no hash of the raw Control Plane record: retained_sources holds only the manifest and the reconstruction bundle; "
        "CP-record to bundle linkage is per-run harness evidence only.",
}
LIMIT_PHRASES = {
    1: ("reconstruction_partial", "b004", "never complete"),
    2: ("synthetic", "unauthenticated", "test-only public ed25519 key", "not current permission"),
    3: ("proposal-level only", "event_decision_linkage not_established", "decision_id is null"),
    4: ("zero executor attempts", "zero destination effects", "none is verified"),
    5: ("original-record incompatibility", "preserved"),
    6: ("identity/proposal-level", "not decision-exact"),
    7: ("signed=false", "no signature is verified", "not issuer identity"),
    8: ("no custody chain", "not custody"),
    9: ("no freshness", "generated_at is uncompared"),
    10: ("caller-asserted", "field name, not a trust finding", "pack constants", "nothing verifies where the supplied", "verifier's, not the producer's"),
    11: ("valid=true", "not reviewer approval", "compliance or audit"),
    12: ("semantically_valid", "valid_bundle_count=1", "not completeness"),
    13: ("verified by replay only", "not by the pack"),
    14: ("not defended",),
    15: ("hub #280", "open"),
    16: ("provisional", "unqualified"),
    17: ("not independently qualified", "not production", "hold"),
    18: ("constitution", "unverified"),
    19: ("no hash of the raw control plane record", "retained_sources", "reconstruction bundle", "harness evidence only"),
    # L20-L27: contract section 16 (new C4 limits), key phrases only
    20: ("action manifest", "produces no proposal", "hand-authored", "hash-pinned"),
    21: ("profile-enabled", "not the c1 configuration", "identity level only"),
    22: ("hold", "does not bind", "no first-class tenant field", "orchestrator-extracted"),
    23: ("effect_id differs by verdict",),
    24: ("run-1", "literal", "not a run identity", "no native per-run end-to-end identity"),
    25: ("not component statuses", "decide()", "observed"),
    26: ("synthetic grant-status input variation", "not a real revocation event"),
    27: ("persisted by no component", "deny", "unexercised"),
}
LIMIT_KEYS = {"status", "bundle_hash_semantics", "uncompared_by_pack", "known_limitations_not_oracles", "synthetic_key_scope",
              *LIMIT_FLAGS, *("L%d" % n for n in LIMIT_PHRASES)}
# crosswalk rows that must exist as NOT LINKED / NOT CARRIED (contract section 6): keyword groups, all must match one row name
CROSSWALK_NOT_LINKED = (("check_id", "decision_id"), ("raw", "record", "bundle"), ("h1", "h2"), ("effect_id", "across"), ("hold", "proposal"),
                        ("producer config",), ("repository",), ("c1", "record"))
FORBIDDEN_CLAIMS = (r"complete reconstruction", r"fully reconstructed", r"reconstruction_complete(?!ness)", r"\bauthenticated authority",
                    r"\bverified execution", r"\bexecution verified", r"\bcertified\b", r"\bapproved\b", r"production[ -]ready",
                    r"\bindependently qualified", r"\bcompliant\b", r"\bcleared for\b", r"\bclearance granted")
NOT_EXECUTED = ("N3-GATE (deferred: the mutated byte is not pinned at freeze)", "hold identity binding in Replay and the Pack (limit L22: not bound natively)",
                "Control Plane deny and effect-time refusal paths", "revocation, expiry and stale-record replay", "partial failure and incomplete journal",
                "complete reconstruction", "executor attempts, destination effects, effect observation and reconciliation records",
                "signature verification, custody chain and freshness checks", "Pack reviewer approval or audit",
                "independent qualification, institutional authority, authenticity, release and production")
LIMITATIONS = ("synthetic unauthenticated authority; test-only public Ed25519 key", "Replay is reconstruction_partial (B004, plus B005 for the hold), never complete reconstruction",
               "Pack valid=True means internally consistent only, not reviewer approval, compliance or audit; for the hold it is not authorization of the action",
               "the Pack carries no hash of the raw Control Plane record; CP-record to bundle linkage is per-run harness evidence only",
               "the Action Manifest component produces no proposal; the proposal is a hand-authored hash-pinned fixture",
               "for a hold, Replay does not bind the supplied proposal, tenant, action or correlation to the record",
               "Replay pin in the Pack is a PROVISIONAL, UNQUALIFIED development pin", "Hub #280 digest-basis divergence is OPEN",
               "Engineering Constitution adoption is UNVERIFIED", "hosted developer evidence only: not independent qualification")
QUALIFICATION = "NOT independent qualification; hosted developer evidence only"
NA_DISPOSITION = ("N-A (harness-side pack_derived_counts_zero mutation survivors): closed for the hosted checker by direct observation of the six "
                  "derived_counts keys in both retained native Pack dumps (P1 and N1-HOLD: present, int and not bool, == 0); it remains an "
                  "implementation-level limitation of the harness-side assertion, which this checker does not edit or replace")


class Fail(Exception):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def evidence_dir():
    return pathlib.Path(os.environ["EVIDENCE_DIR"])


def git(root, *args):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
           "LC_ALL": "C", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1"}
    try:
        done = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(root), *args], cwd=tempfile.gettempdir(), env=env,
                              capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Fail("git failed for %s: %s" % (root, type(exc).__name__)) from None
    if done.returncode != 0:
        raise Fail("%s is not a usable git checkout (git %s failed)" % (root, args[0]))
    return done.stdout.strip()


def strict_loads(data):
    def pairs(items):
        keys = [k for k, _ in items]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate object member refused")
        return dict(items)

    def const(name):
        raise ValueError("non-finite number %s refused" % name)
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=const)


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def h2_of(obj):
    """The Pack's canonical-JSON hash, restated here independently of the Pack helper."""
    return "sha256:" + sha(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"))


def ascii_line(text):
    return " ".join(str(text).split()).encode("ascii", "replace").decode("ascii")


# ------------------------------------------------------------------ verify
def verify():
    ev = evidence_dir()
    ev.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(os.environ.get("GITHUB_WORKSPACE") or os.getcwd()).resolve()
    ctx = {"repository": os.environ.get("GITHUB_REPOSITORY"), "github_sha": os.environ.get("GITHUB_SHA"), "github_ref": os.environ.get("GITHUB_REF"),
           "github_run_id": os.environ.get("GITHUB_RUN_ID"), "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
           "case_id": os.environ.get("CASE_ID"), "workflow": os.environ.get("GITHUB_WORKFLOW"), "event_name": os.environ.get("GITHUB_EVENT_NAME"),
           "runner": {k: os.environ.get(k) for k in ("RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion", "RUNNER_ENVIRONMENT")},
           "python_version": sys.version, "platform": sys.platform, "case_group": CASE_GROUP, "cases": list(CASES), "dependencies": {},
           "components": {}, "fixtures": {}, "host_sources": {}, "pip_version": os.environ.get("PIP_VERSION_TEXT")}
    lines, failures = [], []

    def step(label, fn):
        try:
            fn()
        except (Fail, OSError, KeyError, ValueError, TypeError, AttributeError) as exc:
            failures.append("%s: %s" % (label, str(exc)[:300] if isinstance(exc, Fail) else "%s %s" % (type(exc).__name__, str(exc)[:200])))

    def fail(msg):
        raise Fail(msg)

    if ctx["case_id"] != CASE_GROUP:
        failures.append("case_id %r is not the C4 hosted group %r" % (ctx["case_id"], CASE_GROUP))
    if ctx["event_name"] != "workflow_dispatch":
        failures.append("event is %r, not workflow_dispatch" % ctx["event_name"])
    if ctx["github_ref"] != "refs/heads/main":
        failures.append("dispatched ref is %r; the C4 hosted run is allowed only from refs/heads/main" % ctx["github_ref"])
    try:
        ctx["git_version"] = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=30, check=False).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        ctx["git_version"] = None

    def orchestrator():
        head = git(work, "rev-parse", "HEAD")
        ctx["orchestrator_head"] = head
        if not ctx["github_sha"] or head != ctx["github_sha"]:
            fail("orchestrator HEAD %s != GITHUB_SHA %s" % (head, ctx["github_sha"]))
        if git(work, "status", "--porcelain", "--untracked-files=no") != "":
            fail("orchestrator checkout has modified tracked files")
        lines.append("orchestrator: head==GITHUB_SHA==%s, tracked files clean" % head)
    step("orchestrator", orchestrator)

    for key, (repo, want_sha, want_tree, prefix, env_root) in PINS.items():
        def component(key=key, repo=repo, want_sha=want_sha, want_tree=want_tree, prefix=prefix, env_root=env_root):
            if (os.environ.get(prefix + "_SHA"), os.environ.get(prefix + "_TREE")) != (want_sha, want_tree):
                fail("%s: workflow pin %s_SHA/%s_TREE differs from the checker's frozen pin (workflow/checker drift)" % (key, prefix, prefix))
            raw = os.environ.get(env_root)
            if not raw:
                fail("%s: %s is not set" % (key, env_root))
            root = pathlib.Path(raw).resolve()
            ctx["components"][key] = {"repository": repo, "sha": want_sha, "tree": want_tree, "root": str(root)}
            got = git(root, "rev-parse", "HEAD")
            if got != want_sha:
                fail("%s HEAD is %s, expected %s" % (key, got, want_sha))
            got = git(root, "rev-parse", "HEAD^{tree}")
            if got != want_tree:
                fail("%s tree is %s, expected %s" % (key, got, want_tree))
            if git(root, "rev-parse", "--show-toplevel") != str(root):
                fail("%s toplevel is not %s" % (key, root))
            tags = {line[:2] for line in git(root, "ls-files", "-v").splitlines()}
            if tags != {"H "}:
                fail("%s has tracked files with a tag other than H: %s" % (key, sorted(tags)))
            if git(root, "status", "--porcelain", "--ignored=matching", "--untracked-files=all") != "":
                fail("%s working tree is not clean (modified, untracked or ignored files)" % key)
            lines.extend([key, "  repository: " + repo, "  root: " + str(root), "  sha: " + want_sha, "  tree: " + want_tree,
                          "  checks passed: head==pin, tree==pin, toplevel==root, ls-files all H, status clean (ignored and untracked included)"])
        step("component " + key, component)

    def fixture(name, path, want, base):
        def run():
            got = sha((base / path).read_bytes())
            ctx["fixtures"][name] = {"path": path, "sha256": got, "frozen_sha256": want}
            if got != want:
                fail("fixture %s sha256 %s differs from the frozen %s" % (path, got, want))
        step("fixture " + name, run)
    fixture("proposal", PROPOSAL_PATH, PROPOSAL_SHA, work)
    am_root = os.environ.get(PINS["action_manifest"][4])
    if am_root:
        fixture("action_manifest_fixture", MANIFEST_PATH, MANIFEST_FILE_SHA, pathlib.Path(am_root).resolve())
    else:
        failures.append("fixture action_manifest_fixture: %s is not set" % PINS["action_manifest"][4])
    lines.append("fixtures: proposal and Action Manifest fixture compared with their frozen sha256")

    for rel in HOSTED_SOURCES:
        try:
            ctx["host_sources"][rel] = sha((work / rel).read_bytes())
        except OSError:
            failures.append("host source %s is missing or unreadable" % rel)
    if ctx["host_sources"].get("tests/manual_contract/c2_producer.py") not in (None, C2_PRODUCER_SHA):
        failures.append("c2_producer.py sha256 %s differs from the frozen %s" % (ctx["host_sources"]["tests/manual_contract/c2_producer.py"], C2_PRODUCER_SHA))
    for name in ("pydantic", "pydantic_core", "cryptography", "pytest"):
        try:
            ctx["dependencies"][name] = md.version(name)
        except md.PackageNotFoundError:
            ctx["dependencies"][name] = None
    for name, want in LOCKED.items():
        if not ctx["dependencies"].get(name):
            failures.append("dependency %s is not installed" % name)
        elif ctx["dependencies"][name] != want:
            failures.append("dependency %s is %s, the lock requires %s" % (name, ctx["dependencies"][name], want))
    ctx["dependency_lock_sha256"] = ctx["host_sources"].get(LOCK_PATH)
    ctx["verify"] = "FAIL" if failures else "PASS"
    ctx["verify_failures"] = failures
    for f in failures:
        lines.append("SOURCE VERIFICATION FAILED: " + f)
        print("SOURCE VERIFICATION FAILED: " + f, file=sys.stderr)
    write_json(ev / "context.json", ctx)
    (ev / "sources.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 1 if failures else 0


# ------------------------------------------------------------------ check
def same(a, b):
    """Equality that also requires identical types at every depth (so True is not 1, 0.0 is not 0, a tuple is not a list)."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


class Checks:
    def __init__(self):
        self.rows, self.failed = [], 0

    def eq(self, name, want, got):
        ok = same(want, got)
        self.rows.append(("OK" if ok else "FAIL", name, want, got))
        self.failed += 0 if ok else 1
        return ok

    def true(self, name, cond):
        return self.eq(name, True, bool(cond))

    def text(self):
        out = []
        for status, name, want, got in self.rows:
            out.append(ascii_line("%s %s" % (status, name)) if status == "OK" else ascii_line("FAIL %s -- expected %s, got %s" % (
                name, json.dumps(want, default=str)[:200], json.dumps(got, default=str)[:200])))
        return out


def load(c, ev, name):
    """Read one mandatory evidence file; JSON files are parsed strictly. Returns (obj, bytes) or (None, None) after a named FAIL."""
    try:
        data = (ev / name).read_bytes()
        obj = strict_loads(data) if name.endswith(".json") else None
    except (OSError, ValueError, RecursionError) as exc:
        c.eq("artifact %s readable and strict JSON" % name, "present", "%s: %s" % (type(exc).__name__, str(exc)[:100]))
        return None, None
    c.true("artifact %s present and non-empty" % name, len(data) > 0)
    return obj, data


def walk(obj, path=()):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, path + (str(k),))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, path + (i,))
    else:
        yield path, obj


def d(obj, *keys):
    for k in keys:
        obj = obj.get(k) if isinstance(obj, dict) else None
    return obj


def as_dict(x):
    return x if isinstance(x, dict) else {}


def as_list(x):
    return x if isinstance(x, list) else []


def diff_paths(a, b, path="$"):
    """Every path at which two JSON values differ (independent restatement; lists compared index-wise)."""
    if type(a) is not type(b):
        return [path]
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append("%s.%s" % (path, k))
            else:
                out += diff_paths(a[k], b[k], "%s.%s" % (path, k))
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [path + ".length"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_paths(x, y, "%s[%d]" % (path, i))
        return out
    return [] if a == b else [path]


def boundaries_of(r):
    out = {}
    for b in as_list(r.get("boundaries") if isinstance(r, dict) else None):
        if isinstance(b, dict) and isinstance(b.get("boundary"), str):
            out[b["boundary"]] = b
    return out


def check_limit_texts(c, limits):
    if not isinstance(limits, dict):
        return
    for n in range(1, 20):
        c.eq("limits L%d text is the C3 contract section 9 text (verbatim)" % n, LIMIT_TEXT_L1_L19[n], limits.get("L%d" % n))
    for n, phrases in LIMIT_PHRASES.items():
        text = limits.get("L%d" % n)
        ok = isinstance(text, str) and bool(text.strip())
        c.true("limits L%d is a non-empty string" % n, ok)
        low = text.lower() if ok else ""
        missing = [p for p in phrases if p not in low]
        c.eq("limits L%d carries its key phrases" % n, [], missing)
    c.true("limits bundle_hash_semantics says never interchangeable", "never interchangeable" in str(limits.get("bundle_hash_semantics")))
    ub = limits.get("uncompared_by_pack")
    c.true("limits uncompared_by_pack names bundle_id, generated_at and integrity", isinstance(ub, list) and all(x in ub for x in ("bundle_id", "generated_at", "integrity")))
    kl = limits.get("known_limitations_not_oracles")
    c.true("limits known_limitations_not_oracles has 4 entries", isinstance(kl, list) and len(kl) == 4)
    c.true("limits synthetic_key_scope names the test-only range(32) key", "range(32)" in str(limits.get("synthetic_key_scope")))
    neg = re.compile(r"\b(not|no|never|neither|nor|without)\b|\bun[a-z]+", re.I)
    bad = []
    for k, v in limits.items():
        if isinstance(v, str):
            low = v.lower()
            for pat in FORBIDDEN_CLAIMS:
                for m in re.finditer(pat, low):
                    if not neg.search(low[max(0, m.start() - 40):m.start() + len(m.group(0))]):
                        bad.append(k)
    c.eq("limits state no forbidden claim without a negation", [], bad)


def check_limits(c, label, limits, ref):
    c.true("%s limits is an object" % label, isinstance(limits, dict))
    if not isinstance(limits, dict):
        return
    missing = sorted(k for k in LIMIT_KEYS if k not in limits)
    c.eq("%s limits keys L1..L27, status and flags all present (no key dropped)" % label, [], missing)
    c.eq("%s limits identical to the P1 limits block" % label, ref, limits)
    c.eq("%s limits status" % label, LIMIT_STATUS, limits.get("status"))
    for k, v in LIMIT_FLAGS.items():
        c.eq("%s limits flag %s" % (label, k), v, limits.get(k))


def check_claims(c, results):
    scanned, bad = 0, []
    for cid, entry in results.items():
        for path, value in walk(entry):
            if not isinstance(value, str) or "limits" in path or "known_not_executed" in path:  # negated by construction
                continue
            scanned += 1
            low = value.lower()
            for pat in FORBIDDEN_CLAIMS:
                if re.search(pat, low):
                    bad.append("%s/%s: %s" % (cid, "/".join(map(str, path)), pat))
    c.eq("no positive claim-promotion string outside limits (complete reconstruction, authenticated authority, approved, certified, verified execution)", [], bad[:5])
    c.true("claim scan is not vacuous", scanned > 100)


def check_sources(c, label, r, roots):
    s = as_dict(r.get("sources"))
    for key, (_, want_sha, want_tree, _, _) in PINS.items():
        o = as_dict(d(s, "sources", key) or d(s, key))
        c.eq("%s measured %s head/tree" % (label, key), (want_sha, want_tree), (o.get("observed_head"), o.get("observed_tree")))
        c.true("%s %s clean flags" % (label, key), o.get("tracked_files_clean") is True and o.get("ls_files_all_H") is True and o.get("status_ignored_clean") is True)
    return roots


def decision_record(bundle):
    decs = [x for x in as_list(bundle.get("records") if isinstance(bundle, dict) else None) if isinstance(x, dict) and x.get("record_type") == "runtime_decision"]
    return decs


def findings_of(bundle):
    return [[f.get("code"), f.get("severity")] for rep in as_list(bundle.get("import_reports")) if isinstance(rep, dict)
            for f in as_list(rep.get("findings")) if isinstance(f, dict)]


def check_zero_counts(c, label, T):
    dc = as_dict(T.get("derived_counts"))
    for k in ZERO_COUNT_KEYS:
        v = dc.get(k)
        c.true("N-A %s derived_counts.%s is present, an int (not bool) and == 0 (direct observation of the retained Pack dump)" % (label, k),
               k in dc and type(v) is int and v == 0)
    return dc


def check_hashes_vs_harness(c, label, r, rec_bytes, bundle_bytes, bundle, pack_bytes, pack):
    per = as_dict(d(r, "identity", "per_run"))
    h1, h2 = sha(bundle_bytes), h2_of(bundle)
    c.eq("%s record sha256: recomputed from the retained file == harness report" % label, sha(rec_bytes), per.get("cp_record_sha256"))
    c.eq("%s bundle H1 sha256: recomputed from the retained file == harness report" % label, h1, per.get("bundle_h1_sha256"))
    c.eq("%s bundle H2 (Pack canonical hash): recomputed from the parsed bundle file == harness report" % label, h2, per.get("bundle_h2_pack_canonical_sha256"))
    c.true("%s H1 and H2 are distinct values" % label, ("sha256:" + h1) != h2)
    c.eq("%s Pack file sha256: recomputed from the retained dump == harness report" % label, sha(pack_bytes), per.get("pack_file_sha256"))
    c.eq("%s bundle_id (retained file) == harness report" % label, bundle.get("bundle_id"), per.get("bundle_id"))
    c.eq("%s generated_at (retained file) == harness report" % label, bundle.get("generated_at"), per.get("generated_at"))
    c.eq("%s pack_id (dump) == harness report" % label, pack.get("pack_id"), per.get("pack_id"))
    return h1, h2


def check_cp_common(c, label, rec, dest, r):
    decs = as_list(rec.get("decisions"))
    c.eq("%s native record file has exactly one decision" % label, 1, len(decs))
    dd = as_dict(decs[0]) if decs else {}
    events = as_list(rec.get("check_events"))
    c.eq("%s CP record has 13 check_events" % label, 13, len(events))
    c.eq("%s CP check_events: every decision_id is null (proposal-level association only)" % label, [None] * len(events), [e.get("decision_id") if isinstance(e, dict) else 0 for e in events])
    c.eq("%s CP check_events: proposal commitment on every event" % label, [PROPOSAL_COMMITMENT] * len(events),
         [e.get("proposal_commitment") if isinstance(e, dict) else 0 for e in events])
    c.eq("%s attempts/observations/reconciliations/closeouts/refusals empty (native record file)" % label, {k: [] for k in ("attempts", "closeouts", "observations", "reconciliations", "refusals")},
         {k: rec.get(k) for k in ("attempts", "closeouts", "observations", "reconciliations", "refusals")})
    c.eq("%s destination effects (retained destination file)" % label, {}, dest.get("effects"))
    c.eq("%s destination effect count and effects (harness result)" % label, (0, {}), (d(r, "destination", "effect_count"), d(r, "destination", "effects")))
    c.eq("%s CP decision time_source / decided_at / vocabulary" % label, ("test_override", DECIDED_AT, VOCAB),
         (dd.get("time_source"), dd.get("decided_at"), dd.get("reason_vocabulary_version")))
    c.eq("%s CP decision operation_horizon.proposal_commitment" % label, PROPOSAL_COMMITMENT, d(dd, "operation_horizon", "proposal_commitment"))
    return dd


def check_producer(c, label, r, scenario, mutation):
    p = as_dict(r.get("producer"))
    c.eq("%s producer calls == [decide] only" % label, ["decide"], p.get("calls"))
    c.eq("%s producer scenario / mutation" % label, (scenario, mutation), (p.get("scenario"), p.get("scenario_mutation")))
    c.eq("%s producer manifest source" % label, ("supplied_validated_AM_bytes", True), (p.get("manifest_source"), p.get("manifest_equals_cp_repo_copy")))


def check_pack_common(c, label, pack, bundle, manifest_obj, h2):
    T = as_dict(d(pack, "metadata", "traceable_import"))
    c.eq("%s Pack pack_version" % label, "0.2.0", pack.get("pack_version"))
    c.eq("%s Pack review_status draft" % label, "draft", pack.get("review_status"))
    c.eq("%s Pack transformation_version" % label, TRANSFORMATION, T.get("transformation_version"))
    c.eq("%s Pack selected_revisions" % label, {"manifest": AM_SHA, "replay": RB_SHA, "control_plane": CP_SHA}, T.get("selected_revisions"))
    c.eq("%s Pack replay_semantic_validation" % label, {"validator": VALIDATOR, "required_revision": RB_SHA, "status": "validated_partial"}, T.get("replay_semantic_validation"))
    rbs = pack.get("replay_bundles")
    rb0 = rbs[0] if isinstance(rbs, list) and rbs and isinstance(rbs[0], dict) else {}
    c.eq("%s Pack replay_bundles has exactly one entry" % label, 1, len(rbs) if isinstance(rbs, list) else None)
    c.eq("%s Pack replay_bundles[0] status/signed/redacted/validation_status" % label, ("validated_partial", False, False, "semantically_valid"),
         (rb0.get("status"), rb0.get("signed"), rb0.get("redacted"), rb0.get("validation_status")))
    c.eq("%s Pack replay_bundles[0].bundle_id == bundle file bundle_id" % label, bundle.get("bundle_id"), rb0.get("bundle_id"))
    c.eq("%s Pack reconstruction_completeness" % label, "reconstruction_partial", T.get("reconstruction_completeness"))
    sem = as_dict(T.get("replay_semantics"))
    c.eq("%s Pack replay_semantics flags" % label, {"policy_reevaluation": False, "external_effect_execution": False, "destination_observation": "not_performed",
                                                   "independent_effect_verification": False},
         {k: sem.get(k) for k in ("policy_reevaluation", "external_effect_execution", "destination_observation", "independent_effect_verification")})
    ia = as_list(T.get("input_artifacts"))
    ia0 = ia[0] if ia and isinstance(ia[0], dict) else {}
    ia1 = ia[1] if len(ia) > 1 and isinstance(ia[1], dict) else {}
    c.eq("%s Pack input_artifacts[0].hash == Action Manifest canonical digest" % label, MANIFEST_DIGEST, ia0.get("hash"))
    c.eq("%s Pack input_artifacts[0] role/trusted_revision" % label, ("manifest", AM_SHA), (ia0.get("artifact_role"), ia0.get("trusted_revision")))
    c.eq("%s Pack input_artifacts[1] (bundle) hash == recomputed H2" % label, h2, ia1.get("hash"))
    c.eq("%s Pack input_artifacts[1] role/artifact_id/trusted_revision" % label, ("reconstruction_bundle", bundle.get("bundle_id"), RB_SHA),
         (ia1.get("artifact_role"), ia1.get("artifact_id"), ia1.get("trusted_revision")))
    rs = as_dict(T.get("retained_sources"))
    c.eq("%s Pack retained_sources.reconstruction_bundle == parsed bundle file" % label, bundle, rs.get("reconstruction_bundle"))
    if manifest_obj is not None:
        c.eq("%s Pack retained_sources.manifest == Action Manifest input file parsed" % label, manifest_obj, rs.get("manifest"))
    else:
        c.true("%s Action Manifest input file could be parsed for the retained_sources comparison" % label, False)
    return T, rs


def check_am_gate(c, ctx, data, r, label):
    """AM gate: file hashes recomputed from the retained input copies, compared with the frozen literals and the harness AM boundary."""
    am = boundaries_of(r).get("action_manifest", {})
    c.eq("%s AM boundary orchestration class" % label, "ACCEPTED", am.get("orchestration_class"))
    c.eq("%s AM boundary input sha256 == manifest file hash recomputed from the retained input" % label, data["am_sha"], am.get("input_sha256"))
    c.eq("%s harness-reported manifest sha256 == retained input file" % label, data["am_sha"], d(r, "inputs", "manifest", "sha256"))
    c.eq("%s harness-reported proposal sha256 == retained input file" % label, data["prop_sha"], d(r, "inputs", "proposal", "sha256"))
    gate = as_dict(am.get("native_result"))
    c.eq("%s AM gate native result: valid, canonical digest, proposal digest, no mismatches" % label, (True, MANIFEST_DIGEST, PROPOSAL_COMMITMENT, []),
         (gate.get("valid"), gate.get("manifest_digest"), gate.get("proposal_digest"), gate.get("proposal_mismatches")))
    ag = as_dict(r.get("am_gate"))
    c.eq("%s harness am_gate passed / file hashes" % label, (True, data["am_sha"], data["prop_sha"]),
         (ag.get("passed"), ag.get("manifest_file_sha256"), ag.get("proposal_file_sha256")))
    c.eq("%s harness am_gate digests / mismatches" % label, (MANIFEST_DIGEST, PROPOSAL_COMMITMENT, []),
         (ag.get("manifest_digest"), ag.get("proposal_digest"), ag.get("proposal_mismatches")))


def check_p1(c, ctx, data, roots):
    r = data["results"].get(CASE_P1)
    out = {}
    if not isinstance(r, dict):
        return out
    s = data["p1"]
    rec, dest, bundle, pack = s["cp-record"], s["destination"], s["reconstruction-bundle"], s["evidence-pack"]
    c.eq("P1 schema", EVIDENCE_SCHEMA, r.get("schema"))
    c.eq("P1 case_id", CASE_P1, r.get("case_id"))
    c.eq("P1 scenario", "authorized", r.get("scenario"))
    c.eq("P1 producer config id", CONFIG_ID, d(r, "producer", "config_id"))
    check_sources(c, "P1", r, roots)
    if None in (rec, dest, bundle, pack):
        c.true("P1 retained native files all parsed (CP record, destination, bundle, Pack dump)", False)
        return out
    manifest_obj = data.get("am_obj")
    # ---- AM gate (file hashes and frozen literals; the AM canonical digest is recomputed here from the retained manifest copy)
    check_am_gate(c, ctx, data, r, "P1")
    # ---- CP record file
    dd = check_cp_common(c, "P1", rec, dest, r)
    c.eq("P1 CP result / reasons", ("authorized", []), (dd.get("result"), dd.get("reasons")))
    c.eq("P1 CP effect_id", EFFECT_AUTH, dd.get("effect_id"))
    b = as_dict(dd.get("binding"))
    c.eq("P1 CP binding manifest_digest / proposal_commitment", (MANIFEST_DIGEST, PROPOSAL_COMMITMENT), (b.get("manifest_digest"), b.get("proposal_commitment")))
    c.eq("P1 CP binding tenant / generation / action_id", (TENANT, GENERATION, ACTION_ID), (b.get("tenant_id"), b.get("generation"), b.get("action_id")))
    c.eq("P1 CP binding runtime_authority.profile", PROFILE, d(b, "runtime_authority", "profile"))
    check_producer(c, "P1", r, "authorized", None)
    # ---- Replay from the retained BUNDLE FILE
    c.eq("P1 Replay status (bundle file)", "reconstruction_partial", bundle.get("status"))
    c.eq("P1 Replay findings: exactly B004 warning (bundle file)", [["B004", "warning"]], findings_of(bundle))
    c.eq("P1 Replay import reports are not complete (bundle file)", [False], [rep.get("complete") for rep in as_list(bundle.get("import_reports")) if isinstance(rep, dict)])
    c.eq("P1 Replay integrity [] (bundle file)", [], bundle.get("integrity"))
    c.eq("P1 Replay bundle_version (bundle file)", "0.2.0", bundle.get("bundle_version"))
    types = [x.get("record_type") for x in as_list(bundle.get("records")) if isinstance(x, dict)]
    c.eq("P1 Replay record types (bundle file): no attempt, observation, reconciliation or closeout records", PARTIAL_RECORD_TYPES, sorted(set(types)))
    h1, h2 = check_hashes_vs_harness(c, "P1", r, s["cp-record_bytes"], s["reconstruction-bundle_bytes"], bundle, s["evidence-pack_bytes"], pack)
    # ---- Pack dump, direct observation
    T, rs = check_pack_common(c, "P1", pack, bundle, manifest_obj, h2)
    lc = as_dict(T.get("lifecycle_summary"))
    c.eq("P1 Pack lifecycle_summary", {"authorization": "authorized", "current_permission": "not_evaluated_from_historical_records", "execution_attempted": "no",
                                       "destination_observed": "unknown", "independent_verification": "unavailable", "reconstruction_status": "reconstruction_partial"},
         {k: lc.get(k) for k in ("authorization", "current_permission", "execution_attempted", "destination_observed", "independent_verification", "reconstruction_status")})
    check_zero_counts(c, "P1", T)
    # ---- retained decision chain
    decs = decision_record(bundle)
    c.eq("P1 bundle has exactly one runtime_decision record", 1, len(decs))
    bd = (decs[0].get("data") if len(decs) == 1 else None) or {}
    bbind = as_dict(bd.get("binding"))
    c.eq("P1 retained decision effect_id", EFFECT_AUTH, bd.get("effect_id"))
    c.eq("P1 retained decision proposal commitment", PROPOSAL_COMMITMENT, bbind.get("proposal_commitment"))
    c.eq("P1 retained decision tenant / generation", (TENANT, GENERATION), (bbind.get("tenant_id"), bbind.get("generation")))
    c.eq("P1 retained decision result", "authorized", bd.get("result"))
    c.true("P1 retained decision_id == native record file decision_id (per-run, non-empty)", bool(bd.get("decision_id")) and bd.get("decision_id") == dd.get("decision_id"))
    # ---- validation (harness-reported native Pack validation)
    val = as_dict(d(r, "native", "pack", "validation"))
    c.eq("P1 Pack validation valid (harness-reported)", True, val.get("valid"))
    c.eq("P1 Pack validation errors (harness-reported, zero)", [], val.get("errors"))
    c.true("P1 Pack validation warnings are recorded (not frozen)", isinstance(val.get("warnings"), list))
    # ---- chain
    bs = boundaries_of(r)
    c.eq("P1 boundary order", list(BOUNDARIES), [b.get("boundary") for b in as_list(r.get("boundaries")) if isinstance(b, dict)])
    for name in BOUNDARIES:
        bo = bs.get(name, {})
        c.eq("P1 %s orchestration class ACCEPTED" % name, "ACCEPTED", bo.get("orchestration_class"))
        c.eq("P1 %s retains_upstream_refusal false" % name, False, bo.get("retains_upstream_refusal"))
    for name in BOUNDARIES[1:]:
        c.eq("P1 %s carried authorization state (historical, per L2)" % name, "authorized", bs.get(name, {}).get("carried_authorization_state"))
    c.eq("P1 control_plane native outcome (verbatim)", "authorized", bs.get("control_plane", {}).get("native_outcome"))
    c.eq("P1 control_plane binding present / decision_id / effect_id (harness native result)", (True, dd.get("decision_id"), EFFECT_AUTH),
         tuple(as_dict(bs.get("control_plane", {}).get("native_result")).get(k) for k in ("binding_present", "decision_id", "effect_id")))
    c.eq("P1 chain verdict class", "ACCEPTED", d(r, "chain_verdict", "class"))
    c.true("P1 harness status/oracle (necessary, never sufficient)", r.get("status") == "PASS" and d(r, "oracle", "all_ok") is True)
    st = as_dict(d(r, "identity", "stable"))
    c.eq("P1 identity.stable tuple (action_id, proposal_commitment, manifest_digest, tenant_id)", (ACTION_ID, PROPOSAL_COMMITMENT, MANIFEST_DIGEST, TENANT),
         (st.get("action_id"), st.get("proposal_commitment"), st.get("manifest_digest"), st.get("tenant_id")))
    c.eq("P1 identity.effect_id", EFFECT_AUTH, d(r, "identity", "effect_id"))
    c.eq("P1 identity decision_id (harness) == retained record", dd.get("decision_id"), d(r, "identity", "per_run", "decision_id"))
    c.eq("P1 Pack pack_id (dump) non-empty", True, bool(pack.get("pack_id")))
    out.update(record_sha256=sha(s["cp-record_bytes"]), bundle_h1=h1, bundle_h2=h2, pack_file_sha256=sha(s["evidence-pack_bytes"]),
               destination_file_sha256=sha(s["destination_bytes"]), pack_id=pack.get("pack_id"), bundle_id=bundle.get("bundle_id"),
               generated_at=bundle.get("generated_at"), decision_id=dd.get("decision_id"),
               pack_validation_warning_count=len(val["warnings"]) if isinstance(val.get("warnings"), list) else None)
    return out


def check_n1(c, ctx, data, roots):
    r = data["results"].get(CASE_N1)
    out = {}
    if not isinstance(r, dict):
        return out
    s = data["n1"]
    rec, dest, bundle, pack = s["cp-record"], s["destination"], s["reconstruction-bundle"], s["evidence-pack"]
    c.eq("N1-HOLD schema", EVIDENCE_SCHEMA, r.get("schema"))
    c.eq("N1-HOLD case_id", CASE_N1, r.get("case_id"))
    c.eq("N1-HOLD scenario", "grant_revoked", r.get("scenario"))
    check_sources(c, "N1-HOLD", r, roots)
    if None in (rec, dest, bundle, pack):
        c.true("N1-HOLD retained native files all parsed (CP record, destination, bundle, Pack dump)", False)
        return out
    manifest_obj = data.get("am_obj")
    check_am_gate(c, ctx, data, r, "N1-HOLD")
    # ---- CP record file
    dd = check_cp_common(c, "N1-HOLD", rec, dest, r)
    c.eq("N1-HOLD CP result", "hold", dd.get("result"))
    c.eq("N1-HOLD CP reasons", ["grant_revoked"], dd.get("reasons"))
    c.eq("N1-HOLD CP binding is null", None, dd.get("binding"))
    c.eq("N1-HOLD CP effect_id (hold)", EFFECT_HOLD, dd.get("effect_id"))
    check_producer(c, "N1-HOLD", r, "grant_revoked", "grant_status=revoked")
    # ---- Replay from the retained BUNDLE FILE
    c.eq("N1-HOLD Replay status (bundle file)", "reconstruction_partial", bundle.get("status"))
    codes = [f[0] for f in findings_of(bundle)]
    c.eq("N1-HOLD Replay findings set {B004, B005} (bundle file)", ["B004", "B005"], sorted(codes))
    c.eq("N1-HOLD Replay findings are warnings only (bundle file)", ["warning", "warning"], [f[1] for f in findings_of(bundle)])
    c.eq("N1-HOLD Replay import reports are not complete (bundle file)", [False], [rep.get("complete") for rep in as_list(bundle.get("import_reports")) if isinstance(rep, dict)])
    c.eq("N1-HOLD Replay integrity [] (bundle file)", [], bundle.get("integrity"))
    types = [x.get("record_type") for x in as_list(bundle.get("records")) if isinstance(x, dict)]
    c.eq("N1-HOLD Replay record types (bundle file): no attempt, observation, reconciliation or closeout records", PARTIAL_RECORD_TYPES, sorted(set(types)))
    decs = decision_record(bundle)
    c.eq("N1-HOLD bundle has exactly one runtime_decision record", 1, len(decs))
    bd = (decs[0].get("data") if len(decs) == 1 else None) or {}
    c.eq("N1-HOLD bundle runtime_decision.data.result is hold (no authorized string carried downstream)", "hold", bd.get("result"))
    c.eq("N1-HOLD bundle decision reasons / binding / effect_id", (["grant_revoked"], None, EFFECT_HOLD), (bd.get("reasons"), bd.get("binding"), bd.get("effect_id")))
    c.true("N1-HOLD retained decision_id == native record file decision_id (per-run, non-empty)", bool(bd.get("decision_id")) and bd.get("decision_id") == dd.get("decision_id"))
    h1, h2 = check_hashes_vs_harness(c, "N1-HOLD", r, s["cp-record_bytes"], s["reconstruction-bundle_bytes"], bundle, s["evidence-pack_bytes"], pack)
    # ---- Pack dump, direct observation (hold / held semantics)
    T, rs = check_pack_common(c, "N1-HOLD", pack, bundle, manifest_obj, h2)
    lc = as_dict(T.get("lifecycle_summary"))
    c.eq("N1-HOLD Pack lifecycle authorization is held", "held", lc.get("authorization"))
    c.eq("N1-HOLD Pack lifecycle execution/destination/verification", ("no", "unknown", "unavailable"),
         (lc.get("execution_attempted"), lc.get("destination_observed"), lc.get("independent_verification")))
    c.eq("N1-HOLD Pack lifecycle reconstruction_status", "reconstruction_partial", lc.get("reconstruction_status"))
    dc = check_zero_counts(c, "N1-HOLD", T)
    c.eq("N1-HOLD Pack authorization_held_count / authorization_granted_count", (1, 0), (dc.get("authorization_held_count"), dc.get("authorization_granted_count")))
    rsd = [x for x in decision_record(as_dict(rs.get("reconstruction_bundle")))]
    c.eq("N1-HOLD Pack retained_sources decision result is hold", ["hold"], [as_dict(x.get("data")).get("result") for x in rsd])
    # ---- no authorized string anywhere in the retained decision records of the bundle or the Pack's retained copy
    leak = []
    for label, recs in (("bundle", decs), ("pack", rsd)):
        for x in recs:
            for path, value in walk(x.get("data")):
                if isinstance(value, str) and value.lower() == "authorized":
                    leak.append("%s/%s" % (label, "/".join(map(str, path))))
    c.eq("N1-HOLD no 'authorized' value in any retained downstream decision record", [], leak[:5])
    val = as_dict(d(r, "native", "pack", "validation"))
    c.eq("N1-HOLD Pack validation valid (harness-reported; never read as authorization)", True, val.get("valid"))
    c.eq("N1-HOLD Pack validation errors (harness-reported, zero)", [], val.get("errors"))
    c.true("N1-HOLD Pack validation warnings are recorded (not frozen)", isinstance(val.get("warnings"), list))
    # ---- chain vector
    bs = boundaries_of(r)
    c.eq("N1-HOLD boundary order", list(BOUNDARIES), [b.get("boundary") for b in as_list(r.get("boundaries")) if isinstance(b, dict)])
    c.eq("N1-HOLD action_manifest orchestration class", "ACCEPTED", bs.get("action_manifest", {}).get("orchestration_class"))
    cp = bs.get("control_plane", {})
    c.eq("N1-HOLD control_plane orchestration class (earliest native refusal, never overwritten)", "REFUSED_NATIVE", cp.get("orchestration_class"))
    c.eq("N1-HOLD control_plane native outcome (verbatim)", "hold", cp.get("native_outcome"))
    c.eq("N1-HOLD control_plane binding present / decision_id / effect_id (harness native result)", (False, dd.get("decision_id"), EFFECT_HOLD),
         tuple(as_dict(cp.get("native_result")).get(k) for k in ("binding_present", "decision_id", "effect_id")))
    for name in ("replay_bundle", "evidence_pack"):
        bo = bs.get(name, {})
        c.eq("N1-HOLD %s orchestration class (own honest class, not relabelled)" % name, "ACCEPTED", bo.get("orchestration_class"))
        c.eq("N1-HOLD %s retains_upstream_refusal" % name, True, bo.get("retains_upstream_refusal"))
        c.eq("N1-HOLD %s carried authorization state" % name, "held", bo.get("carried_authorization_state"))
    c.eq("N1-HOLD chain verdict (earliest non-ACCEPTED boundary)", ("REFUSED_NATIVE", "control_plane"), (d(r, "chain_verdict", "class"), d(r, "chain_verdict", "boundary")))
    c.true("N1-HOLD harness status/oracle (necessary, never sufficient)", r.get("status") == "PASS" and d(r, "oracle", "all_ok") is True)
    st = as_dict(d(r, "identity", "stable"))
    c.eq("N1-HOLD identity.stable tuple (action_id, proposal_commitment, manifest_digest, tenant_id)", (ACTION_ID, PROPOSAL_COMMITMENT, MANIFEST_DIGEST, TENANT),
         (st.get("action_id"), st.get("proposal_commitment"), st.get("manifest_digest"), st.get("tenant_id")))
    c.eq("N1-HOLD identity.effect_id (verdict-dependent)", EFFECT_HOLD, d(r, "identity", "effect_id"))
    c.eq("N1-HOLD identity decision_id (harness) == retained record", dd.get("decision_id"), d(r, "identity", "per_run", "decision_id"))
    out.update(record_sha256=sha(s["cp-record_bytes"]), bundle_h1=h1, bundle_h2=h2, pack_file_sha256=sha(s["evidence-pack_bytes"]),
               destination_file_sha256=sha(s["destination_bytes"]), pack_id=pack.get("pack_id"), bundle_id=bundle.get("bundle_id"),
               generated_at=bundle.get("generated_at"), decision_id=dd.get("decision_id"),
               pack_validation_warning_count=len(val["warnings"]) if isinstance(val.get("warnings"), list) else None)
    return out


def check_n2(c, ctx, data, p1_out, n1_out, roots):
    r = data["results"].get(CASE_N2)
    if not isinstance(r, dict):
        return
    n1b, n1b_bytes, n1rec = data["n1"]["reconstruction-bundle"], data["n1"]["reconstruction-bundle_bytes"], data["n1"]["cp-record"]
    mut, mut_bytes = data.get("n2_mut"), data.get("n2_mut_bytes")
    c.eq("N2-FLIP schema", EVIDENCE_SCHEMA, r.get("schema"))
    c.eq("N2-FLIP case_id", CASE_N2, r.get("case_id"))
    c.eq("N2-FLIP scenario", "flip_of_n1", r.get("scenario"))
    check_sources(c, "N2-FLIP", r, roots)
    bs = boundaries_of(r)
    pk = bs.get("evidence_pack", {})
    exc = as_dict(pk.get("native_exception"))
    decision_id = None
    if isinstance(n1rec, dict):
        decs = as_list(n1rec.get("decisions"))
        decision_id = decs[0].get("decision_id") if decs and isinstance(decs[0], dict) else None
    c.true("N2-FLIP decision_id taken from the retained N1 CP record file", bool(decision_id))
    want = "decision %s is authorized but has no binding" % decision_id
    c.eq("N2-FLIP evidence_pack orchestration class", "REFUSED_NATIVE", pk.get("orchestration_class"))
    c.eq("N2-FLIP native exception type", "ImportContractError", exc.get("type"))
    c.eq("N2-FLIP native exception code", None, exc.get("code"))
    c.eq("N2-FLIP native exception message (exact frozen text built from the retained N1 record)", want, exc.get("message"))
    for name in ("action_manifest", "control_plane", "replay_bundle"):
        c.eq("N2-FLIP %s is NOT_EXECUTED (derived from the N1 retained bundle, not re-run)" % name, "NOT_EXECUTED", bs.get(name, {}).get("orchestration_class"))
    c.eq("N2-FLIP evidence_pack native_outcome (verbatim)", "REFUSED_NATIVE", pk.get("native_outcome"))
    c.eq("N2-FLIP chain verdict (only the Pack boundary is exercised)", ("REFUSED_NATIVE", "evidence_pack"), (d(r, "chain_verdict", "class"), d(r, "chain_verdict", "boundary")))
    c.eq("N2-FLIP destination no_effect / before / after", (True, {}, {}), (d(r, "destination", "no_effect"), d(r, "destination", "effects_before"), d(r, "destination", "effects_after")))
    mu = as_dict(r.get("mutation"))
    c.eq("N2-FLIP harness-reported manifest sha256 == retained input file", data["am_sha"], d(r, "inputs", "manifest", "sha256"))
    c.eq("N2-FLIP harness-reported proposal sha256 == retained input file", data["prop_sha"], d(r, "inputs", "proposal", "sha256"))
    c.eq("N2-FLIP mutation field_path/from/to", ("records[runtime_decision].data.result", "hold", "authorized"), (mu.get("field_path"), mu.get("from"), mu.get("to")))
    c.eq("N2-FLIP original Action Manifest supplied and pinned", (True, MANIFEST_FILE_SHA), (mu.get("manifest_supplied"), mu.get("manifest_file_sha256")))
    c.eq("N2-FLIP original bundle unmodified after run (harness flag)", True, mu.get("original_unmodified_after_run"))
    c.eq("N2-FLIP identity n1_decision_id == decision_id of the retained N1 CP record", decision_id, d(r, "identity", "n1_decision_id"))
        # ---- the mutated bundle differs from the N1 bundle in exactly runtime_decision.data.result hold -> authorized
    if isinstance(n1b, dict) and isinstance(mut, dict):
        idx = [i for i, x in enumerate(as_list(n1b.get("records"))) if isinstance(x, dict) and x.get("record_type") == "runtime_decision"]
        c.eq("N2-FLIP the N1 bundle has exactly one runtime_decision record", 1, len(idx))
        path = "$.records[%d].data.result" % idx[0] if len(idx) == 1 else None
        c.eq("N2-FLIP mutated bundle differs from the N1 bundle in exactly one path", [path], diff_paths(n1b, mut))
        if len(idx) == 1:
            c.eq("N2-FLIP original value hold -> mutated value authorized", ("hold", "authorized"),
                 (d(n1b, "records")[idx[0]]["data"].get("result"), d(mut, "records")[idx[0]]["data"].get("result")))
    else:
        c.true("N2-FLIP mutated bundle and N1 bundle both parsed", False)
    if isinstance(mut_bytes, bytes) and isinstance(mut, dict):
        c.eq("N2-FLIP mutated bundle file bytes are the standard serialisation (indent 2, sorted keys, trailing newline)",
             (json.dumps(mut, indent=2, sort_keys=True) + "\n").encode("utf-8"), mut_bytes)
    if isinstance(n1b, dict) and isinstance(n1b_bytes, bytes) and isinstance(mut, dict) and isinstance(mut_bytes, bytes):
        c.eq("N2-FLIP harness original_bundle_H1 == retained N1 bundle file", sha(n1b_bytes), mu.get("original_bundle_H1_sha256"))
        c.eq("N2-FLIP harness original_bundle_H2 == recomputed from the retained N1 bundle", h2_of(n1b), mu.get("original_bundle_H2_pack_canonical_sha256"))
        c.eq("N2-FLIP harness mutated file sha256 == retained mutated bundle", sha(mut_bytes), mu.get("mutated_bundle_file_sha256"))
        c.eq("N2-FLIP harness mutated H2 == recomputed from the retained mutated bundle", h2_of(mut), mu.get("mutated_bundle_H2_pack_canonical_sha256"))
        c.eq("N2-FLIP Pack boundary input sha256 == retained mutated bundle", sha(mut_bytes), pk.get("input_sha256"))
        c.true("N2-FLIP original and mutated H2 differ", h2_of(n1b) != h2_of(mut))
    c.true("N2-FLIP harness status (necessary, never sufficient)", r.get("status") == "PASS" and d(r, "oracle", "all_ok") is True)


def check_cases(c, ctx, data, p1_out, n1_out, roots):
    res = data["results"]
    check_n2(c, ctx, data, p1_out, n1_out, roots)
    ref = d(res, CASE_P1, "limits")
    check_limit_texts(c, ref)
    for label, cid in (("P1", CASE_P1), ("N1-HOLD", CASE_N1), ("N2-FLIP", CASE_N2)):
        if isinstance(res.get(cid), dict):
            check_limits(c, label, res[cid].get("limits"), ref)
    # crosswalk: the mandatory NOT LINKED rows (contract section 6)
    for label, cid in (("P1", CASE_P1), ("N1-HOLD", CASE_N1)):
        rows = [x for x in as_list(d(res, cid, "crosswalk")) if isinstance(x, dict)]
        c.true("%s crosswalk has rows" % label, len(rows) > 0)
        names = [str(x.get("name", "")).lower() for x in rows]
        for group in CROSSWALK_NOT_LINKED:
            hit = [x for x in rows if all(k in str(x.get("name", "")).lower() for k in group)]
            held_row = group == ("hold", "proposal")
            c.true("%s crosswalk carries the NOT LINKED row %s" % (label, "+".join(group)),
                   bool(hit) and (all(str(x.get("class")) == "NOT CARRIED" for x in hit) or (held_row and label == "P1")))
        _ = names
    check_claims(c, res)


def check_files_index(c, ev, r, label):
    """Every hash the harness reports in `files` must equal the sha256 recomputed from the retained evidence copy."""
    files = r.get("files") if isinstance(r, dict) else None
    c.true("%s files index is a non-empty object" % label, isinstance(files, dict) and bool(files))
    bad, seen = [], 0
    for rel, digest in (files or {}).items():
        name = "c4." + rel.replace("/", ".")
        if not (ev / name).is_file():
            continue
        seen += 1
        if sha((ev / name).read_bytes()) != digest:
            bad.append(rel)
    c.eq("%s harness-reported file hashes equal the hashes recomputed from the retained files" % label, [], bad)
    c.true("%s at least one reported file hash was compared" % label, seen > 0)


def load_inputs(c, ev):
    data = {"results": {}, "p1": {}, "n1": {}}
    obj, _ = load(c, ev, "c4.result.json")
    if isinstance(obj, dict):
        c.eq("c4.result.json holds exactly the three C4 case ids", sorted(CASES), sorted(obj))
        data["results"] = {k: obj[k] for k in CASES if isinstance(obj.get(k), dict)}
        for k in CASES:
            c.true("case %s result is an object" % k, isinstance(obj.get(k), dict))
    elif obj is not None:
        c.true("c4.result.json is a JSON object", False)
    for label, names in (("p1", RAW_P1), ("n1", RAW_N1)):
        for name in names:
            o, b = load(c, ev, name)
            if o is not None and not isinstance(o, dict):
                c.true("%s is a JSON object" % name, False)
                o = None
            short = name.split(".", 2)[2][:-5]
            data[label][short], data[label][short + "_bytes"] = o, b
    for key, name in (("am", "c4.inputs.am-manifest.json"), ("prop", "c4.inputs.proposal.json"), ("n2_mut", "c4.n2.mutated-bundle.json")):
        o, b = load(c, ev, name)
        if o is not None and not isinstance(o, dict):
            c.true("%s is a JSON object" % name, False)
            o = None
        data[key if key != "am" else "am_obj"] = o
        data[(key if key != "am" else "am") + "_bytes"] = b
    data["am_sha"] = sha(data["am_bytes"]) if isinstance(data.get("am_bytes"), bytes) else None
    data["prop_sha"] = sha(data["prop_bytes"]) if isinstance(data.get("prop_bytes"), bytes) else None
    c.eq("retained AM manifest input sha256 == frozen manifest file hash", MANIFEST_FILE_SHA, data["am_sha"])
    c.eq("retained proposal input sha256 == frozen proposal file hash", PROPOSAL_SHA, data["prop_sha"])
    if isinstance(data.get("am_obj"), dict):
        c.eq("canonical digest of the retained AM manifest input == frozen digest", MANIFEST_DIGEST, h2_of(data["am_obj"]))
    return data


def expected_count(c, env_name):
    raw = os.environ.get(env_name, "")
    ok = bool(re.fullmatch(r"[1-9][0-9]{0,5}", raw))
    c.true("%s is set to a positive integer by the workflow" % env_name, ok)
    return int(raw) if ok else None


def check_tests(c, ev):
    tj, _ = load(c, ev, "tests.json")
    try:
        log = (ev / "tests.log").read_text(encoding="utf-8")
    except (OSError, ValueError):
        log = ""
    c.true("artifact tests.log present and non-empty", bool(log))
    suites = tj.get("suites") if isinstance(tj, dict) else None
    suites = suites if isinstance(suites, list) else []
    c.eq("tests.json lists exactly two suites", 2, len(suites))
    wants = []
    for pattern, env_name in SUITES:
        expected = expected_count(c, env_name)
        wants.append(expected)
        s = next((x for x in suites if isinstance(x, dict) and x.get("pattern") == pattern), {})
        c.eq("suite %s exit code" % pattern, 0, s.get("exit_code"))
        c.eq("suite %s expected tests (as recorded in tests.json == %s)" % (pattern, env_name), expected, s.get("expected_tests"))
        c.eq("suite %s observed tests" % pattern, expected, s.get("observed_tests"))
        c.true("tests.log contains 'Ran %s tests'" % expected, expected is not None and re.search(r"^Ran %d tests? in " % expected, log, re.M) is not None)
    c.eq("tests.json outcome", "PASSED", (tj or {}).get("outcome") if isinstance(tj, dict) else None)
    c.eq("tests.log observed counts are exactly the two expected counts", sorted(w for w in wants if w is not None),
         sorted(int(x) for x in re.findall(r"^Ran (\d+) tests? in ", log, re.M)))
    bad = re.findall(r"\.\.\. (?:skipped|expected failure|unexpected success|FAIL|ERROR)|^FAILED \(|^OK \((?:skipped|expected failures)|^(?:FAIL|ERROR): ", log, re.M)
    c.eq("tests.log has no skip, expected-failure, unexpected-success, failure or error markers", [], bad[:5])
    c.true("tests.log reports OK for both suites", len(re.findall(r"^OK$", log, re.M)) == 2)
    cj, _ = load(c, ev, "cases.json")
    c.eq("cases.json harness exit code", 0, cj.get("exit_code") if isinstance(cj, dict) else None)
    if isinstance(cj, dict) and any(k in cj for k in ("cases", "case_ids")):
        c.eq("cases.json case ids (when listed) are exactly the three C4 cases", sorted(CASES), sorted(cj.get("cases") or cj.get("case_ids") or []))


def check_context(c, ctx):
    c.eq("context: verify PASS", "PASS", ctx.get("verify"))
    c.eq("context: case group", CASE_GROUP, ctx.get("case_id"))
    c.eq("context re-asserted: ref/event/head", ("refs/heads/main", "workflow_dispatch", os.environ.get("GITHUB_SHA")),
         (ctx.get("github_ref"), ctx.get("event_name"), ctx.get("orchestrator_head")))
    c.true("context re-asserted: GITHUB_SHA non-empty and equals context", bool(os.environ.get("GITHUB_SHA")) and ctx.get("github_sha") == os.environ.get("GITHUB_SHA"))
    c.eq("context re-asserted: host source hashes recorded for every hosted file", sorted(HOSTED_SOURCES), sorted((ctx.get("host_sources") or {}).keys()))
    c.eq("context re-asserted: c2_producer.py sha256 == frozen", C2_PRODUCER_SHA, (ctx.get("host_sources") or {}).get("tests/manual_contract/c2_producer.py"))
    c.eq("context re-asserted: fixture hashes", sorted([PROPOSAL_SHA, MANIFEST_FILE_SHA]), sorted((v or {}).get("sha256") for v in (ctx.get("fixtures") or {}).values()))
    c.eq("context re-asserted: component pins", {k: [v[1], v[2]] for k, v in PINS.items()},
         {k: [(ctx.get("components") or {}).get(k, {}).get("sha"), (ctx.get("components") or {}).get(k, {}).get("tree")] for k in PINS})
    c.eq("context re-asserted: locked dependency versions", LOCKED, {k: (ctx.get("dependencies") or {}).get(k) for k in LOCKED})
    c.true("context re-asserted: dependency lock sha256 recorded", bool((ctx.get("host_sources") or {}).get(LOCK_PATH)))


def check_harness_binding(c, ctx, data):
    """The harness evidence must describe the same sources/runtime that `verify` recorded (host sources, versions, orchestrator head)."""
    hs = ctx.get("host_sources") or {}
    for label, cid in (("P1", CASE_P1), ("N1-HOLD", CASE_N1), ("N2-FLIP", CASE_N2)):
        r = data["results"].get(cid)
        if not isinstance(r, dict):
            continue
        rt = as_dict(r.get("runtime"))
        c.eq("%s runtime versions == context" % label, {k: (ctx.get("dependencies") or {}).get(k) for k in ("cryptography", "pydantic")},
             {k: rt.get(k) for k in ("cryptography", "pydantic")})
        hv = as_dict(r.get("harness"))
        c.true("%s harness block present" % label, bool(hv))
        if hv:
            c.eq("%s harness c2_producer.py sha256 == frozen" % label, C2_PRODUCER_SHA, hv.get("c2_producer_sha256"))
            c.eq("%s harness real_c4.py / c4_producer.py / real_c3.py sha256 == the ones recorded by verify" % label,
                 (hs.get("tests/manual_contract/real_c4.py"), hs.get("tests/manual_contract/c4_producer.py"), hs.get("tests/manual_contract/real_c3.py")),
                 (hv.get("real_c4_sha256"), hv.get("c4_producer_sha256"), hv.get("real_c3_sha256")))
            c.true("%s harness orchestrator head == GITHUB_SHA and tracked files unmodified" % label, bool(os.environ.get("GITHUB_SHA"))
                   and d(hv, "orchestrator", "head") == os.environ.get("GITHUB_SHA") and d(hv, "orchestrator", "tracked_files_modified") is False)


def index_files(ev, skip):
    out = {}
    for p in sorted(ev.iterdir()):
        if p.is_file() and p.name not in skip:
            out[p.name] = sha(p.read_bytes())
    return out


def write_slices(c, ev, data):
    res = data["results"]
    for name, cid in SLICES:
        entry = res.get(cid)
        if entry is None:
            c.true("slice %s written" % name, False)
            continue
        (ev / name).write_text(json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        c.eq("slice %s re-read parses to the source entry" % name, entry, strict_loads((ev / name).read_bytes()))
    derived = (("p1.pack-validation-report.json", d(res, CASE_P1, "native", "pack", "validation")), ("n1.pack-validation-report.json", d(res, CASE_N1, "native", "pack", "validation")),
               ("c4-crosswalk.json", {"p1": d(res, CASE_P1, "crosswalk"), "n1": d(res, CASE_N1, "crosswalk"),
                                       "orchestrator_extraction_note": "verbatim slice of the harness crosswalk rows; orchestrator-owned extraction, not a native field"}),
               ("limits-L1-L27.json", d(res, CASE_P1, "limits")),
               ("boundary-verdicts.json", {cid: {"chain_verdict": d(res, cid, "chain_verdict"), "boundaries": d(res, cid, "boundaries")} for cid in CASES}))
    for name, obj in derived:
        if obj is None or (isinstance(obj, dict) and not obj) or (name == "c4-crosswalk.json" and (obj["p1"] is None or obj["n1"] is None)):
            c.true("slice %s written" % name, False)
            continue
        (ev / name).write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        c.eq("slice %s re-read parses to the source object" % name, obj, strict_loads((ev / name).read_bytes()))
    lim = d(res, CASE_P1, "limits")
    if isinstance(lim, dict) and (ev / "limits-L1-L27.json").is_file():
        c.eq("limits-L1-L27.json carries L1..L27 verbatim", {"L%d" % n: lim.get("L%d" % n) for n in range(1, 28)},
             {k: v for k, v in strict_loads((ev / "limits-L1-L27.json").read_bytes()).items() if re.fullmatch(r"L\d+", k)})


def guarded(c, label, fn, *args):
    try:
        return fn(*args)
    except Exception as exc:  # a crashed section is a named FAIL, never a traceback that hides the other results
        c.eq("%s completed without an internal error" % label, "no exception", "%s: %s" % (type(exc).__name__, str(exc)[:200]))
        return None


def check():
    ev = evidence_dir()
    ev.mkdir(parents=True, exist_ok=True)
    c = Checks()
    for name in FOUND + INPUTS:
        c.true("evidence artifact %s present" % name, (ev / name).is_file())
    ctx, _ = load(c, ev, "context.json")
    ctx = ctx if isinstance(ctx, dict) else {}
    guarded(c, "context checks", check_context, c, ctx)
    guarded(c, "suite checks", check_tests, c, ev)
    data = guarded(c, "input loading", load_inputs, c, ev) or {"results": {}, "p1": {}, "n1": {}}
    roots = {}
    for key, v in PINS.items():
        raw = os.environ.get(v[4])
        c.true("%s is set for the check step" % v[4], bool(raw))
        if raw:
            roots[key] = pathlib.Path(raw).resolve()
    if "action_manifest" in roots:
        try:
            raw = (roots["action_manifest"] / MANIFEST_PATH).read_bytes()
            c.eq("Action Manifest fixture sha256 (read from the Action Manifest root)", MANIFEST_FILE_SHA, sha(raw))
            c.eq("retained AM manifest input is byte-identical to the fixture read from the Action Manifest root", raw, data.get("am_bytes"))
        except OSError as exc:
            c.eq("Action Manifest fixture readable", "present", "%s: %s" % (type(exc).__name__, str(exc)[:100]))
    guarded(c, "harness binding checks", check_harness_binding, c, ctx, data)
    p1_out = guarded(c, "P1 checks", check_p1, c, ctx, data, roots) or {}
    n1_out = guarded(c, "N1-HOLD checks", check_n1, c, ctx, data, roots) or {}
    guarded(c, "N2-FLIP, limits, crosswalk and claim checks", check_cases, c, ctx, data, p1_out, n1_out, roots)
    for label, cid in (("P1", CASE_P1), ("N1-HOLD", CASE_N1), ("N2-FLIP", CASE_N2)):
        if isinstance(data["results"].get(cid), dict):
            guarded(c, "%s files index" % label, check_files_index, c, ev, data["results"][cid], label)
    guarded(c, "slice writing", write_slices, c, ev, data)
    present = {n: (ev / n).is_file() for n in FOUND + INPUTS + tuple(n for n, _ in SLICES) + DERIVED}
    c.true("every mandatory and derived evidence file exists before indexing", all(present.values()))
    idx = index_files(ev, ("oracle.txt", "evidence-manifest.json"))
    verdict = "PASS" if c.failed == 0 else "FAIL"
    lines = c.text()
    header = "C4 hosted oracle comparison: %s (%d checks, %d failed)" % (verdict, len(c.rows), c.failed)
    (ev / "oracle.txt").write_text(header + "\n" + "\n".join(lines) + "\n", encoding="ascii")
    idx["oracle.txt"] = sha((ev / "oracle.txt").read_bytes())
    stable = {"schema": MANIFEST_SCHEMA, "case_group": CASE_GROUP, "cases": list(CASES), "harness_schema": EVIDENCE_SCHEMA,
              "expected_suites_env": {p: e for p, e in SUITES},
              "sources": {k: {"repository": v[0], "sha": v[1], "tree": v[2]} for k, v in PINS.items()},
              "fixtures": {"proposal": {"path": PROPOSAL_PATH, "sha256": PROPOSAL_SHA},
                           "action_manifest_fixture": {"path": MANIFEST_PATH, "sha256": MANIFEST_FILE_SHA, "canonical_digest": MANIFEST_DIGEST}},
              "frozen": {"effect_id_authorized": EFFECT_AUTH, "effect_id_hold": EFFECT_HOLD, "proposal_commitment": PROPOSAL_COMMITMENT, "tenant_id": TENANT,
                         "generation": GENERATION, "action_id": ACTION_ID, "replay_status": "reconstruction_partial", "p1_findings": [["B004", "warning"]],
                         "n1_findings": ["B004", "B005"], "pack_version": "0.2.0", "review_status": "draft", "transformation_version": TRANSFORMATION,
                         "zero_count_keys": list(ZERO_COUNT_KEYS), "n1_reasons": ["grant_revoked"], "n1_chain_verdict": "REFUSED_NATIVE@control_plane",
                         "n2_message_template": "decision <decision_id of the retained N1 CP record> is authorized but has no binding",
                         "c2_producer_sha256": C2_PRODUCER_SHA},
              "oracle_references": {"contract": "Hub #273 comment 6674059997", "freeze": "Architect decision A1-A9 (C4 v0.1 frozen for bounded development)"},
              "dependency_lock_sha256": (ctx.get("host_sources") or {}).get(LOCK_PATH), "locked_versions": LOCKED,
              "host_source_sha256": ctx.get("host_sources"), "limitations": list(LIMITATIONS), "limits_status": LIMIT_STATUS}
    manifest = {"schema": MANIFEST_SCHEMA, "stable_identity": stable,
                "stable_identity_sha256": sha(json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
                "per_run": {"repository": ctx.get("repository"), "workflow": ctx.get("workflow"), "github_run_id": ctx.get("github_run_id"),
                            "github_run_attempt": ctx.get("github_run_attempt"), "github_sha": ctx.get("github_sha"), "github_ref": ctx.get("github_ref"),
                            "orchestrator_head": ctx.get("orchestrator_head"), "runner": ctx.get("runner"), "python_version": ctx.get("python_version"),
                            "pip_version": ctx.get("pip_version"), "git_version": ctx.get("git_version"), "dependencies": ctx.get("dependencies"),
                            "expected_suite_counts": {p: os.environ.get(e) for p, e in SUITES},
                            "values_not_golden": {"p1": p1_out, "n1": n1_out}},
                "values_not_golden_note": "per-run values (decision_id, record/bundle/Pack hashes, bundle_id, generated_at, pack_id) are recorded for consistency only and are never golden literals",
                "evidence_file_sha256": dict(sorted(idx.items())), "evidence_index_excludes": ["evidence-manifest.json (itself)"],
                "verdict": verdict, "check_count": len(c.rows), "failed": c.failed, "qualification": QUALIFICATION,
                "status_vocabulary": ["PASS", "FAIL", "BLOCKED", "NOT EXECUTED"], "not_executed": list(NOT_EXECUTED), "n_a_disposition": NA_DISPOSITION}
    write_json(ev / "evidence-manifest.json", manifest)
    again = index_files(ev, ("evidence-manifest.json",))
    rc = 0 if verdict == "PASS" else 1
    if again != dict(manifest["evidence_file_sha256"]):
        print("c4_hosted_check: evidence index differs from the files on disk after writing", file=sys.stderr)
        rc = 1
    for line in lines:
        if line.startswith("FAIL"):
            print(line, file=sys.stderr)
    return rc


# ------------------------------------------------------------------ summary
def summary():
    try:
        ev = evidence_dir()
        names = {"success": "PASS", "failure": "FAIL", "skipped": "NOT EXECUTED", "cancelled": "BLOCKED"}
        prereq = [os.environ.get(v, "") for v in ("STEP_CHECKOUT_CP", "STEP_CHECKOUT_RB", "STEP_CHECKOUT_PACK", "STEP_CHECKOUT_AM", "STEP_INSTALL")]
        blocked = any(x in ("failure", "cancelled") for x in prereq)
        steps = [("Prerequisites (component checkouts, hash-locked install)", "BLOCKED" if blocked else ("PASS" if all(x == "success" for x in prereq) else "NOT EXECUTED"))] + [
            (label, names.get(os.environ.get(var, ""), "NOT EXECUTED")) for label, var in
            (("Exact-source verification", "STEP_VERIFY"), ("Focused C4 suites", "STEP_TESTS"), ("C4 cases (one harness run)", "STEP_CASES"),
             ("Frozen-literal comparison (orchestrator-owned, not independent)", "STEP_ORACLE"))]
        overall = "BLOCKED" if blocked else "PASS" if all(s == "PASS" for _, s in steps) else ("FAIL" if any(s == "FAIL" for _, s in steps) else "NOT PASSED")

        def clean(v):
            s = "".join(ch if " " <= ch <= "~" else "?" for ch in " ".join(str(v).split()))
            return s.replace("`", "'").replace("|", "/").replace("<", "&lt;").replace(">", "&gt;")[:200]
        out = ["### C4 hosted run (hosted developer evidence only, manual only)", "",
               "**Developer check result: %s** (hosted developer evidence only; not qualification, approval, authenticity, effect proof or complete reconstruction)" % overall, "",
               "| Stage | Status |", "|---|---|"] + ["| %s | %s |" % (a, b) for a, b in steps] + [""]
        try:
            ctx = json.loads((ev / "context.json").read_text(encoding="utf-8"))
            out += ["| Field | Value |", "|---|---|"] + ["| %s | `%s` |" % (k, clean(v)) for k, v in (
                ("Dispatched ref", ctx.get("github_ref")), ("Orchestrator SHA", ctx.get("github_sha")),
                ("Run", "%s attempt %s" % (ctx.get("github_run_id"), ctx.get("github_run_attempt"))), ("Action Manifest pin", AM_SHA), ("Control Plane pin", CP_SHA),
                ("Replay Bundle pin", RB_SHA), ("Evidence Pack pin", PACK_SHA), ("Dependencies", ctx.get("dependencies")), ("Runner", ctx.get("runner")))] + [""]
        except (OSError, ValueError):
            out += ["No context.json was produced.", ""]
        try:
            first = (ev / "oracle.txt").read_text(encoding="utf-8").splitlines()
            out += ["Oracle: `%s`" % clean(first[0] if first else "empty")] + ["- `%s`" % clean(x) for x in first if x.startswith("FAIL")][:20] + [""]
        except OSError:
            out += ["Oracle: not produced (NOT EXECUTED or failed earlier).", ""]
        out += ["N1-HOLD chain verdict: REFUSED_NATIVE at control_plane. Replay and the Pack import the held record as native evidence (Replay reconstruction_partial B004+B005, "
                "Pack authorization held); a valid Pack validation result there is never authorization of the action. The P1 Replay result is reconstruction_partial (B004) and is "
                "never complete. A valid Pack validation result means internal consistency only, not reviewer approval, compliance or audit. Authority is synthetic and "
                "unauthenticated. Hub #280 is OPEN.", "", "Not executed: " + "; ".join(NOT_EXECUTED) + "."]
        text = "\n".join(out) + "\n"
        target = os.environ.get("GITHUB_STEP_SUMMARY")
        if target:
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(text)
        else:
            sys.stdout.write(text)
    except BaseException:  # the summary must never fail the job or hide the real step outcomes
        pass
    return 0


def main(argv):
    if len(argv) != 2 or argv[1] not in ("verify", "check", "summary"):
        print("usage: c4_hosted_check.py verify|check|summary", file=sys.stderr)
        return 2
    try:
        return {"verify": verify, "check": check, "summary": summary}[argv[1]]()
    except Exception as exc:
        print("c4_hosted_check %s failed closed: %s: %s" % (argv[1], type(exc).__name__, str(exc)[:300]), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
