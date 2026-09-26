"""未排序残页转写的阅读顺序穷举。

对 2～4 段未排序转写穷举全部排列（至多 4! = 24 种），逐个顺序复用
:func:`app.assembler.merge_once` 的单步对齐：

- 每一步把**当前拼接文本**作为左段、**下一原段**作为右段交给现有对齐逻辑，
  沿用 ``/api/assemble`` 的续接门槛（最高对齐得分 > 0 且至少 2 对相同已知字）；
- 累计各步对齐得分作为该完整顺序的总分（不是原段两两相似度的排序）；
- 某一步不满足门槛即废弃该顺序，继续尝试其余排列。

取累计得分最高的完整顺序；最高分并列时抛出 :class:`OrderTieError`，携带
全部并列顺序；没有任何完整顺序时抛出 :class:`NoCompleteOrderError`。
来源标记沿用 ``/api/assemble`` 的拼接/来源规则，段序号一律记为**原始输入下标**。
"""

from __future__ import annotations

from itertools import permutations

from .assembler import AssemblyError, merge_once

MIN_SEGMENTS = 2
MAX_SEGMENTS = 4
MAX_SEGMENT_LEN = 100
MAX_TOTAL_LEN = 240


class NoCompleteOrderError(ValueError):
    """所有排列都无法通过续接门槛，不存在完整阅读顺序。"""


class OrderTieError(ValueError):
    """最高分完整顺序并列。"""

    def __init__(self, score: int, tied: list[dict]):
        self.score = score
        self.tied = tied
        super().__init__(
            f"最高累计得分 {score} 的完整顺序有 {len(tied)} 个并列，无法唯一确定阅读顺序"
        )


def _run_order(segments: list[str], order: tuple[int, ...]) -> dict | None:
    """按 ``order``（原始下标排列）逐段拼接，返回完整结果；中途断链返回 None。

    结果形如 ``{"order": ..., "score": 累计得分, "text": ..., "sources": ...}``，
    来源中的段序号即原始输入下标。
    """
    first = order[0]
    text = segments[first]
    sources: list[list[dict]] = [
        [{"segment": first, "pos": p}] for p in range(len(text))
    ]
    total = 0
    for orig_idx in order[1:]:
        try:
            text, sources, step_score = merge_once(
                text, sources, segments[orig_idx], orig_idx
            )
        except AssemblyError:
            return None  # 该顺序在此处断链，废弃
        total += step_score
    return {"order": list(order), "score": total, "text": text, "sources": sources}


def determine_order(segments: list[str]) -> dict:
    """穷举可行阅读顺序，返回累计得分最高的完整顺序结果。

    - 最高分唯一：返回该顺序的 ``{"order", "score", "text", "sources"}``；
    - 最高分并列：抛出 :class:`OrderTieError`（``tied`` 为全部并列结果，按下标
      顺序字典序排列）；
    - 无完整顺序：抛出 :class:`NoCompleteOrderError`。
    """
    if not (MIN_SEGMENTS <= len(segments) <= MAX_SEGMENTS):
        raise ValueError(f"需要 {MIN_SEGMENTS}～{MAX_SEGMENTS} 段转写")

    complete: list[dict] = []
    for order in permutations(range(len(segments))):
        result = _run_order(segments, order)
        if result is not None:
            complete.append(result)

    if not complete:
        raise NoCompleteOrderError(
            "没有任何排列能通过续接门槛（每步最高对齐得分 > 0 且至少 2 对相同已知字），"
            "无法确定完整阅读顺序"
        )

    top = max(r["score"] for r in complete)
    tied = sorted(
        (r for r in complete if r["score"] == top),
        key=lambda r: r["order"],
    )
    if len(tied) > 1:
        raise OrderTieError(top, tied)
    return tied[0]
