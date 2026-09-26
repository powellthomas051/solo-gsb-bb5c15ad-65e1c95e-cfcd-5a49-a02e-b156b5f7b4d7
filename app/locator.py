"""引文定位：在 ``/api/assemble`` 的拼接文本中查找引文的位置。

提交与 :func:`app.assembler.assemble` 相同的有序 segments 与一段引文 quote，
先复用其拼接得到拼接文本与逐字来源（沿用段数/长度限制与续接失败规则），再把
引文与拼接文本的**任意非空连续区间**比较，按逐字编辑代价取最优区间：

- 相同字代价 0；
- 任一侧为 ``?``（未辨认字）的字符对代价 0；
- 替换（双方均为已知且不同）、插入、删除各代价 1。

区间起点、终点均自由（区间前的拼接文本前缀、引文消耗完后的区间后缀不产生
删除/插入代价），但引文必须完全消耗、区间至少包含一个拼接字符。

- 最小代价不超过 :data:`MAX_COST`（2）且区间唯一：返回该左闭右开区间、
  原文片段、代价与该区间的逐字来源；
- 最小代价由多个**不同区间**并列取得：抛出 :class:`QuoteTieError`，
  携带全部并列区间；
- 最小代价大于 2：抛出 :class:`QuoteNotFoundError`。

:func:`locate_quotes` 在此基础上处理 **2～4 段按原文顺序排列的引文**：枚举
每段引文全部代价不超过 :data:`MAX_COST` 的非空区间，再选出区间按引文顺序
排列、两两不重叠（相邻可贴合：前段 ``end`` ≤ 后段 ``start``）且总代价最低
的完整定位链；唯一最优链返回各引文区间，多个不同最优链并列抛出
:class:`QuotesTieError`（携带两条不同最优链），不存在完整链抛出
:class:`QuotesNotFoundError`。

本模块只做定位，绝不改写拼接文本。
"""

from __future__ import annotations

from .aligner import WILDCARD
from .assembler import assemble

MAX_QUOTE_LEN = 80   # 单段引文最大长度
MIN_QUOTES = 2       # 多引文定位的引文段数下限
MAX_QUOTES = 4       # 多引文定位的引文段数上限
MAX_COST = 2         # 仅接受最小代价不超过 2 的区间
_INF = 10 ** 9


class QuoteNotFoundError(ValueError):
    """拼接文本中不存在代价不超过 :data:`MAX_COST` 的区间。"""


class QuoteTieError(ValueError):
    """最小代价由多个不同区间并列取得，无法唯一定位。"""

    def __init__(self, cost: int, hits: list[dict]):
        self.cost = cost
        self.hits = hits
        super().__init__(
            f"引文在拼接文本中有 {len(hits)} 个不同区间以最小代价 {cost} 并列，"
            "无法唯一定位"
        )


class QuotesNotFoundError(ValueError):
    """多段引文不存在完整定位链（某段无合格区间，或区间无法按序不重叠接入）。"""


class QuotesTieError(ValueError):
    """总代价最低的完整定位链由多个不同链并列取得，无法唯一确定。"""

    def __init__(self, cost: int, chains: list[list[dict]]):
        self.cost = cost
        self.chains = chains
        super().__init__(
            f"{len(chains[0])} 段引文在拼接文本中有多个不同定位链以最低总代价 "
            f"{cost} 并列，无法唯一确定"
        )


def _pair_cost(a: str, b: str) -> int:
    """单对字符的代价：相同字或任一侧为 ``?`` 代价 0，否则替换代价 1。"""
    if a == WILDCARD or b == WILDCARD:
        return 0
    return 0 if a == b else 1


