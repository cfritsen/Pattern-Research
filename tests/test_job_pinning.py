import yaml
from pathlib import Path

from patternlab import jobs
from patternlab.config import load_config, read_raw_config


def _cfg(index):
    cfg = read_raw_config(str(Path(__file__).resolve().parent.parent / "config.yaml"))
    cfg["index"] = index
    return cfg


def test_load_config_reads_the_jobs_frozen_copy(tmp_path, monkeypatch):
    frozen = tmp_path / "job.yaml"
    frozen.write_text(yaml.safe_dump(_cfg("sp600")), encoding="utf-8")
    monkeypatch.setenv("PATTERNLAB_CONFIG", str(frozen))
    assert load_config()["index"] == "sp600"
    monkeypatch.delenv("PATTERNLAB_CONFIG")
    real = str(Path(__file__).resolve().parent.parent / "config.yaml")
    assert load_config(real)["index"] == read_raw_config(real)["index"]       # env unset: config.yaml as usual


def test_job_stays_on_its_index_when_config_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "PROJECT_ROOT", tmp_path)
    seen = []

    class Done:
        returncode = 0

    def fake_run(cmd, cwd, stdout, stderr, env):
        # the stage reads the job's frozen copy, whatever config.yaml says by now
        seen.append(yaml.safe_load(Path(env["PATTERNLAB_CONFIG"]).read_text())["index"])
        return Done()

    monkeypatch.setattr(jobs.subprocess, "run", fake_run)
    cfg = _cfg("sp400")
    path = jobs._freeze_config(cfg)
    # the user switches the GUI to the S&P 500 while the job runs
    monkeypatch.setattr("patternlab.config.read_raw_config", lambda *a, **k: _cfg("sp500"))
    jobs._run_chain("full_rediscovery", jobs.JOBS["full_rediscovery"], cfg, path)

    assert seen == ["sp400"] * 6
    assert (tmp_path / "data" / "discovery_log_sp400.json").exists()
    assert (tmp_path / "data" / "price_update_log_sp400.json").exists()
    assert not (tmp_path / "data" / "discovery_log_sp500.json").exists()
    assert jobs.get_status()["job_index"] == "sp400"
