"""人工校订：在拼接文本上落实有序校订。

复用 :func:`app.assembler.assemble` 的拼接文本与逐字来源，把每项校订
``(segment, pos, char)`` 沿逐字来源定位到最终文本位置后落实改字：

- 多项校订经重叠段指向**同一输出位置**且改字相同：合并为一处修改，
  关联校订项全部保留；
- 同一输出位置被指向**不同改字**：抛出 :class:`EditConflictError`，
  由接口层转为 409，并列出全部冲突位置与校订项；
- 段序号或原文下标越界、坐标未映射或映射到多个输出位置：抛出
  :class:`EditLocationError`，由接口层转为 422。

校订为纯内存计算，任一环节失败即不返回任何结果（不产生部分修订）；
不重新对齐，未涉及位置保持原字，``sources`` 沿用拼接结果不变。
"""

from __future__ import annotations

from .assembler import assemble


class EditLocationError(ValueError):
    """校订坐标无法唯一定位（段序号/下标越界、未映射或映射到多个输出位置）。"""


class EditConflictError(ValueError):
    """同一输出位置被多项校订指向不同改字。"""

    def __init__(self, conflicts: list[dict]):
        self.conflicts = conflicts
        positions = "、".join(str(c["pos"]) for c in conflicts)
        super().__init__(
            f"校订冲突：输出位置 {positions} 被多项校订指向不同改字，无法落实修订"
        )


def _locate_edits(
    segments: list[str],
    sources: list[list[dict]],
    edits: list[dict],
) -> dict[int, list[dict]]:
    """校验每项校订坐标并定位到输出位置，返回 ``{输出位置: [校订项, ...]}``。

    校订项形如 ``{"index", "segment", "pos", "char"}``，``index`` 为该校订在
    请求 ``edits`` 列表中的下标（从 0 开始），按校订提交顺序收集。
    坐标越界、未映射或映射到多个输出位置时抛出 :class:`EditLocationError`。
    """
    locations: dict[tuple[int, int], list[int]] = {}
    for out_pos, srcs in enumerate(sources):
        for s in srcs:
            locations.setdefault((s["segment"], s["pos"]), []).append(out_pos)

    targets: dict[int, list[dict]] = {}
    for idx, e in enumerate(edits):
        seg, pos = e["segment"], e["pos"]
        if not 0 <= seg < len(segments):
            raise EditLocationError(
                f"第 {idx + 1} 项校订的段序号 {seg} 越界："
                f"共 {len(segments)} 段（段序号 0～{len(segments) - 1}）"
            )
        if not 0 <= pos < len(segments[seg]):
            raise EditLocationError(
                f"第 {idx + 1} 项校订的下标 {pos} 越界："
                f"段 {seg} 共 {len(segments[seg])} 字（下标 0～{len(segments[seg]) - 1}）"
            )
        mapped = locations.get((seg, pos), [])
        if len(mapped) != 1:
            raise EditLocationError(
                f"第 {idx + 1} 项校订（段 {seg} 下标 {pos}）映射到 "
                f"{len(mapped)} 个输出位置，无法唯一定位"
            )
        item = {"index": idx, "segment": seg, "pos": pos, "char": e["char"]}
        targets.setdefault(mapped[0], []).append(item)
    return targets


def revise(segments: list[str], edits: list[dict]) -> dict:
    """在 2～5 段转写的拼接文本上落实人工校订。

    返回 ``{"text": 修订后文本, "sources": 沿用拼接来源, "changes": 逐位置修订}``；
    ``changes`` 按输出位置升序，每项含原字、新字与关联校订项。
    拼接阶段沿用 :func:`assemble` 的续接门槛，失败时原样抛出
    :class:`~app.assembler.AssemblyError`。
    """
    result = assemble(segments)
    text, sources = result["text"], result["sources"]

    targets = _locate_edits(segments, sources, edits)

    # 同一输出位置被指向不同改字即冲突：收集全部冲突位置后一次性报告
    conflicts = [
        {"pos": out_pos, "edits": items}
        for out_pos, items in sorted(targets.items())
        if len({it["char"] for it in items}) > 1
    ]
    if conflicts:
        raise EditConflictError(conflicts)

    chars = list(text)
    changes: list[dict] = []
    for out_pos, items in sorted(targets.items()):
        new_char = items[0]["char"]  # 同位置改字一致（冲突已在上方排除）
        changes.append({
            "pos": out_pos,
            "from_char": chars[out_pos],
            "to_char": new_char,
            "edits": items,
        })
        chars[out_pos] = new_char

    return {"text": "".join(chars), "sources": sources, "changes": changes}