def _forward_costs(text: str, quote: str) -> list[list[int]]:
    """半全局编辑代价 DP（区间起点自由、引文必须完全消耗、区间非空）。

    求引文与任意非空拼接区间的最小逐字编辑代价。第 0 行 ``f[0][j] = 0``
    表示“尚未开始消耗引文、区间起点待定”，故字符对转移
    ``f[i-1][j-1] + pc`` 在 ``i = 1`` 时自然覆盖“区间自任意 ``j`` 起步、
    前面的引文字全部删除”；终点取 ``f[m][j]``（``j >= 1``）表示引文已
    完全消耗，区间在 ``j`` 结束（其后的拼接字不参与、不产生插入代价）。

    注意：此处不能使用 ``|j - i|`` 带状裁剪——最优路径可能因前导删除临时
    越带后再回到带内（带状只适用于固定长度片段的 :func:`_edit_cost`）。
    """
    m, n = len(quote), len(text)
    f = [[_INF] * (n + 1) for _ in range(m + 1)]
    for j in range(n + 1):
        f[0][j] = 0
    for i in range(1, m + 1):
        f[i][0] = i
        for j in range(1, n + 1):
            pc = _pair_cost(quote[i - 1], text[j - 1])
            f[i][j] = min(
                f[i - 1][j - 1] + pc,   # 字符对（i=1 时即区间自此起步）
                f[i][j - 1] + 1,        # 区间再纳入一个拼接字（插入）
                f[i - 1][j] + 1,        # 删除一个引文字，区间不变
            )
    return f


def _edit_cost(quote: str, fragment: str, cap: int) -> int:
    """引文与固定区间片段之间的逐字编辑代价（全填满 DP，无自由端）。

    只计算 ``|j - i| <= cap`` 的带状区域；实际代价超过 ``cap`` 时返回
    某个大于 ``cap`` 的值即可（调用方只区分“是否等于最优代价”）。
    """
    n = len(fragment)
    row = [_INF] * (n + 1)
    for j in range(min(n, cap) + 1):
        row[j] = j
    for i, qc in enumerate(quote, start=1):
        nxt = [_INF] * (n + 1)
        if i <= cap:
            nxt[0] = i
        for j in range(max(1, i - cap), min(n, i + cap) + 1):
            nxt[j] = min(
                row[j] + 1,                  # 删除一个引文字
                nxt[j - 1] + 1,              # 插入一个区间字
                row[j - 1] + _pair_cost(qc, fragment[j - 1]),  # 字符对
            )
        row = nxt
    return row[n]


def _enumerate_candidate_intervals(
    text: str, quote: str, cap: int
) -> list[tuple[int, int, int]]:
    """枚举代价不超过 ``cap`` 的全部非空区间。

    返回 ``[(start, end, cost), ...]``，按 ``(start, end)`` 升序。对每个
    起点 ``s`` 做一次半全局编辑代价 DP：第 0 行全为 0（区间起点自由，
    ``s`` 之前的拼接字不参与），递推至 ``f[m][j]`` 即引文完全消耗于
    ``text[s:j]`` 的最小编辑代价，一次递推即可枚举该起点下全部终点。

    带外格子代价恒大于 ``cap``：任一从 (0,0) 到 (i,j) 的路径长度差
    |i−(j−s)| 必须由插入/删除弥补，而插入、删除各计 1，故代价
    ≥ |i−(j−s)|；只需计算 |i−(j−s)| ≤ cap 的带状区域，整体
    O(n·m·cap)。
    """
    m, n = len(quote), len(text)
    min_len, max_len = max(1, m - cap), min(n, m + cap)
    candidates: list[tuple[int, int, int]] = []
    for s in range(n):
        f = [0] * (m + 1)  # j = s（区间空）：删除 i 个引文字代价 i，
        for i in range(1, m + 1):  # 但 i > cap 时必超门槛，统一以 _INF 计
            f[i] = i if i <= cap else _INF
        upper = min(n, s + max_len)
        for j in range(s + 1, upper + 1):
            window_len = j - s
            nxt = [_INF] * (m + 1)
            if window_len <= cap:
                nxt[0] = window_len
            lo = max(1, window_len - cap)
            hi = min(m, window_len + cap)
            tc = text[j - 1]
            for i in range(lo, hi + 1):
                nxt[i] = min(
                    f[i] + 1,                              # 区间再纳入一个字（插入）
                    nxt[i - 1] + 1,                        # 删除一个引文字
                    f[i - 1] + _pair_cost(quote[i - 1], tc),
                )
            f = nxt
            if window_len >= min_len and f[m] <= cap:
                candidates.append((s, j, f[m]))
    return candidates


def _merge_chain_reps(
    a: list[list[tuple]], b: list[list[tuple]]
) -> list[list[tuple]]:
    """合并两组（各至多两条、内部按区间字典序排列）代表链。

    去重后保留字典序最小的至多两条不同链。
    """
    seen: set[tuple[tuple[int, int], ...]] = set()
    unique: list[list[tuple]] = []
    for chain in (*a, *b):
        key = tuple((s, e) for s, e, _ in chain)
        if key not in seen:
            seen.add(key)
            unique.append(chain)
    unique.sort(key=lambda ch: [(s, e) for s, e, _ in ch])
    return unique[:2]


