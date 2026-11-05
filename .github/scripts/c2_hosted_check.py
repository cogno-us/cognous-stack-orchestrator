"""Hosted C2 qualification-preparation checker for the manual workflow (stdlib only; run as `python -I -B`).

Development-only and fixture-scoped. NOT independent qualification, release evidence or an authenticated-authority claim.
Subcommands (the workflow passes everything else through the environment, never through shell text):
  verify   exact-source and context check before any component code runs; writes sources.txt and context.json.
  check    independent comparison of the produced artifacts with the frozen C2 oracle (it does not trust the adapter's own
           PASS); writes oracle.txt and evidence-manifest.json. Exit 1 on any mismatch or missing artifact.
  summary  job summary from the step outcomes and the files that exist; never raises.
Every expected literal below is the frozen contract (Hub #273 6665625039 + journal amendment 6667028276), not adapter output.
"""
import hashlib
import importlib.metadata as md
import json
import os
import pathlib
import subprocess
import sys
import tempfile

CASE_GROUP = "c2_p1_n1_n2_hosted_group"
CASES = ("c2_p1_runtime_profile_partial", "c2_n1_stored_tenant_tamper", "c2_n2_c1_records_incompatible")
PINS = {"control_plane": ("cogno-us/cognous-control-plane", "484fdbd297235dd24148ddb0703f2055a31eabff", "c182939882103015f12c5360fccf377c54e2c4f9"),
        "replay_bundle": ("cogno-us/cognous-replay-bundle", "93a76e281fcae6a65d2cd1d35376f87442dafb95", "aca6e6b8bdd33d51db3b34bc0c75eff93b9ff88f")}
EXPECTED_TESTS = 55
PROPOSAL_SHA = "1033c73e7dbe677cc71520711d3aaacb182952e5c12c8eaa489f24be0014cfe2"
C1_RECORDS = {"positive": ("tests/manual_contract/c2/fixtures/c1-hosted-native-records.positive.json",
                           "51e4d278b61134fda1db36b4fa82af7e4ad03df761f53c58941b8e9203b70e91", "42067811832", "13433583494"),
              "negative": ("tests/manual_contract/c2/fixtures/c1-hosted-native-records.negative.json",
                           "6a3e188088fe5fa2913ac5b085351175aa8db77e19d19420c8ed68d8a7b8e9cd", "42068362339", "13434638870")}
PROPOSAL_PATH = "tests/manual_contract/c1/fixtures/proposal.tenant-alpha.json"
EFFECT_ID = "sha256:4e5844d6d53ab6f8694e9c76cb6238ec4110137dd35de73cb0b22963961ecde8"
PROPOSAL_COMMITMENT = "sha256:becaea3f10b5edf56ea181e0cd62793ebe8262238f948fb72dc5c0389c7f8c53"
TENANT, GENERATION = "tenant-alpha", "bounded-authorization-effect/0.3-strict-tenant"
NOW = "2026-10-05T19:00:00+00:00"
VOCAB, RA_PROFILE = "runtime-authority-reasons/0.1", "runtime-authority/0.1"
RECORD_TYPES = ["input_time_floors", "resolution_check", "resolution_check_event", "runtime_decision", "runtime_proposal"]
N1_MESSAGE = "decisions[0].binding.tenant_id conflicts with committed operation"
N2_MESSAGE = "typed refusal profile: resolution journal missing"
SCHEMA_E = "cognous.orchestrator.c2-evidence/0-candidate"
MANIFEST_SCHEMA = "cognous.orchestrator.c2-hosted-evidence-manifest/0-candidate"
ARTIFACTS = ("sources.txt", "context.json", "tests.log", "tests.json", "cases.json", "oracle.txt", "evidence-manifest.json",
             "p1.result.json", "n1.result.json", "n2.result.json", "p1.native-records.json", "p1.native-destination.json",
             "n1.native-records.json", "n1.native-destination.json")
