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


# --- 读/写既有 run 时的路径边界 ---------------------------------------------


@pytest.mark.parametrize(
    "bad", ["/etc", "", "../escape", "../../etc", "a/b", ".", "..", r"..\\escape", "2026_abc"]
)
def test_resolve_run_dir_refuses_anything_that_is_not_a_run_id(tmp_path, bad):
    with pytest.raises(paths.RunDirError, match="不合法的 run id"):
        paths.resolve_run_dir(tmp_path, bad)


def test_absolute_run_id_would_have_escaped_without_the_check(tmp_path):
    """把事故写下来：不做校验时 `Path(root) / '/etc'` 就是 `/etc`。

    所以这一条不是「理论上可能」，而是「Python 的路径拼接语义决定的」。
    """
    from pathlib import Path

    assert Path(tmp_path) / "/etc" == Path("/etc")
    assert Path(tmp_path) / "" == Path(tmp_path)

    with pytest.raises(paths.RunDirError):
        paths.resolve_run_dir(tmp_path, "/etc")
    with pytest.raises(paths.RunDirError):
        paths.resolve_run_dir(tmp_path, "")


def test_resolve_run_dir_returns_the_existing_run(tmp_path):
    created = paths.create_run_dir(tmp_path, "20261016T120000Z_abcdef")
    assert paths.resolve_run_dir(tmp_path, "20261016T120000Z_abcdef") == created.resolve()


def test_resolve_run_dir_reports_a_missing_run(tmp_path):
    with pytest.raises(paths.RunDirError, match="找不到 run 目录"):
        paths.resolve_run_dir(tmp_path, "20261016T120000Z_abcdef")


def test_resolve_run_dir_allows_a_missing_dir_when_asked(tmp_path):
    got = paths.resolve_run_dir(tmp_path, "20261016T120000Z_abcdef", must_exist=False)
    assert got == (tmp_path / "20261016T120000Z_abcdef").resolve()


def test_a_symlinked_run_dir_pointing_outside_is_refused(tmp_path):
    """格式校验看不见符号链接 —— 所以还要 `resolve()` 之后确认父目录。"""
    root = tmp_path / "runs"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "20261016T120000Z_abcdef").symlink_to(outside, target_is_directory=True)

    with pytest.raises(paths.RunDirError, match="跑出了 run 根目录"):
        paths.resolve_run_dir(root, "20261016T120000Z_abcdef")


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
