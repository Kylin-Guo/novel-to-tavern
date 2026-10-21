#!/usr/bin/env bash
# n2t_pipeline.sh — 按序执行 novel-to-tavern 管线各阶段。
#
# 用法（在仓库根目录执行）：
#   scripts/n2t_pipeline.sh <run_id> [选项]
#
#   --require-responses DIR  ingest 后核对 DIR 下的预生成响应覆盖率；
#                            有缺失时打印缺失清单并退出（补齐后加 --skip-ingest 续跑）
#   --skip-ingest           跳过 ingest（已跑过、只补响应的场景）
#   --with-verify           在 timeline 之后追加 n2t verify（需要逐条判定响应）
#   --start-chapter N       导出时追加 --start-chapter N（结构性无剧透档）
#
# 前置条件：.venv 已建好且 pip install -e . 完成、config/config.yaml 已就绪
# （n2t config-check 会先跑，配置有问题在第一步就停下）。
# 中断后用同一 run id 重跑本脚本即可断点续跑（pipeline.resume 默认为 true）。
set -euo pipefail

usage() { sed -n '2,16p' "$0"; exit "${1:-1}"; }

[[ $# -ge 1 ]] || usage
RUN_ID="$1"; shift
WITH_VERIFY=0
SKIP_INGEST=0
REQUIRE_RESPONSES=""
START_CHAPTER=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-verify) WITH_VERIFY=1; shift ;;
    --skip-ingest) SKIP_INGEST=1; shift ;;
    --require-responses) [[ $# -ge 2 ]] || usage; REQUIRE_RESPONSES="$2"; shift 2 ;;
    --start-chapter) [[ $# -ge 2 ]] || usage; START_CHAPTER="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "未知参数：$1" >&2; usage ;;
  esac
done

N2T=".venv/bin/n2t"
if [[ ! -x "$N2T" ]]; then
  echo "找不到 $N2T —— 请在仓库根目录执行本脚本，并先完成：" >&2
  echo "  python3 -m venv .venv && .venv/bin/python -m pip install -e \".[dev]\"" >&2
  exit 1
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

stage() { printf '\n========== %s ==========\n' "$*"; }

stage "0/6 config-check"
"$N2T" config-check

if [[ "$SKIP_INGEST" -eq 1 ]]; then
  printf '\n========== 1/6 ingest（跳过：--skip-ingest） ==========\n'
else
  stage "1/6 ingest（章节索引与分块）"
  "$N2T" ingest --run-id "$RUN_ID"
fi

if [[ -n "$REQUIRE_RESPONSES" ]]; then
  stage "1.5/6 预生成响应覆盖检查"
  if ! python3 "$SCRIPT_DIR/check_responses.py" "runs/$RUN_ID" "$REQUIRE_RESPONSES"; then
    echo "按缺失清单为每个 chunk_id 生成 <chunk_id>.json（schema：src/novel_to_tavern/extract/schema.py），" >&2
    echo "然后重跑：$0 $RUN_ID --skip-ingest --require-responses $REQUIRE_RESPONSES ..." >&2
    exit 1
  fi
fi

stage "2/6 extract（分块原子事实提取）"
"$N2T" extract --run-id "$RUN_ID"

stage "3/6 resolve（实体消歧与角色档案）"
"$N2T" resolve --run-id "$RUN_ID"

stage "4/6 timeline（时间线 · 知识边界 · 世界书规划）"
"$N2T" timeline --run-id "$RUN_ID"

if [[ "$WITH_VERIFY" -eq 1 ]]; then
  stage "5/6 verify（语义支持校验）"
  "$N2T" verify --run-id "$RUN_ID"
else
  printf '\n========== 5/6 verify（跳过；需要时加 --with-verify） ==========\n'
fi

stage "6/6 export（角色卡与世界书）"
if [[ -n "$START_CHAPTER" ]]; then
  "$N2T" export --run-id "$RUN_ID" --start-chapter "$START_CHAPTER"
else
  "$N2T" export --run-id "$RUN_ID"
fi

printf '\n完成。主卡：runs/%s/exports/world_simulator_v2.json\n' "$RUN_ID"
printf '用 scripts/check_card.py 做独立校验并取汇报数字。\n'