LIMIT_VALUES = {"status": "DEVELOPMENT_ONLY_FIXTURE_SCOPED", "authority_basis": "SYNTHETIC_UNAUTHENTICATED_RESOLVER", "time_source": "test_override",
                "decision_semantics_only": True, "effect_executed": False, "consistency_only": True, "hub_280_digest_basis": "OPEN",
                "not_institutional_authority": True, "not_independent_qualification": True, "not_general_interoperability": True,
                "replay_protection": "none", "event_decision_linkage": "NOT_ESTABLISHED", "event_decision_ids": None,
                "journal_association": "proposal_level_association_only"}
HOSTED_SOURCES = ("tests/manual_contract/real_c2.py", "tests/manual_contract/c2_producer.py", "tests/manual_contract/real_c1.py",
                  "tests/manual_contract/runner.py", "tests/manual_contract/c2/test_real_c2.py", ".github/scripts/run_unittest_no_skips.py",
                  ".github/scripts/c2_hosted_check.py", ".github/locks/cryptography-pydantic-pytest-513753.txt",
                  ".github/workflows/manual-contract-edge.yml")
NOT_EXECUTED = ("strict-tenant import with a real executor export (UNVERIFIED: no fixture exists)", "Control Plane refusal record through Replay",
                "revocation, expiry and stale-record replay", "partial failure and incomplete journal", "complete reconstruction",
                "independent qualification, institutional authority, authenticity, release and production")
LIMITATIONS = ("synthetic unauthenticated authority; test-only public Ed25519 key", "fixed caller-supplied clock (decide(now=), time_source test_override)",
               "Replay checks consistency only; a consistently re-derived forgery would import", "no freshness or replay protection",
               "reconstruction_partial (B004) is never complete reconstruction", "journal events are proposal-commitment-associated; direct event-to-decision "
               "identity linkage is not established at the pinned Control Plane revision", "lineage to C1 is identity and proposal level only",
               "Hub #280 digest-basis defect is OPEN", "hosted developer evidence only: not independent qualification")


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


