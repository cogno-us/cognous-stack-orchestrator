"""Hosted C3 frozen-literal checker for the manual workflow (orchestrator-owned; NOT independent) (stdlib only; run as `python -I -B`).

Development-only and fixture-scoped. NOT independent qualification, release evidence or an authenticated-authority claim.
Subcommands (the workflow passes everything else through the environment, never through shell text):
  verify   exact-source and context check before any component code runs (no component import); writes sources.txt and context.json.
  check    comparison of the produced artifacts with the frozen C3 literals. It does not trust the harness's own status/oracle; it
           re-derives hashes from the retained files and re-observes the Pack-side zero counts directly from the native Pack dump.
           It is orchestrator-owned and is NOT an independent verifier. Writes the per-case slices, oracle.txt and
           evidence-manifest.json. Exit 1 on any mismatch or missing/corrupt artifact.
  summary  job summary from the step outcomes and the files that exist; never raises.
Every expected literal below is the frozen contract (Hub #273 comment 6671327666; freeze 6671384213), restated here independently of
the harness; no per-run value (record/bundle/Pack hashes, bundle_id, generated_at, pack_id, decision_id) is ever a golden literal.
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

CASE_GROUP = "c3_p1_n1_n3_n5_hosted_group"
CASE_P1, CASE_N1, CASE_N3, CASE_N5 = ("c3_p1_replay_to_pack_partial", "c3_n1_ten_tenant_tamper", "c3_n3_partial_as_complete", "c3_n5_rev_wrong_revision")
CASES = (CASE_P1, CASE_N1, CASE_N3, CASE_N5)
# key -> (repository, sha, tree, env prefix, root env var)
PINS = {
    "control_plane": ("cogno-us/cognous-control-plane", "484fdbd297235dd24148ddb0703f2055a31eabff", "c182939882103015f12c5360fccf377c54e2c4f9", "C3_CP", "COGNOUS_C3_CONTROL_PLANE_ROOT"),
    "replay_bundle": ("cogno-us/cognous-replay-bundle", "93a76e281fcae6a65d2cd1d35376f87442dafb95", "aca6e6b8bdd33d51db3b34bc0c75eff93b9ff88f", "C3_RB", "COGNOUS_C3_REPLAY_BUNDLE_ROOT"),
    "evidence_pack": ("cogno-us/cognous-governance-evidence-pack", "065150852cc2a8abeb748777bb69d72ccd0e03d8", "fe428a89da2e74346648cdfe014462ddc8624c77", "C3_PACK", "COGNOUS_C3_EVIDENCE_PACK_ROOT"),
    "action_manifest": ("cogno-us/cognous-action-manifest", "fa170815ef96a54c233d0dd9da821b60debabf8b", "3b0e3772e944aa668c8f4b879588c7cc3e2c32be", "C3_AM", "COGNOUS_C3_ACTION_MANIFEST_ROOT"),
}
CP_SHA, RB_SHA, PACK_SHA, AM_SHA = (PINS[k][1] for k in ("control_plane", "replay_bundle", "evidence_pack", "action_manifest"))
SUITES = (("test_real_c3.py", 26), ("test_real_c3_integrity.py", 76))
PROPOSAL_PATH = "tests/manual_contract/c1/fixtures/proposal.tenant-alpha.json"
PROPOSAL_SHA = "1033c73e7dbe677cc71520711d3aaacb182952e5c12c8eaa489f24be0014cfe2"
MANIFEST_PATH = "examples/refund_integration_v1_1.manifest.json"  # inside the Action Manifest root
MANIFEST_FILE_SHA = "789ad39596b9e1ef84a726a671883e1cb6b83343da3a31db0a1120906d68c074"
MANIFEST_DIGEST = "sha256:4d1ad6c96bc242c63998231b4df3ad7c86dc2e5e59cdae63afe7bff86e60f6ac"
C2_PRODUCER_SHA = "7c4f2595d7939e4a373586faafc0de86469dc03b791d893d7b27fb328a02a895"
EFFECT_ID = "sha256:4e5844d6d53ab6f8694e9c76cb6238ec4110137dd35de73cb0b22963961ecde8"
PROPOSAL_COMMITMENT = "sha256:becaea3f10b5edf56ea181e0cd62793ebe8262238f948fb72dc5c0389c7f8c53"
TENANT, GENERATION = "tenant-alpha", "bounded-authorization-effect/0.3-strict-tenant"
TRANSFORMATION = "agep-manifest-reconstruction-import/0.3.10-strict-tenant-candidate"
VALIDATOR = "agent_replay_bundle.importers.import_bounded_workflow"
N1_MESSAGE = "pinned Replay semantic validation failed: decisions[0].binding.tenant_id conflicts with committed operation"
N3_MESSAGE = "pinned Replay semantic validation failed unexpectedly: retained Replay status differs from accepted reconstruction"
N5_MESSAGE = "producer_profiles[0].revision for cogno-us/cognous-agent-control-plane conflicts with pinned supported revision"
N5_WRONG_REVISION = "f63ce914504dd06813c4ccd199b0570dbd8dd427"
ZERO_COUNT_KEYS = ("control_plane_attempt_count", "executor_attempt_count", "attempt_transition_record_count", "destination_effect_count",
                   "effect_observation_count", "reconciliation_count")
PARTIAL_RECORD_TYPES = ["input_time_floors", "resolution_check", "resolution_check_event", "runtime_decision", "runtime_proposal"]
EVIDENCE_SCHEMA = "cognous.orchestrator.c3-evidence/0-candidate"
MANIFEST_SCHEMA = "cognous.orchestrator.c3-hosted-evidence-manifest/0-candidate"
LOCKED = {"pydantic": "2.14.1", "cryptography": "50.0.2", "pytest": "8.4.2"}
LOCK_PATH = ".github/locks/cryptography-pydantic-pytest-513753.txt"
HOSTED_SOURCES = ("tests/manual_contract/real_c3.py", "tests/manual_contract/c2_producer.py", "tests/manual_contract/c3/test_real_c3.py",
                  "tests/manual_contract/c3/test_real_c3_integrity.py", ".github/scripts/c3_hosted_check.py", LOCK_PATH)
INPUTS = ("tests.json", "cases.json", "tests.log", "c3.result.json", "c3.native-records.json", "c3.native-destination.json",
          "c3.reconstruction-bundle.json", "c3.evidence-pack.json")
SLICES = (("p1.result.json", CASE_P1), ("n1-ten.result.json", CASE_N1), ("n3.result.json", CASE_N3), ("n5-rev.result.json", CASE_N5))
DERIVED = ("p1.pack-validation-report.json", "limits-L1-L19.json")
LIMIT_STATUS = "DEVELOPMENT_TESTED_NOT_INDEPENDENTLY_QUALIFIED_FIXTURE_SCOPED"
LIMIT_FLAGS = {"decision_semantics_only": True, "effect_executed": False, "non_authorizing": True,
               "no_certification_clearance_or_production_readiness": "HOLD", "hub_280_digest_basis": "OPEN"}
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
}
LIMIT_KEYS = {"status", "bundle_hash_semantics", "uncompared_by_pack", "known_limitations_not_oracles", "synthetic_key_scope",
              *LIMIT_FLAGS, *("L%d" % n for n in LIMIT_PHRASES)}
FORBIDDEN_CLAIMS = (r"complete reconstruction", r"fully reconstructed", r"reconstruction_complete(?!ness)", r"\bauthenticated authority",
                    r"\bverified execution", r"\bexecution verified", r"\bcertified\b", r"\bapproved\b", r"production[ -]ready",
                    r"\bindependently qualified", r"\bcompliant\b", r"\bcleared for\b", r"\bclearance granted")
NOT_EXECUTED = ("Control Plane refusal record through Replay", "revocation, expiry and stale-record replay", "partial failure and incomplete journal",
                "complete reconstruction", "executor attempts, destination effects, effect observation and reconciliation records",
                "signature verification, custody chain and freshness checks", "Pack reviewer approval or audit",
                "independent qualification, institutional authority, authenticity, release and production")
LIMITATIONS = ("synthetic unauthenticated authority; test-only public Ed25519 key", "Replay is reconstruction_partial (B004), never complete reconstruction",
               "Pack valid=True means internally consistent only, not reviewer approval, compliance or audit",
               "the Pack carries no hash of the raw Control Plane record; CP-record to bundle linkage is per-run harness evidence only",
               "Replay pin in the Pack is a PROVISIONAL, UNQUALIFIED development pin", "Hub #280 digest-basis divergence is OPEN",
               "Engineering Constitution adoption is UNVERIFIED", "hosted developer evidence only: not independent qualification")
NA_DISPOSITION = ("N-A (harness-side pack_derived_counts_zero mutation survivors): closed for the hosted checker by direct observation of the six "
                  "derived_counts keys in the retained native Pack dump (present, int and not bool, == 0); it remains an implementation-level "
                  "limitation of the harness-side assertion, which this checker does not edit or replace")
QUALIFICATION = "NOT independent qualification; hosted developer evidence only"


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
        failures.append("case_id %r is not the C3 hosted group %r" % (ctx["case_id"], CASE_GROUP))
    if ctx["event_name"] != "workflow_dispatch":
        failures.append("event is %r, not workflow_dispatch" % ctx["event_name"])
    if ctx["github_ref"] != "refs/heads/main":
        failures.append("dispatched ref is %r; the C3 hosted run is allowed only from refs/heads/main" % ctx["github_ref"])
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
class Checks:
    def __init__(self):
        self.rows, self.failed = [], 0

    def eq(self, name, want, got):
        ok = want == got and type(want) is type(got)
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
    except (OSError, ValueError) as exc:
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


def check_limits(c, label, limits, ref):
    c.true("%s limits is an object" % label, isinstance(limits, dict))
    if not isinstance(limits, dict):
        return
    c.eq("%s limits key set (no key dropped, none added)" % label, sorted(LIMIT_KEYS), sorted(limits))
    c.eq("%s limits identical to the P1 limits block" % label, ref, limits)
    c.eq("%s limits status" % label, LIMIT_STATUS, limits.get("status"))
    for k, v in LIMIT_FLAGS.items():
        c.eq("%s limits flag %s" % (label, k), v, limits.get(k))


def check_limit_texts(c, limits):
    if not isinstance(limits, dict):
        return
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
    # forbidden positive claims inside limit texts must be negated
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


def check_claims(c, results):
    scanned, bad = 0, []
    for cid, entry in results.items():
        for path, value in walk(entry):
            if not isinstance(value, str) or "limits" in path:
                continue
            scanned += 1
            low = value.lower()
            for pat in FORBIDDEN_CLAIMS:
                if re.search(pat, low):
                    # the only tolerated carrier: the N3 mutation descriptor naming the forged status it injected
                    if pat.startswith("reconstruction_complete") and "mutation" in path and cid == CASE_N3:
                        continue
                    bad.append("%s/%s: %s" % (cid, "/".join(map(str, path)), pat))
    c.eq("no positive claim-promotion string outside limits (complete reconstruction, authenticated authority, approved, certified, verified execution)", [], bad[:5])
    c.true("claim scan is not vacuous", scanned > 100)


def check_sources(c, label, r, roots, blobs):
    s = d(r, "sources") or {}
    c.eq("%s measured revision label" % label, CP_SHA, s.get("revision_label"))
    for key, (_, want_sha, want_tree, _, _) in PINS.items():
        o = d(s, "sources", key) or {}
        c.eq("%s measured %s head/tree" % (label, key), (want_sha, want_tree), (o.get("observed_head"), o.get("observed_tree")))
        c.true("%s %s clean flags" % (label, key), o.get("tracked_files_clean") is True and o.get("ls_files_all_H") is True and o.get("status_ignored_clean") is True)
        if not blobs:
            continue
        mods = o.get("imported_modules") or {}
        need = {"control_plane": ("agent_control_plane.bounded",), "replay_bundle": ("agent_replay_bundle.importers",),
                "evidence_pack": ("agent_governance_evidence_pack.importer", "agent_governance_evidence_pack.validator", "agent_governance_evidence_pack.loader"),
                "action_manifest": ()}[key]
        root = roots.get(key)
        bad = []
        if need:
            for name, m in mods.items():
                try:
                    rel = pathlib.Path(m.get("file", "/")).resolve().relative_to(root).as_posix()
                    if git(root, "rev-parse", "HEAD:" + rel) != m.get("git_blob_sha"):
                        bad.append(name)
                except (ValueError, Fail, AttributeError, TypeError):
                    bad.append(name)
            c.true("%s %s: %d loaded modules lie under the pinned root and equal their git blobs (recomputed here)" % (label, key, len(mods)), bool(mods) and not bad and root is not None)
            c.true("%s %s: required modules were loaded and verified" % (label, key), all(n in mods for n in need))
        else:
            c.eq("%s %s: no component module was imported" % (label, key), {}, mods)


def check_p1(c, ctx, data, roots):
    r, results = data["results"].get(CASE_P1), data["results"]
    rec, rec_bytes, dest, dest_bytes = data["rec"], data["rec_bytes"], data["dest"], data["dest_bytes"]
    bundle, bundle_bytes, pack, pack_bytes = data["bundle"], data["bundle_bytes"], data["pack"], data["pack_bytes"]
    out = {}
    if not isinstance(r, dict):
        return out
    c.eq("P1 schema", EVIDENCE_SCHEMA, r.get("schema"))
    c.eq("P1 case_id", CASE_P1, r.get("case_id"))
    c.eq("P1 outcome", "IMPORTED", r.get("outcome"))
    c.eq("P1 producer config id", "C2-CP-RUNTIME-PROFILE-STRICT-TENANT-DECIDE-ONLY", r.get("producer_config_id"))
    c.eq("P1 proposal fixture sha256 (harness evidence)", PROPOSAL_SHA, d(r, "inputs", "proposal", "sha256"))
    c.eq("P1 Action Manifest fixture sha256 (harness evidence)", MANIFEST_FILE_SHA, d(r, "inputs", "manifest", "sha256"))
    c.eq("P1 harness c2_producer.py sha256 == frozen", C2_PRODUCER_SHA, d(r, "harness", "c2_producer_sha256"))
    c.eq("P1 harness real_c3.py sha256 == the one recorded by verify", (ctx.get("host_sources") or {}).get("tests/manual_contract/real_c3.py"), d(r, "harness", "real_c3_sha256"))
    c.true("P1 harness orchestrator head == GITHUB_SHA and tracked files unmodified", bool(os.environ.get("GITHUB_SHA"))
           and d(r, "harness", "orchestrator", "head") == os.environ.get("GITHUB_SHA") and d(r, "harness", "orchestrator", "tracked_files_modified") is False)
    c.eq("P1 runtime versions == context", {k: (ctx.get("dependencies") or {}).get(k) for k in ("cryptography", "pydantic")},
         {k: (r.get("runtime") or {}).get(k) for k in ("cryptography", "pydantic")})
    check_sources(c, "P1", r, roots, True)
    # ---- Replay: from the retained BUNDLE FILE
    if bundle is None or rec is None or dest is None or pack is None:
        c.true("P1 retained native files all parsed (bundle, records, destination, Pack dump)", False)
        return out
    findings = [[f.get("code"), f.get("severity")] for rep in (bundle.get("import_reports") or []) if isinstance(rep, dict) for f in (rep.get("findings") or []) if isinstance(f, dict)]
    c.eq("P1 Replay status (bundle file)", "reconstruction_partial", bundle.get("status"))
    c.eq("P1 Replay findings: exactly B004 warning (bundle file)", [["B004", "warning"]], findings)
    c.eq("P1 Replay import reports are not complete (bundle file)", [False], [rep.get("complete") for rep in (bundle.get("import_reports") or [])])
    c.eq("P1 Replay integrity [] (bundle file)", [], bundle.get("integrity"))
    c.eq("P1 Replay bundle_version (bundle file)", "0.2.0", bundle.get("bundle_version"))
    types = [x.get("record_type") for x in (bundle.get("records") or []) if isinstance(x, dict)]
    c.eq("P1 Replay record types (bundle file): no attempt, observation, reconciliation or closeout records", PARTIAL_RECORD_TYPES, sorted(set(types)))
    c.eq("P1 attempts/observations/reconciliations/closeouts/refusals empty (native record file)", {k: [] for k in ("attempts", "closeouts", "observations", "reconciliations", "refusals")},
         {k: rec.get(k) for k in ("attempts", "closeouts", "observations", "reconciliations", "refusals")})
    c.eq("P1 destination effects (retained destination file)", {}, dest.get("effects"))
    c.eq("P1 destination effect count and effects (harness result)", (0, {}), (d(r, "destination", "effect_count"), d(r, "destination", "effects")))
    # ---- hashes recomputed from the retained files
    rr, bb, np_ = r.get("record") or {}, r.get("bundle") or {}, r.get("native_pack") or {}
    h1, h2 = sha(bundle_bytes), h2_of(bundle)
    c.eq("P1 record sha256: recomputed from the retained file == harness report", sha(rec_bytes), rr.get("sha256"))
    c.eq("P1 record size_bytes == retained file size", len(rec_bytes), rr.get("size_bytes"))
    c.true("P1 record unchanged after import (harness flag)", rr.get("unchanged_after_import") is True)
    c.eq("P1 bundle H1 sha256: recomputed from the retained file == harness report", h1, bb.get("H1_sha256_persisted_bytes"))
    c.eq("P1 bundle size_bytes == retained file size", len(bundle_bytes), bb.get("size_bytes"))
    c.eq("P1 bundle H2 (Pack canonical hash): recomputed from the parsed bundle file == harness report", h2, bb.get("H2_pack_canonical_sha256"))
    c.true("P1 H1 and H2 are distinct values", ("sha256:" + h1) != h2)
    c.eq("P1 Pack file sha256: recomputed from the retained dump == harness report", sha(pack_bytes), np_.get("pack_file_sha256"))
    c.eq("P1 raw-record-to-bundle linkage (harness evidence only; carried_by_pack False)", (sha(rec_bytes), h1, False),
         (d(r, "raw_record_to_bundle_linkage", "cp_record_sha256"), d(r, "raw_record_to_bundle_linkage", "bundle_H1"), d(r, "raw_record_to_bundle_linkage", "carried_by_pack")))
    c.eq("P1 Pack pack_id (dump) == harness report", pack.get("pack_id"), np_.get("pack_id"))
    # ---- Pack dump, direct observation
    T = d(pack, "metadata", "traceable_import") or {}
    c.eq("P1 Pack pack_version", "0.2.0", pack.get("pack_version"))
    c.eq("P1 Pack review_status draft", "draft", pack.get("review_status"))
    c.eq("P1 Pack transformation_version", TRANSFORMATION, T.get("transformation_version"))
    c.eq("P1 Pack selected_revisions", {"manifest": AM_SHA, "replay": RB_SHA, "control_plane": CP_SHA}, T.get("selected_revisions"))
    c.eq("P1 Pack replay_semantic_validation", {"validator": VALIDATOR, "required_revision": RB_SHA, "status": "validated_partial"}, T.get("replay_semantic_validation"))
    rbs = pack.get("replay_bundles")
    rb0 = rbs[0] if isinstance(rbs, list) and rbs and isinstance(rbs[0], dict) else {}
    c.eq("P1 Pack replay_bundles has exactly one entry", 1, len(rbs) if isinstance(rbs, list) else None)
    c.eq("P1 Pack replay_bundles[0] status/signed/redacted/validation_status", ("validated_partial", False, False, "semantically_valid"),
         (rb0.get("status"), rb0.get("signed"), rb0.get("redacted"), rb0.get("validation_status")))
    c.eq("P1 Pack replay_bundles[0].bundle_id == bundle file bundle_id", bundle.get("bundle_id"), rb0.get("bundle_id"))
    c.eq("P1 Pack reconstruction_completeness", "reconstruction_partial", T.get("reconstruction_completeness"))
    lc = T.get("lifecycle_summary") or {}
    c.eq("P1 Pack lifecycle_summary", {"authorization": "authorized", "current_permission": "not_evaluated_from_historical_records", "execution_attempted": "no",
                                       "destination_observed": "unknown", "independent_verification": "unavailable", "reconstruction_status": "reconstruction_partial"},
         {k: lc.get(k) for k in ("authorization", "current_permission", "execution_attempted", "destination_observed", "independent_verification", "reconstruction_status")})
    sem = T.get("replay_semantics") or {}
    c.eq("P1 Pack replay_semantics flags", {"policy_reevaluation": False, "external_effect_execution": False, "destination_observation": "not_performed",
                                            "independent_effect_verification": False},
         {k: sem.get(k) for k in ("policy_reevaluation", "external_effect_execution", "destination_observation", "independent_effect_verification")})
    ia = T.get("input_artifacts")
    ia = ia if isinstance(ia, list) else []
    ia0 = ia[0] if ia and isinstance(ia[0], dict) else {}
    ia1 = ia[1] if len(ia) > 1 and isinstance(ia[1], dict) else {}
    c.eq("P1 Pack input_artifacts[0].hash == Action Manifest canonical digest", MANIFEST_DIGEST, ia0.get("hash"))
    c.eq("P1 Pack input_artifacts[0] role/trusted_revision", ("manifest", AM_SHA), (ia0.get("artifact_role"), ia0.get("trusted_revision")))
    c.eq("P1 Pack input_artifacts[1] (bundle) hash == recomputed H2", h2, ia1.get("hash"))
    c.eq("P1 Pack input_artifacts[1] role/artifact_id/trusted_revision", ("reconstruction_bundle", bundle.get("bundle_id"), RB_SHA),
         (ia1.get("artifact_role"), ia1.get("artifact_id"), ia1.get("trusted_revision")))
    # ---- N-A closure: the six zero counts directly from the retained Pack dump
    dc = T.get("derived_counts")
    dc = dc if isinstance(dc, dict) else {}
    for k in ZERO_COUNT_KEYS:
        v = dc.get(k)
        c.true("N-A derived_counts.%s is present, an int (not bool) and == 0 (direct observation of the retained Pack dump)" % k,
               k in dc and type(v) is int and v == 0)
    # ---- retained sources
    rs = T.get("retained_sources") or {}
    c.eq("P1 Pack retained_sources.reconstruction_bundle == parsed bundle file", bundle, rs.get("reconstruction_bundle"))
    manifest_obj, manifest_digest_ok = data.get("manifest"), False
    if manifest_obj is not None:
        c.eq("P1 Pack retained_sources.manifest == Action Manifest fixture parsed from the root", manifest_obj, rs.get("manifest"))
        c.eq("P1 canonical digest of the Action Manifest fixture == frozen digest", MANIFEST_DIGEST, h2_of(manifest_obj))
    else:
        c.true("P1 Action Manifest fixture could be read from the Action Manifest root", False)
    # ---- retained decision
    decs = [x for x in (bundle.get("records") or []) if isinstance(x, dict) and x.get("record_type") == "runtime_decision"]
    c.eq("P1 bundle has exactly one runtime_decision record", 1, len(decs))
    dd = (decs[0].get("data") if len(decs) == 1 else None) or {}
    bind = dd.get("binding") or {}
    rdecs = rec.get("decisions") or []
    rd0 = rdecs[0] if rdecs and isinstance(rdecs[0], dict) else {}
    c.eq("P1 native record file has exactly one decision", 1, len(rdecs))
    c.eq("P1 retained decision effect_id", EFFECT_ID, dd.get("effect_id"))
    c.eq("P1 retained decision proposal commitment", PROPOSAL_COMMITMENT, bind.get("proposal_commitment"))
    c.eq("P1 retained decision tenant / generation", (TENANT, GENERATION), (bind.get("tenant_id"), bind.get("generation")))
    c.eq("P1 retained decision result", "authorized", dd.get("result"))
    c.true("P1 retained decision_id == native record file decision_id (per-run, non-empty)", bool(dd.get("decision_id")) and dd.get("decision_id") == rd0.get("decision_id"))
    c.eq("P1 native record file decision effect_id", EFFECT_ID, rd0.get("effect_id"))
    # ---- validation (harness-reported native Pack validation)
    val = np_.get("validation") or {}
    c.eq("P1 Pack validation valid", True, val.get("valid"))
    c.eq("P1 Pack validation errors (zero)", [], val.get("errors"))
    c.true("P1 Pack validation warnings are recorded (not frozen)", isinstance(val.get("warnings"), list))
    c.true("P1 harness status/oracle (necessary, never sufficient)", r.get("status") == "PASS" and d(r, "oracle", "all_ok") is True)
    out.update(record_sha256=sha(rec_bytes), bundle_h1=h1, bundle_h2=h2, pack_file_sha256=sha(pack_bytes), destination_file_sha256=sha(data["dest_bytes"]),
               pack_id=pack.get("pack_id"), bundle_id=bundle.get("bundle_id"), generated_at=bundle.get("generated_at"), decision_id=dd.get("decision_id"),
               pack_validation_warning_count=len(val["warnings"]) if isinstance(val.get("warnings"), list) else None)
    return out


def mutation_expectations(bundle):
    """Independent reproduction of each harness mutation on a copy of the retained bundle file."""
    def deep(o):
        return json.loads(json.dumps(o))

    def n1():
        b = deep(bundle)
        [x for x in b["records"] if x.get("record_type") == "runtime_decision"][0]["data"]["binding"]["tenant_id"] = "tenant-beta"
        return b

    def n3a():
        b = deep(bundle)
        b["status"] = "reconstruction_complete"
        return b

    def n3b():
        b = n3a()
        for rep in b["import_reports"]:
            rep["complete"] = True
            rep["findings"] = []
        return b

    def n5():
        b = deep(bundle)
        b["producer_profiles"][0]["revision"] = N5_WRONG_REVISION
        return b
    return {CASE_N1: n1, "n3a": n3a, "n3b": n3b, CASE_N5: n5}


def check_negative(c, label, r, data, p1, p1_out, expect, repro):
    if not isinstance(r, dict):
        return
    c.eq("%s case_id" % label, expect["case_id"], r.get("case_id"))
    c.eq("%s schema" % label, EVIDENCE_SCHEMA, r.get("schema"))
    c.eq("%s outcome is REFUSED_NATIVE (no harness-error masquerading)" % label, "REFUSED_NATIVE", r.get("outcome"))
    c.true("%s carries no harness failure reason" % label, "reason" not in r)
    np_ = r.get("native_pack") or {}
    c.eq("%s native outcome" % label, "REFUSED_NATIVE", np_.get("outcome"))
    c.eq("%s native exception type" % label, "ImportContractError", np_.get("type"))
    c.eq("%s native exception code" % label, None, np_.get("code"))
    c.eq("%s native exception message (exact frozen text)" % label, expect["message"], np_.get("message"))
    m = r.get("mutation") or {}
    c.eq("%s mutation field_path/from/to" % label, (expect["field_path"], expect["from"], expect["to"]), (m.get("field_path"), m.get("from"), m.get("to")))
    if "variant" in expect:
        c.eq("%s mutation variant" % label, expect["variant"], m.get("variant"))
    c.eq("%s original bundle unmodified after run" % label, True, m.get("original_unmodified_after_run"))
    c.eq("%s original Action Manifest supplied and pinned" % label, (True, MANIFEST_FILE_SHA), (m.get("manifest_supplied"), m.get("manifest_file_sha256")))
    dst = r.get("destination") or {}
    c.eq("%s destination effects before/after" % label, ({}, {}), (dst.get("effects_before"), dst.get("effects_after")))
    c.eq("%s destination no_effect" % label, True, dst.get("no_effect"))
    c.eq("%s P1 precondition passed" % label, ("IMPORTED", "PASS"), (d(r, "p1_precondition", "outcome"), d(r, "p1_precondition", "status")))
    c.eq("%s precondition record == P1 record" % label, p1_out.get("record_sha256"), d(r, "p1_precondition", "record_sha256"))
    c.eq("%s original bundle H1 == retained bundle file" % label, p1_out.get("bundle_h1"), m.get("original_bundle_H1_sha256"))
    c.eq("%s original bundle H2 == recomputed from the bundle file" % label, p1_out.get("bundle_h2"), m.get("original_bundle_H2_pack_canonical_sha256"))
    c.true("%s original and mutated H2 differ" % label, m.get("mutated_bundle_H2_pack_canonical_sha256") != m.get("original_bundle_H2_pack_canonical_sha256"))
    if repro is not None:
        c.eq("%s mutated H2 reproduced from the retained bundle file with only the declared mutation" % label, h2_of(repro), m.get("mutated_bundle_H2_pack_canonical_sha256"))
    c.eq("%s harness status (necessary, never sufficient)" % label, "PASS", r.get("status"))
    c.eq("%s limits block present" % label, True, isinstance(r.get("limits"), dict))


def check_cases(c, ctx, data, p1_out, roots):
    res, bundle = data["results"], data["bundle"]
    mut = mutation_expectations(bundle) if isinstance(bundle, dict) else {}

    def repro(key):
        try:
            return mut[key]()
        except (KeyError, IndexError, TypeError, AttributeError):
            return None
    ref = d(res, CASE_P1, "limits")
    check_negative(c, "N1-TEN", res.get(CASE_N1), data, res.get(CASE_P1), p1_out,
                   {"case_id": CASE_N1, "message": N1_MESSAGE, "field_path": "records[runtime_decision].data.binding.tenant_id", "from": TENANT, "to": "tenant-beta"},
                   repro(CASE_N1))
    n3 = res.get(CASE_N3)
    check_negative(c, "N3 (status alone)", n3, data, res.get(CASE_P1), p1_out,
                   {"case_id": CASE_N3, "message": N3_MESSAGE, "field_path": "status", "from": "reconstruction_partial", "to": "reconstruction_complete",
                    "variant": "status_alone"}, repro("n3a"))
    vb = n3.get("variant_b") if isinstance(n3, dict) else None
    c.true("N3 carries a nested variant_b", isinstance(vb, dict))
    check_negative(c, "N3 variant_b (status and reports forged complete)", vb, data, res.get(CASE_P1), p1_out,
                   {"case_id": CASE_N3, "message": N3_MESSAGE, "field_path": "status+import_reports[*].complete+findings", "from": "reconstruction_partial",
                    "to": "reconstruction_complete, reports complete, findings cleared", "variant": "status_and_reports_forged_complete"}, repro("n3b"))
    if isinstance(n3, dict) and isinstance(vb, dict):
        c.true("N3 variants mutate to different bundles", d(n3, "mutation", "mutated_bundle_H2_pack_canonical_sha256") != d(vb, "mutation", "mutated_bundle_H2_pack_canonical_sha256"))
    check_negative(c, "N5-REV", res.get(CASE_N5), data, res.get(CASE_P1), p1_out,
                   {"case_id": CASE_N5, "message": N5_MESSAGE, "field_path": "producer_profiles[0].revision", "from": CP_SHA, "to": N5_WRONG_REVISION}, repro(CASE_N5))
    for label, entry in (("N1-TEN", res.get(CASE_N1)), ("N3", n3), ("N3 variant_b", vb), ("N5-REV", res.get(CASE_N5))):
        if isinstance(entry, dict):
            check_sources(c, label, entry, roots, False)
    # limits
    check_limit_texts(c, ref)
    for label, entry in (("P1", res.get(CASE_P1)), ("N1-TEN", res.get(CASE_N1)), ("N3", n3), ("N3 variant_b", vb), ("N5-REV", res.get(CASE_N5))):
        if isinstance(entry, dict):
            check_limits(c, label, entry.get("limits"), ref)
    check_claims(c, res)


def load_inputs(c, ev):
    data = {"results": {}}
    obj, _ = load(c, ev, "c3.result.json")
    if isinstance(obj, dict):
        c.eq("c3.result.json holds exactly the four C3 case ids", sorted(CASES), sorted(obj))
        data["results"] = {k: obj[k] for k in CASES if isinstance(obj.get(k), dict)}
        for k in CASES:
            c.true("case %s result is an object" % k, isinstance(obj.get(k), dict))
    elif obj is not None:
        c.true("c3.result.json is a JSON object", False)
    for key, name in (("rec", "c3.native-records.json"), ("dest", "c3.native-destination.json"), ("bundle", "c3.reconstruction-bundle.json"), ("pack", "c3.evidence-pack.json")):
        o, b = load(c, ev, name)
        if o is not None and not isinstance(o, dict):
            c.true("%s is a JSON object" % name, False)
            o = None
        data[key], data[key + "_bytes"] = o, b
    return data


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
    for pattern, expected in SUITES:
        s = next((x for x in suites if isinstance(x, dict) and x.get("pattern") == pattern), {})
        c.eq("suite %s exit code" % pattern, 0, s.get("exit_code"))
        c.eq("suite %s expected tests" % pattern, expected, s.get("expected_tests"))
        c.eq("suite %s observed tests" % pattern, expected, s.get("observed_tests"))
        c.true("tests.log contains 'Ran %d tests'" % expected, re.search(r"^Ran %d tests? in " % expected, log, re.M) is not None)
    c.eq("tests.json outcome", "PASSED", (tj or {}).get("outcome") if isinstance(tj, dict) else None)
    c.eq("tests.log total of observed counts is 102", [26, 76], sorted(int(x) for x in re.findall(r"^Ran (\d+) tests? in ", log, re.M)))
    bad = re.findall(r"\.\.\. (?:skipped|expected failure|unexpected success|FAIL|ERROR)|^FAILED \(|^OK \((?:skipped|expected failures)|^(?:FAIL|ERROR): ", log, re.M)
    c.eq("tests.log has no skip, expected-failure, unexpected-success, failure or error markers", [], bad[:5])
    c.true("tests.log reports OK for both suites", len(re.findall(r"^OK$", log, re.M)) == 2)
    cj, _ = load(c, ev, "cases.json")
    c.eq("cases.json harness exit code", 0, cj.get("exit_code") if isinstance(cj, dict) else None)


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
        text = json.dumps(entry, indent=2, sort_keys=True) + "\n"
        (ev / name).write_text(text, encoding="utf-8")
        c.eq("slice %s re-read parses to the source entry" % name, entry, strict_loads((ev / name).read_bytes()))
    val = d(res, CASE_P1, "native_pack", "validation")
    lim = d(res, CASE_P1, "limits")
    for name, obj in (("p1.pack-validation-report.json", val), ("limits-L1-L19.json", lim)):
        if obj is None:
            c.true("slice %s written" % name, False)
            continue
        (ev / name).write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        c.eq("slice %s re-read parses to the source object" % name, obj, strict_loads((ev / name).read_bytes()))
    if isinstance(lim, dict):
        c.eq("limits-L1-L19.json carries L1..L19 verbatim", {"L%d" % n: lim.get("L%d" % n) for n in range(1, 20)},
             {k: v for k, v in (strict_loads((ev / "limits-L1-L19.json").read_bytes()) if (ev / "limits-L1-L19.json").is_file() else {}).items() if re.fullmatch(r"L\d+", k)})


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
    for name in ("sources.txt", "context.json") + INPUTS:
        c.true("evidence artifact %s present" % name, (ev / name).is_file())
    ctx, _ = load(c, ev, "context.json")
    ctx = ctx if isinstance(ctx, dict) else {}
    guarded(c, "context checks", check_context, c, ctx)
    guarded(c, "suite checks", check_tests, c, ev)
    data = guarded(c, "input loading", load_inputs, c, ev) or {"results": {}, "rec": None, "dest": None, "bundle": None, "pack": None}
    roots = {}
    for key, v in PINS.items():
        raw = os.environ.get(v[4])
        c.true("%s is set for the check step" % v[4], bool(raw))
        if raw:
            roots[key] = pathlib.Path(raw).resolve()
    data["manifest"] = None
    if "action_manifest" in roots:
        try:
            raw = (roots["action_manifest"] / MANIFEST_PATH).read_bytes()
            c.eq("Action Manifest fixture sha256 (read from the Action Manifest root)", MANIFEST_FILE_SHA, sha(raw))
            data["manifest"] = strict_loads(raw)
        except (OSError, ValueError) as exc:
            c.eq("Action Manifest fixture readable and strict JSON", "present", "%s: %s" % (type(exc).__name__, str(exc)[:100]))
    p1_out = guarded(c, "P1 checks", check_p1, c, ctx, data, roots) or {}
    guarded(c, "negative-case, limits and claim checks", check_cases, c, ctx, data, p1_out, roots)
    guarded(c, "slice writing", write_slices, c, ev, data)
    present = {n: (ev / n).is_file() for n in ("sources.txt", "context.json") + INPUTS + tuple(n for n, _ in SLICES) + DERIVED}
    c.true("every mandatory and derived evidence file exists before indexing", all(present.values()))
    idx = index_files(ev, ("oracle.txt", "evidence-manifest.json"))
    c.eq("evidence index re-hash (independent second read of every indexed file)", idx, index_files(ev, ("oracle.txt", "evidence-manifest.json")))
    verdict = "PASS" if c.failed == 0 else "FAIL"
    lines = c.text()
    header = "C3 hosted oracle comparison: %s (%d checks, %d failed)" % (verdict, len(c.rows), c.failed)
    (ev / "oracle.txt").write_text(header + "\n" + "\n".join(lines) + "\n", encoding="ascii")
    idx["oracle.txt"] = sha((ev / "oracle.txt").read_bytes())
    stable = {"schema": MANIFEST_SCHEMA, "case_group": CASE_GROUP, "cases": list(CASES), "harness_schema": EVIDENCE_SCHEMA,
              "expected_suites": {p: n for p, n in SUITES},
              "sources": {k: {"repository": v[0], "sha": v[1], "tree": v[2]} for k, v in PINS.items()},
              "fixtures": {"proposal": {"path": PROPOSAL_PATH, "sha256": PROPOSAL_SHA},
                           "action_manifest_fixture": {"path": MANIFEST_PATH, "sha256": MANIFEST_FILE_SHA, "canonical_digest": MANIFEST_DIGEST}},
              "frozen": {"effect_id": EFFECT_ID, "proposal_commitment": PROPOSAL_COMMITMENT, "tenant_id": TENANT, "generation": GENERATION,
                         "replay_status": "reconstruction_partial", "findings": [["B004", "warning"]], "pack_version": "0.2.0", "review_status": "draft",
                         "transformation_version": TRANSFORMATION, "zero_count_keys": list(ZERO_COUNT_KEYS), "n1_message": N1_MESSAGE,
                         "n3_message": N3_MESSAGE, "n5_message": N5_MESSAGE, "n5_wrong_revision": N5_WRONG_REVISION,
                         "c2_producer_sha256": C2_PRODUCER_SHA},
              "oracle_references": {"contract": "Hub #273 comment 6671327666", "freeze": "Hub #273 comment 6671384213"},
              "dependency_lock_sha256": (ctx.get("host_sources") or {}).get(LOCK_PATH), "locked_versions": LOCKED,
              "host_source_sha256": ctx.get("host_sources"), "limitations": list(LIMITATIONS), "limits_status": LIMIT_STATUS}
    manifest = {"schema": MANIFEST_SCHEMA, "stable_identity": stable,
                "stable_identity_sha256": sha(json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
                "per_run": {"repository": ctx.get("repository"), "workflow": ctx.get("workflow"), "github_run_id": ctx.get("github_run_id"),
                            "github_run_attempt": ctx.get("github_run_attempt"), "github_sha": ctx.get("github_sha"), "github_ref": ctx.get("github_ref"),
                            "orchestrator_head": ctx.get("orchestrator_head"), "runner": ctx.get("runner"), "python_version": ctx.get("python_version"),
                            "pip_version": ctx.get("pip_version"), "git_version": ctx.get("git_version"), "dependencies": ctx.get("dependencies"),
                            "values_not_golden": p1_out},
                "evidence_file_sha256": dict(sorted(idx.items())), "evidence_index_excludes": ["evidence-manifest.json (itself)"],
                "verdict": verdict, "check_count": len(c.rows), "failed": c.failed, "qualification": QUALIFICATION,
                "status_vocabulary": ["PASS", "FAIL", "BLOCKED", "NOT EXECUTED"], "not_executed": list(NOT_EXECUTED), "n_a_disposition": NA_DISPOSITION}
    write_json(ev / "evidence-manifest.json", manifest)
    again = index_files(ev, ("evidence-manifest.json",))
    rc = 0 if verdict == "PASS" else 1
    if again != dict(manifest["evidence_file_sha256"]):
        print("c3_hosted_check: evidence index differs from the files on disk after writing", file=sys.stderr)
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
            (("Exact-source verification", "STEP_VERIFY"), ("Focused C3 suites (26 + 76)", "STEP_TESTS"), ("C3 cases (one harness run)", "STEP_CASES"),
             ("Frozen-literal comparison (orchestrator-owned, not independent)", "STEP_ORACLE"))]
        overall = "BLOCKED" if blocked else "PASS" if all(s == "PASS" for _, s in steps) else ("FAIL" if any(s == "FAIL" for _, s in steps) else "NOT PASSED")

        def clean(v):
            s = "".join(ch if " " <= ch <= "~" else "?" for ch in " ".join(str(v).split()))
            return s.replace("`", "'").replace("|", "/").replace("<", "&lt;").replace(">", "&gt;")[:200]
        out = ["### C3 hosted run (hosted developer evidence only, manual only)", "",
               "**Developer check result: %s** (hosted developer evidence only; not qualification, approval, authenticity, effect proof or complete reconstruction)" % overall, "",
               "| Stage | Status |", "|---|---|"] + ["| %s | %s |" % (a, b) for a, b in steps] + [""]
        try:
            ctx = json.loads((ev / "context.json").read_text(encoding="utf-8"))
            out += ["| Field | Value |", "|---|---|"] + ["| %s | `%s` |" % (k, clean(v)) for k, v in (
                ("Dispatched ref", ctx.get("github_ref")), ("Orchestrator SHA", ctx.get("github_sha")),
                ("Run", "%s attempt %s" % (ctx.get("github_run_id"), ctx.get("github_run_attempt"))), ("Control Plane pin", CP_SHA), ("Replay Bundle pin", RB_SHA),
                ("Evidence Pack pin", PACK_SHA), ("Action Manifest pin", AM_SHA), ("Dependencies", ctx.get("dependencies")), ("Runner", ctx.get("runner")))] + [""]
        except (OSError, ValueError):
            out += ["No context.json was produced.", ""]
        try:
            first = (ev / "oracle.txt").read_text(encoding="utf-8").splitlines()
            out += ["Oracle: `%s`" % clean(first[0] if first else "empty")] + ["- `%s`" % clean(x) for x in first if x.startswith("FAIL")][:20] + [""]
        except OSError:
            out += ["Oracle: not produced (NOT EXECUTED or failed earlier).", ""]
        out += ["The Replay result is `reconstruction_partial` (B004) and is never complete. A valid Pack validation result means internal consistency only, not reviewer approval, "
                "compliance or audit. Authority is synthetic and unauthenticated. Hub #280 is OPEN.", "", "Not executed: " + "; ".join(NOT_EXECUTED) + "."]
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
        print("usage: c3_hosted_check.py verify|check|summary", file=sys.stderr)
        return 2
    try:
        return {"verify": verify, "check": check, "summary": summary}[argv[1]]()
    except Exception as exc:
        print("c3_hosted_check %s failed closed: %s: %s" % (argv[1], type(exc).__name__, str(exc)[:300]), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
