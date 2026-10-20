"""配置加载与校验。

约定：
- 配置文件里只写**环境变量名**，绝不写密钥值（见 `api_key_env` / `base_url_env`）。
- 未知字段直接报错，避免配置写错却静默生效。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import env as env_module

StartMode = Literal["canon_start", "branch_start", "freeform_start"]
ChapterDetection = Literal["auto", "regex", "manual"]
InputFormat = Literal["txt", "md"]
CardSpec = Literal["chara_card_v2"]

DEFAULT_CONFIG_PATH = Path("config") / "config.yaml"
EXAMPLE_CONFIG_PATH = Path("config") / "config.example.yaml"


class ConfigError(RuntimeError):
    """配置文件缺失、YAML 非法或字段不合规。"""


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectConfig(_Base):
    name: str = "novel-to-tavern"
    source_path: str = "./input/novel.txt"
    output_root: str = "./runs"
    mode: StartMode = "branch_start"


class InputConfig(_Base):
    #: 目录导入时认哪些后缀。**真的会被用来筛选文件**（见 `discover_sources`）。
    formats: list[InputFormat] = Field(default_factory=lambda: ["txt", "md"])
    encoding: str = "utf-8"
    chapter_detection: ChapterDetection = "auto"
    chapter_heading_regex: str | None = None
    chunk_target_chars: int = Field(default=10000, gt=0)
    chunk_max_chars: int = Field(default=16000, gt=0)
    #: 章节边界永远是分块边界 —— 这是不变量，不是开关。
    #: 写成 `Literal[True]` 是为了让「想关掉它」的人在这里就撞墙，而不是
    #: 改成一个没有任何代码读的 `false` 然后以为生效了。
    preserve_chapter_boundaries: Literal[True] = True
    #: 是否把 `\r\n` / `\r` 统一成 `\n` 再切行。影响分块内容，所以进配置指纹。
    normalize_newlines: bool = True


class LLMConfig(_Base):
    #: `file` = 从目录读预生成响应，用于无凭据时离线跑通同一条管线。
    provider: Literal["openai_compatible", "file"] = "openai_compatible"
    precomputed_responses_dir: str | None = None
    base_url_env: str = "NOVEL_TAVERN_BASE_URL"
    api_key_env: str = "NOVEL_TAVERN_API_KEY"
    extraction_model: str | None = None
    temperature_extract: float = Field(default=0.1, ge=0.0, le=2.0)
    request_timeout_seconds: int = Field(default=180, gt=0)
    max_retries: int = Field(default=3, ge=0)
    retry_backoff_seconds: float = Field(default=2.0, ge=0)
    max_concurrent_requests: int = Field(default=2, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)


class PipelineConfig(_Base):
    resume: bool = True
    cache_enabled: bool = True
    cache_dir: str = "./cache"
    quarantine_invalid_responses: bool = True


class WorldbookConfig(_Base):
    #: 三个常驻条目各自的开关。常驻内容每轮都进上下文，是唯一确定能省额度的地方，
    #: 所以给用户真正的开关 —— 关掉是真的不生成那个条目。
    always_on_core_rules: bool = True
    always_on_world_overview: bool = True
    always_on_character_index: bool = True
    max_always_on_entries: int = Field(default=3, ge=0)
    #: 常驻条目的**粗估** token 上限。超了只报警告，不阻断导出 —— 粗估不足以做硬门禁。
    max_always_on_tokens: int = Field(default=2500, gt=0)
    #: 单轮上下文的**粗估**预算上限，用于预算报告里的告警。同样是粗估，不阻断。
    target_runtime_budget_tokens: int = Field(default=5000, gt=0)
    #: 递归扫描本项目没有实现。写成 `Literal[False]` 而不是 `bool = False`：
    #: 前者改不动（写 true 直接报错），后者会让用户以为自己打开了什么。
    enable_recursive_scan: Literal[False] = False
    allow_mvu: Literal[False] = False
    allow_ejs: Literal[False] = False


class StyleConfig(_Base):
    """作者风格自动蒸馏（旁路资料流，非 canon）。"""

    #: 总开关。开启后 export 会自动执行风格蒸馏（见 style/pipeline.py）。
    enabled: bool = False
    #: 【叙事风格规范】分节的粗估 token 上限（estimate_tokens 口径）。
    #: 超出先自动压缩，再超报错 —— 不静默截断。
    max_runtime_tokens: int = Field(default=800, gt=0)
    #: 是否把 8 组完整风格档案写进世界书（触发式条目）。
    worldbook_entries: bool = True
    #: 逐块观察的分块数上限；0 = 全部。>0 时等距抽样（确定性，见 select_chunks）。
    observe_max_chunks: int = Field(default=0, ge=0)
    #: 合并阶段每批吃多少份观察。
    merge_batch_size: int = Field(default=30, gt=0)
    #: 可选：用户自持有的作者访谈/创作谈笔记（md/txt），作补充证据。
    #: 相对仓库根目录。
    supplementary_path: str | None = None


class HtmlRenderingConfig(_Base):
    """受控 HTML 输出规范。**提示词约束，不是运行时沙箱。**"""

    #: 开启后世界书多一条「输出格式：受控 HTML 规范」触发条目。不进 Description。
    enabled: bool = False
    mode: Literal["controlled_span"] = "controlled_span"
    allowed_properties: list[Literal["font-size", "color", "font-style"]] = Field(
        default_factory=lambda: ["font-size", "color", "font-style"]
    )
    allowed_font_sizes: list[str] = Field(
        default_factory=lambda: ["0.88em", "1em", "1.08em", "1.12em"]
    )
    color_palette: dict[str, str] = Field(
        default_factory=lambda: {
            "muted": "#9298A3",
            "emphasis": "#B08A38",
            "warning": "#B05A5A",
            "mystery": "#7C8FA6",
        }
    )
    max_suggested_spans_per_reply: int = Field(default=3, ge=0)

    @field_validator("allowed_font_sizes")
    @classmethod
    def _check_sizes(cls, value):
        if not value:
            raise ValueError("allowed_font_sizes 不能为空")
        for item in value:
            if not re.fullmatch(r"\d+(\.\d+)?em", item):
                raise ValueError(f"字号必须是 em 相对单位：{item!r}")
        return value

    @field_validator("color_palette")
    @classmethod
    def _check_palette(cls, value):
        if not value:
            raise ValueError("color_palette 不能为空")
        for name, hex_color in value.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
                raise ValueError(f"色板语义名不合法：{name!r}")
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", hex_color):
                raise ValueError(f"颜色必须是 #RRGGBB：{hex_color!r}")
        return value


class RenderingConfig(_Base):
    html: HtmlRenderingConfig = Field(default_factory=HtmlRenderingConfig)


class ExportConfig(_Base):
    character_card_spec: CardSpec = "chara_card_v2"
    #: 单张 NPC 卡（P2-2）尚未实现。同 `enable_recursive_scan`，用 `Literal[False]` 表达
    #: 「这条路还没修」，而不是给一个改了也没反应的开关。
    include_individual_npc_cards: Literal[False] = False


class PrivacyConfig(_Base):
    never_log_api_keys: Literal[True] = True
    never_include_api_keys_in_exports: Literal[True] = True
    do_not_upload_novel_without_explicit_user_action: Literal[True] = True


class Config(_Base):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    input: InputConfig = Field(default_factory=InputConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    worldbook: WorldbookConfig = Field(default_factory=WorldbookConfig)
    style: StyleConfig = Field(default_factory=StyleConfig)
    rendering: RenderingConfig = Field(default_factory=RenderingConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)


def load_config(path: str | Path | None = None) -> Config:
    """读取 YAML 配置。路径为空时优先 `config/config.yaml`，回退 `config.example.yaml`。"""
    if path is None:
        candidate = DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.is_file() else EXAMPLE_CONFIG_PATH
    else:
        candidate = Path(path)

    if not candidate.is_file():
        raise ConfigError(f"找不到配置文件：{candidate}")

    try:
        raw = yaml.safe_load(candidate.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件不是合法 YAML：{candidate}（{exc}）") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件顶层必须是映射：{candidate}")

    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"配置字段不合规：{candidate}\n{exc}") from exc


def env_status(config: Config, *, dotenv_path: str | Path = env_module.DEFAULT_DOTENV) -> dict[str, bool]:
    """返回 `{环境变量名: 是否已配置}`。只回答有无，不返回值。"""
    names = {config.llm.base_url_env, config.llm.api_key_env}
    return {name: env_module.is_set(name, dotenv_path=dotenv_path) for name in sorted(names)}


def config_warnings(config: Config) -> list[str]:
    """不阻断运行的提示项。"""
    warnings: list[str] = []
    if not config.llm.extraction_model:
        warnings.append("llm.extraction_model 未设置：Phase 0 不需要模型，进入 Phase 2 前必须填写。")
    if not config.worldbook.always_on_core_rules:
        warnings.append(
            "worldbook.always_on_core_rules=false：卡里将没有「世界运行规则」条目，"
            "模型失去时间纪律与知识边界的约束。只在你自己另配规则时才关。"
        )
    if config.input.formats and set(config.input.formats) - {"txt", "md"}:
        warnings.append(f"input.formats 含未支持的后缀：{config.input.formats}")
    if (
        config.style.enabled
        and config.style.supplementary_path
        and not Path(config.style.supplementary_path).is_file()
    ):
        warnings.append(
            f"style.supplementary_path 指向的文件不存在：{config.style.supplementary_path}。"
            "风格编译会因此报错，请修正路径或留空。"
        )
    if config.rendering.html.enabled:
        warnings.append(
            "rendering.html.enabled=true：HTML 规则是世界书触发条目，"
            "且 Tavo 的渲染效果未经实测；提示词不是运行时沙箱。"
        )
    return warnings


def summarize(config: Config) -> dict[str, Any]:
    """用于 `config-check` 输出的摘要，保证不含任何密钥值。"""
    return {
        "project.name": config.project.name,
        "project.source_path": config.project.source_path,
        "project.output_root": config.project.output_root,
        "project.mode": config.project.mode,
        "input.formats": config.input.formats,
        "input.chunk_target_chars": config.input.chunk_target_chars,
        "llm.provider": config.llm.provider,
        "llm.base_url_env": config.llm.base_url_env,
        "llm.api_key_env": config.llm.api_key_env,
        "llm.extraction_model": config.llm.extraction_model,
        "export.character_card_spec": config.export.character_card_spec,
        "worldbook.always_on_core_rules": config.worldbook.always_on_core_rules,
        "worldbook.always_on_world_overview": config.worldbook.always_on_world_overview,
        "worldbook.always_on_character_index": config.worldbook.always_on_character_index,
        "style.enabled": config.style.enabled,
        "style.max_runtime_tokens": config.style.max_runtime_tokens,
        "style.worldbook_entries": config.style.worldbook_entries,
        "rendering.html.enabled": config.rendering.html.enabled,
    }
