"""双版本对勘：两份拼接稿的全局逐字最小编辑对齐。

``left_segments``、``right_segments`` 各自沿用 :func:`app.assembler.assemble`
的段数/长度限制与续接规则，**分别拼接**为两份稿子（各自的逐字来源相互独立、
互不影响）。对勘返回的**版本文本**逐位置取**最早段**的原始字形：拼接过程与
逐字来源完全沿用 :func:`assemble` 的结果，仅当某位置最早段的字形为 ``?``
（前段的未辨认字被同侧后段已知字续接覆盖）时保留该 ``?``，不改写为后段的
补字——版本文本因此忠实反映各版本前段的未辨认字位置。随后对两份保留 ``?``
的版本文本做**全局**（两端固定、不允许自由端）逐字最小编辑对齐：

- 相同字、或任一侧为 ``?``（未辨认字）的字符对代价 0；
- 替换（双方皆为已知字且不同）、删除左字、插入右字各代价 1。

动态规划求最小代价及取得该代价的路径数（只区分 1 条 / 多条）；同一格有多
条同代价入边时，回溯所用对齐按 **对角 → 删除左字 → 插入右字** 的固定次序
择优，故输出确定，另以 ``ambiguous`` 标记终点是否存在多条最优路径。

实现上利用“任何路径的代价都不低于两侧已消耗字数之差”的带状下界：先以从
``|m - n|`` 起倍增的带状代价 DP 找到第一个有限代价 ``C``（``C >= G``，``G``
为全局最优），再只在 ``|i - j| <= C`` 的带内重算一遍以记录路径数与固定择优
入边——最优路径上每格都满足 ``|i - j| <= G <= C``，故该带覆盖**全部**最优
路径，代价、路径数与回溯都是精确的全局结果，又避免对整表做无谓的路径统计。

把对齐列中**连续的非零代价列**合并为差异块，每块给出两侧在各自版本文本上的
左闭右开区间、区间原文与逐字 sources（该侧在块内无字时区间为空、sources 为
空列表）；零代价列用于分块。两份稿子完全一致（或仅差 ``?``）时差异块为空、
总代价为 0。

本模块只做对勘，绝不改写任何一份拼接稿。
"""

from __future__ import annotations

from .aligner import WILDCARD
from .assembler import AssemblyError, assemble

_DIAG = 0  # 对角：左字对右字
_DEL = 1   # 删除左字（右侧空缺）
_INS = 2   # 插入右字（左侧空缺）


class EditionAssemblyError(ValueError):
    """某一侧的 segments 未通过 :func:`assemble` 的续接门槛。"""

    def __init__(self, side: str, failed_segment: int):
        self.side = side
        self.failed_segment = failed_segment
        field = "left_segments" if side == "left" else "right_segments"
        super().__init__(
            f"{field} 第 {failed_segment + 1} 段（段序号 {failed_segment}）"
            "无法与前文可靠拼接：需要最高对齐得分 > 0 且至少 2 对相同已知字"
        )


def _pair_cost(a: str, b: str) -> int:
    """单对字符的代价：相同字或任一侧为 ``?`` 代价 0，否则替换代价 1。"""
    if a == WILDCARD or b == WILDCARD:
        return 0
    return 0 if a == b else 1


def _assemble_side(side: str, segments: list[str]) -> dict:
    """拼接一侧稿子，把续接失败包装为带侧别的 :class:`EditionAssemblyError`。"""
    try:
        return assemble(segments)
    except AssemblyError as exc:
        raise EditionAssemblyError(side, exc.failed_segment) from exc


def _version_text(segments: list[str], sources: list[list[dict]]) -> str:
    """对勘用的版本文本：逐位置取**最早段**的原始字形。

    拼接（对齐、续接门槛）与逐字来源完全沿用 :func:`assemble` 的结果，不重
    新对齐；仅显示字形取各位置来源中最早段的原始字。与拼接文本的唯一差异：
    某位置最早段为 ``?``（前段的未辨认字被同侧后段已知字续接覆盖）时保留
    该 ``?``，不改写为后段的补字；其余情形（最早段已知、或各段皆为 ``?``）
    与拼接文本一致。
    """
    chars = []
    for srcs in sources:
        first = min(srcs, key=lambda s: (s["segment"], s["pos"]))
        chars.append(segments[first["segment"]][first["pos"]])
    return "".join(chars)


