"""Static structure, security and selection-regression tests for the C4 job of manual-contract-edge.yml.

Standard library only. The workflow is read with the self-contained indentation-aware reader that the C3 workflow tests define
(`tests/manual_contract/c3_hosted/test_manual_workflow_c3.py`, loaded by path as a plain module; none of its test classes are
re-exported here). The BASE workflow is the merged-C3 commit, read with read-only `git show`.

Every check is a function over an arbitrary workflow text so that the mutation tests at the bottom can feed mutated copies to the
same checks and require them to report problems. Expectations are restated frozen literals, never read back from the workflow.
"""
import sys

sys.dont_write_bytecode = True

import difflib
import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "manual-contract-edge.yml"
_C3 = ROOT / "tests" / "manual_contract" / "c3_hosted" / "test_manual_workflow_c3.py"
_spec = importlib.util.spec_from_file_location("_c4_wf_reader_c3_workflow_tests", _C3)
R = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = R
_spec.loader.exec_module(R)  # reader / evaluator / job_texts only; nothing from it is collected as a test here

BASE_REV = "aff43bdd4e9540537e6d53f326848f7a37e57b8d"  # merged C3: C1, C2 and C3 jobs must be byte-identical to it
C3_ID = "c3_p1_n1_n3_n5_hosted_group"
C4_ID = "c4_manifest_to_pack_one_action_hosted_group"
C4_JOB = "c4-real-edge"
OLD_JOBS = ("contract-edge", "c1-real-edge", "c2-real-edge", "c3-real-edge")
DEFAULT_CASE = "mock_accept_expected_accept"
LOCK = ".github/locks/cryptography-pydantic-pytest-513753.txt"
EVIDENCE_NAME = "c4-evidence-${{ inputs.case_id }}"
CE_IF = ("${{ !startsWith(inputs.case_id, 'c1_') && !startsWith(inputs.case_id, 'c2_') && inputs.case_id != '%s' "
         "&& inputs.case_id != '%s' }}" % (C3_ID, C4_ID))
CE_EXCL_C4 = "inputs.case_id != '%s'" % C4_ID

# Frozen pins, restated independently of the workflow and of the harness.
PINS = {
    "C4_CP_SHA": "484fdbd297235dd24148ddb0703f2055a31eabff",
    "C4_CP_TREE": "c182939882103015f12c5360fccf377c54e2c4f9",
    "C4_RB_SHA": "93a76e281fcae6a65d2cd1d35376f87442dafb95",
    "C4_RB_TREE": "aca6e6b8bdd33d51db3b34bc0c75eff93b9ff88f",
    "C4_PACK_SHA": "065150852cc2a8abeb748777bb69d72ccd0e03d8",
    "C4_PACK_TREE": "fe428a89da2e74346648cdfe014462ddc8624c77",
    "C4_AM_SHA": "fa170815ef96a54c233d0dd9da821b60debabf8b",
    "C4_AM_TREE": "3b0e3772e944aa668c8f4b879588c7cc3e2c32be",
}
# checkout step order: env var holding the SHA, repository, path, root env var
COMPONENTS = (
    ("C4_CP_SHA", "cogno-us/cognous-control-plane", ".c4-src/control-plane", "COGNOUS_C4_CONTROL_PLANE_ROOT"),
    ("C4_RB_SHA", "cogno-us/cognous-replay-bundle", ".c4-src/replay-bundle", "COGNOUS_C4_REPLAY_BUNDLE_ROOT"),
    ("C4_PACK_SHA", "cogno-us/cognous-governance-evidence-pack", ".c4-src/evidence-pack", "COGNOUS_C4_EVIDENCE_PACK_ROOT"),
    ("C4_AM_SHA", "cogno-us/cognous-action-manifest", ".c4-src/action-manifest", "COGNOUS_C4_ACTION_MANIFEST_ROOT"),
)
ROOT_VARS = [c[3] for c in COMPONENTS]
EXPECTED_ENV_KEYS = set(PINS) | set(ROOT_VARS) | {"C4_EXPECTED_FUNCTIONAL", "C4_EXPECTED_INTEGRITY", "CASE_ID"}
JOB_KEYS = ["if", "runs-on", "timeout-minutes", "permissions", "env", "steps"]
# Fixed focused-suite counts (functional test_real_c4.py, integrity test_real_c4_integrity.py): exact values, no placeholders.
EXPECTED_COUNTS = {"C4_EXPECTED_FUNCTIONAL": "33", "C4_EXPECTED_INTEGRITY": "93"}
HARNESS_LINE = 'python -I -B tests/manual_contract/real_c4.py --case all --workdir "$WORK_ROOT/c4" --out "$EVIDENCE_DIR/c4.result.json"'
VERIFY_LINE = "python -I -B tests/manual_contract/c4/c4_hosted_check.py verify"
FORBIDDEN_RUN = r"\b(curl|wget|git\s+(clone|fetch|pull|remote|push|commit|checkout|add)|npm|apt(-get)?|gh\s+\w+|pip\S*\s+download|docker|ssh|scp|nc|openssl)\b"

git_base = R.git_base
doc_of, job_texts, selected_jobs, options_of = R.doc_of, R.job_texts, R.selected_jobs, R.options_of


def _base():
    return git_base(BASE_REV)


