"""分块原子事实抽取的执行器。

流程：chunk → 提示词 → 缓存/引擎 → 解析 JSON → schema 校验 → **证据定位** → 落盘。

三条不让步的规则：
1. 行号永远由 `evidence.locate_quote` 在原文里搜出来，不接受模型自报。
2. 声称是 canon 却没有可定位证据的条目 → `needs_review`，不当作原著事实。
3. 解析/校验失败的响应进 `_errors/` 隔离目录，绝不静默当作成功。
"""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from .. import config as config_module, secrets
from ..ingest.manifest import Manifest
from ..ingest.source import read_source
from ..llm.provider import MissingResponseError, Provider, ProviderError
from .evidence import QuoteCheck, locate_quote
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from .schema import (
    CANON,
    ChunkExtraction,
    EventRecord,
    FactRecord,
    MentionRecord,
    RawChunkExtraction,
    RelationRecord,
    SourceRef,
)

EXTRACTION_DIR = "extraction"
INDEX_NAME = "_index.json"
ERROR_DIR = "_errors"
SUMMARY_NAME = "extraction_summary.md"

#: 解析失败时最多再问几次。
MAX_PARSE_ATTEMPTS = 2


class ExtractionError(RuntimeError):
    """抽取阶段的致命错误。"""


def parse_json_response(text: str) -> dict:
    """从模型回答里取出 JSON。容忍 ```json 围栏与前后废话，但不猜内容。"""
    if not text or not text.strip():
        raise ValueError("响应为空")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("响应里找不到 JSON 对象")
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"响应不是合法 JSON：{exc}") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


#: 输出 schema 的版本。改了 `schema.py` 里任何会影响解析结果的字段就要 +1 ——
#: 否则旧缓存会被当成新 schema 的结果继续用。
SCHEMA_VERSION = 1