# ------------------------------------------------------------------ verify
def verify():
    ev = evidence_dir()
    ev.mkdir(parents=True, exist_ok=True)
    work = pathlib.Path(os.environ.get("GITHUB_WORKSPACE") or os.getcwd()).resolve()
    roots = {"control_plane": pathlib.Path(os.environ["COGNOUS_C2_CONTROL_PLANE_ROOT"]), "replay_bundle": pathlib.Path(os.environ["COGNOUS_C2_REPLAY_BUNDLE_ROOT"])}
    ctx = {"repository": os.environ.get("GITHUB_REPOSITORY"), "github_sha": os.environ.get("GITHUB_SHA"), "github_ref": os.environ.get("GITHUB_REF"),
           "github_run_id": os.environ.get("GITHUB_RUN_ID"), "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
           "case_id": os.environ.get("CASE_ID"), "workflow": os.environ.get("GITHUB_WORKFLOW"), "event_name": os.environ.get("GITHUB_EVENT_NAME"),
           "runner": {k: os.environ.get(k) for k in ("RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion", "RUNNER_ENVIRONMENT")},
           "python_version": sys.version, "platform": sys.platform, "case_group": CASE_GROUP, "cases": list(CASES), "dependencies": {}}
    for name in ("pydantic", "pydantic_core", "cryptography", "pytest"):
        try:
            ctx["dependencies"][name] = md.version(name)
        except md.PackageNotFoundError:
            ctx["dependencies"][name] = None
    ctx["pip_version"] = os.environ.get("PIP_VERSION_TEXT")
    ctx["fixtures"] = {}
    ctx["host_sources"] = {}
    lines = []
    try:
        if ctx["case_id"] != CASE_GROUP:
            raise Fail("case_id %r is not the C2 hosted group %r" % (ctx["case_id"], CASE_GROUP))
        if ctx["event_name"] != "workflow_dispatch":
            raise Fail("event is %r, not workflow_dispatch" % ctx["event_name"])
        if ctx["github_ref"] != "refs/heads/main":
            raise Fail("dispatched ref is %r; the C2 hosted run is allowed only from refs/heads/main" % ctx["github_ref"])
        head = git(work, "rev-parse", "HEAD")
        ctx["orchestrator_head"] = head
        if not ctx["github_sha"] or head != ctx["github_sha"]:
            raise Fail("orchestrator HEAD %s != GITHUB_SHA %s" % (head, ctx["github_sha"]))
        if git(work, "status", "--porcelain", "--untracked-files=no") != "":
            raise Fail("orchestrator checkout has modified tracked files")
        lines.append("orchestrator: head==GITHUB_SHA==%s, ref==refs/heads/main, tracked files clean" % head)
        for key, root in roots.items():
            repo, want_sha, want_tree = PINS[key]
            prefix = {"control_plane": "C2_CP", "replay_bundle": "C2_RB"}[key]
            if (os.environ.get(prefix + "_SHA"), os.environ.get(prefix + "_TREE")) != (want_sha, want_tree):
                raise Fail("workflow pin %s_SHA/%s_TREE differs from the checker's frozen pin (workflow/checker drift)" % (prefix, prefix))
            root = root.resolve()
            got = git(root, "rev-parse", "HEAD")
            if got != want_sha:
                raise Fail("%s HEAD is %s, expected %s" % (key, got, want_sha))
            got = git(root, "rev-parse", "HEAD^{tree}")
            if got != want_tree:
                raise Fail("%s tree is %s, expected %s" % (key, got, want_tree))
            if git(root, "rev-parse", "--show-toplevel") != str(root):
                raise Fail("%s toplevel is not %s" % (key, root))
            tags = {line[:2] for line in git(root, "ls-files", "-v").splitlines()}
            if tags != {"H "}:
                raise Fail("%s has tracked files with a tag other than H: %s" % (key, sorted(tags)))
            if git(root, "status", "--porcelain", "--ignored=matching", "--untracked-files=all") != "":
                raise Fail("%s working tree is not clean (modified, untracked or ignored files)" % key)
            lines += [key, "  repository: " + repo, "  root: " + str(root), "  sha: " + want_sha, "  tree: " + want_tree,
                      "  checks passed: head==pin, tree==pin, toplevel==root, ls-files all H, status clean (ignored and untracked included)"]
        for rel, expect in (("proposal", (PROPOSAL_PATH, PROPOSAL_SHA)), ("c1_positive", (C1_RECORDS["positive"][0], C1_RECORDS["positive"][1])),
                            ("c1_negative", (C1_RECORDS["negative"][0], C1_RECORDS["negative"][1]))):
            got = sha((work / expect[0]).read_bytes())
            ctx["fixtures"][rel] = {"path": expect[0], "sha256": got, "frozen_sha256": expect[1]}
            if got != expect[1]:
                raise Fail("fixture %s sha256 %s differs from the frozen %s" % (expect[0], got, expect[1]))
        for rel in HOSTED_SOURCES:
            ctx["host_sources"][rel] = sha((work / rel).read_bytes())
        lines.append("fixtures: pinned proposal and both hosted C1 records equal their frozen sha256")
        for name in ("pydantic", "cryptography", "pytest"):
            if not ctx["dependencies"][name]:
                raise Fail("dependency %s is not installed" % name)
        ctx["verify"] = "PASS"
    except (Fail, OSError) as exc:
        ctx["verify"] = "FAIL"
        lines.append("SOURCE VERIFICATION FAILED: %s" % exc)
        write_json(ev / "context.json", ctx)
        (ev / "sources.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(lines[-1], file=sys.stderr)
        return 1
    write_json(ev / "context.json", ctx)
    (ev / "sources.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


# ------------------------------------------------------------------ check
class Checks:
    def __init__(self):
        self.rows, self.failed = [], 0

    def eq(self, name, want, got):
        ok = want == got
        self.rows.append(("OK" if ok else "FAIL", name, want, got))
        self.failed += 0 if ok else 1
        return ok

    def true(self, name, cond):
        return self.eq(name, True, bool(cond))

    def text(self):
        out = []
        for status, name, want, got in self.rows:
            out.append("%s %s" % (status, name) if status == "OK" else "FAIL %s -- expected %s, got %s" % (name, json.dumps(want)[:200], json.dumps(got, default=str)[:200]))
        return out


def load(c, ev, name, strict=True):
    path = ev / name
    try:
        data = path.read_bytes()
        obj = strict_loads(data) if name.endswith(".json") else None
    except (OSError, ValueError) as exc:
        c.eq("artifact %s readable and strict JSON" % name, "present", "%s: %s" % (type(exc).__name__, str(exc)[:100]))
        return None, None
    c.true("artifact %s present and non-empty" % name, len(data) > 0)
    return obj, data


def check_p1(c, ev, ctx):
    r, _ = load(c, ev, "p1.result.json")
    rec, rec_bytes = load(c, ev, "p1.native-records.json")
    dest, _ = load(c, ev, "p1.native-destination.json")
    if not isinstance(r, dict) or not isinstance(rec, dict):
        return {}
    c.eq("P1 schema", SCHEMA_E, r.get("schema"))
    c.eq("P1 case_id", CASES[0], r.get("case_id"))
    c.eq("P1 adapter status/outcome", ("PASS", "IMPORTED"), (r.get("status"), r.get("outcome")))
    c.eq("P1 producer config id", "C2-CP-RUNTIME-PROFILE-STRICT-TENANT-DECIDE-ONLY", r.get("producer_config_id"))
    nr = r.get("native_replay") or {}
    c.eq("P1 Replay status", "reconstruction_partial", nr.get("status"))
    c.eq("P1 Replay findings (exactly B004 warning)", [["B004", "warning"]], nr.get("findings"))
    c.eq("P1 Replay record types", RECORD_TYPES, nr.get("record_types"))
    c.eq("P1 Replay import report", [{"adapter_profile": "control-plane-strict-tenant-stack@484fdbd2", "rb_complete_flag": False,
                                      "source_revision": PINS["control_plane"][1]}], nr.get("import_reports"))
    c.eq("P1 attempts/observations/reconciliations/closeouts (adapter)", {k: 0 for k in ("attempts", "closeouts", "observations", "reconciliations")}, nr.get("counts"))
    dec = r.get("native_cp_decision") or {}
    b = dec.get("binding") or {}
    c.eq("P1 CP result/reasons", ("authorized", []), (dec.get("result"), dec.get("reasons")))
    c.eq("P1 CP time_source/decided_at", ("test_override", NOW), (dec.get("time_source"), dec.get("decided_at")))
    c.eq("P1 effect_id", EFFECT_ID, dec.get("effect_id"))
    c.eq("P1 binding tenant/generation/proposal commitment", (TENANT, GENERATION, PROPOSAL_COMMITMENT),
         (b.get("tenant_id"), b.get("generation"), b.get("proposal_commitment")))
    c.eq("P1 reason vocabulary / runtime-authority profile", (VOCAB, RA_PROFILE), (dec.get("reason_vocabulary_version"), (b.get("runtime_authority") or {}).get("profile")))
    c.eq("P1 proposal fixture sha256 (adapter evidence)", PROPOSAL_SHA, ((r.get("inputs") or {}).get("proposal") or {}).get("sha256"))
    s = r.get("sources") or {}
    for key in ("control_plane", "replay_bundle"):
        _, want_sha, want_tree = PINS[key]
        o = s.get(key) or {}
        c.eq("P1 measured %s head/tree" % key, (want_sha, want_tree), (o.get("observed_head"), o.get("observed_tree")))
        c.true("P1 %s clean flags and loaded modules" % key, o.get("tracked_files_clean") is True and o.get("ls_files_all_H") is True
               and o.get("status_ignored_clean") is True and bool(o.get("imported_modules")))
    c.eq("P1 revision label (measured, not downgraded)", PINS["control_plane"][1], s.get("revision_label"))
    c.true("P1 CP test helpers blob-verified", all(m in (s.get("control_plane") or {}).get("imported_modules", {}) for m in ("tests", "tests.test_bounded_authorization", "tests.test_runtime_authority")))
    prod = r.get("producer") or {}
    c.eq("P1 producer clock/calls", ("none", ["decide"]), (prod.get("clock_patch"), prod.get("calls")))
    c.eq("P1 producer key basis", "synthetic-validator", prod.get("producer_key_id"))
    c.eq("P1 harness orchestrator head == GITHUB_SHA", os.environ.get("GITHUB_SHA"), (r.get("harness") or {}).get("orchestrator_head"))
    c.eq("P1 runtime versions == context", {k: (ctx.get("dependencies") or {}).get(k) for k in ("cryptography", "pydantic")},
         {k: (r.get("runtime") or {}).get(k) for k in ("cryptography", "pydantic")})
    # independent reading of the raw persisted record (not the adapter's evidence)
    rr = r.get("record") or {}
    c.eq("P1 record sha256 == sha256 of the retained file bytes", sha(rec_bytes), rr.get("sha256"))
    c.eq("P1 record size == retained file size", len(rec_bytes), rr.get("size_bytes"))
    c.true("P1 record unchanged after import", rr.get("unchanged_after_import") is True)
    decs = rec.get("decisions") or []
    c.eq("P1 raw record has exactly one decision", 1, len(decs))
    d0 = decs[0] if decs and isinstance(decs[0], dict) else {}
    c.eq("P1 raw decision equals the adapter's native decision", d0, dec)
    c.eq("P1 raw decision effect_id/result", (EFFECT_ID, "authorized"), (d0.get("effect_id"), d0.get("result")))
    for key in ("attempts", "observations", "reconciliations", "closeouts", "refusals"):
        c.eq("P1 raw record %s empty or absent" % key, [], rec.get(key) or [])
    events = rec.get("check_events")
    c.true("P1 journal is a non-empty list", isinstance(events, list) and len(events) > 0)
    events = events if isinstance(events, list) else []
    c.true("P1 every event has decision_id present and null (amended oracle)", bool(events) and all(isinstance(e, dict) and "decision_id" in e and e["decision_id"] is None for e in events))
    c.true("P1 every event proposal commitment == pinned and == persisted decision's", bool(events) and all(
        isinstance(e, dict) and e.get("proposal_commitment") == PROPOSAL_COMMITMENT == (d0.get("binding") or {}).get("proposal_commitment")
        == (d0.get("operation_horizon") or {}).get("proposal_commitment") for e in events))
    c.true("P1 every event carries the reason vocabulary version", bool(events) and all(isinstance(e, dict) and e.get("reason_vocabulary_version") == VOCAB for e in events))
    rcs = rec.get("resolution_checks") or []
    c.true("P1 event check_id reported as observed, not equal to the resolution check id", bool(events) and bool(rcs)
           and all(e.get("check_id") != rcs[0].get("check_id") for e in events))
    j = r.get("journal") or {}
    c.eq("P1 journal limitation (amended oracle)", ("NOT_ESTABLISHED", None, True), (j.get("event_decision_linkage"), j.get("event_decision_ids"), j.get("proposal_level_association_only")))
    c.eq("P1 journal event count == raw record", len(events), j.get("event_count"))
    dev = (r.get("frozen_oracle_deviations") or [{}])[0]
    c.true("P1 predecessor discrepancy preserved and superseded", "REJECTED" in str(dev.get("frozen_text_status")) and "6667028276" in str(dev.get("superseded_by")))
    for k, v in LIMIT_VALUES.items():
        c.eq("P1 limits.%s" % k, v, (r.get("limits") or {}).get(k))
    c.true("P1 limits name the unauthenticated, test-only and partial-history limits", all(
        w in json.dumps(r.get("limits") or {}) for w in ("TEST_ONLY_PUBLIC_SYNTHETIC_ED25519", "no_authenticated_issuer", "not_complete_history", "NOT_ESTABLISHED")))
    dd = (dest or {}).get("effects") if isinstance(dest, dict) else None
    c.eq("P1 destination effects (retained file)", {}, dd)
    c.eq("P1 destination effect count (adapter)", 0, (r.get("destination") or {}).get("effect_count"))
    c.true("P1 adapter oracle block all_ok (necessary, never sufficient)", (r.get("oracle") or {}).get("all_ok") is True)
    return {"record_sha256": sha(rec_bytes), "decision_id": d0.get("decision_id"), "record_size_bytes": len(rec_bytes)}


def check_n1(c, ev):
    r, _ = load(c, ev, "n1.result.json")
    rec, rec_bytes = load(c, ev, "n1.native-records.json")
    dest, _ = load(c, ev, "n1.native-destination.json")
    if not isinstance(r, dict):
        return {}
    c.eq("N1 case_id", CASES[1], r.get("case_id"))
    c.eq("N1 adapter status/outcome", ("PASS", "REFUSED_NATIVE"), (r.get("status"), r.get("outcome")))
    nr = r.get("native_replay") or {}
    c.eq("N1 native exception type/message/code", ("ImportContractError", N1_MESSAGE, None), (nr.get("type"), nr.get("message"), nr.get("code")))
    m = r.get("mutation") or {}
    c.eq("N1 mutated field and values", ("decisions[0].binding.tenant_id", TENANT, "tenant-beta"), (m.get("field_path"), m.get("from"), m.get("to")))
    c.eq("N1 original proposal supplied and pinned", (True, PROPOSAL_SHA), (m.get("proposal_supplied"), m.get("proposal_sha256")))
    c.true("N1 tenant check reached", r.get("tenant_check_reached") is True)
    c.eq("N1 precondition: the unmodified record was imported", "IMPORTED", (r.get("p1_precondition") or {}).get("outcome"))
    if isinstance(rec, dict) and rec_bytes is not None:
        c.eq("N1 original record hash == retained unmodified record", sha(rec_bytes), m.get("original_record_sha256"))
        c.true("N1 mutated input hash differs from the original and is declared a re-serialisation", m.get("mutated_input_sha256") != m.get("original_record_sha256")
               and m.get("sha256_of") == "canonical_reserialisation_of_test_mutation")
        c.eq("N1 retained record still has tenant-alpha (mutation was in memory only)", TENANT, (((rec.get("decisions") or [{}])[0].get("binding")) or {}).get("tenant_id"))
    c.eq("N1 destination effects (retained file)", {}, (dest or {}).get("effects") if isinstance(dest, dict) else None)
    c.eq("N1 revision label", PINS["control_plane"][1], ((r.get("sources") or {}).get("revision_label")))
    return {"original_record_sha256": m.get("original_record_sha256"), "mutated_input_sha256": m.get("mutated_input_sha256")}


def check_n2(c, ev, work):
    r, _ = load(c, ev, "n2.result.json")
    if not isinstance(r, dict):
        return {}
    c.eq("N2 case_id", CASES[2], r.get("case_id"))
    c.eq("N2 adapter status/outcome", ("PASS", "REFUSED_NATIVE"), (r.get("status"), r.get("outcome")))
    c.eq("N2 revision label (genuine measured pin, no downgrade)", PINS["control_plane"][1], (r.get("sources") or {}).get("revision_label"))
    out = {}
    for key, (path, frozen, run_id, artifact_id) in C1_RECORDS.items():
        item = (r.get("records") or {}).get(key) or {}
        c.eq("N2 %s retained fixture sha256 == frozen" % key, frozen, sha((work / path).read_bytes()))
        c.eq("N2 %s adapter-reported sha256 == frozen" % key, frozen, item.get("records_sha256"))
        c.eq("N2 %s hosted run/artifact references" % key, (run_id, artifact_id), (item.get("hosted_run_id"), item.get("hosted_artifact_id")))
        n = item.get("native_replay") or {}
        c.eq("N2 %s native refusal" % key, ("REFUSED_NATIVE", "ImportContractError", N2_MESSAGE, None), (n.get("outcome"), n.get("type"), n.get("message"), n.get("code")))
        out[key] = frozen
    return out


def check():
    ev = evidence_dir()
    work = pathlib.Path(os.environ.get("GITHUB_WORKSPACE") or os.getcwd()).resolve()
    c = Checks()
    for name in ARTIFACTS:
        if name not in ("oracle.txt", "evidence-manifest.json"):
            c.true("evidence artifact %s present" % name, (ev / name).is_file())
    ctx, _ = load(c, ev, "context.json")
    ctx = ctx or {}
    c.eq("context: verify PASS", "PASS", ctx.get("verify"))
    c.eq("context: case group", CASE_GROUP, ctx.get("case_id"))
    tj, _ = load(c, ev, "tests.json")
    tj = tj or {}
    c.eq("focused suite outcome/exit/expected count", ("PASSED", 0, EXPECTED_TESTS), (tj.get("outcome"), tj.get("exit_code"), tj.get("expected_tests")))
    try:
        log = (ev / "tests.log").read_text(encoding="utf-8")
    except OSError:
        log = ""
    c.true("focused suite log: Ran %d tests, OK, no failures/skips/expected failures" % EXPECTED_TESTS, ("\nRan %d tests in " % EXPECTED_TESTS) in ("\n" + log)
           and "\nOK\n" in ("\n" + log + "\n") and "skipped" not in log and "expected failures" not in log and "FAILED" not in log)
    cj, _ = load(c, ev, "cases.json")
    c.eq("case exit codes (all three cases ran)", {n: 0 for n in CASES}, ((cj or {}).get("exit_codes")))
    p1 = check_p1(c, ev, ctx)
    n1 = check_n1(c, ev)
    n2 = check_n2(c, ev, work)
    c.true("P1 and N1 used distinct runs (different decision/record)", bool(p1) and bool(n1) and p1.get("record_sha256") != n1.get("original_record_sha256"))
    lines = c.text()
    verdict = "PASS" if c.failed == 0 else "FAIL"
    # evidence manifest: stable identity part (hashed) kept apart from per-run variable fields
    stable = {"schema": MANIFEST_SCHEMA, "case_group": CASE_GROUP, "cases": list(CASES), "expected_focused_tests": EXPECTED_TESTS,
              "sources": {k: {"repository": v[0], "sha": v[1], "tree": v[2]} for k, v in PINS.items()},
              "fixtures": {"proposal": {"path": PROPOSAL_PATH, "sha256": PROPOSAL_SHA},
                           **{"c1_" + k: {"path": v[0], "sha256": v[1], "hosted_run_id": v[2], "hosted_artifact_id": v[3]} for k, v in C1_RECORDS.items()}},
              "oracle": {"effect_id": EFFECT_ID, "proposal_commitment": PROPOSAL_COMMITMENT, "tenant_id": TENANT, "generation": GENERATION,
                         "replay_status": "reconstruction_partial", "findings": [["B004", "warning"]], "n1_message": N1_MESSAGE, "n2_message": N2_MESSAGE,
                         "journal": {"event_decision_linkage": "NOT_ESTABLISHED", "event_decision_ids": None, "proposal_level_association_only": True}},
              "oracle_references": {"freeze": "Hub #273 comment 6665625039", "contract": "Hub #273 comment 6665220369",
                                    "journal_amendment": "Hub #273 comment 6667028276", "original_discrepancy": "freeze §14 event decision_id equality (REJECTED, preserved)"},
              "dependency_lock_sha256": (ctx.get("host_sources") or {}).get(".github/locks/cryptography-pydantic-pytest-513753.txt"),
              "host_source_sha256": ctx.get("host_sources"), "limitations": list(LIMITATIONS), "not_executed": list(NOT_EXECUTED)}
    manifest = {"schema": MANIFEST_SCHEMA, "stable_identity": stable,
                "stable_identity_sha256": sha(json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")),
                "per_run": {"verdict": verdict, "check_count": len(c.rows), "failed_checks": c.failed, "repository": ctx.get("repository"),
                            "workflow": ctx.get("workflow"), "github_run_id": ctx.get("github_run_id"), "github_run_attempt": ctx.get("github_run_attempt"),
                            "github_sha": ctx.get("github_sha"), "github_ref": ctx.get("github_ref"), "orchestrator_head": ctx.get("orchestrator_head"),
                            "runner": ctx.get("runner"), "python_version": ctx.get("python_version"), "dependencies": ctx.get("dependencies"),
                            "p1": p1, "n1": n1, "n2_records_sha256": n2,
                            "evidence_file_sha256": {n: sha((ev / n).read_bytes()) for n in ARTIFACTS if n not in ("oracle.txt", "evidence-manifest.json") and (ev / n).is_file()}},
                "status_vocabulary": ["PASS", "FAIL", "BLOCKED", "NOT EXECUTED"], "qualification": "NOT independent qualification; hosted developer evidence only"}
    (ev / "oracle.txt").write_text("C2 hosted oracle comparison: %s (%d checks, %d failed)\n" % (verdict, len(c.rows), c.failed) + "\n".join(lines) + "\n", encoding="utf-8")
    write_json(ev / "evidence-manifest.json", manifest)
    for line in lines:
        if line.startswith("FAIL"):
            print(line, file=sys.stderr)
    return 0 if verdict == "PASS" else 1


# ------------------------------------------------------------------ summary
def summary():
    try:
        ev = evidence_dir()
        names = {"success": "PASS", "failure": "FAIL", "skipped": "NOT EXECUTED", "cancelled": "BLOCKED"}
        steps = [(label, names.get(os.environ.get(var, ""), "NOT EXECUTED")) for label, var in
                 (("Exact-source verification", "STEP_VERIFY"), ("Focused C2 suite", "STEP_TESTS"), ("P1/N1/N2 cases", "STEP_CASES"), ("Independent oracle comparison", "STEP_ORACLE"))]
        overall = "PASS" if all(s == "PASS" for _, s in steps) else ("FAIL" if any(s == "FAIL" for _, s in steps) else "NOT PASSED")
        clean = lambda v: " ".join(str(v).split()).replace("`", "'").replace("|", "/").replace("<", "&lt;").replace(">", "&gt;")[:200]  # noqa: E731
        out = ["### C2 hosted run (developer evidence, manual only)", "", "**Result: %s** (hosted developer evidence, **not** independent qualification, authenticity, effect proof or complete reconstruction)" % overall, "",
               "| Stage | Status |", "|---|---|"] + ["| %s | %s |" % (a, b) for a, b in steps] + [""]
        try:
            ctx = json.loads((ev / "context.json").read_text(encoding="utf-8"))
            out += ["| Field | Value |", "|---|---|"] + ["| %s | `%s` |" % (k, clean(v)) for k, v in (
                ("Dispatched ref", ctx.get("github_ref")), ("Orchestrator SHA", ctx.get("github_sha")), ("Run", "%s attempt %s" % (ctx.get("github_run_id"), ctx.get("github_run_attempt"))),
                ("Control Plane pin", PINS["control_plane"][1]), ("Replay Bundle pin", PINS["replay_bundle"][1]), ("Dependencies", ctx.get("dependencies")), ("Runner", ctx.get("runner")))] + [""]
        except (OSError, ValueError):
            out += ["No context.json was produced.", ""]
        try:
            first = (ev / "oracle.txt").read_text(encoding="utf-8").splitlines()
            out += ["Oracle: `%s`" % clean(first[0] if first else "empty")] + ["- `%s`" % clean(x) for x in first if x.startswith("FAIL")][:20] + [""]
        except OSError:
            out += ["Oracle: not produced (NOT EXECUTED or failed earlier).", ""]
        out += ["Journal: events are source-preserved and associated through the proposal commitment; direct event-to-decision linkage is NOT_ESTABLISHED at the pinned Control Plane. "
                "P1 is `reconstruction_partial` (B004), never complete. N2 is adverse incompatibility evidence for the original C1 records, not a C1-to-Replay integration. Hub #280 OPEN.", "",
                "Not executed: " + "; ".join(NOT_EXECUTED) + "."]
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
    except BaseException:  # the summary must never fail the job or hide the real step outcomes
        pass
    return 0


def main(argv):
    if len(argv) != 2 or argv[1] not in ("verify", "check", "summary"):
        print("usage: c2_hosted_check.py verify|check|summary", file=sys.stderr)
        return 2
    try:
        return {"verify": verify, "check": check, "summary": summary}[argv[1]]()
    except (Fail, KeyError, OSError, ValueError) as exc:
        print("c2_hosted_check %s failed closed: %s: %s" % (argv[1], type(exc).__name__, str(exc)[:300]), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
