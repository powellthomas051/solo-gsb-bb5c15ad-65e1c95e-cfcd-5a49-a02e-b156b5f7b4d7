"""通读证据路径：在 ``/api/assemble`` 的拼接稿区间内为逐字选原始段证据。

提交与 :func:`app.assembler.assemble` 相同的有序 segments 与拼接稿上一个
**左闭右开**区间 ``[start, end)``，复用其拼接文本与逐字来源，为区间内每个
输出字选一个来源（某原始段的某原文下标）作为该字证据：

- **证据资格**：来源原字等于该输出字，或来源原字为 ``?``（未辨认字）才可
  作为该字证据；异字来源不可用，故不是每个字都一定有证据；
- **同段连续**：连续两个字选了同一段时，所取原文下标必须**逐次加一**
  （严格 ``+1``），即同段一段路径必须覆盖该段连续的一串原文；
- **换段约束**：相邻两字从段 ``a`` 换到段 ``b``（``a != b``）时，交界
  **两侧至少各有一个字**同时携带 ``a``、``b`` 两段来源——交界**换前侧**
  （区间内交界之前的部分）存在某个字来源中既含 ``a`` 又含 ``b``，交界
  **换后侧**（区间内交界之后的部分，含交界右字）同样存在某个字同时含
  ``a``、``b``；即换段只能发生在两段来源共同覆盖区的内部，不能贴着
  共同覆盖区的边界跳入/跳出，段序号不要求递增。

为整个区间求一条覆盖全部输出字的完整证据路径，目标依次为：

1. **换段次数最少**；
2. 换段次数相同时，所选证据中原文为 ``?`` 的字数最少；
3. 仍相同时，按 ``(段序号序列, 原文下标序列)`` 的字典序取首条；

并以 :data:`ambiguous` 标记取得该最优（同换段次数、同 ``?`` 数）的完整
路径是否还有其他路径（字典序取首只决定返回哪一条，不影响该标记）。

返回区间文本、每段一条路径（路径段）在拼接稿与该段原文上的左闭右开区间、
换段交界位置与所选 ``?`` 位置。区间非法或不存在覆盖整个区间的完整路径时
抛出 :class:`TraceReadingError`，由接口层转为 422。

本模块只做证据追溯，绝不改写拼接文本。
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right

from .aligner import WILDCARD
from .assembler import AssemblyError, assemble


class TraceReadingError(ValueError):
    """区间非法，或不存在覆盖整个区间的完整证据路径。"""


def _eligible_options(
    segments: list[str],
    text: str,
    sources: list[list[dict]],
    start: int,
    end: int,
) -> list[list[tuple[int, int]]]:
    """区间每个输出字的合格证据候选 ``(段序号, 原文下标)`` 列表。

    来源原字等于输出字、或来源原字为 ``?`` 才合格；逐字来源已按
    ``(segment, pos)`` 排序，这里保持该序（供后续字典序择优）。
    """
    options: list[list[tuple[int, int]]] = []
    for j in range(start, end):
        out = text[j]
        opts = [
            (src["segment"], src["pos"])
            for src in sources[j]
            if segments[src["segment"]][src["pos"]] == out
            or segments[src["segment"]][src["pos"]] == WILDCARD
        ]
        options.append(opts)
    return options


def _joint_coverage(
    sources: list[list[dict]], n_segments: int
) -> list[list[list[int]]]:
    """每对段 ``(a, b)`` 在拼接稿中同时出现于逐字来源的位置（升序列表）。

    即某字来源中既含段 ``a`` 又含段 ``b`` 的全部拼接稿位置；供换段约束
    判定“交界两侧至少一字同时有换前、换后段来源”。``joint[a][b]`` 与
    ``joint[b][a]`` 同一份列表（无序对，存两份便于按段序号直接索引）。
    """
    present: list[set[int]] = [set() for _ in range(n_segments)]
    for pos, srcs in enumerate(sources):
        for src in srcs:
            present[src["segment"]].add(pos)
    joint: list[list[list[int]]] = [
        [[] for _ in range(n_segments)] for _ in range(n_segments)
    ]
    for a in range(n_segments):
        for b in range(a, n_segments):
            covered = sorted(present[a] & present[b])
            joint[a][b] = covered
            joint[b][a] = covered
    return joint


def _switch_allowed(
    joint: list[list[list[int]]],
    boundary: int,
    start: int,
    end: int,
    a: int,
    b: int,
) -> bool:
    """换段交界 ``boundary``（位于 ``text[boundary-1] | text[boundary]``）合法否。

    要求区间内**换前侧** ``[start, boundary)`` 与**换后侧** ``[boundary, end)``
    各至少存在一个同时携带段 ``a``、``b`` 来源的字。
    """
    covered = joint[a][b]
    # 换前侧：共同覆盖位置落在 [start, boundary)
    has_left = bisect_left(covered, boundary) > bisect_right(covered, start - 1)
    if not has_left:
        return False
    # 换后侧：共同覆盖位置落在 [boundary, end)
    has_right = bisect_left(covered, end) > bisect_left(covered, boundary)
    return has_right


def _best_path(
    segments: list[str],
    options: list[list[tuple[int, int]]],
    joint: list[list[list[int]]],
    start: int,
    end: int,
) -> tuple[int, tuple[int, ...], tuple[int, ...], bool]:
    """逐层 DP 求整个区间的最优证据路径。

    每一层（区间内一个输出字）以**收尾状态** ``(收尾段, 收尾原文下标)``
    分桶——同段续接只允许 ``原文下标 = 上一字下标 + 1``，故未来转移只依赖
    该收尾状态，与此前序列无关。每个桶只保留代价（换段次数、``?`` 数）最小
    的前缀：代价相同则保留字典序最小的完整段序号序列与原文下标序列，另以
    ``ways``（封顶 2）累计取得该代价的不同路径数。

    返回 ``(换段次数, 段序号序列, 原文下标序列, 是否存在其他同分路径)``；
    无完整路径抛出 :class:`TraceReadingError`。
    """
    # 状态：{(收尾段, 收尾原文下标): {"sw", "qm", "seg_seq", "pos_seq", "ways"}}
    states: dict[tuple[int, int], dict] = {}

    def add_state(
        key: tuple[int, int],
        sw: int,
        qm: int,
        seg_seq: tuple[int, ...],
        pos_seq: tuple[int, ...],
        ways: int,
    ) -> None:
        old = states.get(key)
        if old is None:
            states[key] = {
                "sw": sw,
                "qm": qm,
                "seg_seq": seg_seq,
                "pos_seq": pos_seq,
                "ways": ways,
            }
            return
        cost, old_cost = (sw, qm), (old["sw"], old["qm"])
        if cost < old_cost:
            old.update(sw=sw, qm=qm, seg_seq=seg_seq, pos_seq=pos_seq, ways=ways)
        elif cost == old_cost:
            # 同 (换段次数, ? 数) 的不同序列都是同分路径，路径数须累加；
            # 代表序列另取字典序更小者，供最终取首。
            old["ways"] = min(2, old["ways"] + ways)
            if (seg_seq, pos_seq) < (old["seg_seq"], old["pos_seq"]):
                old["seg_seq"] = seg_seq
                old["pos_seq"] = pos_seq
        # 代价更大的候选不参与最优路径

    # 第 0 个输出字：无前驱，每个合格证据自成一条前缀
    for seg, pos in options[0]:
        qm = 1 if segments[seg][pos] == WILDCARD else 0
        add_state((seg, pos), 0, qm, (seg,), (pos,), 1)

    # 第 1 个输出字起：同段要求原文下标逐次加一；异段要求交界两侧双覆盖
    for i in range(1, len(options)):
        prev_states = states
        states = {}
        boundary = start + i
        for (p_seg, p_pos), prev in prev_states.items():
            for seg, pos in options[i]:
                if seg == p_seg:
                    if pos != p_pos + 1:
                        continue  # 同段连续取字，原文下标必须逐次加一
                    sw = prev["sw"]
                else:
                    if not _switch_allowed(
                        joint, boundary, start, end, p_seg, seg
                    ):
                        continue
                    sw = prev["sw"] + 1
                qm = prev["qm"] + (
                    1 if segments[seg][pos] == WILDCARD else 0
                )
                add_state(
                    (seg, pos),
                    sw,
                    qm,
                    (*prev["seg_seq"], seg),
                    (*prev["pos_seq"], pos),
                    prev["ways"],
                )
        if not states:
            raise TraceReadingError(
                f"区间 [{start}, {start + len(options)}) 内第 {i + 1} 字"
                "（拼接稿下标 "
                f"{start + i}）无法在满足同段连续与换段约束的前提下接入证据路径"
            )

    global_cost = min((s["sw"], s["qm"]) for s in states.values())
    tied = [s for s in states.values() if (s["sw"], s["qm"]) == global_cost]
    best = min(tied, key=lambda s: (s["seg_seq"], s["pos_seq"]))
    ways = min(2, sum(s["ways"] for s in tied))
    return best["sw"], best["seg_seq"], best["pos_seq"], ways > 1


def trace_reading(segments: list[str], start: int, end: int) -> dict:
    """为拼接稿区间 ``[start, end)`` 求最优通读证据路径。

    返回 ``{"text", "start", "end", "interval_text", "legs",
    "switch_positions", "question_positions", "switch_count",
    "question_count", "ambiguous"}``；拼接阶段失败原样抛出
    :class:`~app.assembler.AssemblyError`，区间非法或无完整路径抛出
    :class:`TraceReadingError`。
    """
    result = assemble(segments)
    text, sources = result["text"], result["sources"]
    n = len(text)

    if type(start) is not int or type(end) is not int:
        raise TraceReadingError("区间起点、终点必须为整数")
    if start < 0 or end < 0:
        raise TraceReadingError("区间起点、终点不能为负")
    if start >= end:
        raise TraceReadingError(
            f"区间非法：左闭右开区间 [{start}, {end}) 为空，start 须小于 end"
        )
    if end > n:
        raise TraceReadingError(
            f"区间非法：终点 end={end} 超出拼接文本长度 {n}"
        )

    options = _eligible_options(segments, text, sources, start, end)
    for i, opts in enumerate(options):
        if not opts:
            raise TraceReadingError(
                f"区间 [{start}, {end}) 内第 {i + 1} 字（拼接稿下标 "
                f"{start + i}，输出字“{text[start + i]}”）没有原字等于该字"
                "或为 ? 的来源，无完整证据路径"
            )

    joint = _joint_coverage(sources, len(segments))
    switch_count, seg_seq, pos_seq, ambiguous = _best_path(
        segments, options, joint, start, end
    )

    # 按收尾段把序列切成每段一条路径（路径段），同时汇总换段交界与所选 ?
    legs: list[dict] = []
    switch_positions: list[dict] = []
    question_positions: list[dict] = []
    run_seg = seg_seq[0]
    run_begin = 0
    for i in range(1, len(seg_seq) + 1):
        if i < len(seg_seq) and seg_seq[i] == run_seg:
            continue
        # 一段路径覆盖区间下标 [run_begin, i)（拼接稿下标 start+run_begin 起）
        m_start, m_end = start + run_begin, start + i
        o_start, o_end = pos_seq[run_begin], pos_seq[i - 1] + 1
        leg_sources = [
            [{"segment": run_seg, "pos": pos_seq[k]}]
            for k in range(run_begin, i)
        ]
        original_sources = [
            [{"segment": run_seg, "pos": p}] for p in range(o_start, o_end)
        ]
        legs.append({
            "segment": run_seg,
            "merged": {
                "start": m_start,
                "end": m_end,
                "fragment": text[m_start:m_end],
                "sources": leg_sources,
            },
            "original": {
                "start": o_start,
                "end": o_end,
                "fragment": segments[run_seg][o_start:o_end],
                "sources": original_sources,
            },
        })
        for k in range(run_begin, i):
            if segments[run_seg][pos_seq[k]] == WILDCARD:
                question_positions.append({
                    "pos": start + k,
                    "segment": run_seg,
                    "original_pos": pos_seq[k],
                    "output_char": text[start + k],
                })
        if i < len(seg_seq):
            # 换段交界位于 text[start+i-1] 与 text[start+i] 之间
            switch_positions.append({
                "pos": start + i,
                "from_segment": run_seg,
                "to_segment": seg_seq[i],
            })
            run_seg = seg_seq[i]
            run_begin = i

    return {
        "text": text,
        "start": start,
        "end": end,
        "interval_text": text[start:end],
        "legs": legs,
        "switch_positions": switch_positions,
        "question_positions": question_positions,
        "switch_count": switch_count,
        "question_count": len(question_positions),
        "ambiguous": ambiguous,
    }
