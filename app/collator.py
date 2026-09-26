"""多段残页转写的异文校勘（复核）。

复用 :func:`app.assembler.assemble` 的拼接文本与逐字来源，逐个输出位置回查
各原始段的原字，以**原始段为投票单位**做异文统计：

- 同一原始段在该位置贡献多个来源标记时（同段重复来源）只计一次；
- 原字为 ``?``（未辨认字）的来源不投票；
- 仅保留得票，即至少有两种**不同已知字**的位置——纯补字位置（各来源原字
  只有一种已知字，其余为 ``?``）不构成异文，不列入；
- 建议字取唯一最高票候选；最高票并列时建议字为 ``None``。

本模块只做复核统计，绝不改写拼接文本。
"""

from __future__ import annotations

from .aligner import WILDCARD
from .assembler import assemble


def _votes_at_position(segments: list[str], srcs: list[dict]) -> dict[int, str]:
    """收集一个输出位置上各原始段的投票：``{段序号: 原字}``。

    以原始段为投票单位，分两步处理来源标记：先按段去重（同段重复来源只计
    一次，取该段首个来源所指原字；同段各来源指向同一输出位置，原字一致），
    再丢弃原字为 ``?`` 的票（``?`` 不投票）。
    """
    original: dict[int, str] = {}
    for s in srcs:
        seg, pos = s["segment"], s["pos"]
        if seg not in original:
            original[seg] = segments[seg][pos]
    return {seg: ch for seg, ch in original.items() if ch != WILDCARD}


def collate(segments: list[str]) -> dict:
    """对 2～5 段转写做异文校勘，返回 ``{"text": ..., "variants": ...}``。

    拼接阶段沿用 :func:`assemble` 的续接门槛，失败时原样抛出
    :class:`~app.assembler.AssemblyError`。``variants`` 中每项按输出位置
    升序排列；候选项按得票数降序、并列时按最小支持段序号升序排列。
    """
    result = assemble(segments)
    text, sources = result["text"], result["sources"]

    variants: list[dict] = []
    for out_pos, (cur_char, srcs) in enumerate(zip(text, sources)):
        votes = _votes_at_position(segments, srcs)
        tally: dict[str, list[int]] = {}
        for seg, ch in votes.items():
            tally.setdefault(ch, []).append(seg)

        if len(tally) < 2:
            continue  # 仅一种已知字（纯补字/单源），无异文，不列入

        candidates = [
            {"char": ch, "segments": sorted(segs)}
            for ch, segs in tally.items()
        ]
        candidates.sort(key=lambda c: (-len(c["segments"]), min(c["segments"])))

        top = len(candidates[0]["segments"])
        tied = [c for c in candidates if len(c["segments"]) == top]
        # 唯一最高票给建议字；并列最高票则建议为 None，不自动改写拼接文本
        suggestion = tied[0]["char"] if len(tied) == 1 else None

        variants.append({
            "pos": out_pos,
            "current": cur_char,
            "candidates": candidates,
            "suggestion": suggestion,
        })

    return {"text": text, "variants": variants}
