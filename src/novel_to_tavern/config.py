"""配置加载与校验。

约定：
- 配置文件里只写**环境变量名**，绝不写密钥值（见 `api_key_env` / `base_url_env`）。
- 未知字段直接报错，避免配置写错却静默生效。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    default_start_chapter: int | None = None
    mode: StartMode = "branch_start"


class InputConfig(_Base):
    formats: list[InputFormat] = Field(default_factory=lambda: ["txt", "md"])
    encoding: str = "utf-8"
    chapter_detection: ChapterDetection = "auto"
    chapter_heading_regex: str | None = None
    chunk_target_chars: int = Field(default=10000, gt=0)
    chunk_max_chars: int = Field(default=16000, gt=0)
    preserve_chapter_boundaries: bool = True
    normalize_newlines: bool = True


class LLMConfig(_Base):
    #: `file` = 从目录读预生成响应，用于无凭据时离线跑通同一条管线。
    provider: Literal["openai_compatible", "file"] = "openai_compatible"
    precomputed_responses_dir: str | None = None
    base_url_env: str = "NOVEL_TAVERN_BASE_URL"
    api_key_env: str = "NOVEL_TAVERN_API_KEY"
    extraction_model: str | None = None
    synthesis_model: str | None = None
    audit_model: str | None = None
    temperature_extract: float = Field(default=0.1, ge=0.0, le=2.0)
    temperature_synthesis: float = Field(default=0.2, ge=0.0, le=2.0)
    request_timeout_seconds: int = Field(default=180, gt=0)
    max_retries: int = Field(default=3, ge=0)
    retry_backoff_seconds: float = Field(default=2.0, ge=0)
    max_concurrent_requests: int = Field(default=2, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    log_token_usage_when_available: bool = True
    never_auto_switch_provider: bool = True


class PipelineConfig(_Base):
    resume: bool = True
    cache_enabled: bool = True
    cache_dir: str = "./cache"
    preserve_raw_responses: bool = True
    require_source_refs_for_canon: bool = True
    merge_low_confidence_entities: bool = False
    drop_characters_by_default: bool = False
    fail_on_invalid_model_json: bool = False
    quarantine_invalid_responses: bool = True


class WorldbookConfig(_Base):
    always_on_core_rules: bool = True
    always_on_world_overview: bool = True
    always_on_character_index: bool = True
    max_always_on_entries: int = Field(default=3, ge=0)
    target_runtime_budget_tokens: int = Field(default=5000, gt=0)
    enable_recursive_scan: bool = False
    allow_mvu: Literal[False] = False
    allow_ejs: Literal[False] = False
    allow_html_beautification: Literal[False] = False


class ExportConfig(_Base):
    character_card_spec: CardSpec = "chara_card_v2"
    include_embedded_character_book: bool = True
    also_export_standalone_worldbook: bool = True
    include_individual_npc_cards: bool = False
    validate_before_export: bool = True
    overwrite_existing_run: bool = False


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
    if config.export.overwrite_existing_run:
        warnings.append("export.overwrite_existing_run=true：将允许覆盖已有 run 产物，请确认已备份。")
    if config.worldbook.allow_mvu or config.worldbook.allow_ejs:
        warnings.append("worldbook 中 MVU/EJS 已启用：超出 MVP 范围，需用户明确要求。")
    if config.pipeline.drop_characters_by_default:
        warnings.append("pipeline.drop_characters_by_default=true：与本项目「默认不丢人物」原则冲突。")
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
        "export.include_embedded_character_book": config.export.include_embedded_character_book,
    }
