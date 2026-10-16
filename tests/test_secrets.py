"""密钥不得出现在日志或任何导出结构里。"""

from __future__ import annotations

import json

from novel_to_tavern import secrets
from novel_to_tavern.logging_setup import setup_logging

FAKE_KEY = "sk-abcdefghijklmnopqrstuvwxyz012345"


def test_registered_secret_is_removed_from_text():
    secrets.register_secret(FAKE_KEY)
    assert FAKE_KEY not in secrets.redact(f"key={FAKE_KEY}")
    assert secrets.REDACTED in secrets.redact(f"key={FAKE_KEY}")


def test_unregistered_provider_key_is_still_caught():
    """兜底模式：即使忘记登记，形如供应商密钥的串也要被擦掉。"""
    assert FAKE_KEY not in secrets.redact(f"Authorization: Bearer {FAKE_KEY}")


def test_short_values_are_not_registered():
    """避免把常见短串当密钥，导致正常文本被大面积误擦。"""
    secrets.register_secret("test")
    assert secrets.redact("this is a test") == "this is a test"


def test_redact_object_walks_nested_structures():
    secrets.register_secret(FAKE_KEY)
    payload = {"a": [{"b": FAKE_KEY}], "c": ("x", FAKE_KEY)}
    cleaned = json.dumps(secrets.redact_object(payload), ensure_ascii=False)
    assert FAKE_KEY not in cleaned


def test_log_file_never_contains_the_key(tmp_path):
    secrets.register_secret(FAKE_KEY)
    log_path = tmp_path / "run.log"
    log = setup_logging("DEBUG", log_file=log_path)
    log.info("调用 API，key=%s", FAKE_KEY)
    log.info("拼在消息里的 %s", f"prefix-{FAKE_KEY}-suffix")
    log.debug("base64 之外的裸串 %s", FAKE_KEY)

    content = log_path.read_text(encoding="utf-8")
    assert FAKE_KEY not in content
    assert secrets.REDACTED in content


def test_log_survives_non_string_args(tmp_path):
    log_path = tmp_path / "run.log"
    log = setup_logging("DEBUG", log_file=log_path)
    log.info("计数 %d，对象 %s", 3, {"k": 1})
    assert "计数 3" in log_path.read_text(encoding="utf-8")


def test_setup_logging_is_idempotent(tmp_path):
    log_path = tmp_path / "run.log"
    setup_logging("INFO", log_file=log_path)
    log = setup_logging("INFO", log_file=log_path)
    log.info("只应出现一次")
    assert log_path.read_text(encoding="utf-8").count("只应出现一次") == 1