def _locate_chain(
    candidate_layers: list[list[tuple[int, int, int]]],
) -> tuple[int, list[list[tuple[int, int, int]]]] | None:
    """在各段引文的合格区间候选中求按序不重叠、总代价最低的完整定位链。

    ``candidate_layers[k]`` 为第 k 段引文全部代价 ≤ :data:`MAX_COST` 的
    ``(start, end, cost)`` 候选，按 ``(start, end)`` 升序。链要求
    前段 ``end`` ≤ 后段 ``start``（相邻可贴合，不共享字即不算重叠）。

    动态规划：每个候选状态记录以该区间收尾的最低前缀总代价，以及取得该
    代价的字典序最小的至多两条不同前缀链；上一段候选按 ``end`` 排序，随
    当前候选起点递增做扫描即可维护“``end`` ≤ 当前起点”的最低代价集合。

    返回 ``(最低总代价, [至多两条不同最优链])``；不存在完整链返回 ``None``。
    """
    # 第 0 段：无前驱约束，每个候选自成一条前缀链
    states: list[dict | None] = [
        {"total": cost, "chains": [[(s, e, cost)]]}
        for s, e, cost in candidate_layers[0]
    ]

    # 逐层 DP：上一段候选按 end 排序，随当前候选起点递增扫描
    prev_layer = candidate_layers[0]
    prev_states = states
    for layer in candidate_layers[1:]:
        # 上一段候选按 end 排序，供扫描维护 end <= 当前 start 的集合
        order = sorted(range(len(prev_layer)), key=lambda k: prev_layer[k][1])
        pointer = 0
        run_best = _INF
        run_chains: list[list[tuple]] = []
        new_states: list[dict | None] = []
        for s, e, cost in layer:  # layer 已按 start（再按 end）升序
            while pointer < len(order) and prev_layer[order[pointer]][1] <= s:
                prev = prev_states[order[pointer]]
                pointer += 1
                if prev is None:
                    continue
                if prev["total"] < run_best:
                    run_best = prev["total"]
                    run_chains = [list(ch) for ch in prev["chains"]]
                elif prev["total"] == run_best:
                    run_chains = _merge_chain_reps(
                        run_chains, prev["chains"]
                    )
            if not run_chains:
                new_states.append(None)  # 该候选无法接入任何完整前缀链
                continue
            chains = [
                [*chain, (s, e, cost)]
                for chain in run_chains[:2]
            ]
            new_states.append({"total": run_best + cost, "chains": chains})
        prev_layer = layer
        prev_states = new_states

    best = _INF
    best_chains: list[list[tuple]] = []
    for state in prev_states:
        if state is None:
            continue
        if state["total"] < best:
            best = state["total"]
            best_chains = [list(ch) for ch in state["chains"]]
        elif state["total"] == best:
            best_chains = _merge_chain_reps(best_chains, state["chains"])
    if best == _INF:
        return None
    return best, best_chains


def _enumerate_hits(text: str, quote: str, cap: int) -> tuple[int, list[tuple[int, int]]]:
    """枚举全部最优区间，返回 ``(最小代价, [(start, end), ...])``。

    先用正向半全局 DP 求出最小代价；超过 ``cap`` 时直接返回（无合格
    区间）。否则枚举取得该代价的全部不同区间：最优对齐若含前导/后导空缺列，
    删去这些空缺列不增加代价，故必存在一个不含前后导空缺列的等价最优对齐——
    其中插入列数与删除列数之差即区间长度与引文长度之差，而插入数、删除数均
    不超过总代价，故最优区间长度必落在 ``len(quote) ± best`` 之内。
    """
    m = len(quote)
    f = _forward_costs(text, quote)
    best = min(f[m][j] for j in range(1, len(text) + 1))
    if best > cap:
        return best, []

    candidates = _enumerate_candidate_intervals(text, quote, best)
    intervals = [(s, e) for s, e, cost in candidates if cost == best]
    return best, intervals


