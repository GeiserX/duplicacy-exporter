"""Tests for durable metric state persistence (issue duplicacy-ha#12)."""

import json
import os
import sys
from pathlib import Path

import pytest
from prometheus_client import CollectorRegistry, Counter, Gauge

sys.path.insert(0, str(Path(__file__).parent.parent))

from duplicacy_exporter import (  # noqa: E402
    MetricsPersistence,
    PERSISTED_METRICS,
    backup_running,
    backup_speed_bps,
    backup_progress,
    backup_chunks_uploaded,
    backup_chunks_skipped,
    prune_running,
)


def _fresh():
    """A small, isolated registry mirroring the real metric shapes."""
    reg = CollectorRegistry()
    labelled_gauge = Gauge("dx_g", "d", ["a", "b"], registry=reg)
    plain_gauge = Gauge("dx_gn", "d", registry=reg)
    labelled_counter = Counter("dx_c_total", "d", ["a"], registry=reg)
    plain_counter = Counter("dx_cn_total", "d", registry=reg)
    # Keys are the registry-emitted names: prometheus_client strips the trailing
    # ``_total`` from a Counter, so a Counter("dx_c_total") collects as "dx_c".
    metrics = {
        "dx_g": labelled_gauge,
        "dx_gn": plain_gauge,
        "dx_c": labelled_counter,
        "dx_cn": plain_counter,
    }
    return reg, metrics


# ---------------------------------------------------------------------------
# snapshot()
# ---------------------------------------------------------------------------

def test_snapshot_excludes_created_samples(tmp_path):
    reg, metrics = _fresh()
    metrics["dx_c"].labels("x").inc(5)
    p = MetricsPersistence(str(tmp_path / "s.json"), reg, metrics)
    names = {(r["name"], r["value"]) for r in p.snapshot()}
    # The counter's value sample is present; the _created timestamp sample is not.
    assert ("dx_c", 5.0) in names
    assert not any(r["name"].endswith("_created") for r in p.snapshot())


def test_snapshot_only_includes_allowlisted_metrics(tmp_path):
    reg, metrics = _fresh()
    # A metric in the registry but NOT in the allowlist must never be persisted.
    Gauge("dx_unlisted", "d", registry=reg)
    metrics["dx_gn"].set(1)
    p = MetricsPersistence(str(tmp_path / "s.json"), reg, metrics)
    assert all(r["name"] != "dx_unlisted" for r in p.snapshot())


# ---------------------------------------------------------------------------
# save() / restore() round trip
# ---------------------------------------------------------------------------

def test_roundtrip_gauge_and_counter(tmp_path):
    reg, metrics = _fresh()
    metrics["dx_g"].labels("x", "y").set(3.5)
    metrics["dx_gn"].set(9.0)
    metrics["dx_c"].labels("x").inc(100)
    metrics["dx_cn"].inc(7)

    path = str(tmp_path / "state.json")
    assert MetricsPersistence(path, reg, metrics).save() is True

    # Fresh registry/metrics simulate a process restart.
    reg2, metrics2 = _fresh()
    restored = MetricsPersistence(path, reg2, metrics2).restore()

    assert restored == 4
    assert reg2.get_sample_value("dx_g", {"a": "x", "b": "y"}) == 3.5
    assert reg2.get_sample_value("dx_gn") == 9.0
    assert reg2.get_sample_value("dx_c_total", {"a": "x"}) == 100.0
    assert reg2.get_sample_value("dx_cn_total") == 7.0


def test_save_skips_when_unchanged(tmp_path):
    reg, metrics = _fresh()
    metrics["dx_gn"].set(1)
    p = MetricsPersistence(str(tmp_path / "s.json"), reg, metrics)
    assert p.save() is True
    assert p.save() is False  # nothing changed -> no rewrite


def test_save_writes_again_after_change(tmp_path):
    reg, metrics = _fresh()
    metrics["dx_gn"].set(1)
    p = MetricsPersistence(str(tmp_path / "s.json"), reg, metrics)
    assert p.save() is True
    metrics["dx_gn"].set(2)
    assert p.save() is True


def test_save_leaves_no_tmp_files(tmp_path):
    reg, metrics = _fresh()
    metrics["dx_gn"].set(1)
    MetricsPersistence(str(tmp_path / "s.json"), reg, metrics).save()
    assert [f for f in os.listdir(tmp_path) if f.endswith(".tmp")] == []


def test_save_creates_parent_directory(tmp_path):
    reg, metrics = _fresh()
    metrics["dx_gn"].set(1)
    nested = tmp_path / "sub" / "dir" / "state.json"
    assert MetricsPersistence(str(nested), reg, metrics).save() is True
    assert nested.exists()


# ---------------------------------------------------------------------------
# restore() resilience
# ---------------------------------------------------------------------------

def test_restore_missing_file_returns_zero(tmp_path):
    reg, metrics = _fresh()
    assert MetricsPersistence(str(tmp_path / "nope.json"), reg, metrics).restore() == 0


