"""CLI 冒烟测试：全部离线，不做任何 API 调用。"""

from __future__ import annotations

from pathlib import Path

import pytest

from novel_to_tavern import __version__
from novel_to_tavern.cli import main


def test_help_exits_zero(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "usage:" in out
    assert "config-check" in out


def test_version_command(capsys):
    assert main(["version"]) == 0
    out = capsys.readouterr().out
    assert __version__ in out
    assert "SillyTavern" in out


def test_config_check_on_example_config(repo_root, capsys, monkeypatch):
    monkeypatch.chdir(repo_root)
    assert main(["config-check"]) == 0
    out = capsys.readouterr().out
    assert "chara_card_v2" in out
    # 只报告环境变量是否存在，绝不打印其值。
    assert "NOVEL_TAVERN_API_KEY: 未配置" in out


def test_config_check_reports_invalid_config(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("project:\n  mode: 不存在的模式\n", encoding="utf-8")
    assert main(["--config", str(bad), "config-check"]) == 1
    err = capsys.readouterr().err
    assert "配置校验失败" in err


def test_config_check_missing_file(tmp_path, capsys):
    assert main(["--config", str(tmp_path / "nope.yaml"), "config-check"]) == 1
    assert "找不到配置文件" in capsys.readouterr().err


def test_doctor_passes_without_api_credentials(repo_root, capsys, monkeypatch):
    """Phase 0 不需要凭据，缺凭据只能算提示，不能算失败。"""
    monkeypatch.chdir(repo_root)
    code = main(["doctor"])
    out = capsys.readouterr().out
    assert "环境检查" in out
    assert ".env 已被 .gitignore 排除" in out
    assert code == 0
    assert "提示：" in out


def test_doctor_fails_when_env_is_not_gitignored(tmp_path, capsys, monkeypatch):
    (tmp_path / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    config = tmp_path / "c.yaml"
    config.write_text("project:\n  name: x\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["--config", str(config), "doctor"]) == 1
    assert "未通过" in capsys.readouterr().out


def test_doctor_fails_on_broken_config(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    bad = tmp_path / "bad.yaml"
    bad.write_text("project:\n  nope: 1\n", encoding="utf-8")
    assert main(["--config", str(bad), "doctor"]) == 1
    assert "配置文件" in capsys.readouterr().out


# --- run-id 边界与章节号参数 ------------------------------------------------


@pytest.mark.parametrize(
    "bad_run_id",
    ["/etc", "", "../../etc", "../escape", "a/b", r"..\\escape", "20261016T120000Z_ZZZZZZ", "."],
)
def test_escaping_run_ids_are_refused_before_any_write(tmp_path, capsys, bad_run_id):
    """`--run-id /etc` 会让 `Path(root) / '/etc'` 变成 `/etc` 并写进去。

    格式闸门必须先于任何文件访问生效 —— 所以断言错误信息里出现的是
    「不合法的 run id」，而不是后续阶段的报错。
    """
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        f"project:\n  output_root: {tmp_path / 'runs'}\nllm:\n  provider: file\n",
        encoding="utf-8",
    )
    assert main(["--config", str(cfg), "timeline", "--run-id", bad_run_id]) == 1
    err = capsys.readouterr().err
    assert "不合法的 run id" in err
    assert not (tmp_path / "runs").exists()


def test_a_valid_run_id_that_does_not_exist_is_reported_clearly(tmp_path, capsys):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        f"project:\n  output_root: {tmp_path / 'runs'}\nllm:\n  provider: file\n",
        encoding="utf-8",
    )
    assert main(["--config", str(cfg), "timeline", "--run-id", "20261016T120000Z_abcdef"]) == 1
    assert "找不到 run 目录" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["0", "-1", "abc", ""])
def test_start_chapter_rejects_non_positive_chapters(bad):
    """0 是 falsy —— 早先被当成「没指定」，静默走默认档。"""
    from novel_to_tavern.cli import build_parser

    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["export", "--run-id", "20261016T120000Z_abcdef",
                                   "--start-chapter", bad])
    assert exc.value.code == 2


def test_start_chapter_accepts_one():
    from novel_to_tavern.cli import build_parser

    args = build_parser().parse_args(
        ["export", "--run-id", "20261016T120000Z_abcdef", "--start-chapter", "1"]
    )
    assert args.start_chapter == 1


def test_omitting_start_chapter_is_none_not_zero():
    from novel_to_tavern.cli import build_parser

    args = build_parser().parse_args(["export", "--run-id", "20261016T120000Z_abcdef"])
    assert args.start_chapter is None


def test_log_file_gets_written_and_is_redacted(tmp_path, repo_root, monkeypatch):
    monkeypatch.chdir(repo_root)
    log_path = tmp_path / "run.log"
    assert main(["--log-file", str(log_path), "config-check"]) == 0
    assert log_path.is_file()
    assert "config-check 完成" in log_path.read_text(encoding="utf-8")