def prompt_template_hash() -> str:
    """提示词模板自身的 hash。

    用 `PROMPT_VERSION` 一个字串容易漏：改了提示词却忘了改版本号，
    缓存就会命中旧结果，修复看起来「没生效」。本项目真踩过这个坑。
    """
    payload = json.dumps(
        {
            "system": SYSTEM_PROMPT,
            # 用占位值渲染一次 —— 只要模板本身变了，hash 就变。
            "user": build_user_prompt(
                book_title="{book_title}",
                chapter_label="{chapter_label}",
                chapter_title="{chapter_title}",
                text="{text}",
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _declared(item, field: str) -> bool:
    """模型**是否真的写了**这个字段。

    Pydantic 会把缺失字段静默填成默认值，光看取值分不出「模型写了 unknown」
    和「模型根本没写」。`model_fields_set` 分得出 —— 这两件事的处理方式不同：
    前者是模型的判断，后者是模型的遗漏，后者必须进复核队列。
    """
    return field in item.model_fields_set


def _append_note(note: str, extra: str) -> str:
    """拼接复核理由，避免出现「；；」或开头的分号。"""
    return f"{note}；{extra}" if note else extra


def cache_key(*, model: str, provider: str, chunk_sha: str, temperature: float) -> str:
    """缓存键必须包含**全部语义相关输入**。

    漏掉任何一项都会造成「改了东西但结果没变」这种最难查的故障：
    模型、引擎、提示词版本、提示词模板 hash、输出 schema 版本、
    输入 chunk 的 hash、以及 temperature。
    """
    payload = json.dumps(
        {
            "provider": provider,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "prompt_template_sha256": prompt_template_hash(),
            "schema_version": SCHEMA_VERSION,
            "chunk_sha256": chunk_sha,
            "temperature": temperature,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


class ExtractionRunner:
    def __init__(
        self,
        config: config_module.Config,
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
            raise ExtractionError(f"该 run 没有 manifest：{manifest_path}，请先跑 ingest。")
        self.manifest = Manifest.model_validate(
            json.loads(manifest_path.read_text(encoding="utf-8"))
        )

        self.out_dir = self.run_dir / EXTRACTION_DIR
        self.error_dir = self.out_dir / ERROR_DIR
        self.index_path = self.out_dir / INDEX_NAME
        self.cache_dir = Path(config.pipeline.cache_dir)
        self._lock = threading.Lock()
        self._sources: dict[str, list[str]] = {}
        self._chapter_meta = {c.chunk_id: c for c in self.manifest.chunks}
        self._chapter_by_id = {c.chapter_id: c for c in self.manifest.chapters}
        # 多卷本的 ChapterRecord.index 是"来源内"序号，三卷都从 0 起，直接用会撞号。
        self._global_order = self.manifest.global_chapter_order()
        self._source_names = self.manifest.source_display_names()

    # --- 原文访问 ---------------------------------------------------------

    def lines_for(self, source_id: str) -> list[str]:
        if source_id not in self._sources:
            record = next(
                (s for s in self.manifest.sources if s.source_id == source_id), None
            )
            if record is None:
                raise ExtractionError(f"manifest 里没有来源：{source_id}")
            self._sources[source_id] = read_source(
                record.path, encoding=record.encoding, source_id=record.source_id
            ).lines
        return self._sources[source_id]

    # --- 缓存 -------------------------------------------------------------

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _load_cache(self, key: str) -> str | None:
        if not self.config.pipeline.cache_enabled:
            return None
        path = self._cache_path(key)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8")).get("text")

    def _store_cache(self, key: str, text: str, *, model: str) -> None:
        if not self.config.pipeline.cache_enabled:
            return
        self._write_cache(self._cache_path(key), {"text": text, "model": model})

    @staticmethod
    def _write_cache(path: Path, payload) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    # --- 单块处理 ---------------------------------------------------------

    def process_chunk(self, chunk_id: str, *, use_cache: bool = True) -> ChunkExtraction:
        chunk = self._chapter_meta[chunk_id]
        chapter = self._chapter_by_id[chunk.chapter_id]
        lines = self.lines_for(chunk.source_id)
        text = "".join(lines[chunk.start_line : chunk.end_line])

        source_record = next(
            s for s in self.manifest.sources if s.source_id == chunk.source_id
        )
        book_title = source_record.filename
        chapter_label = self.chapter_label_of(chapter)

        user_prompt = build_user_prompt(
            book_title=book_title,
            chapter_label=chapter_label,
            chapter_title=chapter.title,
            text=text,
        )

        model = getattr(self.provider, "model", "") or self.provider.name
        key = cache_key(
            model=model,
            provider=self.provider.name,
            chunk_sha=chunk.sha256,
            temperature=self.config.llm.temperature_extract,
        )

        problems: list[str] = []
        raw_text: str | None = None
        source_of_text = "provider"

        if use_cache:
            cached = self._load_cache(key)
            if cached is not None:
                raw_text = cached
                source_of_text = "cache"

        last_error: Exception | None = None
        raw: RawChunkExtraction | None = None
        if raw_text is not None:
            try:
                raw = RawChunkExtraction.model_validate(parse_json_response(raw_text))
            except (ValueError, ValidationError) as exc:
                problems.append(f"缓存内容无法解析，已忽略缓存：{exc}")
                raw_text = None
                source_of_text = "provider"

        attempts = 0
        while raw is None:
            attempts += 1
            try:
                completion = self.provider.complete(
                    chunk_id=chunk_id, system_prompt=SYSTEM_PROMPT, user_prompt=user_prompt
                )
            except MissingResponseError:
                raise
            except ProviderError as exc:
                raise ExtractionError(f"{chunk_id} 抽取失败：{exc}") from exc

            raw_text = completion.text
            source_of_text = "provider"
            try:
                raw = RawChunkExtraction.model_validate(parse_json_response(raw_text))
            except (ValueError, ValidationError) as exc:
                last_error = exc
                if attempts >= MAX_PARSE_ATTEMPTS:
                    self._quarantine(chunk_id, raw_text, str(exc))
                    raise ExtractionError(
                        f"{chunk_id} 的响应不是合法的抽取 JSON（已隔离到 {ERROR_DIR}/）：{exc}"
                    ) from exc
                problems.append(f"第 {attempts} 次响应解析失败，重试：{exc}")

        if source_of_text == "provider":
            self._store_cache(key, raw_text or "", model=model)

        extraction = self._to_records(chunk_id, raw, lines, chunk, chapter, problems)
        extraction.provider = self.provider.name
        extraction.model = model
        extraction.prompt_version = PROMPT_VERSION
        extraction.input_sha256 = chunk.sha256
        extraction.output_sha256 = hashlib.sha256((raw_text or "").encode("utf-8")).hexdigest()
        return extraction

    def _quarantine(self, chunk_id: str, text: str, reason: str) -> None:
        if not self.config.pipeline.quarantine_invalid_responses:
            return
        target = self.error_dir / f"{chunk_id}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# reason: {reason}\n# chunk: {chunk_id}\n\n{text}\n", encoding="utf-8")

    def _to_records(
        self,
        chunk_id: str,
        raw: RawChunkExtraction,
        lines: list[str],
        chunk,
        chapter,
        problems: list[str],
    ) -> ChunkExtraction:
        window = (chunk.start_line, chunk.end_line)
        located_total = 0
        located_ok = 0
        ambiguous_total = 0

        def resolve(quote: str) -> tuple[list[SourceRef], QuoteCheck]:
            nonlocal located_total, located_ok, ambiguous_total
            located_total += 1
            check = locate_quote(lines, quote, window=window)
            if check.located is None:
                return [], check
            located_ok += 1
            if check.ambiguous:
                ambiguous_total += 1
            return [
                SourceRef(
                    source_id=chunk.source_id,
                    chapter_id=chunk.chapter_id,
                    start_line=check.located.start_line,
                    end_line=check.located.end_line,
                    quote=check.located.matched_text,
                    quote_exact=quote,
                    ambiguous=check.ambiguous,
                    match_count=check.match_count,
                )
            ], check

        common = {
            "chunk_id": chunk_id,
            "source_id": chunk.source_id,
            "chapter_id": chunk.chapter_id,
            "chapter_index": self._global_order.get(chunk.chapter_id, chapter.index),
            "chapter_label": self.chapter_label_of(chapter),
        }

        mentions: list[MentionRecord] = []
        for i, item in enumerate(raw.mentions):
            refs, check = resolve(item.quote)
            status = "accepted" if refs or not item.quote else "needs_review"
            note = item.note
            if not refs and item.quote:
                problems.append(f"mention「{item.name}」的引文无法在原文定位")
            if check.ambiguous:
                status = "needs_review"
                note = _append_note(note, check.reason)
                problems.append(f"mention「{item.name}」的引文定位不唯一")
            if not _declared(item, "kind"):
                # 模型没说这是什么 —— 不能替它认成人物。
                status = "needs_review"
                note = _append_note(note, "模型未给出 kind，按 unknown 处理")
                problems.append(f"mention「{item.name}」未给出 kind，已按 unknown 处理")
            mentions.append(
                MentionRecord(
                    mention_id=f"{chunk_id}_m{i:03d}",
                    name=item.name,
                    aliases=list(item.aliases),
                    kind=item.kind,
                    note=note,
                    source_refs=refs,
                    review_status=status,
                    **common,
                )
            )

        facts: list[FactRecord] = []
        for i, item in enumerate(raw.facts):
            refs, check = resolve(item.quote)
            status = "accepted"
            note = ""
            if check.ambiguous:
                # 找到了但不止一处 —— 「来源」这件事还没落实，不能算已核查。
                status = "needs_review"
                note = _append_note(note, check.reason)
                problems.append(
                    f"fact「{item.subject}.{item.predicate}」的引文定位不唯一"
                )
            if not _declared(item, "fact_type"):
                # 少写一个字段是常见的，静默补成 canon_fact 是本项目最不能犯的错。
                status = "needs_review"
                note = _append_note(note, "模型未给出 fact_type，按 unknown 处理（不得当作原著正史）")
                problems.append(
                    f"fact「{item.subject}.{item.predicate}」未给出 fact_type，已按 unknown 处理"
                )
            if not refs:
                # canon 必须可核查；定位失败就不能当原著事实。
                status = "needs_review"
                note = _append_note(note, "引文无法在原文定位" if item.quote else "缺少引文")
                problems.append(f"fact「{item.subject}.{item.predicate}」{note}")
                if item.fact_type == CANON:
                    note = _append_note(note, "声称 canon 但无证据，需人工复核")
            facts.append(
                FactRecord(
                    fact_id=f"{chunk_id}_f{i:03d}",
                    subject=item.subject,
                    predicate=item.predicate,
                    value=item.value,
                    fact_type=item.fact_type,
                    source_refs=refs,
                    review_status=status,
                    review_note=note,
                    **common,
                )
            )

        events: list[EventRecord] = []
        for i, item in enumerate(raw.events):
            refs, check = resolve(item.quote)
            status = "accepted" if refs else "needs_review"
            if check.ambiguous:
                status = "needs_review"
                problems.append(f"event「{item.title}」的引文定位不唯一")
            if not _declared(item, "fact_type"):
                status = "needs_review"
                problems.append(
                    f"event「{item.title}」未给出 fact_type，已按 unknown 处理"
                )
            if not refs:
                problems.append(f"event「{item.title}」的引文无法在原文定位")
            events.append(
                EventRecord(
                    event_id=f"{chunk_id}_e{i:03d}",
                    order_in_chapter=i,
                    title=item.title,
                    summary=item.summary,
                    participants=list(item.participants),
                    location=item.location,
                    fact_type=item.fact_type,
                    source_refs=refs,
                    review_status=status,
                    **common,
                )
            )

        relations: list[RelationRecord] = []
        for i, item in enumerate(raw.relations):
            refs, check = resolve(item.quote)
            status = "accepted" if refs else "needs_review"
            if check.ambiguous:
                status = "needs_review"
                problems.append(
                    f"relation「{item.from_entity}→{item.to_entity}」的引文定位不唯一"
                )
            if not refs:
                problems.append(
                    f"relation「{item.from_entity}→{item.to_entity}」的引文无法在原文定位"
                )
            relations.append(
                RelationRecord(
                    relation_id=f"{chunk_id}_r{i:03d}",
                    from_entity=item.from_entity,
                    to_entity=item.to_entity,
                    relation=item.relation,
                    source_refs=refs,
                    review_status=status,
                    **common,
                )
            )

        return ChunkExtraction(
            chunk_id=chunk_id,
            chapter_id=chunk.chapter_id,
            source_id=chunk.source_id,
            chapter_index=self._global_order.get(chunk.chapter_id, chapter.index),
            chapter_label=self.chapter_label_of(chapter),
            chapter_title=chapter.title.strip(),  # 只存标题本身，卷名与"第N章" 由展示层拼
            summary=raw.summary,
            mentions=mentions,
            facts=facts,
            events=events,
            relations=relations,
            evidence_total=located_total,
            evidence_located=located_ok,
            evidence_ambiguous=ambiguous_total,
            problems=problems,
        )

    def chapter_label_of(self, chapter) -> str:
        """章节的展示标签，多卷时带上卷名，避免"第1章"出现三次。"""
        local = f"第{chapter.number}{chapter.level}" if chapter.level != "段" else f"第{chapter.number}段"
        volume = self._source_names.get(chapter.source_id, "")
        multi = len(self.manifest.sources) > 1
        return f"{volume} {local} {chapter.title}".strip() if multi else f"{local} {chapter.title}".strip()

    def output_path(self, chunk_id: str) -> Path:
        return self.out_dir / f"{chunk_id}.json"


class ExtractionRunResult:
    def __init__(self, run_dir: Path, index: dict) -> None:
        self.run_dir = run_dir
        self.index = index

    @property
    def done(self) -> list[str]:
        return self.index["done"]

    @property
    def failed(self) -> dict[str, str]:
        return self.index["failed"]

    @property
    def skipped(self) -> list[str]:
        return self.index["skipped"]

    @property
    def ok(self) -> bool:
        return not self.failed


def _load_index(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"done": [], "failed": {}, "skipped": [], "updated_at": ""}


def run_extraction(
    config: config_module.Config,
    run_dir: str | Path,
    provider: Provider,
    *,
    resume: bool | None = None,
    limit: int | None = None,
    log=None,
) -> ExtractionRunResult:
    """对 manifest 里所有分块跑抽取，逐块落盘以便随时中断续跑。"""
    runner = ExtractionRunner(config, run_dir, provider, log=log)
    resume = config.pipeline.resume if resume is None else resume

    chunks = sorted(runner.manifest.chunks, key=lambda c: c.index)
    if limit is not None:
        chunks = chunks[:limit]

    index = _load_index(runner.index_path) if resume else {"done": [], "failed": {}, "skipped": [], "updated_at": ""}
    done_set = set(index["done"])
    index["failed"] = {} if not resume else index["failed"]

    lock = threading.Lock()

    def checkpoint() -> None:
        index["updated_at"] = _now()
        _write_json(runner.index_path, index)

    pending: list[str] = []
    for chunk in chunks:
        if resume and chunk.chunk_id in done_set and runner.output_path(chunk.chunk_id).is_file():
            index["skipped"].append(chunk.chunk_id)
            continue
        pending.append(chunk.chunk_id)

    if log:
        log.info("待抽取 %d 块（跳过 %d 块）", len(pending), len(index["skipped"]))

    failures: dict[str, str] = {}

    def work(chunk_id: str) -> tuple[str, str | None]:
        try:
            extraction = runner.process_chunk(chunk_id)
        except MissingResponseError as exc:
            return chunk_id, f"缺少预生成响应：{exc}"
        except ExtractionError as exc:
            return chunk_id, str(exc)
        with lock:
            _write_json(runner.output_path(chunk_id), extraction.model_dump(mode="json"))
            index["done"].append(chunk_id)
        return chunk_id, None

    workers = max(1, min(config.llm.max_concurrent_requests, len(pending) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work, cid): cid for cid in pending}
        completed = 0
        for future in as_completed(futures):
            chunk_id, error = future.result()
            completed += 1
            if error:
                failures[chunk_id] = error
                if log:
                    log.error("抽取失败 %s：%s", chunk_id, error)
            with lock:
                index["failed"] = failures
                if completed % 10 == 0 or completed == len(pending):
                    checkpoint()

    index["failed"] = failures
    checkpoint()

    _write_report(runner, index)
    return ExtractionRunResult(runner.run_dir, index)


def _write_report(runner: ExtractionRunner, index: dict) -> None:
    """汇总逐块结果，产出人类可读的审计数据。"""
    totals = {
        "mentions": 0,
        "facts": 0,
        "events": 0,
        "relations": 0,
        "evidence_total": 0,
        "evidence_located": 0,
        "evidence_ambiguous": 0,
        "needs_review": 0,
    }
    per_source: dict[str, dict[str, int]] = {}

    for chunk_id in index["done"]:
        path = runner.output_path(chunk_id)
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        source_id = data["source_id"]
        bucket = per_source.setdefault(
            source_id,
            {"chunks": 0, "mentions": 0, "facts": 0, "events": 0, "relations": 0, "needs_review": 0},
        )
        bucket["chunks"] += 1
        for key in ("mentions", "facts", "events", "relations"):
            totals[key] += len(data[key])
            bucket[key] += len(data[key])
            totals["needs_review"] += sum(
                1 for item in data[key] if item["review_status"] == "needs_review"
            )
            bucket["needs_review"] += sum(
                1 for item in data[key] if item["review_status"] == "needs_review"
            )
        totals["evidence_total"] += data["evidence_total"]
        totals["evidence_located"] += data["evidence_located"]
        totals["evidence_ambiguous"] += data.get("evidence_ambiguous", 0)

    coverage = (
        totals["evidence_located"] / totals["evidence_total"]
        if totals["evidence_total"]
        else 1.0
    )
    unique = (
        (totals["evidence_located"] - totals["evidence_ambiguous"]) / totals["evidence_located"]
        if totals["evidence_located"]
        else 1.0
    )

    lines = [
        "# 分块原子事实抽取报告",
        "",
        f"- run_id：`{runner.run_dir.name}`",
        f"- 生成时间：{_now()}",
        f"- 抽取引擎：`{runner.provider.name}`",
        f"- 提示词版本：`{PROMPT_VERSION}`",
        "",
        "## 进度",
        "",
        f"- 已完成分块：{len(index['done'])}",
        f"- 本次续跑跳过：{len(index['skipped'])}",
        f"- 失败分块：{len(index['failed'])}",
        "",
        "## 抽取量",
        "",
        f"- 实体提及：{totals['mentions']}",
        f"- 原子事实：{totals['facts']}",
        f"- 事件：{totals['events']}",
        f"- 关系：{totals['relations']}",
        f"- 待人工复核：{totals['needs_review']}",
        "",
        "## 来源覆盖率（引文能否在原文定位）",
        "",
        f"- 引文总数：{totals['evidence_total']}",
        f"- 成功定位：{totals['evidence_located']}",
        f"- 定位失败：{totals['evidence_total'] - totals['evidence_located']}",
        f"- 覆盖率：**{coverage:.2%}**",
        f"- 其中**多处命中**（找到但不唯一）：{totals['evidence_ambiguous']}",
        f"- 唯一定位率：**{unique:.2%}**（= (成功定位 − 多处命中) / 成功定位）",
        "",
        "> 定位失败的条目一律标为 `needs_review`，不会作为原著事实使用。",
        "> 「覆盖率」回答「能不能找到」，「唯一定位率」回答「是不是只有一处」——",
        "> 两者都过，才谈得上这条事实的来源落实了。",
        "",
        "## 逐来源",
        "",
        "| 来源 | 分块 | 提及 | 事实 | 事件 | 关系 | 待复核 |",
        "|---|---|---|---|---|---|---|",
    ]
    for source_id, bucket in sorted(per_source.items()):
        lines.append(
            f"| {source_id} | {bucket['chunks']} | {bucket['mentions']} | {bucket['facts']} | "
            f"{bucket['events']} | {bucket['relations']} | {bucket['needs_review']} |"
        )

    if index["failed"]:
        lines += ["", "## 失败分块", ""]
        for chunk_id, reason in sorted(index["failed"].items()):
            lines.append(f"- `{chunk_id}`：{reason}")

    lines += [
        "",
        "> 本报告不含小说原文；引文保存在各分块结果文件里，仅用于来源核查。",
        "",
    ]
    (runner.run_dir / "reports" / SUMMARY_NAME).write_text("\n".join(lines), encoding="utf-8")