def _banded_cost(left: str, right: str, k: int) -> list[list[int]] | None:
    """只填 ``|i - j| <= k`` 带状区域的代价 DP。

    任何 (0,0)→(i,j) 路径的代价都不低于两侧已消耗字数之差 ``|i - j|``
    （长度差只能由各计 1 的插入/删除弥补），故带外格子不可能取得低于
    ``|i - j|`` 的代价，以一个足够大的上界占位于带外（绝不参与转移）。
    终点 (m,n) 在带内取得有限代价时返回整张代价表，否则返回 ``None``
    （最优代价超出该带所能容纳的范围，需要放宽带宽重算）。
    """
    m, n = len(left), len(right)
    inf = m + n + 1
    dp = [[inf] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = 0
    for i in range(m + 1):
        row, prev_row = dp[i], dp[i - 1] if i else None
        lc = left[i - 1] if i else ""
        lo = max(0, i - k)
        hi = min(n, i + k)
        for j in range(lo, hi + 1):
            if i == 0 and j == 0:
                continue
            best = inf
            if i and j:
                v = prev_row[j - 1] + _pair_cost(lc, right[j - 1])
                if v < best:
                    best = v
            if i:
                v = prev_row[j] + 1
                if v < best:
                    best = v
            if j:
                v = row[j - 1] + 1
                if v < best:
                    best = v
            row[j] = best
    if dp[m][n] < inf:
        return dp
    return None


def _fill_band_paths(
    left: str, right: str, k: int
) -> tuple[int, list[bytearray], list[bytearray]]:
    """在带宽 ``k`` 内重算代价，并沿转移记录路径数与固定择优入边。

    调用前须保证 ``k`` 不小于全局最优代价（最优路径上每格 ``|i - j|`` 都不
    超过该代价），此时带内覆盖全部最优路径，返回的 ``(总代价, ways, move)``
    是精确的全局结果：``ways`` 只区分 1 条 / 多条最优路径（达到 2 即封顶）；
    ``move`` 记录每格取得最小代价的固定择优入边（对角 → 删除 → 插入），供
    回溯。带外格子保持 0，不会被最优路径访问。
    """
    m, n = len(left), len(right)
    inf = m + n + 1
    dp = [[inf] * (n + 1) for _ in range(m + 1)]
    ways = [bytearray(n + 1) for _ in range(m + 1)]
    move = [bytearray(n + 1) for _ in range(m + 1)]
    dp[0][0] = 0
    ways[0][0] = 1
    for i in range(m + 1):
        row, prev_row = dp[i], dp[i - 1] if i else None
        wr, wp = ways[i], ways[i - 1] if i else None
        mr = move[i]
        lc = left[i - 1] if i else ""
        lo = max(0, i - k)
        hi = min(n, i + k)
        for j in range(lo, hi + 1):
            if i == 0 and j == 0:
                continue
            if i == 0:
                row[j] = j
                wr[j] = 1
                mr[j] = _INS
                continue
            if j == 0:
                row[j] = i
                wr[j] = 1
                mr[j] = _DEL
                continue

            c_diag = prev_row[j - 1] + _pair_cost(lc, right[j - 1])
            c_del = prev_row[j] + 1
            c_ins = row[j - 1] + 1
            best = min(c_diag, c_del, c_ins)
            row[j] = best

            count = 0
            if c_diag == best:
                count += wp[j - 1]
            if c_del == best:
                count += wp[j]
            if c_ins == best:
                count += wr[j - 1]
            wr[j] = min(2, count)

            if c_diag == best:
                mr[j] = _DIAG
            elif c_del == best:
                mr[j] = _DEL
            else:
                mr[j] = _INS

    return dp[m][n], ways, move


def _edit_alignment(left: str, right: str):
    """全局逐字最小编辑对齐。

    返回 ``(总代价, 回溯列, 终点最优路径数是否多于 1)``。回溯列为
    ``(左下标或 None, 右下标或 None, 本列代价)``，按阅读顺序排列。

    先用从 ``|m - n|`` 起倍增的带状代价 DP 找到第一个有限代价 ``C``
    （``C >= G``，``G`` 为全局最优代价），再在 ``|i - j| <= C`` 的带内重算
    一遍以取得精确的总代价、路径数与固定择优入边；回溯按 **对角 → 删除左字
    → 插入右字** 的固定次序择优，故输出确定。
    """
    m, n = len(left), len(right)

    k = abs(m - n)
    dp = None
    while dp is None:
        dp = _banded_cost(left, right, k)
        if dp is None:
            k = max(1, k * 2)
    # 带状代价必为全局最优的上界：C >= G；而最优路径上每格 |i - j| <= G <= C，
    # 故带宽 C 覆盖全部最优路径，在其内重算即得精确结果。
    band = dp[m][n]

    total, ways, move = _fill_band_paths(left, right, band)
    ambiguous = ways[m][n] > 1

    # 回溯固定择优的最优路径
    columns: list[tuple[int | None, int | None, int]] = []
    i, j = m, n
    while i > 0 or j > 0:
        if i == 0:
            mv = _INS
        elif j == 0:
            mv = _DEL
        else:
            mv = move[i][j]
        if mv == _DIAG:
            columns.append((i - 1, j - 1, _pair_cost(left[i - 1], right[j - 1])))
            i -= 1
            j -= 1
        elif mv == _DEL:
            columns.append((i - 1, None, 1))
            i -= 1
        else:
            columns.append((None, j - 1, 1))
            j -= 1
    columns.reverse()

    return total, columns, ambiguous


def compare_editions(left_segments: list[str], right_segments: list[str]) -> dict:
    """对两份各 2～5 段的转写组分别拼接后做全局逐字最小编辑对勘。

    两侧各自沿用 :func:`assemble` 的拼接与逐字来源，但返回的版本文本保留
    前段被同侧后段已知字续接覆盖的 ``?``（见 :func:`_version_text`），跨
    版本对齐即以保留 ``?`` 的文本计算。返回 ``{"left_text", "right_text",
    "total_cost", "ambiguous", "blocks"}``；任一侧拼接未通过续接门槛抛出
    :class:`EditionAssemblyError`（携带 ``side`` 与 ``failed_segment``）。
    """
    left_result = _assemble_side("left", left_segments)
    right_result = _assemble_side("right", right_segments)
    left_sources = left_result["sources"]
    right_sources = right_result["sources"]
    left = _version_text(left_segments, left_sources)
    right = _version_text(right_segments, right_sources)

    total_cost, columns, ambiguous = _edit_alignment(left, right)

    def interval(text: str, sources: list[list[dict]], s: int, e: int) -> dict:
        return {
            "start": s,
            "end": e,
            "fragment": text[s:e],
            "sources": [list(srcs) for srcs in sources[s:e]],
        }

    # 连续非零代价列合并为差异块；lp/rp 为两侧已消耗字数（当前列起点）
    blocks: list[dict] = []
    lp = rp = 0
    k = 0
    while k < len(columns):
        while k < len(columns) and columns[k][2] == 0:
            li, ri, _ = columns[k]
            if li is not None:
                lp += 1
            if ri is not None:
                rp += 1
            k += 1
        if k >= len(columns):
            break
        ls, rs = lp, rp
        while k < len(columns) and columns[k][2] != 0:
            li, ri, _ = columns[k]
            if li is not None:
                lp += 1
            if ri is not None:
                rp += 1
            k += 1
        blocks.append({
            "left": interval(left, left_sources, ls, lp),
            "right": interval(right, right_sources, rs, rp),
        })

    return {
        "left_text": left,
        "right_text": right,
        "total_cost": total_cost,
        "ambiguous": ambiguous,
        "blocks": blocks,
    }
