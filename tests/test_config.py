"""配置加载、校验与环境变量间接寻址。"""

from __future__ import annotations

from pathlib import Path

import pytest

from novel_to_tavern import config as config_module


def test_example_config_loads_and_covers_every_key(repo_root):
    """config.example.yaml 必须能被完整解析——有未建模的键就会失败。"""
    config = config_module.load_config(repo_root / "config" / "config.example.yaml")
    assert config.project.mode == "branch_start"
    assert config.export.character_card_spec == "chara_card_v2"
    assert config.input.formats == ["txt", "md"]


def test_unknown_key_is_rejected(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("project:\n  name: x\n  typo_key: 1\n", encoding="utf-8")
    with pytest.raises(config_module.ConfigError) as excinfo:
        config_module.load_config(path)
    assert "不合规" in str(excinfo.value)


def test_missing_file_raises(tmp_path):
    with pytest.raises(config_module.ConfigError):
        config_module.load_config(tmp_path / "absent.yaml")


def test_invalid_yaml_raises(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("project: [unclosed\n", encoding="utf-8")
    with pytest.raises(config_module.ConfigError) as excinfo:
        config_module.load_config(path)
    assert "YAML" in str(excinfo.value)


def test_safety_literals_cannot_be_flipped(tmp_path):
    """隐私与 MVP 边界是 Literal，配置里无法打开。"""
    path = tmp_path / "c.yaml"
    path.write_text(
        "worldbook:\n  allow_mvu: true\n",
        encoding="utf-8",
    )
    with pytest.raises(config_module.ConfigError):
        config_module.load_config(path)


def test_env_status_reports_presence_only(tmp_path, monkeypatch):
    config = config_module.Config()
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{config.llm.api_key_env}=super-secret-value-1234\n", encoding="utf-8")
    monkeypatch.delenv(config.llm.api_key_env, raising=False)

    status = config_module.env_status(config, dotenv_path=dotenv)
    assert status[config.llm.api_key_env] is True
    assert status[config.llm.base_url_env] is False
    # 返回值里不得出现密钥本身。
    assert "super-secret-value-1234" not in repr(status)


def test_env_status_prefers_real_environment(tmp_path, monkeypatch):
    config = config_module.Config()
    monkeypatch.setenv(config.llm.base_url_env, "https://example.invalid/v1")
    status = config_module.env_status(config, dotenv_path=tmp_path / "absent.env")
    assert status[config.llm.base_url_env] is True


def test_warnings_flag_unset_model():
    warnings = config_module.config_warnings(config_module.Config())
    assert any("extraction_model" in w for w in warnings)


def test_summary_contains_no_secret_values(tmp_path, monkeypatch):
    config = config_module.Config()
    monkeypatch.setenv(config.llm.api_key_env, "leak-me-if-you-can-9999")
    summary = config_module.summarize(config)
    assert "leak-me-if-you-can-9999" not in repr(summary)
    assert summary["llm.api_key_env"] == config.llm.api_key_env


def test_style_section_defaults_are_disabled():
    cfg = config_module.Config()
    assert cfg.style.enabled is False
    assert cfg.style.max_runtime_tokens == 800
    assert cfg.style.worldbook_entries is True
    assert cfg.style.observe_max_chunks == 0
    assert cfg.style.merge_batch_size == 30
    assert cfg.style.supplementary_path is None


def test_summary_exposes_the_style_switches():
    summary = config_module.summarize(config_module.Config())
    assert summary["style.enabled"] is False
    assert summary["style.max_runtime_tokens"] == 800
    assert summary["style.worldbook_entries"] is True


def test_warning_when_supplementary_file_is_missing(tmp_path):
    cfg = config_module.Config()
    cfg = cfg.model_copy(
        update={
            "style": cfg.style.model_copy(
                update={
                    "enabled": True,
                    "supplementary_path": str(tmp_path / "absent.md"),
                }
            )
        }
    )
    warnings = config_module.config_warnings(cfg)
    assert any("supplementary_path" in w for w in warnings)

    note = tmp_path / "note.md"
    note.write_text("作者自述。", encoding="utf-8")
    cfg = cfg.model_copy(
        update={"style": cfg.style.model_copy(update={"supplementary_path": str(note)})}
    )
    assert not any("supplementary_path" in w for w in config_module.config_warnings(cfg))


def test_paths_are_strings_not_path_objects():
    """摘要要能安全序列化，不能混入 Path 对象。"""
    summary = config_module.summarize(config_module.Config())
    assert all(isinstance(k, str) for k in summary)
    assert isinstance(summary["project.source_path"], str)
