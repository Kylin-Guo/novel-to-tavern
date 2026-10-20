"""把逐块观察编译成风格档案。

步骤（与 docs/AUTHOR_STYLE_PIPELINE.md 对应）：

1. 读 `author_style/observations/*.json`；
2. 按 `merge_batch_size` 分批合并，逐批落盘；
3. 汇总批次笔记 + 章节摘要 + 可选补充资料 → 编译 `StyleProfile`；
4. **代码**填 profile_id / created_at / works_in_scope / source_manifest /
   inputs_fingerprint（模型留空的字段由程序补齐）；
5. 预算超限走压缩；压缩后仍超 → 报错并写审计，**不静默截断**；
6. 落盘 6 份产物。

风格资料不是 canon：不写 facts / entities / timeline / knowledge。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from ..extract.runner import parse_json_response
from ..ingest.manifest import Manifest
from ..llm.provider import MissingResponseError, ProviderError
from ..timeline.worldbible import estimate_tokens
from . import StyleError
from .cache import load_cached_response, store_cached_response, style_cache_key
from .prompts import (
    PROMPT_VERSION_COMPILE,
    PROMPT_VERSION_COMPRESS,
    PROMPT_VERSION_MERGE,
    SYSTEM_PROMPT_COMPILE,
    SYSTEM_PROMPT_COMPRESS,
    SYSTEM_PROMPT_MERGE,
    build_compile_user_prompt,
    build_compress_user_prompt,
    build_merge_user_prompt,
    prompt_template_hash,
)
from .schema import (
    OBSERVATION_SCHEMA_VERSION,
    PROFILE_SCHEMA_VERSION,
    STYLE_DIMENSIONS,
    SourceManifestEntry,
    StyleDimension,
    StyleProfile,
    _Base,
)
from .worldbook import (
    STYLE_ENTRY_GROUPS,
    build_style_entries,
    write_style_entries,
)

MERGE_DIR = "merged"
ERROR_DIR = "_errors"
PROFILE_JSON = "style_profile.json"
PROFILE_MD = "style_profile.md"
RUNTIME_MD = "runtime_style_prompt.md"
ENTRIES_JSON = "style_worldbook_entries.json"
EVAL_CASES_JSON = "style_eval_cases.json"
AUDIT_NAME = "audit.md"

MAX_PARSE_ATTEMPTS = 2
MAX_QUARANTINE_CHARS = 20_000


class StyleCompileError(StyleError):
    """编译阶段的致命错误。"""


class MergedNotes(_Base):
    dimensions: dict[str, StyleDimension] = Field(default_factory=dict)
    contextual_variants: list[str] = Field(default_factory=list)
    anti_patterns: list[str] = Field(default_factory=list)
    motifs: list[str] = Field(default_factory=list)


class CompressedRules(_Base):
    runtime_rules: str
    dropped: list[str] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _style_dir(run_dir: Path) -> Path:
    return run_dir / "author_style"


def _load_manifest(run_dir: Path) -> Manifest:
    path = run_dir / "manifest.json"
    if not path.is_file():
        raise StyleCompileError(f"该 run 没有 manifest：{path}，请先跑 ingest。")
    return Manifest.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _load_observations(run_dir: Path) -> list[dict]:
    directory = _style_dir(run_dir) / "observations"
    observations = []
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        observations.append(json.loads(path.read_text(encoding="utf-8")))
    return observations


def _trim_observation(observation: dict) -> dict:
    """合并阶段的输入：不带 chunk 元数据与引文，控制长度。"""
    trimmed = {dim: observation.get(dim, "unknown") for dim in STYLE_DIMENSIONS}
    trimmed["notable_motifs"] = observation.get("notable_motifs", [])
    trimmed["anti_patterns_observed"] = observation.get("anti_patterns_observed", [])
    return trimmed


def _digest_lines(run_dir: Path) -> list[str]:
    """章节摘要清单（仅标题 + 一句话），供编译时理解语境。"""
    by_chapter: dict[int, dict] = {}
    for path in sorted((run_dir / "extraction").glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        index = data.get("chapter_index")
        if index is None or index in by_chapter:
            continue
        by_chapter[index] = data
    lines: list[str] = []
    for index in sorted(by_chapter):
        data = by_chapter[index]
        title = str(data.get("chapter_title", "") or "").strip()
        summary = str(data.get("summary", "") or "").strip()
        lines.append(f"第{index + 1}章 {title}：{summary}".strip())
    return lines


def _supplementary(config) -> tuple[str, Path | None]:
    raw = config.style.supplementary_path
    if not raw:
        return "", None
    path = Path(raw)
    if not path.is_file():
        raise StyleCompileError(
            f"style.supplementary_path 指向的文件不存在：{path}。"
            "请修正路径，或把它留空。"
        )
    return path.read_text(encoding="utf-8"), path


def compute_inputs_fingerprint(
    run_path, config, *, endpoint_fingerprint: str = ""
) -> str:
    """产物新鲜度判定依据。

    组成与 PLAN §7.2 一致：提示词版本与模板 hash、两个 schema 版本、模型、
    endpoint、全部来源 sha256、观察/合并预算、补充资料 sha256。

    注意：export 在**没有凭据**时也要判断产物是否新鲜，所以编译时写入的
    指纹使用空 endpoint。调用方显式传值时才纳入 endpoint。
    """
    run_dir = Path(run_path)
    manifest = _load_manifest(run_dir)
    supplement_sha: str | None = None
    raw = config.style.supplementary_path
    if raw:
        path = Path(raw)
        supplement_sha = _sha256(path.read_text(encoding="utf-8")) if path.is_file() else "missing"

    payload = {
        "kind": "style_pipeline",
        "prompt_versions": [
            PROMPT_VERSION_COMPILE,
            PROMPT_VERSION_COMPRESS,
            PROMPT_VERSION_MERGE,
            "style-observe-v1",
        ],
        "prompt_template_sha256": prompt_template_hash(),
        "observation_schema_version": OBSERVATION_SCHEMA_VERSION,
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "model": config.llm.extraction_model or "",
        "endpoint_fingerprint": endpoint_fingerprint,
        "source_sha256": [source.sha256 for source in manifest.sources],
        "observe_max_chunks": config.style.observe_max_chunks,
        "merge_batch_size": config.style.merge_batch_size,
        "max_runtime_tokens": config.style.max_runtime_tokens,
        "supplementary_sha256": supplement_sha,
    }
    return _sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def _quarantine(run_dir: Path, chunk_id: str, text: str, reason: str) -> None:
    body = text or ""
    if len(body) > MAX_QUARANTINE_CHARS:
        head = body[: MAX_QUARANTINE_CHARS // 2]
        tail = body[-MAX_QUARANTINE_CHARS // 2 :]
        body = (
            f"{head}\n\n…（此处省略 {len(text) - MAX_QUARANTINE_CHARS} 字符）…\n\n{tail}"
        )
    _write_json(
        _style_dir(run_dir) / ERROR_DIR / f"{chunk_id}.json",
        {
            "chunk_id": chunk_id,
            "reason": reason,
            "raw_response": body,
            "raw_length": len(text or ""),
        },
    )


def _complete_json(
    *,
    provider,
    config,
    run_dir: Path,
    kind: str,
    chunk_id: str,
    prompt_version: str,
    system_prompt: str,
    user_prompt: str,
    input_sha256: str,
    extra: dict,
    model_cls: type[BaseModel],
    log=None,
):
    """缓存 → 引擎 → 解析 → schema 校验；失败重试一次，再失败隔离并报错。"""
    key = style_cache_key(
        kind=kind,
        config=config,
        provider=provider,
        prompt_version=prompt_version,
        input_sha256=input_sha256,
        extra=extra,
    )
    raw_text = load_cached_response(config, key)
    parsed = None
    if raw_text is not None:
        try:
            parsed = model_cls.model_validate(parse_json_response(raw_text))
        except (ValueError, ValidationError):
            raw_text = None

    model = (
        config.llm.extraction_model
        or getattr(provider, "model", "")
        or provider.name
    )
    attempts = 0
    while parsed is None:
        attempts += 1
        try:
            completion = provider.complete(
                chunk_id=chunk_id, system_prompt=system_prompt, user_prompt=user_prompt
            )
        except MissingResponseError as exc:
            raise StyleCompileError(f"{chunk_id} 缺少预生成响应：{exc}") from exc
        except ProviderError as exc:
            raise StyleCompileError(f"{chunk_id} 调用引擎失败：{exc}") from exc

        raw_text = completion.text
        try:
            parsed = model_cls.model_validate(parse_json_response(raw_text))
        except (ValueError, ValidationError) as exc:
            if attempts >= MAX_PARSE_ATTEMPTS:
                _quarantine(run_dir, chunk_id, raw_text, str(exc))
                raise StyleCompileError(
                    f"{chunk_id} 的响应不符合 schema（已隔离到 "
                    f"author_style/{ERROR_DIR}/）：{exc}"
                ) from exc
            if log:
                log.warning("%s 响应解析失败，重试一次：%s", chunk_id, exc)

    store_cached_response(config, key, raw_text or "", model=model)
    return parsed, raw_text or "", model


def _merge_batches(
    observations: list[dict], config, provider, run_dir: Path, log=None
) -> list[dict]:
    batch_size = config.style.merge_batch_size
    batches = [
        observations[index : index + batch_size]
        for index in range(0, len(observations), batch_size)
    ]
    merged_dir = _style_dir(run_dir) / MERGE_DIR
    notes: list[dict] = []

    for index, batch in enumerate(batches):
        chunk_id = f"style_merge_batch_{index:03d}"
        trimmed = [_trim_observation(item) for item in batch]
        user_prompt = build_merge_user_prompt(
            observations_json=json.dumps(trimmed, ensure_ascii=False, indent=2)
        )
        input_sha = _sha256(
            json.dumps(trimmed, sort_keys=True, ensure_ascii=False)
        )
        merged, _raw, _model = _complete_json(
            provider=provider,
            config=config,
            run_dir=run_dir,
            kind="style_merge",
            chunk_id=chunk_id,
            prompt_version=PROMPT_VERSION_MERGE,
            system_prompt=SYSTEM_PROMPT_MERGE,
            user_prompt=user_prompt,
            input_sha256=input_sha,
            extra={"batch_index": index},
            model_cls=MergedNotes,
            log=log,
        )
        payload = merged.model_dump(mode="json")
        _write_json(merged_dir / f"batch_{index:03d}.json", payload)
        notes.append(payload)
        if log:
            log.info("风格合并：第 %d 批（%d 份观察）", index + 1, len(batch))
    return notes


def run_style_compile(run_dir, config, provider, *, log=None) -> StyleProfile:
    run_path = Path(run_dir)
    observations = _load_observations(run_path)
    if not observations:
        raise StyleCompileError(
            "没有可用的风格观察。请先跑 `n2t style-observe`"
            "（或开启 style.enabled 后直接 export 自动蒸馏）。"
        )

    manifest = _load_manifest(run_path)
    notes = _merge_batches(observations, config, provider, run_path, log=log)

    digests = _digest_lines(run_path)
    supplementary_text, supplementary_path = _supplementary(config)
    max_runtime = config.style.max_runtime_tokens

    compile_input = {
        "batch_notes": notes,
        "digests": digests,
        "supplementary": supplementary_text,
        "max_runtime_tokens": max_runtime,
    }
    compile_sha = _sha256(
        json.dumps(compile_input, sort_keys=True, ensure_ascii=False)
    )
    supplement_sha = (
        _sha256(supplementary_text) if supplementary_path is not None else None
    )

    profile, _raw, _model = _complete_json(
        provider=provider,
        config=config,
        run_dir=run_path,
        kind="style_compile",
        chunk_id="style_compile",
        prompt_version=PROMPT_VERSION_COMPILE,
        system_prompt=SYSTEM_PROMPT_COMPILE,
        user_prompt=build_compile_user_prompt(
            batch_notes_json=json.dumps(notes, ensure_ascii=False, indent=2),
            digests=digests,
            supplementary=supplementary_text,
            max_runtime_tokens=max_runtime,
        ),
        input_sha256=compile_sha,
        extra={
            "max_runtime_tokens": max_runtime,
            "supplementary_sha256": supplement_sha,
        },
        model_cls=StyleProfile,
        log=log,
    )

    fingerprint = compute_inputs_fingerprint(run_path, config)
    profile_id = f"style-{fingerprint[:12]}"
    profile = profile.model_copy(
        update={
            "profile_id": profile_id,
            "created_at": _now(),
            "works_in_scope": [source.filename for source in manifest.sources],
            "source_manifest": [
                SourceManifestEntry(
                    kind="novel",
                    locator=source.filename,
                    detail=f"sha256:{source.sha256[:12]}",
                )
                for source in manifest.sources
            ]
            + (
                [
                    SourceManifestEntry(
                        kind="note",
                        locator=str(supplementary_path),
                        detail="用户提供的补充资料；外部证据，需与小说文本交叉检查",
                    )
                ]
                if supplementary_path is not None
                else []
            ),
            "inputs_fingerprint": fingerprint,
        }
    )

    dropped: list[str] = []
    compressed = False
    runtime_tokens = estimate_tokens(profile.runtime_rules)
    if runtime_tokens > max_runtime:
        compressed = True
        compress_sha = _sha256(profile.runtime_rules)
        result, _raw, _model = _complete_json(
            provider=provider,
            config=config,
            run_dir=run_path,
            kind="style_compress",
            chunk_id="style_compress",
            prompt_version=PROMPT_VERSION_COMPRESS,
            system_prompt=SYSTEM_PROMPT_COMPRESS,
            user_prompt=build_compress_user_prompt(
                runtime_rules=profile.runtime_rules, max_tokens=max_runtime
            ),
            input_sha256=compress_sha,
            extra={"max_runtime_tokens": max_runtime},
            model_cls=CompressedRules,
            log=log,
        )
        dropped = list(result.dropped)
        profile = profile.model_copy(update={"runtime_rules": result.runtime_rules})
        runtime_tokens = estimate_tokens(profile.runtime_rules)
        if runtime_tokens > max_runtime:
            _write_audit(
                run_path,
                profile=profile,
                observations=observations,
                manifest=manifest,
                runtime_tokens=runtime_tokens,
                max_runtime=max_runtime,
                compressed=compressed,
                dropped=dropped,
                supplementary_path=supplementary_path,
                failure=(
                    f"压缩后运行时规范仍为 {runtime_tokens} token，"
                    f"超过预算 {max_runtime}。已中止，未截断。"
                ),
            )
            raise StyleCompileError(
                f"运行时风格规范压缩后仍超过预算（{runtime_tokens} > {max_runtime}）。"
                "没有静默截断；请调高 style.max_runtime_tokens 或精简风格档案。"
            )

    _write_artifacts(run_path, profile, config)
    _write_audit(
        run_path,
        profile=profile,
        observations=observations,
        manifest=manifest,
        runtime_tokens=runtime_tokens,
        max_runtime=max_runtime,
        compressed=compressed,
        dropped=dropped,
        supplementary_path=supplementary_path,
        failure="",
    )

    if log:
        log.info(
            "风格编译完成：%s（运行时约 %d token，预算 %d）",
            profile.profile_id,
            runtime_tokens,
            max_runtime,
        )
    return profile


def _write_artifacts(run_path: Path, profile: StyleProfile, config) -> None:
    base = _style_dir(run_path)
    _write_json(base / PROFILE_JSON, profile.model_dump(mode="json"))
    _write_text(base / PROFILE_MD, render_profile_md(profile))
    _write_text(base / RUNTIME_MD, render_runtime_prompt(profile))
    entries = build_style_entries(profile)
    write_style_entries(base / ENTRIES_JSON, entries)
    _write_json(
        base / EVAL_CASES_JSON,
        [case.model_dump(mode="json") for case in profile.eval_cases],
    )


def render_profile_md(profile: StyleProfile) -> str:
    """人工阅读版。只使用档案内容，**不复制原著句子**。"""
    lines = [
        "# 作者风格档案",
        "",
        f"- profile_id：`{profile.profile_id}`",
        f"- 作者：{profile.author_label}",
        f"- 作品范围：{'、'.join(profile.works_in_scope) or '（未记录）'}",
        f"- 生成时间：{profile.created_at}",
        f"- schema：`{profile.schema_version}`",
        f"- inputs_fingerprint：`{profile.inputs_fingerprint}`",
        "",
        "## 资料清单",
        "",
        "| 类型 | 位置 | 说明 |",
        "|---|---|---|",
    ]
    for source in profile.source_manifest:
        lines.append(f"| {source.kind} | {source.locator} | {source.detail or '—'} |")

    lines += ["", "## 维度", ""]
    for dim in (*STYLE_DIMENSIONS, "genre_tone"):
        value: StyleDimension = getattr(profile, dim)
        lines.append(f"### {dim}（置信度：{value.confidence}）")
        lines.append("")
        lines.append(value.summary)
        if value.rules:
            lines.append("")
            for rule in value.rules:
                lines.append(f"- {rule}")
        lines.append("")

    lines += ["## 反模式（与本作不相容的生成倾向）", ""]
    lines += [f"- {item}" for item in profile.anti_patterns] or ["- （无）"]
    lines += ["", "## 情境差异", ""]
    lines += [f"- {item}" for item in profile.contextual_variants] or ["- （无）"]
    lines += ["", "## 局限", ""]
    lines += [f"- {item}" for item in profile.limitations] or ["- （无）"]
    lines += ["", "## 待人工复核", ""]
    lines += [f"- {item}" for item in profile.human_review_items] or ["- （无）"]
    lines += ["", "## 运行时规范", "", profile.runtime_rules.strip(), ""]

    lines += ["## 评估样例", ""]
    for case in profile.eval_cases:
        lines.append(f"### {case.case_id} · {case.scenario_type}")
        lines.append("")
        lines.append(case.instruction)
        lines.append("")
        lines.append("应体现：" + "；".join(case.expected_traits))
        if case.anti_patterns:
            lines.append("")
            lines.append("应避免：" + "；".join(case.anti_patterns))
        lines.append("")

    lines += [
        "> 本档案是写作风格资料，不是原著事实。"
        "不得据此改写 canon 数据。",
        "",
    ]
    return "\n".join(lines)


def render_runtime_prompt(profile: StyleProfile) -> str:
    """`runtime_style_prompt.md` 的内容 —— export 追加进 Description 的唯一风格主体。"""
    return "写作执行要点：\n" + profile.runtime_rules.strip() + "\n"


def _write_audit(
    run_path: Path,
    *,
    profile: StyleProfile,
    observations: list[dict],
    manifest: Manifest,
    runtime_tokens: int,
    max_runtime: int,
    compressed: bool,
    dropped: list[str],
    supplementary_path: Path | None,
    failure: str,
) -> None:
    quotes_dropped = sum(int(item.get("quotes_dropped", 0)) for item in observations)
    confidence_counts: dict[str, int] = {}
    for dim in (*STYLE_DIMENSIONS, "genre_tone"):
        confidence = getattr(profile, dim).confidence
        confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1

    lines = [
        "# 作者风格蒸馏审计",
        "",
        f"- run_id：`{run_path.name}`",
        f"- profile_id：`{profile.profile_id}`",
        f"- inputs_fingerprint：`{profile.inputs_fingerprint}`",
        f"- 生成时间：{_now()}",
        "",
        "## 观察覆盖（先读这一节）",
        "",
        f"- 已观察分块：{len(observations)}",
        f"- 全部分块：{len(manifest.chunks)}",
    ]
    if len(observations) < len(manifest.chunks):
        lines.append(
            "- **这是抽样结果，不是全量**：覆盖率见上，抽样结果不冒充全量。"
        )
    lines += [
        f"- 引文定位失败被丢弃：{quotes_dropped}",
        "",
        "## 维度置信度分布",
        "",
    ]
    for key in ("high", "medium", "low", "unknown"):
        if confidence_counts.get(key):
            lines.append(f"- {key}：{confidence_counts[key]}")
    lines += [
        "",
        "## 运行时预算",
        "",
        f"- 运行时规范粗估：{runtime_tokens} token（预算 {max_runtime}）",
        f"- 是否触发压缩：{'是' if compressed else '否'}",
        f"- 丢弃规律数：{len(dropped)}",
    ]

    built = {entry.entry_id for entry in build_style_entries(profile)}
    skipped_groups = [group for group in STYLE_ENTRY_GROUPS if group[0] not in built]
    if skipped_groups:
        lines.append(
            "- 未生成的世界书条目组（全组维度都是 unknown）："
            + "、".join(f"{entry_id}（{title}）" for entry_id, title, _ in skipped_groups)
        )
    if dropped:
        lines.append("")
        lines.append("压缩时删去的规律：")
        lines.append("")
        lines += [f"- {item}" for item in dropped]

    lines += [
        "",
        "## 补充资料",
        "",
        (
            f"- 使用了：`{supplementary_path}`"
            "（外部证据，已在 limitations 中记录交叉检查结论）"
            if supplementary_path is not None
            else "- 未使用"
        ),
        "",
        "## 局限与人工复核项",
        "",
    ]
    lines += [f"- {item}" for item in profile.limitations] or ["- （模型未列出）"]
    lines += [f"- [复核] {item}" for item in profile.human_review_items]

    if failure:
        lines += ["", "## 中止原因", "", failure, ""]

    lines += [
        "",
        "## 产物",
        "",
        f"- `author_style/{PROFILE_JSON}`",
        f"- `author_style/{PROFILE_MD}`",
        f"- `author_style/{RUNTIME_MD}`",
        f"- `author_style/{ENTRIES_JSON}`",
        f"- `author_style/{EVAL_CASES_JSON}`",
        "",
        "> 风格资料不是 canon：不写 facts / entities / timeline / knowledge，"
        "不改变任何原著事实。",
        "> 本报告不含小说原文。",
        "",
    ]
    _write_text(_style_dir(run_path) / AUDIT_NAME, "\n".join(lines))
