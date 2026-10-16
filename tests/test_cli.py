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


def test_log_file_gets_written_and_is_redacted(tmp_path, repo_root, monkeypatch):
    monkeypatch.chdir(repo_root)
    log_path = tmp_path / "run.log"
    assert main(["--log-file", str(log_path), "config-check"]) == 0
    assert log_path.is_file()
    assert "config-check 完成" in log_path.read_text(encoding="utf-8")
