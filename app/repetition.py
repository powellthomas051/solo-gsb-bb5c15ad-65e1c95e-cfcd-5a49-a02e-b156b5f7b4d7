"""重复抄写发现：在 ``/api/assemble`` 的拼接文本中查找两处互不重叠的重复区间。

提交与 :func:`app.assembler.assemble` 相同的有序 segments，先复用其拼接得到
拼接文本与逐字来源（沿用段数/长度限制与续接失败规则），再在**同一份拼接
文本**内寻找两个互不重叠的等长连续区间：

- 逐字**兼容**：对应位置的两个字相同，或任一字为 ``?``（未辨认字）；
- 区间长度至少 :data:`MIN_LENGTH`（6）；
- 区间内至少 :data:`MIN_KNOWN_EQUAL`（4）个位置是两侧皆为已知字且相同
  （``?`` 配对不计入已知相同位）。

选择规则：先取**长度最长**的区间对；长度相同时取**已知相同位更多**者；
再相同则按**两起点升序**（``(first.start, second.start)``）取首对。两区间
互不重叠并允许贴合（前段 ``end`` ≤ 后段 ``start``，不共享字即不算重叠）。

找到时返回拼接文本与两个左闭右开区间（各带原文与逐字 sources）；无合格
重复时 ``repeat`` 为 ``None``。

实现：区间等长且逐字配对，一对候选对应字符比较矩阵的一条正对角
（``j - i = d``）上的一段。逐对角扫描把连续兼容位置切成 run；互不重叠
要求窗口长度不超过对角偏移量 ``d``，故 run 内最长可行窗口为
``w = min(run_len, d)``——任一更短合格窗口都可在 run 内扩成包含它的
``w`` 长窗口（已知相同位单调不减），故每段 run 只需考虑长度为 ``w`` 的
窗口，以滑动窗口取已知相同位最多、起点最小者。全部对角合计 O(n²)。

本模块只做发现，绝不改写拼接文本。
"""

from __future__ import annotations

from .aligner import WILDCARD
from .assembler import assemble

MIN_LENGTH = 6        # 重复区间最短长度
MIN_KNOWN_EQUAL = 4   # 重复区间内至少的已知相同位数


def _compatible(a: str, b: str) -> bool:
    """两字是否兼容：相同，或任一侧为 ``?``。"""
    return a == WILDCARD or b == WILDCARD or a == b


def _known_equal(text: str, i: int, d: int) -> int:
    """对角位置 (i, i+d) 是否两侧皆为已知字且相同。"""
    a, b = text[i], text[i + d]
    return 1 if a != WILDCARD and b != WILDCARD and a == b else 0


def _best_window_in_run(
    text: str, run_start: int, run_len: int, d: int
) -> tuple[int, int, int] | None:
    """在一条兼容 run 内取该 run 的最优长度为 ``w = min(run_len, d)`` 的窗口。

    返回 ``(窗口长度 w, 已知相同位数, 窗口起点 i)``；``w`` 不足
    :data:`MIN_LENGTH`、或最长窗口的已知相同位不足
    :data:`MIN_KNOWN_EQUAL` 时返回 ``None``（更短窗口不可能反超，见模块
    说明）。同已知相同位取起点最小者：滑动窗口随起点推进，只在严格更大
    时更新即可。
    """
    w = min(run_len, d)
    if w < MIN_LENGTH:
        return None

    count = sum(_known_equal(text, run_start + k, d) for k in range(w))
    best_start, best_count = run_start, count
    for off in range(1, run_len - w + 1):
        count -= _known_equal(text, run_start + off - 1, d)
        count += _known_equal(text, run_start + off + w - 1, d)
        if count > best_count:
            best_start, best_count = run_start + off, count

    if best_count < MIN_KNOWN_EQUAL:
        return None
    return w, best_count, best_start


def find_repetition(segments: list[str]) -> dict:
    """在 2～5 段转写的拼接文本中发现重复抄写区间。

    返回 ``{"text", "repeat"}``；``repeat`` 为 ``None`` 或
    ``{"first": 区间, "second": 区间}``，区间按起点升序排列，各含
    ``start``/``end``/``fragment``/``sources``。拼接阶段失败原样抛出
    :class:`~app.assembler.AssemblyError`。
    """
    result = assemble(segments)
    text, sources = result["text"], result["sources"]
    n = len(text)

    # 选择键：长度最长 → 已知相同位最多 → (一起点, 二起点) 升序；
    # 前两项取负，统一以元组最小者为最优
    best_key: tuple[int, int, int, int] | None = None
    best_i = best_d = best_w = 0

    for d in range(1, n):
        limit = n - d
        i = 0
        while i < limit:
            if not _compatible(text[i], text[i + d]):
                i += 1
                continue
            run_start = i
            while i < limit and _compatible(text[i], text[i + d]):
                i += 1
            hit = _best_window_in_run(text, run_start, i - run_start, d)
            if hit is None:
                continue
            w, known, start = hit
            key = (-w, -known, start, start + d)
            if best_key is None or key < best_key:
                best_key, best_i, best_d, best_w = key, start, d, w

    if best_key is None:
        return {"text": text, "repeat": None}

    def interval(start: int) -> dict:
        return {
            "start": start,
            "end": start + best_w,
            "fragment": text[start : start + best_w],
            "sources": [list(src) for src in sources[start : start + best_w]],
        }

    first_start, second_start = best_i, best_i + best_d
    return {
        "text": text,
        "repeat": {
            "first": interval(first_start),
            "second": interval(second_start),
        },
    }
