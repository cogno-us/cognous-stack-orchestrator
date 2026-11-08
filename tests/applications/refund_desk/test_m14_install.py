"""Refund Desk (F3) M1-4 developer-installation checks (Amendment M4). DEVELOPMENT ONLY / SYNTHETIC / test-owner developer checks, NOT independent qualification.

Stack-free tests (always run): usage, refusal, `env`, `evidence` and, above all, CLEANUP SAFETY against hand-built owned workspaces in temporary directories.
Network tests (CHECK 1-3, fresh install, demo, repeatability): run only with M14_FRESH_INSTALL=1 (a skip is not a pass); they clone the pinned
repositories and install the repository's hash-locked dependencies into a temporary workspace and then remove it.

Run: python -m unittest discover -s tests/applications/refund_desk -p 'test_m14_install.py' -v
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEV_DIR = REPO / "development" / "refund-desk-local"
DEV = DEV_DIR / "dev.sh"
DEVTOOL = DEV_DIR / "devtool.py"
MARKER = ".cognous-refund-desk-dev-owner"
SOURCES = json.loads((REPO / "applications/refund_desk/SOURCES.json").read_text())["native_components_used"]
PINS = json.loads((REPO / "orchestration/adapters/refund_disposition/source_pins.json").read_text())["components"]
COMPONENTS = ("control_plane", "runtime", "replay", "institutional_governance")
FRESH = os.environ.get("M14_FRESH_INSTALL") == "1"


def dev(*args, workspace=None, env=None, cwd=None, timeout=900):
    cmd = ["bash", str(DEV)]
    if workspace is not None:
        cmd += ["--workspace", str(workspace)]
    cmd += list(args)
    e = dict(os.environ)
    e.pop("COGNOUS_RD_DEV_WORKSPACE", None)
    e.update(env or {})
    return subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=cwd, timeout=timeout)


def make_owned(ws: Path, *, with_children=True, marker_workspace=None):
    ws.mkdir(parents=True, exist_ok=True)
    (ws / MARKER).write_text(json.dumps({"owner": "cognous-refund-desk-local", "schema": 1, "workspace": str(marker_workspace or ws.resolve())}))
    if with_children:
        for d in ("state", "venv", "stack"):
            (ws / d).mkdir(exist_ok=True)
            (ws / d / "f.txt").write_text("x")
        (ws / "install-record.json").write_text("{}")


class Files(unittest.TestCase):
    def test_exact_installation_files_exist(self):
        for n in ("dev.sh", "devtool.py", "README.md"):
            self.assertTrue((DEV_DIR / n).is_file(), n)
        self.assertEqual(sorted(p.name for p in DEV_DIR.iterdir() if p.name != "__pycache__"), ["README.md", "dev.sh", "devtool.py"])

    def test_pins_come_from_sources_json_and_agree_with_f1_pins(self):
        out = subprocess.run([sys.executable, "-I", str(DEVTOOL), "pins", "--repo", str(REPO)], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        got = {l.split()[0]: l.split() for l in out.stdout.splitlines() if l.strip()}
        self.assertEqual(set(got), set(COMPONENTS))
        for c in COMPONENTS:
            self.assertEqual(got[c][2], SOURCES[c]["commit"])
            self.assertEqual(SOURCES[c]["commit"], PINS[c])
            self.assertEqual(got[c][1], SOURCES[c]["repository"].split("/")[-1])
        text = DEV.read_text() + DEVTOOL.read_text()
        for c in COMPONENTS:
            self.assertNotIn(PINS[c], text, "no hard-coded SHA in the installation files")


class Usage(unittest.TestCase):
    def test_help_and_usage_errors(self):
        r = dev("--help")
        self.assertEqual(r.returncode, 0, r.stderr)
        for w in ("setup", "env", "demo", "evidence", "cleanup"):
            self.assertIn(w, r.stdout)
        for args in ([], ["frobnicate"], ["cleanup"], ["evidence"], ["setup", "extra"], ["cleanup", "--all", "--state-only"]):
            with tempfile.TemporaryDirectory(prefix="m14-u-") as td:
                self.assertEqual(dev(*args, workspace=Path(td) / "w").returncode, 2, args)

    def test_env_before_setup_is_refused_and_creates_nothing(self):
        with tempfile.TemporaryDirectory(prefix="m14-e-") as td:
            ws = Path(td) / "w"
            r = dev("env", workspace=ws)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertFalse(ws.exists())

    def test_setup_refuses_a_nonempty_unowned_directory_untouched(self):
        with tempfile.TemporaryDirectory(prefix="m14-s-") as td:
            ws = Path(td) / "mydata"
            ws.mkdir()
            (ws / "precious.txt").write_text("keep")
            r = dev("setup", workspace=ws)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertEqual(sorted(p.name for p in ws.iterdir()), ["precious.txt"])
            self.assertEqual((ws / "precious.txt").read_text(), "keep")


class CleanupSafety(unittest.TestCase):
    def test_plan_only_without_yes_removes_nothing_and_shows_exact_targets(self):
        with tempfile.TemporaryDirectory(prefix="m14-c-") as td:
            ws = Path(td) / "w"
            make_owned(ws)
            r = dev("cleanup", "--all", workspace=ws)
            self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
            for n in ("state", "venv", "stack", "install-record.json", MARKER):
                self.assertIn(str(ws.resolve() / n), r.stdout + r.stderr)
                self.assertTrue((ws / n).exists())

    def test_state_only_removes_only_state(self):
        with tempfile.TemporaryDirectory(prefix="m14-c-") as td:
            ws = Path(td) / "w"
            make_owned(ws)
            r = dev("cleanup", "--state-only", "--yes", workspace=ws)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertFalse((ws / "state").exists())
            for n in ("venv", "stack", "install-record.json", MARKER):
                self.assertTrue((ws / n).exists(), n)

    def test_all_removes_only_owned_children_and_keeps_unknown_files_and_outside_data(self):
        with tempfile.TemporaryDirectory(prefix="m14-c-") as td:
            outside = Path(td) / "outside.txt"
            outside.write_text("caller data")
            ws = Path(td) / "w"
            make_owned(ws)
            (ws / "notes.txt").write_text("not owned")
            r = dev("cleanup", "--all", "--yes", workspace=ws)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(sorted(p.name for p in ws.iterdir()), ["notes.txt"], "unknown file preserved, workspace kept")
            self.assertIn("notes.txt", r.stdout + r.stderr, "unknown files are reported")
            self.assertEqual(outside.read_text(), "caller data")

    def test_all_removes_an_empty_workspace_directory(self):
        with tempfile.TemporaryDirectory(prefix="m14-c-") as td:
            ws = Path(td) / "w"
            make_owned(ws)
            self.assertEqual(dev("cleanup", "--all", "--yes", workspace=ws).returncode, 0)
            self.assertFalse(ws.exists())

    def _refused(self, ws_arg, *, env=None, cwd=None, prepare=None):
        r = dev("cleanup", "--all", "--yes", workspace=ws_arg, env=env, cwd=cwd)
        self.assertEqual(r.returncode, 1, (ws_arg, r.stdout, r.stderr))
        return r

    def test_unsafe_targets_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="m14-x-") as td:
            td = Path(td)
            home = td / "home"
            home.mkdir()
            (home / "doc.txt").write_text("mine")
            make_owned(home)  # even a validly marked HOME is refused
            self._refused(home, env={"HOME": str(home)})
            self.assertTrue((home / "doc.txt").exists() and (home / "state").exists())
            self._refused("/")
            self._refused(str(REPO))
            self._refused(str(REPO.parent))
            self._refused(str(REPO / "development"))
            self._refused("relative/path")
            nomarker = td / "nomarker"
            (nomarker / "state").mkdir(parents=True)
            self._refused(nomarker)
            self.assertTrue((nomarker / "state").exists())
            other = td / "other"
            make_owned(other, marker_workspace=td / "somewhere-else")
            self._refused(other)
            self.assertTrue((other / "state").exists(), "marker for another path")
            real = td / "real"
            make_owned(real)
            link = td / "link"
            link.symlink_to(real)
            self._refused(link)
            self.assertTrue((real / "state").exists())
            self._refused(str(td / "real" / ".." / "real"))
            self.assertTrue((real / "state").exists())

    def test_symlinked_owned_child_is_refused_and_target_untouched(self):
        with tempfile.TemporaryDirectory(prefix="m14-y-") as td:
            td = Path(td)
            victim = td / "victim"
            victim.mkdir()
            (victim / "keep.txt").write_text("keep")
            ws = td / "w"
            make_owned(ws, with_children=False)
            (ws / "state").symlink_to(victim)
            r = dev("cleanup", "--state-only", "--yes", workspace=ws)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertEqual((victim / "keep.txt").read_text(), "keep")

    def test_malformed_marker_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="m14-z-") as td:
            ws = Path(td) / "w"
            make_owned(ws)
            (ws / MARKER).write_text("not json")
            self.assertEqual(dev("cleanup", "--all", "--yes", workspace=ws).returncode, 1)
            self.assertTrue((ws / "state").exists())


class EvidenceIndex(unittest.TestCase):
    def test_lists_artifacts_with_digests_and_reads_sqlite_read_only(self):
        with tempfile.TemporaryDirectory(prefix="m14-i-") as td:
            ws = Path(td) / "w"
            make_owned(ws, with_children=False)
            st = ws / "state" / "demo" / "routine"
            (st / "cp").mkdir(parents=True)
            (st / "evidence" / "CASE-1").mkdir(parents=True)
            (st / "sqlite").mkdir()
            (st / "cp" / "CASE-1.json").write_text("{}")
            (st / "cp" / "CASE-1.json.lock").write_text("")
            for n in ("cp_run_record-aa.json", "runtime_export-bb.json", "replay_bundle-cc.json"):
                (st / "evidence" / "CASE-1" / n).write_text('{"k":1}')
            (st / "routine.result.json").write_text(json.dumps({"outcome": "executed", "control_plane": {"result": "authorized"},
                                                                 "evidence": {"replay_state": "imported", "replay_note": None}}))
            con = sqlite3.connect(st / "sqlite" / "refunds.sqlite3")
            con.execute("create table effects (effect_id text, state text, amount real, unit text)")
            con.execute("insert into effects values ('e1','applied',64.25,'USD')")
            con.commit()
            con.close()
            before = {p: p.read_bytes() for p in st.rglob("*") if p.is_file()}
            r = dev("evidence", "--state", str(st), workspace=ws)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            for w in ("cp_run_record-aa.json", "runtime_export-bb.json", "replay_bundle-cc.json", "CASE-1.json", "sha256:", "e1", "applied",
                      "producer-reported", "import_failed", "authorized", "held", "uncertain", "routine.result.json"):
                self.assertIn(w, r.stdout, w)
            self.assertEqual({p: p.read_bytes() for p in st.rglob("*") if p.is_file()}, before, "evidence listing modifies nothing")
            out = dev("evidence", "--state", str(Path(td) / "elsewhere"), workspace=ws)
            self.assertEqual(out.returncode, 1)
            out = dev("evidence", "--state", str(ws / "state" / ".." / ".."), workspace=ws)
            self.assertEqual(out.returncode, 1)


@unittest.skipUnless(FRESH, "network fresh-install checks run only with M14_FRESH_INSTALL=1 (a skip is not a pass)")
class FreshInstall(unittest.TestCase):
    """CHECK 1, 2 and 3 on the real pinned stack in a temporary workspace (clones the four pinned repositories)."""

    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.mkdtemp(prefix="m14-fresh-")
        cls.ws = Path(cls.td) / "ws"

    @classmethod
    def tearDownClass(cls):
        r = dev("cleanup", "--all", "--yes", workspace=cls.ws)
        shutil.rmtree(cls.td, ignore_errors=True) if r.returncode == 0 or not cls.ws.exists() else None

    def heads(self):
        out = {}
        for c in COMPONENTS:
            d = self.ws / "stack" / c
            out[c] = (subprocess.check_output(["git", "-C", str(d), "rev-parse", "HEAD"], text=True).strip(),
                      subprocess.check_output(["git", "-C", str(d), "rev-parse", "HEAD^{tree}"], text=True).strip())
        return out

    def test_workflow_in_order(self):
        # CHECK 1: fresh install
        r = dev("setup", workspace=self.ws)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        h1 = self.heads()
        for c in COMPONENTS:
            self.assertEqual(h1[c][0], PINS[c])
        rec = json.loads((self.ws / "install-record.json").read_text())
        self.assertIn("tool_versions", rec)
        # CHECK 3a: repeat setup leaves pinned sources unchanged
        r = dev("setup", workspace=self.ws)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.heads(), h1)
        self.assertIn("already at pin", r.stdout + r.stderr)
        # env
        env = dev("env", workspace=self.ws)
        self.assertEqual(env.returncode, 0, env.stderr)
        self.assertIn("REFUND_DESK_STACK_ROOT", env.stdout)
        # CHECK 2: product workflow
        d = dev("demo", "--name", "t1", workspace=self.ws)
        self.assertEqual(d.returncode, 0, d.stdout + d.stderr)
        for s in ("routine", "high", "hold", "mismatch", "uncertain"):
            self.assertRegex(d.stdout, rf"PASS\s+{s}")
        self.assertNotIn("FAIL", d.stdout)
        st = self.ws / "state" / "t1"
        res = json.loads((st / "routine" / "routine.result.json").read_text())
        self.assertEqual(res["outcome"], "executed")
        con = sqlite3.connect(f"file:{st / 'routine' / 'sqlite' / 'refunds.sqlite3'}?mode=ro", uri=True)
        rows = con.execute("select effect_id,state from effects").fetchall()
        con.close()
        self.assertEqual(rows, [(res["effect"]["effect_id"], "applied")])
        # demo refuses to overwrite existing evidence
        again = dev("demo", "--name", "t1", workspace=self.ws)
        self.assertEqual(again.returncode, 1, again.stdout + again.stderr)
        self.assertEqual(json.loads((st / "routine" / "routine.result.json").read_text()), res)
        ev = dev("evidence", "--state", str(st / "routine"), workspace=self.ws)
        self.assertEqual(ev.returncode, 0, ev.stderr)
        self.assertIn(res["effect"]["effect_id"], ev.stdout)
        # CHECK 3b: repeated authorized action -> still one row, same effect id
        e = dict(os.environ)
        e.update({"REFUND_DESK_STACK_ROOT": str(self.ws / "stack"), "PYTHONPATH": f"{REPO}:{REPO}/applications/refund_desk"})
        argv = [str(self.ws / "venv/bin/python"), "-m", "refund_desk", "process", "--case-id", res["case_id"], "--tenant", "harborview-retail",
                "--customer-account", "customer-001", "--amount", "64.25", "--reason", "damaged_item", "--authority", "valid", "--state-dir", str(st / "routine")]
        p = subprocess.run(argv, capture_output=True, text=True, env=e)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        r2 = json.loads(p.stdout)
        self.assertEqual(r2["effect"]["effect_id"], res["effect"]["effect_id"])
        con = sqlite3.connect(f"file:{st / 'routine' / 'sqlite' / 'refunds.sqlite3'}?mode=ro", uri=True)
        self.assertEqual(con.execute("select count(*) from effects").fetchone()[0], 1)
        con.close()
        # CHECK 3c: a mismatched component is refused and left unmodified
        cp = self.ws / "stack" / "control_plane"
        subprocess.check_call(["git", "-C", str(cp), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "--allow-empty", "-q", "-m", "drift"])
        drifted = subprocess.check_output(["git", "-C", str(cp), "rev-parse", "HEAD"], text=True).strip()
        r = dev("setup", workspace=self.ws)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(subprocess.check_output(["git", "-C", str(cp), "rev-parse", "HEAD"], text=True).strip(), drifted, "never reset")
        subprocess.check_call(["git", "-C", str(cp), "reset", "-q", "--hard", PINS["control_plane"]])  # test restores its own owned copy
        # cleanup: state only, evidence preserved until elected
        self.assertEqual(dev("setup", workspace=self.ws).returncode, 0)
        self.assertTrue(st.exists())
        self.assertEqual(dev("cleanup", "--state-only", "--yes", workspace=self.ws).returncode, 0)
        self.assertFalse((self.ws / "state").exists())
        self.assertTrue((self.ws / "stack").exists())
        # CHECK 3d: all, then setup reproduces the same pins
        self.assertEqual(dev("cleanup", "--all", "--yes", workspace=self.ws).returncode, 0)
        self.assertFalse(self.ws.exists())
        self.assertEqual(dev("setup", workspace=self.ws).returncode, 0)
        self.assertEqual(self.heads(), h1)


if __name__ == "__main__":
    unittest.main()
