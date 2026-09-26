"""多段残页转写的顺序拼接。

按阅读顺序逐段复用 ``aligner.align`` 的后缀-前缀对齐：把当前拼接文本作为
左段、下一段原始转写作为右段做一次对齐，并把对齐结果映射回逐字来源。

每个输出字携带所有贡献该字的原始段序号与原文下标（均从 0 开始）：

- 相同字：双方来源都保留；
- ``?`` 补字：``?`` 一方与补字一方的来源都保留；
- 异字冲突：保留左段字形，冲突双方的来源都保留；
- 空缺列：仅未空缺一方贡献来源。

每一步（合并第 k 段，k 从 1 开始）只有在最高对齐得分大于 0、且至少有 2 对
相同已知字（``match`` 列）时才继续，否则抛出 :class:`AssemblyError`，
由接口层转为 422；拼接为纯内存计算，失败即不返回任何结果。
"""

from __future__ import annotations

from .aligner import WILDCARD, align

MIN_SCORE = 1          # 续接要求 score > 0
MIN_SAME_KNOWN_PAIRS = 2  # 续接要求至少 2 对相同已知字


class AssemblyError(ValueError):
    """某一段无法与当前拼接文本可靠续接。"""

    def __init__(self, failed_segment: int):
        self.failed_segment = failed_segment
        super().__init__(
            f"第 {failed_segment + 1} 段（段序号 {failed_segment}）无法与前文可靠拼接："
            f"需要最高对齐得分 > 0 且至少 {MIN_SAME_KNOWN_PAIRS} 对相同已知字"
        )


def merge_once(
    cur_text: str,
    cur_sources: list[list[dict]],
    nxt: str,
    seg_index: int,
) -> tuple[str, list[list[dict]], int]:
    """将当前拼接文本与第 ``seg_index`` 段对齐合并一步。

    返回 (新文本, 新逐字来源, 本步对齐得分)。不满足续接门槛时抛出
    :class:`AssemblyError`。
    """
    r = align(cur_text, nxt)
    same_known_pairs = sum(1 for c in r["columns"] if c["type"] == "match")
    if r["score"] < MIN_SCORE or same_known_pairs < MIN_SAME_KNOWN_PAIRS:
        raise AssemblyError(seg_index)

    start = r["left_interval"]["start"]
    end_j = r["right_interval"]["end"]

    out_chars: list[str] = []
    out_sources: list[list[dict]] = []

    def emit(ch: str, srcs: list[dict]) -> None:
        out_chars.append(ch)
        out_sources.append(sorted(srcs, key=lambda s: (s["segment"], s["pos"])))

    # 左段（当前拼接文本）未参与对齐的自由前缀
    for p in range(start):
        emit(cur_text[p], list(cur_sources[p]))

    for col in r["columns"]:
        lp, lc = col["left_pos"], col["left_char"]
        rp, rc = col["right_pos"], col["right_char"]
        left_srcs = list(cur_sources[lp]) if lp is not None else []
        right_srcs = [{"segment": seg_index, "pos": rp}] if rp is not None else []
        if lc is not None and rc is not None:
            # 与 aligner 的取字规则一致：左段为 ? 时取右字（双方皆 ? 时仍是 ?），
            # 其余情况（相同字 / 右段为 ? / 异字）取左字；来源保留双方。
            ch = rc if lc == WILDCARD else lc
            emit(ch, [*left_srcs, *right_srcs])
        elif lc is not None:  # 右段空缺：仅当前文本一方贡献
            emit(lc, left_srcs)
        else:                 # 左段空缺：仅新段一方贡献
            emit(rc, right_srcs)

    # 右段未参与对齐的自由后缀
    for p in range(end_j, len(nxt)):
        emit(nxt[p], [{"segment": seg_index, "pos": p}])

    return "".join(out_chars), out_sources, r["score"]


def assemble(segments: list[str]) -> dict:
    """按阅读顺序拼接 2～5 段转写，返回 ``{"text": ..., "sources": ...}``。

    失败时抛出 :class:`AssemblyError`（``failed_segment`` 为失败段序号，
    从 0 开始）。
    """
    if len(segments) < 2:
        raise ValueError("至少需要 2 段转写")

    text = segments[0]
    sources: list[list[dict]] = [
        [{"segment": 0, "pos": p}] for p in range(len(text))
    ]
    for k in range(1, len(segments)):
        text, sources, _score = merge_once(text, sources, segments[k], k)
    return {"text": text, "sources": sources}
