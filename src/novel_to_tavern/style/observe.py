"""逐分块的作者风格观察。

流程：chunk → 提示词 → 缓存/引擎 → 解析 JSON → schema 校验 → **引文定位** → 落盘。

三条规则与抽取器一致：
1. 行号由 `extract.evidence.locate_quote` 在原文里搜出来，不接受模型自报。
2. 引文定位失败就**丢弃**并计数 —— 观察本身保留，但不把编造的引文当证据。
3. 解析/校验失败的响应进 `_errors/` 隔离目录，绝不静默当作成功。

**日志与报告不出现小说原文。**
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from ..extract.evidence import locate_quote
from ..extract.runner import parse_json_response
from ..ingest.manifest import Manifest
from ..ingest.source import read_source
from ..llm.provider import MissingResponseError, Provider, ProviderError
from . import StyleError
from .cache import (
    load_cached_response,
    store_cached_response,
    style_cache_key,
)
from .prompts import (
    PROMPT_VERSION_OBSERVE,
    SYSTEM_PROMPT_OBSERVE,
    build_observe_user_prompt,
)
from .schema import (
    OBSERVATION_SCHEMA_VERSION,
    RawStyleObservation,
    StyleEvidence,
    StyleObservation,
)

STYLE_DIR = "author_style"
OBSERVATIONS_DIR = "observations"
ERROR_DIR = "_errors"
INDEX_NAME = "_index.json"
REPORT_NAME = "author_style_observe.md"

#: 解析失败时最多再问几次（与抽取器一致）。
MAX_PARSE_ATTEMPTS = 2

#: 隔离文件里保留多少字符。失败记录不需要无上限写盘。
MAX_QUARANTINE_CHARS = 20_000


class StyleObserveError(StyleError):
    """观察阶段的致命错误。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def select_chunks(manifest: Manifest, max_chunks: int) -> list:
    """选择要观察的分块。

    `max_chunks <= 0` → 全部。否则**等距抽样**（确定性的）：
    排序后取 `floor(i*(n-1)/(k-1))` 位，首尾必含。

    抽样存在的原因：156 块各一次调用成本不低。确定性保证同一输入
    得到同一抽样，缓存与续跑才有意义。报告必须写明覆盖率，抽样结果
    不冒充全量。
    """
    chunks = sorted(manifest.chunks, key=lambda c: c.index)
    if max_chunks <= 0 or max_chunks >= len(chunks):
        return chunks
    if max_chunks == 1:
        return [chunks[0]]
    n = len(chunks)
    k = max_chunks
    indices = sorted({(i * (n - 1)) // (k - 1) for i in range(k)})
    return [chunks[i] for i in indices]


class StyleObservationRunner:
    def __init__(
        self,
        config,
        run_dir: str | Path,
        provider: Provider,
        *,
        log=None,
    ) -> None:
        self.config = config
        self.run_dir = Path(run_dir)
        self.provider = provider
        self.log = log

        manifest_path = self.run_dir / "manifest.json"
        if not manifest_path.is_file():
            raise StyleObserveError(
                f"该 run 没有 manifest：{manifest_path}，请先跑 ingest。"
            )
        self.manifest = Manifest.model_validate(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )

        self.out_dir = self.run_dir / STYLE_DIR / OBSERVATIONS_DIR
        self.error_dir = self.out_dir / ERROR_DIR
        self.index_path = self.out_dir / INDEX_NAME

        self._sources: dict[str, list[str]] = {}
        self._chunks = {c.chunk_id: c for c in self.manifest.chunks}
        self._chapters = {c.chapter_id: c for c in self.manifest.chapters}
        self._global_order = self.manifest.global_chapter_order()

    # --- 原文访问 ---------------------------------------------------------

    def lines_for(self, source_id: str) -> list[str]:
        if source_id not in self._sources:
            record = next(
                (s for s in self.manifest.sources if s.source_id == source_id), None
            )
            if record is None:
                raise StyleObserveError(f"manifest 里没有来源：{source_id}")
            self._sources[source_id] = read_source(
                record.path, encoding=record.encoding, source_id=record.source_id
            ).lines
        return self._sources[source_id]

    # --- 单块处理 ---------------------------------------------------------

    def process_chunk(self, chunk_id: str, *, use_cache: bool = True) -> StyleObservation:
        chunk = self._chunks[chunk_id]
        chapter = self._chapters[chunk.chapter_id]
        chapter_index = self._global_order.get(chunk.chapter_id, chapter.index)
        lines = self.lines_for(chunk.source_id)
        text = "".join(lines[chunk.start_line : chunk.end_line])

        source_record = next(
            s for s in self.manifest.sources if s.source_id == chunk.source_id
        )
        label = f"第{chapter_index + 1}章"
        if chapter.title:
            label = f"{label} {chapter.title}"

        user_prompt = build_observe_user_prompt(
            book_title=source_record.filename,
            chapter_label=label,
            chapter_title="",
            text=text,
        )

        model = (
            self.config.llm.extraction_model
            or getattr(self.provider, "model", "")
            or self.provider.name
        )
        key = style_cache_key(
            kind="style_observe",
            config=self.config,
            provider=self.provider,
            prompt_version=PROMPT_VERSION_OBSERVE,
            input_sha256=chunk.sha256,
            extra={"chunk_sha256": chunk.sha256},
        )

        raw_text: str | None = None
        if use_cache:
            raw_text = load_cached_response(self.config, key)

        raw: RawStyleObservation | None = None
        last_error: Exception | None = None
        attempts = 0

        while raw is None:
            if raw_text is not None:
                # 缓存命中：先试着解析。解析不了就当作没命中，重新问引擎。
                try:
                    raw = RawStyleObservation.model_validate(parse_json_response(raw_text))
                    break
                except (ValueError, ValidationError):
                    raw_text = None

            attempts += 1
            try:
                completion = self.provider.complete(
                    chunk_id=chunk_id,
                    system_prompt=SYSTEM_PROMPT_OBSERVE,
                    user_prompt=user_prompt,
                )
            except MissingResponseError as exc:
                raise StyleObserveError(f"{chunk_id} 缺少预生成响应：{exc}") from exc
            except ProviderError as exc:
                raise StyleObserveError(f"{chunk_id} 观察失败：{exc}") from exc

            raw_text = completion.text
            try:
                raw = RawStyleObservation.model_validate(parse_json_response(raw_text))
            except (ValueError, ValidationError) as exc:
                last_error = exc
                if attempts >= MAX_PARSE_ATTEMPTS:
                    self._quarantine(chunk_id, raw_text, str(exc))
                    raise StyleObserveError(
                        f"{chunk_id} 的响应不是合法的风格观察 JSON"
                        f"（已隔离到 {ERROR_DIR}/）：{exc}"
                    ) from exc
                if self.log:
                    self.log.warning("%s 响应解析失败，重试一次：%s", chunk_id, exc)

        store_cached_response(self.config, key, raw_text or "", model=model)

        # --- 引文定位：行号由代码算，定位失败就丢弃 ---
        window = (chunk.start_line, chunk.end_line)
        evidence: list[StyleEvidence] = []
        dropped = 0
        for item in raw.evidence:
            check = locate_quote(lines, item.quote, window=window)
            if check.located is None:
                dropped += 1
                continue
            evidence.append(
                StyleEvidence(
                    aspect=item.aspect,
                    quote=item.quote,
                    start_line=check.located.start_line,
                    end_line=check.located.end_line,
                )
            )

        observation = StyleObservation(
            chunk_id=chunk_id,
            chapter_index=chapter_index,
            source_id=chunk.source_id,
            schema_version=OBSERVATION_SCHEMA_VERSION,
            narrative_voice=raw.narrative_voice,
            sentence_rhythm=raw.sentence_rhythm,
            description_patterns=raw.description_patterns,
            figurative_language=raw.figurative_language,
            dialogue_patterns=raw.dialogue_patterns,
            psychological_narration=raw.psychological_narration,
            scene_pacing=raw.scene_pacing,
            notable_motifs=list(raw.notable_motifs),
            anti_patterns_observed=list(raw.anti_patterns_observed),
            evidence=evidence,
            quotes_dropped=dropped,
            model=model,
            prompt_version=PROMPT_VERSION_OBSERVE,
            input_sha256=chunk.sha256,
            output_sha256=hashlib.sha256((raw_text or "").encode("utf-8")).hexdigest(),
        )
        return observation

    def _quarantine(self, chunk_id: str, text: str, reason: str) -> None:
        if not self.config.pipeline.quarantine_invalid_responses:
            return
        body = text or ""
        if len(body) > MAX_QUARANTINE_CHARS:
            head = body[: MAX_QUARANTINE_CHARS // 2]
            tail = body[-MAX_QUARANTINE_CHARS // 2 :]
            body = (
                f"{head}\n\n…（此处省略 {len(text) - MAX_QUARANTINE_CHARS} 字符）…\n\n{tail}"
            )
        _write_json(
            self.error_dir / f"{chunk_id}.json",
            {
                "chunk_id": chunk_id,
                "reason": reason,
                "raw_response": body,
                "raw_length": len(text or ""),
            },
        )

    def output_path(self, chunk_id: str) -> Path:
        return self.out_dir / f"{chunk_id}.json"


def _load_index(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"done": [], "failed": {}, "skipped": [], "updated_at": ""}


def run_style_observation(
    config,
    run_dir: str | Path,
    provider: Provider,
    *,
    resume: bool | None = None,
    limit: int | None = None,
    log=None,
    max_chunks: int | None = None,
) -> dict:
    """对选中的分块跑风格观察，逐块落盘以便随时中断续跑。"""
    runner = StyleObservationRunner(config, run_dir, provider, log=log)
    resume = config.pipeline.resume if resume is None else resume

    if max_chunks is None:
        style_cfg = getattr(config, "style", None)
        max_chunks = style_cfg.observe_max_chunks if style_cfg is not None else 0

    selected = select_chunks(runner.manifest, max_chunks)
    if limit is not None:
        selected = selected[:limit]

    index = _load_index(runner.index_path) if resume else {
        "done": [],
        "failed": {},
        "skipped": [],
        "updated_at": "",
    }
    index["failed"] = {} if not resume else index["failed"]
    done_set = set(index["done"])

    pending: list[str] = []
    for chunk in selected:
        if (
            resume
            and chunk.chunk_id in done_set
            and runner.output_path(chunk.chunk_id).is_file()
        ):
            index["skipped"].append(chunk.chunk_id)
            continue
        pending.append(chunk.chunk_id)

    if log:
        log.info(
            "风格观察：待观察 %d 块，跳过 %d 块（共 %d 块）",
            len(pending),
            len(index["skipped"]),
            len(runner.manifest.chunks),
        )

    failures: dict[str, str] = {}
    for chunk_id in pending:
        try:
            observation = runner.process_chunk(chunk_id)
        except StyleObserveError as exc:
            failures[chunk_id] = str(exc)
            if log:
                log.error("风格观察失败 %s：%s", chunk_id, exc)
            index["failed"] = failures
            index["updated_at"] = _now()
            _write_json(runner.index_path, index)
            continue
        _write_json(runner.output_path(chunk_id), observation.model_dump(mode="json"))
        index["done"].append(chunk_id)
        index["failed"] = failures
        index["updated_at"] = _now()
        _write_json(runner.index_path, index)

    index["failed"] = failures
    index["updated_at"] = _now()
    _write_json(runner.index_path, index)

    report = _write_report(runner, index, selected)
    return {
        "done": list(index["done"]),
        "skipped": list(index["skipped"]),
        "failed": dict(failures),
        "ok": not failures,
        "report": str(report),
        "coverage": {
            "observed": len(
                [c for c in selected if runner.output_path(c.chunk_id).is_file()]
            ),
            "selected": len(selected),
            "total_chunks": len(runner.manifest.chunks),
        },
    }


def _write_report(runner: StyleObservationRunner, index: dict, selected: list) -> Path:
    """观察覆盖率与引文丢弃情况的报告。**不含小说原文。**"""
    observations = []
    for path in sorted(runner.out_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        observations.append(json.loads(path.read_text(encoding="utf-8")))

    quotes_dropped = sum(int(item.get("quotes_dropped", 0)) for item in observations)
    quotes_total = sum(len(item.get("evidence", [])) for item in observations) + quotes_dropped
    unknown_dims = 0
    for item in observations:
        for dim in (
            "narrative_voice",
            "sentence_rhythm",
            "description_patterns",
            "figurative_language",
            "dialogue_patterns",
            "psychological_narration",
            "scene_pacing",
        ):
            if item.get(dim) == "unknown":
                unknown_dims += 1

    lines = [
        "# 作者风格观察报告",
        "",
        f"- run_id：`{runner.run_dir.name}`",
        f"- 生成时间：{_now()}",
        f"- 观察引擎：`{runner.provider.name}`",
        f"- 提示词版本：`{PROMPT_VERSION_OBSERVE}`",
        "",
        "## 覆盖率（先读这一节）",
        "",
        f"- 全部分块：{len(runner.manifest.chunks)}",
        f"- 本次选中：{len(selected)}",
        f"- 已完成观察：{len(observations)}",
        f"- 本次跳过（续跑）：{len(index['skipped'])}",
        f"- 失败：{len(index['failed'])}",
    ]
    if len(selected) < len(runner.manifest.chunks):
        lines.append(
            "- **这是抽样结果，不是全量**：`style.observe_max_chunks` 打开了等距抽样。"
        )
    lines += [
        "",
        "## 引文证据",
        "",
        f"- 已定位引文：{quotes_total - quotes_dropped}",
        f"- 定位失败被丢弃：{quotes_dropped}",
        "",
        "> 丢弃的引文不影响观察本身，但它**不是证据**。",
        "",
        "## 维度完整度",
        "",
        f"- 填了 `unknown` 的维度计数：{unknown_dims}"
        f"（共 {len(observations)} 份 × 7 个维度）",
        "",
    ]
    if index["failed"]:
        lines += ["## 失败分块", ""]
        for chunk_id, reason in sorted(index["failed"].items()):
            lines.append(f"- `{chunk_id}`：{reason}")
        lines.append("")

    lines += ["> 本报告不含小说原文。", ""]
    path = runner.run_dir / "reports" / REPORT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
