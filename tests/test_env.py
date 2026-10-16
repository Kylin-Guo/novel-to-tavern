""".env 解析（标准库实现）。"""

from __future__ import annotations

from novel_to_tavern import env as env_module


def test_parse_basic_pairs_and_comments():
    parsed = env_module.parse_dotenv(
        "\n".join(
            [
                "# 注释行",
                "",
                "NOVEL_TAVERN_BASE_URL=https://example.invalid/v1",
                "  SPACED = padded  ",
                "export EXPORTED=yes",
            ]
        )
    )
    assert parsed["NOVEL_TAVERN_BASE_URL"] == "https://example.invalid/v1"
    assert parsed["SPACED"] == "padded"
    assert parsed["EXPORTED"] == "yes"
    assert len(parsed) == 3


def test_quoted_values_are_unwrapped():
    parsed = env_module.parse_dotenv("A='single'\nB=\"double\"\nC=\"has=equals\"\n")
    assert parsed == {"A": "single", "B": "double", "C": "has=equals"}


def test_lines_without_equals_are_skipped():
    assert env_module.parse_dotenv("just-a-word\nDONE\n") == {}


def test_load_dotenv_missing_file_is_empty(tmp_path):
    assert env_module.load_dotenv(tmp_path / "nope.env") == {}


def test_real_environment_wins_over_dotenv(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text("SOME_VAR=from-file\n", encoding="utf-8")
    monkeypatch.setenv("SOME_VAR", "from-env")
    assert env_module.resolve_variable("SOME_VAR", dotenv_path=dotenv) == "from-env"


def test_is_set_returns_bool_not_value(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("TOKEN_ABC=value-should-not-surface\n", encoding="utf-8")
    result = env_module.is_set("TOKEN_ABC", dotenv_path=dotenv)
    assert result is True
    assert "value-should-not-surface" not in repr(result)