def locate_quote(segments: list[str], quote: str) -> dict:
    """在 2～5 段转写的拼接文本中定位引文。

    返回唯一命中时的 ``{"text", "quote", "start", "end", "fragment",
    "cost", "sources"}``；拼接阶段失败原样抛出
    :class:`~app.assembler.AssemblyError`，无合格区间抛出
    :class:`QuoteNotFoundError`，多区间并列抛出 :class:`QuoteTieError`。
    """
    if not 1 <= len(quote) <= MAX_QUOTE_LEN:
        raise ValueError(f"引文长度需为 1～{MAX_QUOTE_LEN} 字")

    result = assemble(segments)
    text, sources = result["text"], result["sources"]

    best, intervals = _enumerate_hits(text, quote, MAX_COST)
    if best > MAX_COST:
        raise QuoteNotFoundError(
            f"引文（{len(quote)} 字）在拼接文本中最接近区间的代价为 {best}，"
            f"超过 {MAX_COST}，无合格区间"
        )

    def make_hit(start: int, end: int) -> dict:
        return {
            "start": start,
            "end": end,
            "fragment": text[start:end],
            "cost": best,
            "sources": [list(src) for src in sources[start:end]],
        }

    hits = [make_hit(s, e) for s, e in intervals]
    if len(hits) > 1:
        raise QuoteTieError(best, hits)

    return {"text": text, "quote": quote, **hits[0]}


def locate_quotes(segments: list[str], quotes: list[str]) -> dict:
    """在 2～5 段转写的拼接文本中按序定位 2～4 段引文。

    各引文（1～80 字）按**原文顺序**给出；先复用 :func:`assemble` 得到拼接
    文本与逐字来源（失败原样抛出 :class:`~app.assembler.AssemblyError`），
    再枚举每段引文全部代价不超过 :data:`MAX_COST` 的非空区间，选出区间按
    引文顺序排列、两两不重叠（前段 ``end`` ≤ 后段 ``start``）且总代价最低
    的完整定位链：

    - 唯一最优链：返回 ``{"text", "quotes", "total_cost", "hits"}``，
      ``hits`` 与 quotes 等长、等序，各带区间、原文片段、该段代价与 sources；
    - 多个不同最优链并列：抛出 :class:`QuotesTieError`，携带两条不同最优链；
    - 某段引文无合格区间、或合格区间无法按序接入完整链：抛出
      :class:`QuotesNotFoundError`。
    """
    if not MIN_QUOTES <= len(quotes) <= MAX_QUOTES:
        raise ValueError(f"引文段数需为 {MIN_QUOTES}～{MAX_QUOTES} 段")
    for idx, quote in enumerate(quotes):
        if not 1 <= len(quote) <= MAX_QUOTE_LEN:
            raise ValueError(
                f"第 {idx + 1} 段引文长度需为 1～{MAX_QUOTE_LEN} 字"
            )

    result = assemble(segments)
    text, sources = result["text"], result["sources"]

    candidate_layers: list[list[tuple[int, int, int]]] = []
    for idx, quote in enumerate(quotes):
        f = _forward_costs(text, quote)
        floor = min(f[len(quote)][j] for j in range(1, len(text) + 1))
        if floor > MAX_COST:
            raise QuotesNotFoundError(
                f"第 {idx + 1} 段引文（{len(quote)} 字）在拼接文本中最接近区间的"
                f"代价为 {floor}，超过 {MAX_COST}，无完整定位链"
            )
        candidates = _enumerate_candidate_intervals(text, quote, MAX_COST)
        if not candidates:
            raise QuotesNotFoundError(
                f"第 {idx + 1} 段引文在拼接文本中没有代价不超过 {MAX_COST} 的区间，"
                "无完整定位链"
            )
        candidate_layers.append(candidates)

    solved = _locate_chain(candidate_layers)
    if solved is None:
        raise QuotesNotFoundError(
            "各段引文虽有代价不超过 "
            f"{MAX_COST} 的区间，但无法按原文顺序选出互不重叠的完整定位链"
        )
    total_cost, chains = solved

    def make_chain(chain: list[tuple[int, int, int]]) -> list[dict]:
        return [
            {
                "start": s,
                "end": e,
                "fragment": text[s:e],
                "cost": cost,
                "sources": [list(src) for src in sources[s:e]],
            }
            for s, e, cost in chain
        ]

    if len(chains) > 1:
        raise QuotesTieError(total_cost, [make_chain(ch) for ch in chains[:2]])

    return {
        "text": text,
        "quotes": list(quotes),
        "total_cost": total_cost,
        "hits": make_chain(chains[0]),
    }
