"""受控 HTML：配置闸门、规则文本只含白名单、样例矩阵、导出条目。"""

from __future__ import annotations

import json
import re

import pytest

from novel_to_tavern import config as config_module
from novel_to_tavern.config import HtmlRenderingConfig
from novel_to_tavern.export import export
from novel_to_tavern.render import (
    HtmlPolicy,
    HtmlPolicyError,
    build_html_entry,
    build_html_rules_text,
    validate_html_sample,
)


def _policy() -> HtmlPolicy:
    return HtmlPolicy.from_config(config_module.Config().rendering.html)


def _load_invalid(tmp_path, body: str) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(config_module.ConfigError):
        config_module.load_config(path)


# --- 配置闸门 --------------------------------------------------------------


def test_bad_color_rejected(tmp_path):
    _load_invalid(
        tmp_path,
        'rendering:\n  html:\n    color_palette:\n      muted: "red"\n',
    )


def test_bad_size_rejected(tmp_path):
    _load_invalid(
        tmp_path,
        'rendering:\n  html:\n    allowed_font_sizes: ["12px"]\n',
    )


def test_unknown_property_rejected(tmp_path):
    _load_invalid(
        tmp_path,
        "rendering:\n  html:\n    allowed_properties: [background]\n",
    )


def test_empty_palette_rejected(tmp_path):
    _load_invalid(tmp_path, "rendering:\n  html:\n    color_palette: {}\n")


def test_policy_from_config_rejects_unvalidated_values():
    """即使绕过 pydantic 构造，from_config 也要挡住非法值。"""
    bad = HtmlRenderingConfig.model_construct(
        enabled=True,
        mode="controlled_span",
        allowed_properties=("font-size",),
        allowed_font_sizes=("12px",),
        color_palette={"muted": "#9298A3"},
        max_suggested_spans_per_reply=1,
    )
    with pytest.raises(HtmlPolicyError, match="em"):
        HtmlPolicy.from_config(bad)


# --- 规则文本 --------------------------------------------------------------


def test_rules_text_whitelist_only():
    policy = _policy()
    text = build_html_rules_text(policy)

    samples = re.findall(r"<span[^>]*>.*?</span>", text)
    assert samples, "规则文本里应当有可复制的示例"
    for sample in samples:
        assert validate_html_sample(sample, policy) == [], sample

    lowered = text.lower()
    for banned in ("script", "iframe", "onclick", "onerror", "<div", "class="):
        assert banned not in lowered, f"规则文本含禁用内容：{banned}"


def test_rules_text_uses_only_configured_values():
    cfg = config_module.Config().rendering.html
    cfg = cfg.model_copy(
        update={
            "allowed_font_sizes": ["1em"],
            "color_palette": {"muted": "#112233"},
        }
    )
    text = build_html_rules_text(HtmlPolicy.from_config(cfg))
    assert "#112233" in text
    assert "1em" in text
    assert "#9298A3" not in text


# --- 样例矩阵 --------------------------------------------------------------


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("纯文本，没有标签。", None),
        ('<span style="color: #9298A3">旁注</span>', None),
        (
            '<span style="font-size: 1.08em; font-style: italic">低语</span>',
            None,
        ),
        (
            '<span style="color: #B08A38">甲</span> 与 '
            '<span style="color: #B05A5A">乙</span>',
            None,
        ),
        ("<script>alert(1)</script>", "只允许 span"),
        ('<span onclick="x()">a</span>', "只允许 style 属性"),
        ("<div>块级标签</div>", "只允许 span"),
        ('<span style="background: #9298A3">a</span>', "不在白名单"),
        ('<span style="font-style: oblique">a</span>', "font-style"),
        ('<span style="font-size: 2em">a</span>', "字号"),
        ('<span style="color: #000000">a</span>', "颜色"),
        ('<span><span style="color: #9298A3">a</span></span>', "嵌套"),
        ('<span style="color: #9298A3">未闭合', "未闭合"),
    ],
)
def test_validate_sample_matrix(sample, expected):
    violations = validate_html_sample(sample, _policy())
    if expected is None:
        assert violations == [], violations
    else:
        assert any(expected in reason for reason in violations), violations


# --- 世界书条目 ------------------------------------------------------------


def test_entry_triggered_not_always_on_and_keys():
    entry = build_html_entry(_policy())
    assert entry.entry_id == "wb_rendering_html"
    assert entry.category == "rendering"
    assert entry.always_on is False
    assert entry.chapter_gated is False
    assert entry.keys
    assert "非 canon" in "".join(entry.quality_flags)
    assert "不是世界设定" in entry.content_runtime
    assert any("格式" in key or "排版" in key for key in entry.keys)


# --- 导出集成 --------------------------------------------------------------


def _with_html(enabled: bool) -> config_module.Config:
    base = config_module.Config()
    html = base.rendering.html.model_copy(update={"enabled": enabled})
    return base.model_copy(
        update={"rendering": base.rendering.model_copy(update={"html": html})}
    )


def test_export_entry_present_when_enabled_absent_when_disabled(tmp_path):
    from test_style_export_integration import _prepare_run

    run = _prepare_run(tmp_path)

    result = export(run, _with_html(True))
    rendering_ids = [e.entry_id for e in result["entries"] if e.category == "rendering"]
    assert rendering_ids == ["wb_rendering_html"]
    assert "受控 HTML 规范" not in result["card"].data.description
    assert not (run / "author_style").exists(), "HTML 模块不应触发风格蒸馏"

    manifest = json.loads(
        (run / "exports" / "export_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["rendering"]["enabled"] is True
    assert manifest["style"] == {"enabled": False}

    audit = (run / "reports" / "audit.md").read_text(encoding="utf-8")
    assert "受控 HTML" in audit
    assert "无运行时过滤" in audit

    result2 = export(run, _with_html(False))
    assert [e.entry_id for e in result2["entries"] if e.category == "rendering"] == []
    manifest2 = json.loads(
        (run / "exports" / "export_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest2["rendering"] == {"enabled": False}