# --------------------------------------------------------------------------------------------------------------------
# Checks (each returns a list of problem strings)
# --------------------------------------------------------------------------------------------------------------------
def check_triggers(text, base):
    P = []
    doc, bdoc = doc_of(text), doc_of(base)
    on = doc.get("on")
    if not isinstance(on, dict) or list(on) != ["workflow_dispatch"]:
        return ["on: must contain only workflow_dispatch, got %r" % (list(on) if isinstance(on, dict) else on)]
    wd = on["workflow_dispatch"]
    if list(wd) != ["inputs"] or list(wd["inputs"]) != ["case_id"]:
        return ["workflow_dispatch must have exactly the single input case_id"]
    ci, bci = wd["inputs"]["case_id"], bdoc["on"]["workflow_dispatch"]["inputs"]["case_id"]
    if ci.get("type") != "choice":
        P.append("case_id type must be choice")
    if ci.get("default") != DEFAULT_CASE or ci.get("default") != bci.get("default"):
        P.append("case_id default changed")
    if ci.get("required") != bci.get("required"):
        P.append("case_id required changed")
    opts, bopts = ci.get("options"), bci.get("options")
    if opts != list(bopts) + [C4_ID]:
        P.append("options must equal base options + [%s] appended last, got %r" % (C4_ID, opts))
    if len(opts or []) != len(bopts) + 1 or len(set(opts or [])) != len(opts or []):
        P.append("option count must be base+1 with no duplicates")
    if doc.get("permissions") != {"contents": "read"}:
        P.append("top-level permissions must be exactly contents: read")
    return P


def check_selection(text, base):
    P = []
    doc, bdoc = doc_of(text), doc_of(base)
    for n, j in doc["jobs"].items():
        if re.search(r"github\.|\bref\b|refs/", str(j.get("if", ""))):
            P.append("job %s: main-branch/context guard must not be a job-level if" % n)
    if P:
        return P  # such an if cannot be evaluated by the selection model
    opts, bopts = options_of(doc), options_of(bdoc)
    for o in opts:
        sel = selected_jobs(doc, o)
        if o == C4_ID:
            exp = [C4_JOB]
        elif o == C3_ID:
            exp = ["c3-real-edge"]
        elif o.startswith("c1_"):
            exp = ["c1-real-edge"]
        elif o.startswith("c2_"):
            exp = ["c2-real-edge"]
        else:
            exp = ["contract-edge"]
        if sel != exp:
            P.append("option %s selects %r, expected %r (exactly one job)" % (o, sel, exp))
    for o in bopts:
        if selected_jobs(doc, o) != selected_jobs(bdoc, o):
            P.append("selection of existing option %s changed vs base" % o)
    for neg in (C4_ID + "_x", C4_ID[:-1], "c4_", "c4_zzz", "c4_other", C4_ID.replace("c4_", "c4-", 1)):
        if selected_jobs(doc, neg) != ["contract-edge"]:
            P.append("unknown c4_ id %r must select contract-edge only (fail closed), got %r" % (neg, selected_jobs(doc, neg)))
    for neg in ("C4_" + C4_ID[3:], " " + C4_ID, C4_ID + " ", C4_ID.upper()):
        if C4_JOB in selected_jobs(doc, neg):
            P.append("near-miss id %r selects the C4 job" % neg)
    for neg in (C3_ID + "_x", "c3_zzz", "zzz_unknown", "c1_zzz", "c2_zzz"):  # earlier behaviour unchanged
        if selected_jobs(doc, neg) != selected_jobs(bdoc, neg):
            P.append("selection of %r differs from base" % neg)
    job = doc["jobs"].get(C4_JOB)
    if job is None:
        return P + ["job %s missing" % C4_JOB]
    iff = job.get("if")
    if iff != "${{ inputs.case_id == '%s' }}" % C4_ID:
        P.append("c4 job-level if must be exactly the equality to the C4 id, got %r" % iff)
    ce = doc["jobs"]["contract-edge"].get("if", "")
    if ce.strip() != CE_IF:
        P.append("contract-edge if must additionally exclude exactly the C4 id (fail-closed), got %r" % ce)
    if "startsWith(inputs.case_id, 'c4_')" in ce:
        P.append("contract-edge if must not exclude the c4_ prefix")
    return P


def check_existing_unchanged(text, base):
    P = []
    jt, bt = job_texts(text), job_texts(base)
    if list(bt) != list(OLD_JOBS):
        P.append("base job list unexpected: %r" % list(bt))
    if list(jt) != list(bt) + [C4_JOB]:
        return P + ["job order must be the base jobs then %s, got %r" % (C4_JOB, list(jt))]
    for n in ("c1-real-edge", "c2-real-edge", "c3-real-edge"):
        if jt[n] != bt[n]:
            P.append("job %s is not byte-identical to base" % n)
    a, b = jt["contract-edge"].split("\n"), bt["contract-edge"].split("\n")
    if len(a) != len(b):
        P.append("contract-edge line count changed")
    else:
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        if len(diff) != 1 or not diff[0][0].startswith("    if:") or not diff[0][1].startswith("    if:"):
            P.append("contract-edge may differ from base only in its if: line")
        elif diff[0][1].rstrip(" }") + " && " + CE_EXCL_C4 + " }}" != diff[0][0]:
            P.append("contract-edge if must be the base if plus the exact C4 exclusion only")
    aa, bb = text.split("\n"), base.split("\n")
    sm = difflib.SequenceMatcher(None, bb, aa, autojunk=False)
    jobs_start = aa.index("jobs:")
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        old, new = bb[i1:i2], aa[j1:j2]
        if not old and j2 <= jobs_start and all(l.startswith("#") or not l.strip() for l in new):
            continue  # header comment additions
        if len(old) == 1 and len(new) == 1 and old[0].lstrip().startswith("description:") and new[0].lstrip().startswith("description:"):
            continue
        if not old and new == ["          - " + C4_ID]:
            continue
        if len(old) == 1 and len(new) == 1 and old[0].startswith("    if:") and new[0].startswith("    if:"):
            continue
        heads = [l for l in new if re.fullmatch(r"  [A-Za-z0-9_-]+:", l)]
        if not old and j1 >= jobs_start and (j2 - j1) > 20 and heads == ["  %s:" % C4_JOB]:
            continue
        P.append("unexpected diff vs base at base lines %d-%d: %r -> %r" % (i1 + 1, i2, old[:2], [l[:80] for l in new[:2]]))
    for key in ("permissions:\n  contents: read\n", "name: Manual contract edge (manual only)\n"):
        if key not in text:
            P.append("missing unchanged block %r" % key)
    return P