def test_restore_corrupt_json_ignored(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    reg, metrics = _fresh()
    assert MetricsPersistence(str(path), reg, metrics).restore() == 0


def test_restore_non_list_ignored(tmp_path):
    path = tmp_path / "obj.json"
    path.write_text(json.dumps({"name": "dx_gn", "value": 1}))
    reg, metrics = _fresh()
    assert MetricsPersistence(str(path), reg, metrics).restore() == 0


def test_restore_skips_unknown_metric_keeps_known(tmp_path):
    path = tmp_path / "mix.json"
    path.write_text(json.dumps([
        {"name": "dx_gn", "labels": {}, "value": 4},
        {"name": "dx_gone", "labels": {}, "value": 99},  # not in allowlist
    ]))
    reg, metrics = _fresh()
    assert MetricsPersistence(str(path), reg, metrics).restore() == 1
    assert reg.get_sample_value("dx_gn") == 4.0


def test_restore_skips_malformed_record(tmp_path):
    path = tmp_path / "mal.json"
    path.write_text(json.dumps([
        {"labels": {}, "value": 1},          # missing name
        {"name": "dx_gn", "value": "abc"},   # non-numeric value
        {"name": "dx_gn", "labels": {}, "value": 5},
    ]))
    reg, metrics = _fresh()
    assert MetricsPersistence(str(path), reg, metrics).restore() == 1
    assert reg.get_sample_value("dx_gn") == 5.0


def test_restore_counter_skips_nonpositive(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps([{"name": "dx_cn", "labels": {}, "value": 0}]))
    reg, metrics = _fresh()
    # A zero counter cannot be incremented and is skipped; it stays at 0.
    assert MetricsPersistence(str(path), reg, metrics).restore() == 0
    assert reg.get_sample_value("dx_cn_total") == 0.0


def test_restore_bad_label_does_not_crash(tmp_path):
    path = tmp_path / "lbl.json"
    # Wrong label names for the metric -> the .labels() call raises, is caught.
    path.write_text(json.dumps([{"name": "dx_g", "labels": {"wrong": "z"}, "value": 1}]))
    reg, metrics = _fresh()
    assert MetricsPersistence(str(path), reg, metrics).restore() == 0


# ---------------------------------------------------------------------------
# Write-failure handling
# ---------------------------------------------------------------------------

def test_save_failure_disables_persistence(tmp_path):
    # Point the state file "inside" an existing file so makedirs() raises OSError.
    afile = tmp_path / "afile"
    afile.write_text("x")
    reg, metrics = _fresh()
    metrics["dx_gn"].set(1)
    p = MetricsPersistence(str(afile / "state.json"), reg, metrics)
    assert p.save() is False
    assert p._failed is True
    assert p.save() is False  # stays disabled, never raises


def test_save_replace_failure_cleans_tmp(tmp_path, monkeypatch):
    import duplicacy_exporter as dx

    def _raise_oserror(*_a, **_k):
        raise OSError("replace failed")

    reg, metrics = _fresh()
    metrics["dx_gn"].set(1)
    p = MetricsPersistence(str(tmp_path / "r.json"), reg, metrics)
    monkeypatch.setattr(dx.os, "replace", _raise_oserror)

    assert p.save() is False
    assert p._failed is True
    # The temp file must have been removed by the finally block.
    assert [f for f in os.listdir(tmp_path) if f.endswith(".tmp")] == []


def test_run_forever_saves_then_exits(tmp_path, monkeypatch):
    import duplicacy_exporter as dx

    reg, metrics = _fresh()
    metrics["dx_gn"].set(3)
    path = tmp_path / "rf.json"
    p = MetricsPersistence(str(path), reg, metrics, interval=0)
    monkeypatch.setattr(dx.time, "sleep", lambda _seconds: None)

    real_save = p.save

    def save_once():
        result = real_save()
        p._failed = True  # let the loop run exactly one cycle, then stop
        return result

    p.save = save_once
    p.run_forever()

    assert path.exists()


# ---------------------------------------------------------------------------
# Module invariants
# ---------------------------------------------------------------------------

def test_persisted_metrics_keys_match_registry_names():
    """Every allowlist key must be a real name emitted by registry.collect()."""
    from duplicacy_exporter import registry as real_registry
    names = {metric.name for metric in real_registry.collect()}
    missing = [k for k in PERSISTED_METRICS if k not in names]
    assert missing == [], f"allowlist keys not in registry: {missing}"


def test_persisted_metrics_excludes_realtime_gauges():
    """Real-time progress gauges must not be persisted (would restore stale)."""
    persisted_objects = set(PERSISTED_METRICS.values())
    for transient in (
        backup_running,
        backup_speed_bps,
        backup_progress,
        backup_chunks_uploaded,
        backup_chunks_skipped,
        prune_running,
    ):
        assert transient not in persisted_objects


def test_persisted_metrics_excludes_version_info():
    """The version Info must reflect the running build, never a restored value."""
    assert "duplicacy_exporter" not in PERSISTED_METRICS
