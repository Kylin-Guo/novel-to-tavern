"""原文读取与指纹。

小说原文是**只读**来源：本模块只读取、只计算，绝不改写。
规范化后的内容一律写到 run 目录下的新文件。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from pydantic import BaseModel

#: 支持的输入后缀。DOCX/EPUB/PDF 属于后续增量，MVP 不做。
SUPPORTED_SUFFIXES = (".txt", ".md")


class SourceReadError(RuntimeError):
    """文件不存在、后缀不支持或无法按指定编码解码。"""


class SourceText(BaseModel):
    """一次读取的结果。`lines` 保留行尾换行符，便于无损重组。"""

    model_config = {"arbitrary_types_allowed": True}

    source_id: str
    path: str
    filename: str
    sha256: str
    size_bytes: int
    encoding: str
    newline_style: str
    total_lines: int
    total_chars: int
    text: str
    lines: list[str]


def sha256_of(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _detect_newline_style(data: bytes) -> str:
    crlf = data.count(b"\r\n")
    lf = data.count(b"\n") - crlf
    cr = data.count(b"\r") - crlf
    present = [name for name, count in (("crlf", crlf), ("lf", lf), ("cr", cr)) if count]
    if not present:
        return "none"
    if len(present) > 1:
        return "mixed"
    return present[0]


_UNSAFE_ID_CHARS = re.compile(r"[^\w一-鿿぀-ヿ-]+", re.UNICODE)


def slugify_source_id(name: str) -> str:
    """把文件名规整成可用作 ID 的字符串。

    中文保留；全角冒号、空格、括号等会被 `source_id`/`chunk_id` 带进文件名与日志，
    统一替换成 `-`，避免后续按 ID 拼路径时出问题。
    """
    slug = _UNSAFE_ID_CHARS.sub("-", name).strip("-")
    return slug or "source"


def read_source(path: str | Path, *, encoding: str = "utf-8", source_id: str | None = None) -> SourceText:
    """读取一个原文文件。

    `lines` 用 `str.splitlines(keepends=True)` 切分，保证
    `"".join(lines) == text` —— 这是无损重组测试的基础。
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise SourceReadError(f"找不到原文文件：{file_path}")
    if file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise SourceReadError(
            f"暂不支持的后缀 {file_path.suffix!r}；Phase 1 只支持 {list(SUPPORTED_SUFFIXES)}。"
        )

    raw = file_path.read_bytes()
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError as exc:
        raise SourceReadError(f"{file_path} 无法按 {encoding} 解码：{exc}") from exc

    lines = text.splitlines(keepends=True)
    return SourceText(
        source_id=source_id or slugify_source_id(file_path.stem),
        path=str(file_path),
        filename=file_path.name,
        sha256=sha256_of(raw),
        size_bytes=len(raw),
        encoding=encoding,
        newline_style=_detect_newline_style(raw),
        total_lines=len(lines),
        total_chars=len(text),
        text=text,
        lines=lines,
    )


def line_offsets(lines: list[str]) -> list[int]:
    """每行起始字符 offset，长度比 `lines` 多 1（末位为总长）。"""
    offsets = [0]
    running = 0
    for line in lines:
        running += len(line)
        offsets.append(running)
    return offsets


def reassemble(lines: list[str]) -> str:
    """把行列表拼回原文。用于无损性断言。"""
    return "".join(lines)
