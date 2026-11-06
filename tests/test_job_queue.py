import threading
import pytest
import yaml
from pathlib import Path

from patternlab import jobs
from patternlab.config import read_raw_config


def _cfg(index="sp500"):
    cfg = read_raw_config(str(Path(__file__).resolve().parent.parent / "config.yaml"))
    cfg["index"] = index
    return cfg


class InlineThread:
    """Runs the target when started, on the calling thread, so the test is deterministic."""
    def __init__(self, target=None, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("patternlab.config.read_raw_config", lambda *a, **k: _cfg("sp500"))
    jobs._queue.clear()
    jobs._results.clear()
    jobs._worker_active = False
    jobs._state.update(status="idle", job_name=None, job_index=None, error=None)
    yield
    jobs._queue.clear()
    jobs._worker_active = False


class Proc:
    def __init__(self, code):
        self.returncode = code


def test_queued_runs_go_one_at_a_time_each_on_its_own_index(monkeypatch):
    running = []
    order = []
    peak = [0]

    def fake_run(cmd, cwd, stdout, stderr, env):
        index = yaml.safe_load(Path(env["PATTERNLAB_CONFIG"]).read_text())["index"]
        running.append(index)
        peak[0] = max(peak[0], len(running))
        if not order or order[-1] != index:
            order.append(index)
        running.pop()
        return Proc(0)

    monkeypatch.setattr(jobs.subprocess, "run", fake_run)
    monkeypatch.setattr(jobs.threading, "Thread", InlineThread)
    ok, msg = jobs.start_job("full_rediscovery", ["sp500", "sp400", "sp600"])
    assert ok and msg == "started"
    assert order == ["sp500", "sp400", "sp600"] and peak[0] == 1
    st = jobs.get_status()
    assert [(r["index"], r["status"]) for r in st["results"]] == [("sp500", "done"), ("sp400", "done"), ("sp600", "done")]
    assert st["queue"] == [] and not jobs.is_running()


def test_a_failed_run_does_not_stop_the_rest(monkeypatch):
    def fake_run(cmd, cwd, stdout, stderr, env):
        index = yaml.safe_load(Path(env["PATTERNLAB_CONFIG"]).read_text())["index"]
        return Proc(1 if index == "sp400" else 0)

    monkeypatch.setattr(jobs.subprocess, "run", fake_run)
    monkeypatch.setattr(jobs.threading, "Thread", InlineThread)
    jobs.start_job("update_data", ["sp500", "sp400", "sp600"])
    res = {r["index"]: r["status"] for r in jobs.get_status()["results"]}
    assert res == {"sp500": "done", "sp400": "error", "sp600": "done"}


def test_queue_skips_duplicates_and_allows_removal(monkeypatch):
    class NoThread(InlineThread):
        def start(self):
            pass                                   # worker never runs: the queue just fills

    monkeypatch.setattr(jobs.threading, "Thread", NoThread)
    assert jobs.start_job("full_rediscovery", ["sp500", "sp400"]) == (True, "started")
    assert jobs.start_job("full_rediscovery", ["sp400", "sp600"]) == (True, "queued")      # sp400 already waiting
    assert [q["index"] for q in jobs.get_status()["queue"]] == ["sp500", "sp400", "sp600"]
    assert jobs.start_job("full_rediscovery", ["sp600"])[0] is False
    assert jobs.remove_queued(1) is True
    assert [q["index"] for q in jobs.get_status()["queue"]] == ["sp500", "sp600"]
    assert jobs.remove_queued(9) is False
    assert jobs.start_job("full_rediscovery", ["nasdaq"])[0] is False


def test_default_index_is_the_selected_one(monkeypatch):
    class NoThread(InlineThread):
        def start(self):
            pass

    monkeypatch.setattr(jobs.threading, "Thread", NoThread)
    jobs.start_job("update_data")
    assert [q["index"] for q in jobs.get_status()["queue"]] == ["sp500"]


def test_clear_empties_the_finished_list(monkeypatch):
    monkeypatch.setattr(jobs.subprocess, "run", lambda *a, **k: Proc(0))
    monkeypatch.setattr(jobs.threading, "Thread", InlineThread)
    jobs.start_job("update_data", ["sp500", "sp400"])
    assert len(jobs.get_status()["results"]) == 2
    jobs.clear_results()
    st = jobs.get_status()
    assert st["results"] == [] and st["active"] is False
