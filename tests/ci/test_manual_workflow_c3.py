"""Static structure, security and selection-regression tests for the C3 job of manual-contract-edge.yml.

Standard library only. The workflow is read with a small self-contained indentation-aware reader (see `parse_yaml`), so the
tests do not depend on PyYAML. Limits of the reader: block mappings, block sequences, plain/quoted scalars and `|`/`>` block
scalars only; no anchors, tags, flow collections, multi-line plain scalars or multiple documents; duplicate mapping keys are
an error; scalar values are returned as strings. If PyYAML happens to be importable, one test also cross-checks the reader
against it. The BASE workflow is read with read-only `git show`.

Every check is a function over an arbitrary workflow text so that the mutation tests at the bottom can feed mutated copies
to the same checks and require them to report problems.
"""
import sys

sys.dont_write_bytecode = True

import difflib
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "manual-contract-edge.yml"
BASE_REV = "716f3247a93fe5b9fcda5aa430412de0aeecfef1"
BASE_PATH = ".github/workflows/manual-contract-edge.yml"

C3_ID = "c3_p1_n1_n3_n5_hosted_group"
C3_JOB = "c3-real-edge"
DEFAULT_CASE = "mock_accept_expected_accept"

# Frozen literals, restated independently.
PINS = {
    "C3_CP_SHA": "484fdbd297235dd24148ddb0703f2055a31eabff",
    "C3_CP_TREE": "c182939882103015f12c5360fccf377c54e2c4f9",
    "C3_RB_SHA": "93a76e281fcae6a65d2cd1d35376f87442dafb95",
    "C3_RB_TREE": "aca6e6b8bdd33d51db3b34bc0c75eff93b9ff88f",
    "C3_PACK_SHA": "065150852cc2a8abeb748777bb69d72ccd0e03d8",
    "C3_PACK_TREE": "fe428a89da2e74346648cdfe014462ddc8624c77",
    "C3_AM_SHA": "fa170815ef96a54c233d0dd9da821b60debabf8b",
    "C3_AM_TREE": "3b0e3772e944aa668c8f4b879588c7cc3e2c32be",
}
# (checkout step order) env var holding the SHA, repository, path, root env var
COMPONENTS = (
    ("C3_CP_SHA", "cogno-us/cognous-control-plane", ".c3-src/control-plane", "COGNOUS_C3_CONTROL_PLANE_ROOT"),
    ("C3_RB_SHA", "cogno-us/cognous-replay-bundle", ".c3-src/replay-bundle", "COGNOUS_C3_REPLAY_BUNDLE_ROOT"),
    ("C3_PACK_SHA", "cogno-us/cognous-governance-evidence-pack", ".c3-src/evidence-pack", "COGNOUS_C3_EVIDENCE_PACK_ROOT"),
    ("C3_AM_SHA", "cogno-us/cognous-action-manifest", ".c3-src/action-manifest", "COGNOUS_C3_ACTION_MANIFEST_ROOT"),
)
FORBIDDEN_TRIGGERS = ("push", "pull_request", "pull_request_target", "schedule", "workflow_run", "repository_dispatch", "workflow_call")


# --------------------------------------------------------------------------------------------------------------------
# Minimal YAML reader
# --------------------------------------------------------------------------------------------------------------------
class YamlError(Exception):
    pass


_KEY = re.compile(r"""^(?P<k>"[^"]*"|'[^']*'|[^\s'"#\-][^:]*?|-[^\s][^:]*?):(?:\s+(?P<v>.*))?$""")


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _skip(lines, i):
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    return i


def _scalar(v):
    v = v.strip()
    if v[:1] in "\"'" and len(v) >= 2 and v.endswith(v[0]):
        return v[1:-1]
    return re.sub(r"\s+#.*$", "", v).strip()


def _block_scalar(lines, i, parent_indent):
    body = []
    while i < len(lines) and (not lines[i].strip() or _indent(lines[i]) > parent_indent):
        body.append(lines[i])
        i += 1
    while body and not body[-1].strip():
        body.pop()
    ind = min((_indent(b) for b in body if b.strip()), default=0)
    return "\n".join(b[ind:] if b.strip() else "" for b in body) + "\n", i


def _node(lines, i, indent):
    i = _skip(lines, i)
    if i >= len(lines) or _indent(lines[i]) < indent:
        return None, i
    cur = _indent(lines[i])
    if lines[i].lstrip().startswith("- ") or lines[i].strip() == "-":
        out = []
        while True:
            i = _skip(lines, i)
            if i >= len(lines) or _indent(lines[i]) != cur or not (lines[i].lstrip().startswith("- ") or lines[i].strip() == "-"):
                return out, i
            rest = lines[i].lstrip()[1:]
            if not rest.strip():
                raise YamlError("bare '-' unsupported: %r" % lines[i])
            if _KEY.match(rest.strip()) and not rest.strip().startswith(("'", '"')) or _KEY.match(rest.strip()):
                lines[i] = " " * (cur + 2) + rest.lstrip()
                item, i = _node(lines, i, cur + 2)
                out.append(item)
            else:
                out.append(_scalar(rest))
                i += 1
    out = {}
    while True:
        i = _skip(lines, i)
        if i >= len(lines) or _indent(lines[i]) != cur:
            if i < len(lines) and _indent(lines[i]) > cur:
                raise YamlError("unexpected indentation: %r" % lines[i])
            return out, i
        m = _KEY.match(lines[i].strip())
        if not m:
            raise YamlError("cannot read line: %r" % lines[i])
        key = _scalar(m.group("k"))
        if key in out:
            raise YamlError("duplicate key %r" % key)
        v = m.group("v")
        if v is None or not v.strip() or v.strip().startswith("#"):
            j = _skip(lines, i + 1)
            if j < len(lines) and (_indent(lines[j]) > cur or (_indent(lines[j]) == cur and lines[j].lstrip().startswith("- "))):
                out[key], i = _node(lines, j, cur if _indent(lines[j]) == cur else cur + 1)
            else:
                out[key], i = None, i + 1
        elif v.strip()[0] in "|>" and re.fullmatch(r"[|>][+-]?", v.strip()):
            out[key], i = _block_scalar(lines, i + 1, cur)
        elif v.strip().startswith(("[", "{")):
            raise YamlError("flow collections unsupported: %r" % lines[i])
        else:
            out[key] = _scalar(v)
            i += 1


