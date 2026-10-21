#!/usr/bin/env python3
"""check_responses.py — 核对预生成响应是否覆盖 run 的全部分块。

用法：
    python3 check_responses.py runs/<run_id> <precomputed目录>

读取 runs/<run_id>/manifest.json 的 chunks[*].chunk_id，逐一检查
<precomputed目录>/<chunk_id>.json 是否存在。n2t extract 遇到缺失文件会直接
报错中止，所以在跑 extract 之前先核对，缺哪个补哪个。只用标准库。

退出码：0 = 全覆盖；1 = 有缺失（并打印缺失清单）；2 = 用法/manifest 错误。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    run_dir = Path(argv[1])
    responses = Path(argv[2])

    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"找不到 {manifest_path} —— 先跑 n2t ingest。")
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    chunk_ids = [c["chunk_id"] for c in manifest.get("chunks", [])]
    if not chunk_ids:
        print("manifest 里没有分块 —— ingest 可能没完成，重跑 n2t ingest。")
        return 2

    missing = [cid for cid in chunk_ids if not (responses / f"{cid}.json").is_file()]
    total = len(chunk_ids)
    if missing:
        print(f"响应覆盖 {total - len(missing)}/{total}，缺 {len(missing)} 块：")
        for cid in missing:
            print(f"  - {cid}.json")
        print("补齐后重跑（加 --skip-ingest 跳过已完成的 ingest）。")
        return 1
    print(f"响应覆盖 {total}/{total}，可以跑 n2t extract。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
