"""Directly affected developer checks for the Q4 cleanup-failure remediation (DEVELOPMENT ONLY). Cleanup helper only; not a G3 scenario,
not a qualification oracle. Pure local; no component is imported."""
import io
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g3_cleanup as C  # noqa: E402


@pytest.fixture
def tmp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


def test_success_removes_only_the_owned_workspace_and_says_so(tmp_root, capsys):
    other = tmp_root / "g3-valid-other-run"
    other.mkdir()
    (other / "refunds.sqlite3").write_text("another invocation's database")
    seen = []
    code = C.run_in_owned_workspace("g3-valid-", lambda work: (seen.append(work), (work / "refunds.sqlite3").write_text("x")))
    assert code == 0 and not seen[0].exists()
    assert (other / "refunds.sqlite3").read_text() == "another invocation's database"  # unrelated directory untouched
    assert f"WORKSPACE-DISPOSED {seen[0]}" in capsys.readouterr().out


def test_failed_removal_is_observable_and_never_reported_as_disposed(tmp_root, monkeypatch, capsys):
    calls = []
    def failing_rmtree(path, *a, **kw):
        calls.append((Path(path), kw))
        raise PermissionError("simulated undeletable file")
    monkeypatch.setattr(C.shutil, "rmtree", failing_rmtree)
    err = io.StringIO()
    seen = []
    code = C.run_in_owned_workspace("g3-valid-", lambda work: seen.append(work), err=err)
    assert code == C.CLEANUP_FAILED_EXIT != 0
    assert seen[0].exists()  # the owned directory is really still there
    assert "CLEANUP-FAILED" in err.getvalue() and str(seen[0]) in err.getvalue()
    assert "WORKSPACE-DISPOSED" not in capsys.readouterr().out
    assert [c[0] for c in calls] == [seen[0]] and all("ignore_errors" not in c[1] for c in calls)  # exactly the owned path; errors not suppressed


def test_silent_noop_removal_does_not_count_as_disposal(tmp_root, monkeypatch, capsys):
    monkeypatch.setattr(C.shutil, "rmtree", lambda *a, **kw: None)  # claims success, deletes nothing
    err = io.StringIO()
    seen = []
    assert C.run_in_owned_workspace("g3-valid-", lambda work: seen.append(work), err=err) == C.CLEANUP_FAILED_EXIT
    assert "still exists" in err.getvalue() and "WORKSPACE-DISPOSED" not in capsys.readouterr().out


def test_original_failure_is_preserved_and_cleanup_failure_is_reported_with_it(tmp_root, monkeypatch, capsys):
    monkeypatch.setattr(C.shutil, "rmtree", lambda *a, **kw: (_ for _ in ()).throw(OSError("simulated")))
    err = io.StringIO()
    def body(work):
        raise RuntimeError("original execution failure")
    with pytest.raises(RuntimeError, match="original execution failure") as info:
        C.run_in_owned_workspace("g3-valid-", body, err=err)
    assert any("cleanup also failed" in n for n in info.value.__notes__)
    assert "CLEANUP-FAILED" in err.getvalue() and "PRIMARY-FAILURE" in err.getvalue()
    assert "WORKSPACE-DISPOSED" not in capsys.readouterr().out


def test_original_failure_without_cleanup_failure_is_unchanged(tmp_root, capsys):
    seen = []
    def body(work):
        seen.append(work)
        raise ValueError("body failed")
    with pytest.raises(ValueError, match="body failed"):
        C.run_in_owned_workspace("g3-valid-", body)
    assert not seen[0].exists()