def parse_yaml(text):
    lines = text.split("\n")
    doc, i = _node(lines, 0, 0)
    if _skip(lines, i) < len(lines):
        raise YamlError("trailing content at line %d" % (i + 1))
    return doc


# --------------------------------------------------------------------------------------------------------------------
# Raw text helpers
# --------------------------------------------------------------------------------------------------------------------
def job_texts(text):
    """Raw text of each job (name -> text), trailing blank lines and trailing comment lines (indent <= 2) removed."""
    lines = text.split("\n")
    start = next((n for n, l in enumerate(lines) if l == "jobs:"), None)
    if start is None:
        raise YamlError("no jobs: section")
    heads = [(n, l.strip()[:-1]) for n, l in enumerate(lines) if n > start and re.fullmatch(r"  [A-Za-z0-9_-]+:\s*", l)]
    out = {}
    for idx, (n, name) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        block = lines[n:end]
        while block and (not block[-1].strip() or (block[-1].lstrip().startswith("#") and _indent(block[-1]) <= 2)):
            block.pop()
        out[name] = "\n".join(block)
    return out


def job_order(text):
    return list(job_texts(text))


def doc_of(text):
    return parse_yaml(text)


def options_of(doc):
    return doc["on"]["workflow_dispatch"]["inputs"]["case_id"]["options"]


def job_if(job):
    v = job.get("if")
    return v


# --------------------------------------------------------------------------------------------------------------------
# if: evaluator for the exact forms used
# --------------------------------------------------------------------------------------------------------------------
_TOK = re.compile(r"\s*(&&|\|\||==|!=|!|\(|\)|,|startsWith|inputs\.case_id|'[^']*'|true|false)")


def eval_if(expr, case_id):
    """Evaluate a job `if:` for inputs.case_id == case_id. None (no if) is True. Unsupported syntax raises."""
    if expr is None:
        return True
    e = expr.strip()
    m = re.fullmatch(r"\$\{\{(.*)\}\}", e, re.S)
    if m:
        e = m.group(1)
    toks, pos = [], 0
    e = e.rstrip()
    while pos < len(e):
        m = _TOK.match(e, pos)
        if not m:
            raise YamlError("unsupported if expression near %r in %r" % (e[pos:], expr))
        toks.append(m.group(1))
        pos = m.end()
    p = [0]

    def peek():
        return toks[p[0]] if p[0] < len(toks) else None

    def eat(t=None):
        if p[0] >= len(toks) or (t is not None and toks[p[0]] != t):
            raise YamlError("unexpected token in %r" % expr)
        p[0] += 1
        return toks[p[0] - 1]

    def lit():
        t = eat()
        if not t.startswith("'"):
            raise YamlError("string literal expected in %r" % expr)
        return t[1:-1]

    def primary():
        t = peek()
        if t == "(":
            eat("(")
            v = orx()
            eat(")")
            return v
        if t == "startsWith":
            eat()
            eat("(")
            eat("inputs.case_id")
            eat(",")
            s = lit()
            eat(")")
            return case_id.startswith(s)
        if t == "inputs.case_id":
            eat()
            op = eat()
            if op not in ("==", "!="):
                raise YamlError("bad operator in %r" % expr)
            s = lit()
            return (case_id == s) if op == "==" else (case_id != s)
        if t in ("true", "false"):
            eat()
            return t == "true"
        raise YamlError("unsupported primary %r in %r" % (t, expr))

    def unary():
        if peek() == "!":
            eat()
            return not unary()
        return primary()

    def andx():
        v = unary()
        while peek() == "&&":
            eat()
            r = unary()
            v = v and r
        return v

    def orx():
        v = andx()
        while peek() == "||":
            eat()
            r = andx()
            v = v or r
        return v

    v = orx()
    if p[0] != len(toks):
        raise YamlError("trailing tokens in %r" % expr)
    return v


def selected_jobs(doc, case_id):
    return sorted(n for n, j in doc["jobs"].items() if eval_if(job_if(j), case_id))


# --------------------------------------------------------------------------------------------------------------------
# Checks (each returns a list of problem strings)
# --------------------------------------------------------------------------------------------------------------------
CE_EXCL = "inputs.case_id != '%s'" % C3_ID


