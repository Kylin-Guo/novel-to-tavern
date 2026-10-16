"""run 目录隔离：不复用、不清空、不覆盖。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from novel_to_tavern import paths


def test_new_run_id_format():
    run_id = paths.new_run_id(now=datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc))
    assert run_id.startswith("20261016T120000Z_")
    assert paths.is_valid_run_id(run_id)


def test_run_ids_do_not_collide():
    ids = {paths.new_run_id() for _ in range(50)}
    assert len(ids) == 50


def test_invalid_run_id_is_rejected(tmp_path):
    with pytest.raises(paths.RunDirError):
        paths.create_run_dir(tmp_path, "../escape")


def test_create_run_dir_builds_expected_layout(tmp_path):
    run_dir = paths.create_run_dir(tmp_path, "20261016T120000Z_abcdef")
    layout = paths.run_layout(run_dir)
    assert set(layout) == set(paths.RUN_SUBDIRS)
    assert all(p.is_dir() for p in layout.values())


def test_second_create_is_refused(tmp_path):
    paths.create_run_dir(tmp_path, "20261016T120000Z_abcdef")
    with pytest.raises(paths.RunDirError) as excinfo:
        paths.create_run_dir(tmp_path, "20261016T120000Z_abcdef")
    assert "已存在" in str(excinfo.value)


def test_existing_artifacts_survive_when_explicitly_reused(tmp_path):
    run_dir = paths.create_run_dir(tmp_path, "20261016T120000Z_abcdef")
    marker = run_dir / "exports" / "world_simulator_v2.json"
    marker.write_text("{}", encoding="utf-8")

    reused = paths.create_run_dir(tmp_path, "20261016T120000Z_abcdef", allow_existing=True)
    assert reused == run_dir
    assert marker.is_file()
    assert marker.read_text(encoding="utf-8") == "{}"


def test_distinct_runs_are_isolated(tmp_path):
    first = paths.create_run_dir(tmp_path)
    second = paths.create_run_dir(tmp_path)
    assert first != second
    (first / "reports" / "audit.md").write_text("a", encoding="utf-8")
    assert not (second / "reports" / "audit.md").exists()
