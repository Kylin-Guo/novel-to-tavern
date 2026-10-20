"""每个配置键都必须真的被读 —— 否则配置文件就在撒谎。

为什么值得一条专门的测试：本项目踩过一次，`config.py` 里 57 个字段有
**24 个可变字段**从未被任何代码读过。用户把 `export.validate_before_export`
改成 `false`，导出校验照跑；把 `pipeline.require_source_refs_for_canon`
改成 `true`，也不会多出任何来源检查。两种方向相反的谎都比「没有这个开关」更误导。

所以这里的规则是：**每个键要么有消费点，要么它的类型声明它只能是那一个值。**
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args, get_origin, Literal

import pytest
from pydantic import BaseModel

from novel_to_tavern import config as config_module

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "novel_to_tavern"
CONFIG_PY = SRC / "config.py"
EXAMPLE_YAML = REPO_ROOT / "config" / "config.example.yaml"


def _config_classes() -> dict[str, type[BaseModel]]:
    out: dict[str, type[BaseModel]] = {}
    for name in dir(config_module):
        obj = getattr(config_module, name)
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not config_module.Config:
            if name.endswith("Config"):
                out[name] = obj
    return out


def _all_fields() -> list[tuple[str, str, object]]:
    """返回 `[(section, field, field_info), ...]`，section 是点分实例路径。

    递归展开嵌套配置段（例如 `rendering.html`），否则嵌套段的键
    永远不会被接线检查覆盖。
    """
    rows: list[tuple[str, str, object]] = []

    def walk(model: type[BaseModel], prefix: str) -> None:
        for field, finfo in model.model_fields.items():
            annotation = finfo.annotation
            path = f"{prefix}.{field}" if prefix else field
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                walk(annotation, path)
            else:
                rows.append((prefix, field, finfo))

    walk(config_module.Config, "")
    return rows


def _sections() -> dict[str, set[str]]:
    """`{点分路径: 该段的字段名集合}`，只含真正的配置段。"""
    sections: dict[str, set[str]] = {}

    def walk(model: type[BaseModel], prefix: str) -> None:
        names: set[str] = set()
        for field, finfo in model.model_fields.items():
            annotation = finfo.annotation
            path = f"{prefix}.{field}" if prefix else field
            names.add(field)
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                walk(annotation, path)
        if prefix:
            sections[prefix] = names

    walk(config_module.Config, "")
    return sections


def _is_single_value_literal(annotation) -> bool:
    """`Literal[True]` / `Literal[False]` / `Literal["x"]` —— 只能取一个值。

    这类字段是声明（「这条路还没修」「这是不变量」），不是开关：
    写不出别的取值，也就谈不上「改了没反应」。
    """
    if get_origin(annotation) is not Literal:
        return False
    return len(get_args(annotation)) == 1


def _consumption_sites(field: str) -> list[str]:
    """在 `src/` 里找 `.<field>` 的出现处，排除 config.py 自己。"""
    pattern = re.compile(rf"\.{re.escape(field)}\b")
    hits: list[str] = []
    for path in SRC.rglob("*.py"):
        if path == CONFIG_PY:
            continue
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            hits.append(str(path.relative_to(REPO_ROOT)))
    return hits


FIELDS = _all_fields()


def test_the_field_list_is_not_empty():
    """先确认这套自省真的抓到了字段，否则下面的断言会空过。"""
    assert len(FIELDS) > 30


@pytest.mark.parametrize(
    ("section", "field", "finfo"), FIELDS, ids=[f"{s}.{f}" for s, f, _ in FIELDS]
)
def test_every_config_key_is_either_consumed_or_a_single_value_declaration(section, field, finfo):
    if _is_single_value_literal(finfo.annotation):
        return
    sites = _consumption_sites(field)
    assert sites, (
        f"配置键 {section}.{field} 没有任何消费点：没有任何代码读它。"
        "要么把它接上（并在这里留下的路径自然会通过），"
        "要么删掉它；如果它是「未实现」的声明，把类型改成单值 Literal 并在注释里写明。"
        "详见 docs/CONFIG_REFERENCE.md。"
    )


def test_single_value_literal_fields_are_documented_in_the_example_config():
    """声明型字段也要在示例配置里出现，并写明「只能为这个值」。"""
    text = EXAMPLE_YAML.read_text(encoding="utf-8")
    missing: list[str] = []
    for section, field, finfo in FIELDS:
        if not _is_single_value_literal(finfo.annotation):
            continue
        if f"{field}:" not in text:
            missing.append(f"{section}.{field}")
    assert missing == [], f"示例配置里缺少这些声明型字段：{missing}"


def _yaml_leaf_keys(text: str, sections: dict[str, set[str]]) -> set[tuple[str, str]]:
    """按缩进还原点分路径，只记录**配置段**下面的叶子键。"""
    seen: set[tuple[str, str]] = set()
    stack: list[tuple[int, str]] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^(\s*)([a-z_]+):(.*)$", line)
        if not match:
            continue
        indent = len(match.group(1))
        key = match.group(2)
        rest = match.group(3).strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        parent = ".".join(name for _, name in stack)
        path = f"{parent}.{key}" if parent else key
        if (
            parent in sections
            and key in sections[parent]
            and path not in sections  # 嵌套段本身不是叶子键
        ):
            seen.add((parent, key))
        if not rest:
            stack.append((indent, key))
    return seen


def test_the_example_config_covers_exactly_the_real_keys():
    """示例配置与 schema 必须一一对应 —— 多一个键会在加载时直接报错。"""
    from novel_to_tavern.config import load_config

    cfg = load_config(EXAMPLE_YAML)
    assert isinstance(cfg, config_module.Config)

    declared = {(section, field) for section, field, _ in FIELDS}
    seen = _yaml_leaf_keys(EXAMPLE_YAML.read_text(encoding="utf-8"), _sections())

    assert seen == declared, (
        f"示例配置与 schema 不一致：只在 schema 里 {sorted(declared - seen)}；"
        f"只在示例里 {sorted(seen - declared)}"
    )


def test_the_local_config_matches_the_schema_if_present():
    """本地 config.yaml 也要能加载 —— 删键之后它是最容易忘记同步的那份。"""
    local = REPO_ROOT / "config" / "config.yaml"
    if not local.is_file():
        pytest.skip("本机没有 config/config.yaml")
    assert isinstance(config_module.load_config(local), config_module.Config)


def test_removed_keys_stay_removed():
    """这几个键被删掉是因为它们从未接线。删了就不许回来 —— 除非先接上线。"""
    removed = [
        "default_start_chapter",
        "synthesis_model",
        "audit_model",
        "temperature_synthesis",
        "log_token_usage_when_available",
        "never_auto_switch_provider",
        "preserve_raw_responses",
        "require_source_refs_for_canon",
        "merge_low_confidence_entities",
        "drop_characters_by_default",
        "fail_on_invalid_model_json",
        "validate_before_export",
        "overwrite_existing_run",
        "include_embedded_character_book",
        "also_export_standalone_worldbook",
        "allow_html_beautification",
    ]
    names = {field for _, field, _ in FIELDS}
    assert not (set(removed) & names), (
        "这些键重新出现了，但没有任何消费点。要恢复就先接上线并加测试。"
    )
