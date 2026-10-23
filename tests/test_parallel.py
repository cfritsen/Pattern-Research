import numpy as np
import pandas as pd
import pytest
from patternlab.parallel import resolved_worker_count, _init_worker, m4_task, m5_task


def test_resolved_workers_off():
    assert resolved_worker_count({"multithreading": False}) == 1


def test_resolved_workers_on(monkeypatch):
    monkeypatch.setattr("patternlab.parallel.cpu_count", lambda: 8)
    assert resolved_worker_count({"multithreading": True}) == 6


def test_resolved_workers_floor_on_low_core_count(monkeypatch):
    monkeypatch.setattr("patternlab.parallel.cpu_count", lambda: 2)
    assert resolved_worker_count({"multithreading": True}) == 1