def git_base():
    r = subprocess.run(["git", "-C", str(ROOT), "show", "%s:%s" % (BASE_REV, BASE_PATH)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("cannot read base workflow: " + r.stderr)
    return r.stdout


def check_triggers(text, base):
    P = []
    doc, bdoc = doc_of(text), doc_of(base)
    on = doc.get("on")
    if not isinstance(on, dict) or list(on) != ["workflow_dispatch"]:
        P.append("on: must contain only workflow_dispatch, got %r" % (list(on) if isinstance(on, dict) else on))
        return P
    wd = on["workflow_dispatch"]
    if list(wd) != ["inputs"] or list(wd["inputs"]) != ["case_id"]:
        P.append("workflow_dispatch must have exactly the single input case_id")
        return P
    ci, bci = wd["inputs"]["case_id"], bdoc["on"]["workflow_dispatch"]["inputs"]["case_id"]
    if ci.get("type") != "choice":
        P.append("case_id type must be choice")
    if ci.get("default") != DEFAULT_CASE or ci.get("default") != bci.get("default"):
        P.append("case_id default changed")
    if ci.get("required") != bci.get("required"):
        P.append("case_id required changed")
    opts, bopts = ci.get("options"), bci.get("options")
    if opts != list(bopts) + [C3_ID]:
        P.append("options must equal base options + [%s] appended last, got %r" % (C3_ID, opts))
    if len(opts or []) != len(bopts) + 1:
        P.append("option count must be base+1")
    return P


def check_selection(text, base):
    P = []
    doc, bdoc = doc_of(text), doc_of(base)
    for n, j in doc["jobs"].items():
        if re.search(r"github\.|\bref\b|refs/", str(j.get("if", ""))):
            return ["job %s: main-branch/context guard must not be a job-level if" % n]
    opts = options_of(doc)
    bopts = options_of(bdoc)
    for o in opts:
        try:
            sel = selected_jobs(doc, o)
        except YamlError as e:
            return P + ["if evaluation failed: %s" % e]
        if len(sel) != 1:
            P.append("option %s selects %r (need exactly one job)" % (o, sel))
            continue
        if o == C3_ID:
            exp = [C3_JOB]
        elif o.startswith("c1_"):
            exp = ["c1-real-edge"]
        elif o.startswith("c2_"):
            exp = ["c2-real-edge"]
        elif o.startswith("mock_"):
            exp = ["contract-edge"]
        else:
            exp = ["?"]
        if sel != exp:
            P.append("option %s selects %r, expected %r" % (o, sel, exp))
    for o in bopts:  # existing cases select exactly what they selected at base
        if selected_jobs(doc, o) != selected_jobs(bdoc, o):
            P.append("selection of existing option %s changed vs base" % o)
    # negatives: other c3_ ids and near misses select nothing; an unknown non-prefixed id reaches only the mock job (as at base)
    for neg in (C3_ID + "_x", C3_ID[:-1], "c3_", "c3_zzz", "c3_other"):  # fail closed: the mock runner refuses and fails the job
        sel = selected_jobs(doc, neg)
        if sel != ["contract-edge"]:
            P.append("unknown c3_ id %r must select contract-edge only (never zero jobs), got %r" % (neg, sel))
    for neg in ("C3_" + C3_ID[3:], " " + C3_ID, C3_ID + " "):  # not c3_-prefixed: never select the C3 job
        if C3_JOB in selected_jobs(doc, neg) or len(selected_jobs(doc, neg)) > 1:
            P.append("near-miss id %r selects %r" % (neg, selected_jobs(doc, neg)))
    if selected_jobs(doc, "zzz_unknown") != selected_jobs(bdoc, "zzz_unknown"):
        P.append("unknown non-prefixed id selection differs from base")
    job = doc["jobs"].get(C3_JOB)
    if job is None:
        return P + ["job %s missing" % C3_JOB]
    iff = job_if(job)
    if iff is None or not re.fullmatch(r"\$\{\{\s*inputs\.case_id == '%s'\s*\}\}" % C3_ID, iff.strip()):
        P.append("c3 job-level if must be exactly the equality to the C3 id, got %r" % iff)
    for n, j in doc["jobs"].items():
        if re.search(r"github\.|\bref\b|refs/", str(j.get("if", ""))):
            P.append("job %s: main-branch/context guard must not be a job-level if" % n)
    return P


def check_existing_unchanged(text, base):
    P = []
    jt, bt = job_texts(text), job_texts(base)
    if list(jt) != list(bt) + [C3_JOB]:
        P.append("job order must be base jobs then %s, got %r" % (C3_JOB, list(jt)))
        return P
    for n in ("c1-real-edge", "c2-real-edge"):
        if jt[n] != bt[n]:
            P.append("job %s is not byte-identical to base" % n)
    a, b = jt["contract-edge"].split("\n"), bt["contract-edge"].split("\n")
    if len(a) != len(b):
        P.append("contract-edge line count changed")
    else:
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        if len(diff) != 1 or not diff[0][0].startswith("    if:") or not diff[0][1].startswith("    if:"):
            P.append("contract-edge may differ from base only in its if: line")
    # everything outside the job bodies: only allowed diffs
    strip = lambda t: [l for l in t.split("\n")]
    c3_lines = set()
    aa, bb = strip(text), strip(base)
    sm = difflib.SequenceMatcher(None, bb, aa, autojunk=False)
    jobs_start = aa.index("jobs:")
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        old, new = bb[i1:i2], aa[j1:j2]
        if all(l.startswith("#") or not l.strip() for l in new) and not old and j2 <= jobs_start:
            continue  # header comment additions
        if len(old) == 1 and len(new) == 1 and old[0].lstrip().startswith("description:") and new[0].lstrip().startswith("description:"):
            continue
        if not old and new == ["          - " + C3_ID]:
            continue
        if len(old) == 1 and len(new) == 1 and old[0].startswith("    if:") and new[0].startswith("    if:"):
            continue
        # the appended c3 job (and its leading blank/comment lines)
        if not old and j1 >= jobs_start and (j2 - j1) > 20 and any(l == "  %s:" % C3_JOB for l in new):
            continue
        P.append("unexpected diff vs base at base lines %d-%d: %r -> %r" % (i1 + 1, i2, old[:2], [l[:80] for l in new[:2]]))
    for key in ("permissions:\n  contents: read\n", "name: Manual contract edge (manual only)\n"):
        if key not in text:
            P.append("missing unchanged block %r" % key)
    if doc_of(text).get("permissions") != {"contents": "read"}:
        P.append("top-level permissions must be exactly contents: read")
    return P


def _step_has(step, key):
    return key in step


def _runs(job):
    return [(s, s["run"]) for s in job["steps"] if "run" in s]


def check_security(text, base):
    P = []
    doc = doc_of(text)
    job = doc["jobs"].get(C3_JOB)
    if job is None:
        return ["job %s missing" % C3_JOB]
    jt = job_texts(text)[C3_JOB]
    base_uses = set(re.findall(r"uses:\s*(\S+@[0-9a-f]{40})\s+#\s*v[0-9][0-9.]*", base))
    all_uses = re.findall(r"^\s*(?:-\s+)?uses:\s*(.*)$", text, re.M)
    for u in all_uses:
        m = re.fullmatch(r"(\S+@[0-9a-f]{40}) # v\d+\.\d+\.\d+", u.strip())
        if not m:
            P.append("uses not SHA-pinned with version comment: %r" % u)
        elif m.group(1) not in base_uses:
            P.append("action %s is not one already used at base" % m.group(1))
    if "continue-on-error" in text:
        P.append("continue-on-error present")
    if "secrets." in jt or "secrets." in text:
        P.append("secrets. referenced")
    if job.get("permissions") != {"contents": "read"}:
        P.append("c3 job permissions must be exactly contents: read, got %r" % job.get("permissions"))
    to = job.get("timeout-minutes")
    if not (to and to.isdigit() and 0 < int(to) <= 20):
        P.append("timeout-minutes must be present and <= 20, got %r" % to)
    env = job.get("env") or {}
    for k, v in PINS.items():
        if env.get(k) != v:
            P.append("env pin %s is %r, expected %s" % (k, env.get(k), v))
    steps = job["steps"]
    co = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")]
    if len(co) != 5:
        P.append("expected 5 checkouts, found %d" % len(co))
    for s in co:
        if (s.get("with") or {}).get("persist-credentials") != "false":
            P.append("checkout without persist-credentials: false (%r)" % s.get("name", s.get("uses")))
    if co:
        w = co[0].get("with") or {}
        if "repository" in w or "ref" in w or "path" in w or w.get("fetch-depth") != "0":
            P.append("first checkout must be the plain orchestrator checkout with fetch-depth: 0")
        if steps.index(co[0]) > 1 or any("uses" not in s for s in steps[:steps.index(co[0])]):
            pass
        order = [s for s in steps if s in co]
        if order[0] is not co[0]:
            P.append("orchestrator checkout is not first among checkouts")
    paths = []
    for (pin, repo, path, rootvar), s in zip(COMPONENTS, co[1:]):
        w = s.get("with") or {}
        ref = w.get("ref")
        if w.get("repository") != repo:
            P.append("checkout repository %r != %s" % (w.get("repository"), repo))
        if ref not in ("${{ env.%s }}" % pin, PINS[pin]):
            P.append("checkout ref %r for %s is not the env pin / literal SHA" % (ref, repo))
        depth = w.get("fetch-depth")
        want = "2" if repo == "cogno-us/cognous-replay-bundle" else None
        if depth != want:
            P.append("component checkout %s fetch-depth must be %s, got %r" % (repo, want or "unset (depth 1)", depth))
        if w.get("path") != path:
            P.append("checkout path %r != %s" % (w.get("path"), path))
        paths.append(w.get("path"))
        if env.get(rootvar) != "${{ github.workspace }}/" + path:
            P.append("root env %s = %r" % (rootvar, env.get(rootvar)))
    if len(set(paths)) != 4 or not all((p or "").startswith(".c3-src/") for p in paths):
        P.append("component paths must be 4 distinct .c3-src/ paths")
    # run blocks
    for s, run in _runs(job):
        if re.search(r"\$\{\{", run):
            P.append("expression interpolated in run text of step %r" % s.get("name", s.get("id")))
        has_set = re.search(r"^\s*set\s+-[A-Za-z]*u?[A-Za-z]*(?:\s+-o\s+pipefail|o\s+pipefail)|^\s*set\s+-euo\s+pipefail", run, re.M)
        explicit = re.search(r"\|\| true|\$\?|PIPESTATUS|_RC=", run)
        if not (has_set or explicit):
            P.append("run block without set -euo pipefail or explicit rc handling: %r" % s.get("name", s.get("id")))
        for m in re.finditer(r"pip\S*\s+install[^\n]*", run):
            if "--require-hashes" not in m.group(0) or "--only-binary=:all:" not in m.group(0):
                P.append("pip install without --require-hashes --only-binary=:all:")
        if re.search(r"\b(curl|wget|git\s+(clone|fetch|pull|remote)|npm|apt(-get)?|gh\s+api|pip\S*\s+download)\b", run):
            P.append("network fetch command in run block of %r" % s.get("name", s.get("id")))
    # guard / verify ordering
    ids = [s.get("id") for s in steps]
    install = next((n for n, s in enumerate(steps) if "pip" in s.get("run", "") and "install" in s.get("run", "")), None)
    verify = next((n for n, s in enumerate(steps) if "c3_hosted_check.py verify" in s.get("run", "")), None)
    if install is None or verify is None:
        P.append("install or verify step missing")
    else:
        if verify != install + 1:
            P.append("verify must be the step immediately after the dependency install")
        for n, s in enumerate(steps[:verify]):
            u = str(s.get("uses", ""))
            if u.startswith(("actions/checkout@", "actions/setup-python@")):
                continue
            if n == install:
                lines = [l.strip() for l in s["run"].split("\n") if l.strip() and not l.strip().startswith("#")]
                if not all(l.startswith("set -") or re.fullmatch(r"python -m pip install --require-hashes --only-binary=:all: -r \.github/locks/[A-Za-z0-9._-]+\.txt", l) for l in lines):
                    P.append("install step runs something other than the hash-locked pip install")
                continue
            if s.get("id") == "guard" and n == 0:
                body = s["run"]
                if re.search(r"python|\.github/|tests/|\./|source |\bsh\b|bash ", body.replace("shell: bash", "")):
                    P.append("guard step touches repository code")
                if not all(x in body for x in ("GITHUB_EVENT_NAME", "GITHUB_REF", "CASE_ID", "refs/heads/main", "workflow_dispatch", C3_ID, "exit 1")):
                    P.append("guard step incomplete")
                continue
            P.append("step before verify executes something other than checkout/setup-python/install/guard: %r" % s.get("name", s.get("uses")))
        v = steps[verify]
        if "if" in v or "continue-on-error" in v:
            P.append("verify step must be unconditional")
    if ids[:1] != ["guard"]:
        P.append("first step must be the guard step")
    # upload
    ups = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    if len(ups) != 1:
        P.append("expected exactly one upload-artifact step")
    for s in ups:
        if (s.get("if") or "").strip() != "always()":
            P.append("upload-artifact step must have if: always()")
        if (s.get("with") or {}).get("if-no-files-found") not in ("warn", "error"):
            P.append("upload-artifact if-no-files-found must be warn or error")
        if not (s.get("with") or {}).get("name", "").startswith("c3-evidence"):
            P.append("upload artifact name unexpected")
    return P


def check_suites(text, base):
    P = []
    job = doc_of(text)["jobs"].get(C3_JOB)
    if job is None:
        return ["job %s missing" % C3_JOB]
    steps = job["steps"]

    def find(s_):
        return [n for n, s in enumerate(steps) if s_ in s.get("run", "")]

    tests, cases, check, summ, verify = find("run_unittest_no_skips.py"), find("tests/manual_contract/real_c3.py"), find("c3_hosted_check.py check"), find("c3_hosted_check.py summary"), find("c3_hosted_check.py verify")
    for nm, lst in (("tests", tests), ("cases", cases), ("check", check), ("summary", summ), ("verify", verify)):
        if len(lst) != 1:
            P.append("expected exactly one %s step, found %d" % (nm, len(lst)))
    if P:
        return P
    t, c, k, s_, v = tests[0], cases[0], check[0], summ[0], verify[0]
    if not v < t < c < k < s_ < len(steps) - 1:
        P.append("step order must be verify, tests, cases, check, summary, upload")
    trun = steps[t]["run"]
    roots = [r[3] for r in COMPONENTS]
    invs = re.findall(r"^\s*python -I -B \.github/scripts/run_unittest_no_skips\.py[^\n]*$", trun, re.M)
    if len(invs) != 2:
        P.append("expected exactly two focused suite invocations, found %d" % len(invs))
    pats = []
    for inv in invs:
        if "tests/manual_contract/c3" not in inv:
            P.append("suite does not target tests/manual_contract/c3")
        m = re.search(r"--pattern (\S+)", inv)
        pats.append(m.group(1) if m else None)
    if sorted(pats) != ["test_real_c3.py", "test_real_c3_integrity.py"]:
        P.append("suite patterns wrong: %r" % pats)
    req = re.findall(r"--require-env ([A-Z0-9_]+)", trun)
    for r in roots:
        # each root once in the shared REQ array or once per invocation
        if r not in req:
            P.append("--require-env %s missing" % r)
    if "${REQ[@]}" in trun:
        if trun.count("${REQ[@]}") != 2 or sorted(req) != sorted(roots):
            P.append("REQ array not applied to both suites with exactly the four roots")
    else:
        for inv in invs:
            if sorted(re.findall(r"--require-env ([A-Z0-9_]+)", inv)) != sorted(roots):
                P.append("suite invocation lacks the four --require-env roots")
    if "verify" in steps[t].get("if", "") is False:
        pass
    if "steps.verify.outcome == 'success'" not in steps[t].get("if", ""):
        P.append("tests step must be gated on verify success")
    if "always()" in steps[t].get("if", ""):
        P.append("tests step must not be always()")
    hinv = re.findall(r"^\s*python -I -B tests/manual_contract/real_c3\.py[^\n]*$", steps[c]["run"], re.M)
    if len(hinv) != 1 or "--case all" not in hinv[0]:
        P.append("harness must be invoked exactly once with --case all")
    if "--case" in hinv[0] and len(re.findall(r"--case\b", hinv[0])) != 1:
        P.append("harness --case given more than once")
    for nm, idx in (("cases", c), ("check", k)):
        cond = steps[idx].get("if", "")
        if "always()" not in cond or "steps.verify.outcome == 'success'" not in cond:
            P.append("%s step must be 'always() && steps.verify.outcome == success'" % nm)
    if "always()" not in steps[s_].get("if", ""):
        P.append("summary step must be if: always()")
    if "steps" in steps[v].get("if", "") or steps[v].get("if"):
        P.append("verify step must not be conditional")
    # no other job runs the C3 harness or mentions the C3 id
    return P


def check_counts(text, base):
    P = []
    doc, bdoc = doc_of(text), doc_of(base)
    if len(options_of(doc)) != len(options_of(bdoc)) + 1:
        P.append("option count != base + 1")
    jt = job_texts(text)
    for n, t in jt.items():
        if n == C3_JOB:
            continue
        for l in t.split("\n"):
            if "c3_" in l or "C3_" in l or ".c3-src" in l:
                if not (n == "contract-edge" and l.startswith("    if:") and CE_EXCL in l):
                    P.append("job %s mentions c3: %r" % (n, l.strip()[:80]))
    ce = doc["jobs"]["contract-edge"].get("if", "")
    expected_ce = "${{ !startsWith(inputs.case_id, 'c1_') && !startsWith(inputs.case_id, 'c2_') && inputs.case_id != '%s' }}" % C3_ID
    if ce.strip() != expected_ce:
        P.append("contract-edge if must exclude exactly the C3 id (fail-closed), got %r" % ce)
    if "startsWith(inputs.case_id, 'c3_')" in ce:
        P.append("contract-edge if must not exclude the c3_ prefix (unknown c3_ ids must reach the refusing mock runner)")
    if text.count("  %s:\n" % C3_JOB) != 1:
        P.append("c3 job must be defined exactly once")
    if sum(1 for n, j in doc["jobs"].items() if "inputs.case_id == '%s'" % C3_ID in str(j.get("if", ""))) != 1:
        P.append("exactly one job may be selected by the C3 id in its if")
    return P


CHECKS = (check_triggers, check_selection, check_existing_unchanged, check_security, check_suites, check_counts)


def all_problems(text, base):
    out = []
    for f in CHECKS:
        try:
            out += ["%s: %s" % (f.__name__, p) for p in f(text, base)]
        except (YamlError, KeyError, IndexError, TypeError, AttributeError, StopIteration) as e:
            out.append("%s: crashed (%s: %s)" % (f.__name__, type(e).__name__, e))
    return out


# --------------------------------------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------------------------------------
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.base = git_base()


class ReaderTests(unittest.TestCase):
    def test_reader_basics(self):
        d = parse_yaml("a:\n  b: 'x y'\n  c: |\n    l1\n      l2\n\n    l3\n  d:\n    - k: v # c\n      m: 1\n    - plain\n")
        self.assertEqual(d, {"a": {"b": "x y", "c": "l1\n  l2\n\nl3\n", "d": [{"k": "v", "m": "1"}, "plain"]}})

    def test_reader_rejects_duplicate_keys(self):
        with self.assertRaises(YamlError):
            parse_yaml("a: 1\na: 2\n")

    def test_evaluator(self):
        e = "${{ !startsWith(inputs.case_id, 'c1_') && (inputs.case_id == 'x' || startsWith(inputs.case_id, 'y')) }}"
        self.assertEqual([eval_if(e, i) for i in ("x", "y1", "c1_x", "z")], [True, True, False, False])
        self.assertTrue(eval_if(None, "q"))
        with self.assertRaises(YamlError):
            eval_if("${{ always() }}", "q")

    def test_reader_agrees_with_pyyaml_when_present(self):
        try:
            import yaml
        except ImportError:
            yaml = None
        text = WORKFLOW.read_text(encoding="utf-8")
        mine = parse_yaml(text)

        def norm(x):
            if isinstance(x, dict):
                return {("on" if k is True else str(k)): norm(v) for k, v in x.items()}
            if isinstance(x, list):
                return [norm(v) for v in x]
            if x is None:
                return None
            if isinstance(x, bool):
                return "true" if x else "false"
            return str(x)

        self.assertIn(C3_JOB, mine["jobs"])
        if yaml is not None:
            self.assertEqual(mine, norm(yaml.safe_load(text)))


class TriggerTests(Base):
    def test_triggers_and_inputs(self):
        self.assertEqual(check_triggers(self.text, self.base), [])


class SelectionTests(Base):
    def test_selection(self):
        self.assertEqual(check_selection(self.text, self.base), [])

    def test_every_option_selects_exactly_one(self):
        doc = doc_of(self.text)
        for o in options_of(doc):
            self.assertEqual(len(selected_jobs(doc, o)), 1, o)
        self.assertEqual(selected_jobs(doc, C3_ID), [C3_JOB])


class UnchangedTests(Base):
    def test_existing_unchanged(self):
        self.assertEqual(check_existing_unchanged(self.text, self.base), [])


class CheckoutDepthTests(Base):
    def test_checkout_depths(self):
        job = doc_of(self.text)["jobs"][C3_JOB]
        co = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")]
        depths = [(s["with"].get("path", "."), s["with"].get("fetch-depth")) for s in co]
        self.assertEqual(depths, [(".", "0"), (".c3-src/control-plane", None), (".c3-src/replay-bundle", "2"),
                                  (".c3-src/evidence-pack", None), (".c3-src/action-manifest", None)])


class SecurityTests(Base):
    def test_security(self):
        self.assertEqual(check_security(self.text, self.base), [])


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

    def test_clean_baseline(self):
        self.assertEqual(all_problems(self.text, self.base), [])

    def test_add_push_trigger(self):
        self.assertCaught(self.text.replace("on:\n  workflow_dispatch:", "on:\n  push:\n  workflow_dispatch:", 1), "only workflow_dispatch")

    def test_add_pull_request_target(self):
        self.assertCaught(self.text.replace("on:\n  workflow_dispatch:", "on:\n  pull_request_target:\n  workflow_dispatch:", 1), "only workflow_dispatch")

    def test_drop_persist_credentials(self):
        m = _in_job(C3_JOB, _rx(r"(path: \.c3-src/replay-bundle\n(?:\s+[a-z-]+: [^\n]*\n)*?)\s+persist-credentials: false\n", r"\1"))
        self.assertCaught(m(self.text), "persist-credentials")

    def test_unpin_action(self):
        m = _in_job(C3_JOB, _rep("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2", "actions/upload-artifact@v4"))
        self.assertCaught(m(self.text), "SHA-pinned")

    def test_new_action_sha(self):
        m = _in_job(C3_JOB, _rep("actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02", "actions/upload-artifact@" + "a" * 40))
        self.assertCaught(m(self.text), "not one already used")

    def test_widen_permissions(self):
        m = _in_job(C3_JOB, _rep("    permissions:\n      contents: read", "    permissions:\n      contents: write"))
        self.assertCaught(m(self.text), "permissions")

    def test_second_job_selected_by_c3_id(self):
        extra = "\n  c3-extra:\n    if: ${{ inputs.case_id == '%s' }}\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n" % C3_ID
        self.assertCaught(self.text.rstrip("\n") + "\n" + extra, "selects")

    def test_main_guard_as_job_level_if(self):
        m = _in_job(C3_JOB, _rep("if: ${{ inputs.case_id == '%s' }}" % C3_ID, "if: ${{ inputs.case_id == '%s' && github.ref == 'refs/heads/main' }}" % C3_ID))
        self.assertCaught(m(self.text), "job-level if")

    def test_weaker_if_prefix(self):
        m = _in_job(C3_JOB, _rep("if: ${{ inputs.case_id == '%s' }}" % C3_ID, "if: ${{ startsWith(inputs.case_id, 'c3_') }}"))
        self.assertCaught(m(self.text), "c3 job-level if")

    def test_contract_edge_no_longer_excludes_c3(self):
        self.assertCaught(self.text.replace(" && " + CE_EXCL, "", 1), "selects")

    def test_contract_edge_reverted_to_c3_prefix_exclusion(self):
        # weakens fail-closed: an unknown c3_ id would select zero jobs (an all-skipped green run)
        mutated = self.text.replace(CE_EXCL, "!startsWith(inputs.case_id, 'c3_')", 1)
        self.assertCaught(mutated, "unknown c3_ id")
        self.assertCaught(mutated, "fail-closed")

    def test_contract_edge_exclusion_wrong_id(self):
        self.assertCaught(self.text.replace(CE_EXCL, "inputs.case_id != 'c3_other'", 1), "selects")

    def test_interpolate_input_into_run(self):
        m = _in_job(C3_JOB, _rep("python -I -B .github/scripts/c3_hosted_check.py check", 'echo "${{ inputs.case_id }}"; python -I -B .github/scripts/c3_hosted_check.py check'))
        self.assertCaught(m(self.text), "interpolated")

    def test_secrets_reference(self):
        m = _in_job(C3_JOB, _rep("      CASE_ID: ${{ inputs.case_id }}", "      CASE_ID: ${{ inputs.case_id }}\n      TOKEN: ${{ secrets.X }}"))
        self.assertCaught(m(self.text), "secrets.")

    def test_timeout_too_long(self):
        m = _in_job(C3_JOB, _rep("timeout-minutes: 20", "timeout-minutes: 60"))
        self.assertCaught(m(self.text), "timeout-minutes")

    def test_continue_on_error(self):
        m = _in_job(C3_JOB, _rep("        id: verify\n", "        id: verify\n        continue-on-error: true\n"))
        self.assertCaught(m(self.text), "continue-on-error")

    def test_verify_if_always(self):
        m = _in_job(C3_JOB, _rep("        id: verify\n", "        id: verify\n        if: always()\n"))
        self.assertCaught(m(self.text), "verify")

    def test_pip_without_hashes(self):
        m = _in_job(C3_JOB, _rep("--require-hashes --only-binary=:all: ", ""))
        self.assertCaught(m(self.text), "pip install")

    def test_upload_not_always(self):
        m = _in_job(C3_JOB, _rep("        if: always()\n        uses: actions/upload-artifact", "        uses: actions/upload-artifact"))
        self.assertCaught(m(self.text), "upload-artifact")

    def test_upload_ignore(self):
        m = _in_job(C3_JOB, _rep("if-no-files-found: warn", "if-no-files-found: ignore"))
        self.assertCaught(m(self.text), "if-no-files-found")

    def test_pin_drift(self):
        m = _in_job(C3_JOB, _rep("C3_AM_TREE: 3b0e3772e944aa668c8f4b879588c7cc3e2c32be", "C3_AM_TREE: " + "0" * 40))
        self.assertCaught(m(self.text), "C3_AM_TREE")

    def test_checkout_ref_not_pinned(self):
        m = _in_job(C3_JOB, _rep("ref: ${{ env.C3_PACK_SHA }}", "ref: main"))
        self.assertCaught(m(self.text), "ref")

    def test_replay_checkout_depth_removed(self):
        m = _in_job(C3_JOB, _rx(r"\n\s+fetch-depth: 2[^\n]*(?=\n\s+persist-credentials: false)", ""))
        self.assertCaught(m(self.text), "fetch-depth must be 2")

    def test_other_component_gets_depth(self):
        m = _in_job(C3_JOB, _rep("          path: .c3-src/action-manifest\n", "          path: .c3-src/action-manifest\n          fetch-depth: 2\n"))
        self.assertCaught(m(self.text), "fetch-depth must be unset")

    def test_orchestrator_shallow(self):
        m = _in_job(C3_JOB, _rep("          fetch-depth: 0\n", ""))
        self.assertCaught(m(self.text), "fetch-depth")

    def test_step_before_verify(self):
        m = _in_job(C3_JOB, _rep("      - name: Verify the exact sources", "      - name: Early\n        run: |\n          set -euo pipefail\n          python .github/scripts/c3_hosted_check.py check\n      - name: Verify the exact sources"))
        self.assertCaught(m(self.text), "verify")

    def test_harness_twice(self):
        m = _in_job(C3_JOB, _rep('          CASES_RC=$?\n', '          python -I -B tests/manual_contract/real_c3.py --case all --workdir "$WORK_ROOT/c3b" --out "$EVIDENCE_DIR/b.json"\n          CASES_RC=$?\n'))
        self.assertCaught(m(self.text), "harness")

    def test_drop_require_env(self):
        m = _in_job(C3_JOB, _rep(" --require-env COGNOUS_C3_ACTION_MANIFEST_ROOT", ""))
        self.assertCaught(m(self.text), "REQ")

    def test_cases_not_always(self):
        m = _in_job(C3_JOB, _rep("if: always() && steps.verify.outcome == 'success'", "if: steps.verify.outcome == 'success'"))
        self.assertCaught(m(self.text), "step must be")

    def test_modify_c1_job(self):
        m = _in_job("c1-real-edge", _rep("timeout-minutes: 10", "timeout-minutes: 11"))
        self.assertCaught(m(self.text), "c1-real-edge")

    def test_modify_c2_job(self):
        m = _in_job("c2-real-edge", _rep("timeout-minutes: 15", "timeout-minutes: 16"))
        self.assertCaught(m(self.text), "c2-real-edge")

    def test_modify_contract_edge_beyond_if(self):
        m = _in_job("contract-edge", _rep("timeout-minutes: 5", "timeout-minutes: 6"))
        self.assertCaught(m(self.text), "contract-edge")

    def test_option_removed_or_reordered(self):
        self.assertCaught(self.text.replace("          - mock_refuse_expected_refuse\n", "", 1), "options")

    def test_default_changed(self):
        self.assertCaught(self.text.replace("default: mock_accept_expected_accept", "default: " + C3_ID, 1), "default")

    def test_top_level_permissions_widened(self):
        self.assertCaught(self.text.replace("permissions:\n  contents: read\n\njobs:", "permissions:\n  contents: write\n\njobs:", 1), "permissions")

    def test_remove_guard_step(self):
        m = _in_job(C3_JOB, _rx(r"      - name: Refuse unless.*?\n(?=      # The orchestrator checkout)", ""))
        self.assertCaught(m(self.text), "guard")

    def test_curl_in_run(self):
        m = _in_job(C3_JOB, _rep("          python -I -B .github/scripts/c3_hosted_check.py check", "          curl -sSf https://example.invalid/x\n          python -I -B .github/scripts/c3_hosted_check.py check"))
        self.assertCaught(m(self.text), "network fetch")

    def test_c3_mention_in_other_job(self):
        m = _in_job("c2-real-edge", _rep("    runs-on: ubuntu-latest", "    runs-on: ubuntu-latest\n    # c3_x"))
        self.assertCaught(m(self.text), "c3")


if __name__ == "__main__":
    unittest.main()