def _checkouts(steps):
    return [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")]


def check_security(text, base):
    P = []
    doc = doc_of(text)
    job = doc["jobs"].get(C4_JOB)
    if job is None:
        return ["job %s missing" % C4_JOB]
    jt = job_texts(text)[C4_JOB]
    if list(job) != JOB_KEYS:
        P.append("c4 job keys must be exactly %r in that order, got %r" % (JOB_KEYS, list(job)))
    if job.get("runs-on") != "ubuntu-latest":
        P.append("runs-on must be ubuntu-latest")
    base_uses = set(re.findall(r"uses:\s*(\S+@[0-9a-f]{40})\s+#\s*v[0-9][0-9.]*", base))
    for u in re.findall(r"^\s*(?:-\s+)?uses:\s*(.*)$", text, re.M):
        m = re.fullmatch(r"(\S+@[0-9a-f]{40}) # v\d+\.\d+\.\d+", u.strip())
        if not m:
            P.append("uses not SHA-pinned with version comment: %r" % u)
        elif m.group(1) not in base_uses:
            P.append("action %s is not one already used at base" % m.group(1))
    if "continue-on-error" in text:
        P.append("continue-on-error present")
    if "secrets." in text:
        P.append("secrets. referenced")
    if re.search(r"\b(environment|services|container|needs|strategy|outputs):", jt):
        P.append("c4 job uses a forbidden job-level key")
    if job.get("permissions") != {"contents": "read"}:
        P.append("c4 job permissions must be exactly contents: read, got %r" % job.get("permissions"))
    if job.get("timeout-minutes") != "20":
        P.append("timeout-minutes must be exactly 20, got %r" % job.get("timeout-minutes"))
    env = job.get("env") or {}
    if set(env) != EXPECTED_ENV_KEYS:
        P.append("env keys differ from the expected set: extra %r missing %r" % (sorted(set(env) - EXPECTED_ENV_KEYS), sorted(EXPECTED_ENV_KEYS - set(env))))
    for k, v in PINS.items():
        if env.get(k) != v:
            P.append("env pin %s is %r, expected %s" % (k, env.get(k), v))
    if env.get("CASE_ID") != "${{ inputs.case_id }}":
        P.append("CASE_ID env must be the input")
    for k, v in EXPECTED_COUNTS.items():
        if env.get(k) != v:
            P.append("env %s must be exactly %s, got %r" % (k, v, env.get(k)))
    if re.search(r"c3_|C3_|\.c3-src|COGNOUS_C3", jt):
        P.append("c4 job refers to C3 names (copy-paste residue)")
    steps = job["steps"]
    co = _checkouts(steps)
    if len(co) != 5:
        P.append("expected 5 checkouts, found %d" % len(co))
    for s in co:
        if (s.get("with") or {}).get("persist-credentials") != "false":
            P.append("checkout without persist-credentials: false (%r)" % s.get("name", s.get("uses")))
    if co:
        w = co[0].get("with") or {}
        if set(w) != {"fetch-depth", "persist-credentials"} or w.get("fetch-depth") != "0":
            P.append("first checkout must be the plain orchestrator checkout with fetch-depth: 0")
    paths = []
    for (pin, repo, path, rootvar), s in zip(COMPONENTS, co[1:]):
        w = s.get("with") or {}
        if w.get("repository") != repo:
            P.append("checkout repository %r != %s" % (w.get("repository"), repo))
        if w.get("ref") not in ("${{ env.%s }}" % pin, PINS[pin]):
            P.append("checkout ref %r for %s is not the env pin / literal SHA" % (w.get("ref"), repo))
        want = "2" if repo == "cogno-us/cognous-replay-bundle" else None
        if w.get("fetch-depth") != want:
            P.append("component checkout %s fetch-depth must be %s, got %r" % (repo, want or "unset (depth 1)", w.get("fetch-depth")))
        if w.get("path") != path:
            P.append("checkout path %r != %s" % (w.get("path"), path))
        paths.append(w.get("path"))
        if env.get(rootvar) != "${{ github.workspace }}/" + path:
            P.append("root env %s = %r" % (rootvar, env.get(rootvar)))
    if len(set(paths)) != 4 or not all((p or "").startswith(".c4-src/") for p in paths):
        P.append("component paths must be 4 distinct .c4-src/ paths")
    sp = [s for s in steps if str(s.get("uses", "")).startswith("actions/setup-python@")]
    if len(sp) != 1 or (sp[0].get("with") or {}).get("python-version") != "3.13":
        P.append("expected exactly one setup-python step with python 3.13")
    for s in steps:
        if "run" in s:
            run = s["run"]
            if re.search(r"\$\{\{", run):
                P.append("expression interpolated in run text of step %r" % s.get("name", s.get("id")))
            if not (re.search(r"^\s*set\s+-[A-Za-z]*u[A-Za-z]*(?:\s+-o\s+pipefail|o\s+pipefail)", run, re.M) or re.search(r"^\s*set\s+-euo\s+pipefail", run, re.M)
                    or (s.get("name") == "Job summary" and run.strip().endswith("c4_hosted_check.py summary || true"))):  # the summary step is advisory: its single command ends in `|| true`
                P.append("run block without set -u/-e with pipefail: %r" % s.get("name", s.get("id")))
            for m in re.finditer(r"pip\S*\s+install[^\n]*", run):
                line = m.group(0)
                if "--require-hashes" not in line or "--only-binary=:all:" not in line or not line.rstrip().endswith("-r " + LOCK):
                    P.append("pip install must be hash-locked, binary-only and use exactly the shared lock")
            if re.search(FORBIDDEN_RUN, "\n".join(l for l in run.split("\n") if not l.strip().startswith("#"))):
                P.append("network/VCS/other forbidden command in run block of %r" % s.get("name", s.get("id")))
    ids = [s.get("id") for s in steps]
    if ids[:1] != ["guard"] or "if" in steps[0]:
        P.append("first step must be the unconditional guard step")
    else:
        body = steps[0]["run"]
        if re.search(r"python|\.github/|tests/|\./|source |\bsh\b|bash ", body):
            P.append("guard step touches repository code")
        for need in ("GITHUB_EVENT_NAME", "GITHUB_REF", "CASE_ID", "refs/heads/main", "workflow_dispatch", C4_ID, "exit 1"):
            if need not in body:
                P.append("guard step incomplete: %s" % need)
        if C3_ID in body:
            P.append("guard step names the C3 id")
    install = [n for n, s in enumerate(steps) if "pip" in s.get("run", "") and "install" in s.get("run", "")]
    verify = [n for n, s in enumerate(steps) if "c4_hosted_check.py verify" in s.get("run", "")]
    if len(install) != 1 or len(verify) != 1:
        return P + ["install or verify step missing or duplicated"]
    install, verify = install[0], verify[0]
    if verify != install + 1:
        P.append("verify must be the step immediately after the dependency install")
    for n, s in enumerate(steps[:verify]):
        u = str(s.get("uses", ""))
        if u.startswith(("actions/checkout@", "actions/setup-python@")) or (n == 0 and s.get("id") == "guard"):
            continue
        if n == install:
            lines = [l.strip() for l in s["run"].split("\n") if l.strip() and not l.strip().startswith("#")]
            if not all(l.startswith("set -") or l == "python -m pip install --require-hashes --only-binary=:all: -r " + LOCK for l in lines):
                P.append("install step runs something other than the hash-locked pip install")
            continue
        P.append("step before verify executes something other than checkout/setup-python/install/guard: %r" % s.get("name", s.get("uses")))
    v = steps[verify]
    if "if" in v or "continue-on-error" in v:
        P.append("verify step must be unconditional")
    vlines = [l.strip() for l in v["run"].split("\n") if l.strip() and not l.strip().startswith("#")]
    if vlines.count(VERIFY_LINE) != 1:
        P.append("verify must run exactly: %s" % VERIFY_LINE)
    ups = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    if len(ups) != 1 or steps[-1] is not ups[0]:
        P.append("expected exactly one upload-artifact step, as the last step")
    for s in ups:
        if (s.get("if") or "").strip() != "always()":
            P.append("upload-artifact step must have if: always()")
        w = s.get("with") or {}
        if w.get("if-no-files-found") not in ("warn", "error"):
            P.append("upload-artifact if-no-files-found must be warn or error")
        if w.get("name") != EVIDENCE_NAME:
            P.append("upload artifact name unexpected")
    return P


def check_suites(text, base):
    P = []
    job = doc_of(text)["jobs"].get(C4_JOB)
    if job is None:
        return ["job %s missing" % C4_JOB]
    steps = job["steps"]

    def find(s_):
        return [n for n, s in enumerate(steps) if s_ in s.get("run", "")]

    found = {"tests": find("run_unittest_no_skips.py"), "cases": find("tests/manual_contract/real_c4.py"),
             "check": find("c4_hosted_check.py check"), "summary": find("c4_hosted_check.py summary"), "verify": find("c4_hosted_check.py verify")}
    for nm, lst in found.items():
        if len(lst) != 1:
            P.append("expected exactly one %s step, found %d" % (nm, len(lst)))
    if P:
        return P
    t, c, k, s_, v = (found[x][0] for x in ("tests", "cases", "check", "summary", "verify"))
    if not v < t < c < k < s_ < len(steps) - 1:
        P.append("step order must be verify, tests, cases, check, summary, upload")
    trun = steps[t]["run"]
    invs = re.findall(r"^\s*python -I -B \.github/scripts/run_unittest_no_skips\.py[^\n]*$", trun, re.M)
    if len(invs) != 2:
        P.append("expected exactly two focused suite invocations, found %d" % len(invs))
    pats = []
    for inv in invs:
        if not re.match(r"\s*python -I -B \.github/scripts/run_unittest_no_skips\.py tests/manual_contract/c4 --pattern ", inv):
            P.append("suite does not target tests/manual_contract/c4")
        m = re.search(r"--pattern (\S+)", inv)
        pats.append(m.group(1) if m else None)
    if sorted(pats) != ["test_real_c4.py", "test_real_c4_integrity.py"]:
        P.append("suite patterns wrong: %r" % pats)
    req = re.findall(r"--require-env ([A-Z0-9_]+)", trun)
    if sorted(req) != sorted(ROOT_VARS) and "${REQ[@]}" in trun:
        P.append("REQ array must carry exactly the four COGNOUS_C4 roots, got %r" % sorted(req))
    for r in ROOT_VARS:
        if r not in req:
            P.append("--require-env %s missing" % r)
    if "${REQ[@]}" in trun:
        if trun.count("${REQ[@]}") != 2:
            P.append("REQ array not applied to both suites")
    else:
        for inv in invs:
            if sorted(re.findall(r"--require-env ([A-Z0-9_]+)", inv)) != sorted(ROOT_VARS):
                P.append("suite invocation lacks the four --require-env roots")
    if steps[t].get("if") != "steps.verify.outcome == 'success'":
        P.append("tests step must be gated on verify success only (not always())")
    for nm in ("COGNOUS_C3", "--skip", "-k "):
        if nm in trun:
            P.append("tests step contains %r" % nm)
    hrun = steps[c]["run"]
    hinv = re.findall(r"^\s*python -I -B tests/manual_contract/real_c4\.py[^\n]*$", hrun, re.M)
    if len(hinv) != 1 or hinv[0].strip() != HARNESS_LINE:
        P.append("harness must be invoked exactly once as: %s" % HARNESS_LINE)
    for nm, idx in (("cases", c), ("check", k)):
        if steps[idx].get("if") != "always() && steps.verify.outcome == 'success'":
            P.append("%s step must be 'always() && steps.verify.outcome == success'" % nm)
    if steps[s_].get("if") != "always()":
        P.append("summary step must be if: always()")
    if steps[v].get("if"):
        P.append("verify step must not be conditional")
    return P


def check_counts(text, base):
    P = []
    doc, bdoc = doc_of(text), doc_of(base)
    if len(options_of(doc)) != len(options_of(bdoc)) + 1:
        P.append("option count != base + 1")
    for n, t in job_texts(text).items():
        if n == C4_JOB:
            continue
        for l in t.split("\n"):
            if "c4_" in l or "C4_" in l or ".c4-src" in l or "c4-" in l:
                if not (n == "contract-edge" and l.startswith("    if:") and CE_EXCL_C4 in l):
                    P.append("job %s mentions c4: %r" % (n, l.strip()[:80]))
    if text.count("  %s:\n" % C4_JOB) != 1:
        P.append("c4 job must be defined exactly once")
    if sum(1 for j in doc["jobs"].values() if "inputs.case_id == '%s'" % C4_ID in str(j.get("if", ""))) != 1:
        P.append("exactly one job may be selected by the C4 id in its if")
    return P


CHECKS = (check_triggers, check_selection, check_existing_unchanged, check_security, check_suites, check_counts)


def all_problems(text, base):
    out = []
    for f in CHECKS:
        try:
            out += ["%s: %s" % (f.__name__, p) for p in f(text, base)]
        except (R.YamlError, KeyError, IndexError, TypeError, AttributeError, StopIteration, ValueError) as e:
            out.append("%s: crashed (%s: %s)" % (f.__name__, type(e).__name__, e))
    return out


# --------------------------------------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------------------------------------
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.base = _base()


class TriggerTests(Base):
    def test_triggers_and_inputs(self):
        self.assertEqual(check_triggers(self.text, self.base), [])

    def test_workflow_dispatch_is_the_sole_trigger(self):
        self.assertEqual(list(doc_of(self.text)["on"]), ["workflow_dispatch"])


class SelectionTests(Base):
    def test_selection(self):
        self.assertEqual(check_selection(self.text, self.base), [])

    def test_c4_id_selects_only_the_c4_job(self):
        self.assertEqual(selected_jobs(doc_of(self.text), C4_ID), [C4_JOB])

    def test_every_option_selects_exactly_one(self):
        doc = doc_of(self.text)
        for o in options_of(doc):
            self.assertEqual(len(selected_jobs(doc, o)), 1, o)


class UnchangedTests(Base):
    def test_existing_unchanged(self):
        self.assertEqual(check_existing_unchanged(self.text, self.base), [])

    def test_old_jobs_are_byte_identical_to_the_merged_c3_commit(self):
        jt, bt = job_texts(self.text), job_texts(self.base)
        for n in ("c1-real-edge", "c2-real-edge", "c3-real-edge"):
            self.assertEqual(jt[n], bt[n], n)
            self.assertGreater(len(jt[n]), 500)

    def test_contract_edge_differs_only_in_its_if_line(self):
        a = job_texts(self.text)["contract-edge"].split("\n")
        b = job_texts(self.base)["contract-edge"].split("\n")
        self.assertEqual(len(a), len(b))
        self.assertEqual([i for i, (x, y) in enumerate(zip(a, b)) if x != y], [1])
        self.assertEqual(a[1], "    if: " + CE_IF)


class CheckoutDepthTests(Base):
    def test_checkout_depths(self):
        job = doc_of(self.text)["jobs"][C4_JOB]
        depths = [(s["with"].get("path", "."), s["with"].get("fetch-depth")) for s in _checkouts(job["steps"])]
        self.assertEqual(depths, [(".", "0"), (".c4-src/control-plane", None), (".c4-src/replay-bundle", "2"),
                                  (".c4-src/evidence-pack", None), (".c4-src/action-manifest", None)])


class SecurityTests(Base):
    def test_security(self):
        self.assertEqual(check_security(self.text, self.base), [])

    def test_env_pins_equal_frozen_shas_and_trees(self):
        env = doc_of(self.text)["jobs"][C4_JOB]["env"]
        for k, v in PINS.items():
            self.assertEqual(env[k], v, k)

    def test_guard_is_an_executed_first_step_not_a_job_level_if(self):
        job = doc_of(self.text)["jobs"][C4_JOB]
        self.assertEqual(job["steps"][0]["id"], "guard")
        self.assertNotIn("github", job["if"])
        self.assertNotIn("refs/", job["if"])


class SuiteTests(Base):
    def test_suites_and_order(self):
        self.assertEqual(check_suites(self.text, self.base), [])


class CountTests(Base):
    def test_counts(self):
        self.assertEqual(check_counts(self.text, self.base), [])

    def test_all_checks_clean(self):
        self.assertEqual(all_problems(self.text, self.base), [])


def _in_job(name, fn):
    def mut(text):
        jt = job_texts(text)[name]
        new = fn(jt)
        assert new != jt, "mutation did not change the job"
        return text.replace(jt, new, 1)
    return mut


def _rep(old, new, count=1):
    def f(s):
        assert old in s, "mutation target missing: %r" % old
        return s.replace(old, new, count)
    return f


def _rx(pat, new):
    def f(s):
        out, n = re.subn(pat, new, s, count=1, flags=re.M | re.S)
        assert n == 1, "mutation pattern missing: %r" % pat
        return out
    return f


class MutationTests(Base):
    """Each deliberate mutation of a COPY of the workflow text must be reported by the checks."""

    def assertCaught(self, mutated, needle):
        self.assertNotEqual(mutated, self.text)
        probs = all_problems(mutated, self.base)
        self.assertTrue(probs, "mutation not detected")
        self.assertTrue(any(needle in p for p in probs), "expected %r in %r" % (needle, probs))

    def c4(self, fn, needle):
        self.assertCaught(_in_job(C4_JOB, fn)(self.text), needle)

    def test_clean_baseline(self):
        self.assertEqual(all_problems(self.text, self.base), [])

    def test_add_push_trigger(self):
        self.assertCaught(self.text.replace("on:\n  workflow_dispatch:", "on:\n  push:\n  workflow_dispatch:", 1), "only workflow_dispatch")

    def test_add_pull_request_target(self):
        self.assertCaught(self.text.replace("on:\n  workflow_dispatch:", "on:\n  pull_request_target:\n  workflow_dispatch:", 1), "only workflow_dispatch")

    def test_c4_option_missing(self):
        self.assertCaught(self.text.replace("          - " + C4_ID + "\n", "", 1), "options")

    def test_c4_option_not_last(self):
        o3, o4 = "          - " + C3_ID + "\n", "          - " + C4_ID + "\n"
        self.assertCaught(self.text.replace(o3 + o4, o4 + o3, 1), "options")

    def test_second_new_option(self):
        self.assertCaught(self.text.replace("          - " + C4_ID + "\n", "          - " + C4_ID + "\n          - c4_extra\n", 1), "options")

    def test_default_changed(self):
        self.assertCaught(self.text.replace("default: mock_accept_expected_accept", "default: " + C4_ID, 1), "default")

    def test_top_level_permissions_widened(self):
        self.assertCaught(self.text.replace("permissions:\n  contents: read\n\njobs:", "permissions:\n  contents: write\n\njobs:", 1), "permissions")

    def test_drop_persist_credentials(self):
        self.c4(_rx(r"(path: \.c4-src/replay-bundle\n(?:\s+[a-z-]+: [^\n]*\n)*?)\s+persist-credentials: false\n", r"\1"), "persist-credentials")

    def test_unpin_action(self):
        self.c4(_rep("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2", "actions/upload-artifact@v4"), "SHA-pinned")

    def test_new_action_sha(self):
        self.c4(_rep("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", "actions/upload-artifact@" + "a" * 40), "not one already used")

    def test_widen_job_permissions(self):
        self.c4(_rep("    permissions:\n      contents: read", "    permissions:\n      contents: write"), "permissions")

    def test_job_gains_extra_key(self):
        self.c4(_rep("    runs-on: ubuntu-latest\n", "    runs-on: ubuntu-latest\n    environment: prod\n"), "job keys")

    def test_second_job_selected_by_c4_id(self):
        extra = "\n  c4-extra:\n    if: ${{ inputs.case_id == '%s' }}\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n" % C4_ID
        self.assertCaught(self.text.rstrip("\n") + "\n" + extra, "selects")

    def test_main_guard_as_job_level_if(self):
        self.c4(_rep("if: ${{ inputs.case_id == '%s' }}" % C4_ID, "if: ${{ inputs.case_id == '%s' && github.ref == 'refs/heads/main' }}" % C4_ID), "job-level if")

    def test_weaker_if_prefix(self):
        self.c4(_rep("if: ${{ inputs.case_id == '%s' }}" % C4_ID, "if: ${{ startsWith(inputs.case_id, 'c4_') }}"), "c4 job-level if")

    def test_contract_edge_no_longer_excludes_c4(self):
        self.assertCaught(self.text.replace(" && " + CE_EXCL_C4, "", 1), "selects")

    def test_contract_edge_excludes_c4_prefix_instead(self):
        mutated = self.text.replace(CE_EXCL_C4, "!startsWith(inputs.case_id, 'c4_')", 1)
        self.assertCaught(mutated, "unknown c4_ id")
        self.assertCaught(mutated, "fail-closed")

    def test_contract_edge_exclusion_wrong_id(self):
        self.assertCaught(self.text.replace(CE_EXCL_C4, "inputs.case_id != 'c4_other'", 1), "selects")

    def test_contract_edge_drops_c3_exclusion(self):
        self.assertCaught(self.text.replace(" && inputs.case_id != '%s'" % C3_ID, "", 1), "selects")

    def test_interpolate_input_into_run(self):
        self.c4(_rep("python -I -B tests/manual_contract/c4/c4_hosted_check.py check", 'echo "${{ inputs.case_id }}"; python -I -B tests/manual_contract/c4/c4_hosted_check.py check'), "interpolated")

    def test_interpolate_github_expression_into_run(self):
        self.c4(_rep("python -I -B tests/manual_contract/c4/c4_hosted_check.py summary", "echo ${{ github.event.head_commit.message }}; python -I -B tests/manual_contract/c4/c4_hosted_check.py summary"), "interpolated")

    def test_secrets_reference(self):
        self.c4(_rep("      CASE_ID: ${{ inputs.case_id }}", "      CASE_ID: ${{ inputs.case_id }}\n      TOKEN: ${{ secrets.X }}"), "secrets.")

    def test_timeout_too_long(self):
        self.c4(_rep("timeout-minutes: 20", "timeout-minutes: 60"), "timeout-minutes")

    def test_timeout_shorter_than_frozen(self):
        self.c4(_rep("timeout-minutes: 20", "timeout-minutes: 19"), "timeout-minutes")

    def test_continue_on_error(self):
        self.c4(_rep("        id: verify\n", "        id: verify\n        continue-on-error: true\n"), "continue-on-error")

    def test_verify_if_always(self):
        self.c4(_rep("        id: verify\n", "        id: verify\n        if: always()\n"), "verify")

    def test_pip_without_hashes(self):
        self.c4(_rep("--require-hashes --only-binary=:all: ", ""), "pip install")

    def test_pip_other_lock(self):
        self.c4(_rep("cryptography-pydantic-pytest-513753.txt", "other.txt"), "pip install")

    def test_upload_not_always(self):
        self.c4(_rep("        if: always()\n        uses: actions/upload-artifact", "        uses: actions/upload-artifact"), "upload-artifact")

    def test_upload_ignore(self):
        self.c4(_rep("if-no-files-found: warn", "if-no-files-found: ignore"), "if-no-files-found")

    def test_upload_name_changed(self):
        self.c4(_rep("name: c4-evidence-${{ inputs.case_id }}", "name: evidence"), "upload artifact name")

    def test_pin_drift_sha_and_tree(self):
        self.c4(_rep("C4_AM_TREE: 3b0e3772e944aa668c8f4b879588c7cc3e2c32be", "C4_AM_TREE: " + "0" * 40), "C4_AM_TREE")
        self.c4(_rep("C4_CP_SHA: 484fdbd297235dd24148ddb0703f2055a31eabff", "C4_CP_SHA: " + "1" * 40), "C4_CP_SHA")

    def test_checkout_ref_not_pinned(self):
        self.c4(_rep("ref: ${{ env.C4_PACK_SHA }}", "ref: main"), "ref")

    def test_checkout_wrong_repository(self):
        self.c4(_rep("repository: cogno-us/cognous-action-manifest", "repository: other/cognous-action-manifest"), "repository")

    def test_root_env_wrong(self):
        self.c4(_rep("COGNOUS_C4_REPLAY_BUNDLE_ROOT: ${{ github.workspace }}/.c4-src/replay-bundle", "COGNOUS_C4_REPLAY_BUNDLE_ROOT: ${{ github.workspace }}/.c4-src/elsewhere"), "root env")

    def test_replay_checkout_depth_removed(self):
        self.c4(_rx(r"\n\s+fetch-depth: 2[^\n]*(?=\n\s+persist-credentials: false)", ""), "fetch-depth must be 2")

    def test_other_component_gets_depth(self):
        self.c4(_rep("          path: .c4-src/action-manifest\n", "          path: .c4-src/action-manifest\n          fetch-depth: 2\n"), "fetch-depth must be unset")

    def test_orchestrator_shallow(self):
        self.c4(_rep("          fetch-depth: 0\n", ""), "fetch-depth")

    def test_step_before_verify(self):
        self.c4(_rep("      - name: Verify the exact sources", "      - name: Early\n        run: |\n          set -euo pipefail\n          echo early\n      - name: Verify the exact sources"), "verify")

    def test_verify_after_tests(self):
        def swap(jt):
            v = re.search(r"      - name: Verify the exact sources.*?(?=      - name: Focused C4 suites)", jt, re.S).group(0)
            t = re.search(r"      - name: Focused C4 suites.*?(?=      - name: Run P1)", jt, re.S).group(0)
            return jt.replace(v + t, t + v, 1)
        self.c4(swap, "verify")

    def test_harness_twice(self):
        self.c4(_rep('          CASES_RC=$?\n', '          python -I -B tests/manual_contract/real_c4.py --case all --workdir "$WORK_ROOT/c4b" --out "$EVIDENCE_DIR/b.json"\n          CASES_RC=$?\n'), "harness")

    def test_harness_single_case_only(self):
        self.c4(_rep("--case all", "--case c4_p1_authorized_chain"), "harness")

    def test_drop_require_env(self):
        self.c4(_rep(" --require-env COGNOUS_C4_ACTION_MANIFEST_ROOT", ""), "REQ")

    def test_require_env_wrong_family(self):
        self.c4(_rep("--require-env COGNOUS_C4_EVIDENCE_PACK_ROOT", "--require-env COGNOUS_C3_EVIDENCE_PACK_ROOT"), "REQ")

    def test_suite_directory_wrong(self):
        self.c4(_rep("tests/manual_contract/c4 --pattern test_real_c4_integrity.py", "tests/manual_contract/c3 --pattern test_real_c4_integrity.py"), "tests/manual_contract/c4")

    def test_tests_step_always(self):
        self.c4(_rep("        if: steps.verify.outcome == 'success'\n        env:\n          EVIDENCE_DIR: ${{ runner.temp }}/c4-evidence\n        shell: bash\n        run: |\n          set -u -o pipefail\n          set +e  # an explicit",
                     "        if: always() && steps.verify.outcome == 'success'\n        env:\n          EVIDENCE_DIR: ${{ runner.temp }}/c4-evidence\n        shell: bash\n        run: |\n          set -u -o pipefail\n          set +e  # an explicit"), "tests step")

    def test_cases_not_always(self):
        self.c4(_rep("if: always() && steps.verify.outcome == 'success'", "if: steps.verify.outcome == 'success'"), "step must be")

    def test_summary_not_always(self):
        self.c4(_rep("      - name: Job summary\n        if: always()\n", "      - name: Job summary\n"), "summary")

    def test_summary_before_check(self):
        def swap(jt):
            o = re.search(r"      - name: Frozen-literal comparison.*?(?=      - name: Job summary)", jt, re.S).group(0)
            s = re.search(r"      - name: Job summary.*?(?=      - name: Keep the C4 evidence)", jt, re.S).group(0)
            return jt.replace(o + s, s + o, 1)
        self.c4(swap, "order")

    def test_expected_count_placeholder_restored(self):
        self.c4(_rep("C4_EXPECTED_FUNCTIONAL: '33'", "C4_EXPECTED_FUNCTIONAL: '__FUNCTIONAL__'"), "C4_EXPECTED_FUNCTIONAL")
        self.c4(_rep("C4_EXPECTED_INTEGRITY: '93'", "C4_EXPECTED_INTEGRITY: '__INTEGRITY__'"), "C4_EXPECTED_INTEGRITY")

    def test_expected_count_value_changed(self):
        self.c4(_rep("C4_EXPECTED_FUNCTIONAL: '33'", "C4_EXPECTED_FUNCTIONAL: '32'"), "C4_EXPECTED_FUNCTIONAL")
        self.c4(_rep("C4_EXPECTED_INTEGRITY: '93'", "C4_EXPECTED_INTEGRITY: '94'"), "C4_EXPECTED_INTEGRITY")

    def test_remove_guard_step(self):
        self.c4(_rx(r"      - name: Refuse unless.*?\n(?=      # The orchestrator checkout)", ""), "guard")

    def test_guard_missing_case_check(self):
        self.c4(_rep(' || [ "${CASE_ID}" != "%s" ]' % C4_ID, ""), "guard step incomplete")

    def test_guard_names_c3_id(self):
        self.c4(_rep(' || [ "${CASE_ID}" != "%s" ]' % C4_ID, ' || [ "${CASE_ID}" != "%s" ]' % C3_ID), "C3")

    def test_curl_in_run(self):
        self.c4(_rep("          python -I -B tests/manual_contract/c4/c4_hosted_check.py check", "          curl -sSf https://example.invalid/x\n          python -I -B tests/manual_contract/c4/c4_hosted_check.py check"), "forbidden command")

    def test_git_push_in_run(self):
        self.c4(_rep("          python -I -B tests/manual_contract/c4/c4_hosted_check.py check", "          git push origin HEAD\n          python -I -B tests/manual_contract/c4/c4_hosted_check.py check"), "forbidden command")

    def test_c3_name_in_c4_job(self):
        self.c4(_rep("    runs-on: ubuntu-latest", "    runs-on: ubuntu-latest\n    # c3_x"), "C3 names")

    def test_c4_mention_in_other_job(self):
        _in = _in_job("c2-real-edge", _rep("    runs-on: ubuntu-latest", "    runs-on: ubuntu-latest\n    # c4_x"))
        self.assertCaught(_in(self.text), "c4")

    def test_modify_c1_c2_c3_jobs(self):
        self.assertCaught(_in_job("c1-real-edge", _rep("timeout-minutes: 10", "timeout-minutes: 11"))(self.text), "c1-real-edge")
        self.assertCaught(_in_job("c2-real-edge", _rep("timeout-minutes: 15", "timeout-minutes: 16"))(self.text), "c2-real-edge")
        self.assertCaught(_in_job("c3-real-edge", _rep("timeout-minutes: 20", "timeout-minutes: 21"))(self.text), "c3-real-edge")

    def test_c3_job_comment_added(self):
        self.assertCaught(_in_job("c3-real-edge", _rep("    runs-on: ubuntu-latest", "    runs-on: ubuntu-latest\n    # note"))(self.text), "c3-real-edge")

    def test_modify_contract_edge_beyond_if(self):
        self.assertCaught(_in_job("contract-edge", _rep("timeout-minutes: 5", "timeout-minutes: 6"))(self.text), "contract-edge")

    def test_c4_job_not_last(self):
        jt = job_texts(self.text)
        swapped = self.text.replace(jt["c3-real-edge"], "@@C3@@", 1).replace(jt[C4_JOB], jt["c3-real-edge"], 1).replace("@@C3@@", jt[C4_JOB], 1)
        self.assertCaught(swapped, "job order")


if __name__ == "__main__":
    unittest.main()
