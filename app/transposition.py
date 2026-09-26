"""移位审计：诊断拼接稿中一段连续文字被移到另一位置的情形。

提交与 :func:`app.assembler.assemble` 相同的有序 segments 与一段独立参照转写
``reference``，先复用其拼接得到拼接文本与逐字来源（沿用段数/长度限制与续接
失败规则）。两稿须**等长**且均不超过 :data:`MAX_TEXT_LEN`（120）字，且拼接
稿与参照稿之间须存在**已知字冲突**（双方皆已知且异字的位置），否则不适用
本诊断（:class:`TranspositionRequirementError`）。

**枚举移位操作**：枚举拼接稿的左闭右开区间 ``[s, e)``（长度
:data:`MIN_MOVED_LEN`～:data:`MAX_MOVED_LEN`，即 2～12 字），把该区间剪下，
得到剩余文本 ``rem = text[:s] + text[e:]``（长 ``n - L``），再按剩余文本的
插入下标 ``i``（``0 <= i <= n - L``）放回，重排文本为
``rem[:i] + text[s:e] + rem[i:]``。排除**原位**（``i == s``，必然还原原文）
及**重排后未改变文本**的操作。

**判定**：重排文本逐字与参照稿比较，相同字或任一侧为 ``?`` 算吻合；须全部
位置吻合，且移位片段在其新位置上至少有 :data:`MIN_KNOWN_SAME`（2）个
**两侧已知且相同**的字，方为合格操作。

**择优**：按移位长度最短取解。最短长度下操作唯一时返回原区间、剪下后的
插入下标、移位文本及原区间逐字 sources；最短长度存在多个不同操作时抛出
:class:`TranspositionTieError`（接口层转为 409，给出两种操作）；不存在合格
操作时抛出 :class:`TranspositionNotFoundError`（接口层转为 422）。

本模块只供人工复核，绝不改写拼接文本。
"""

from __future__ import annotations

from .aligner import WILDCARD
from .assembler import assemble

MAX_TEXT_LEN = 120   # 两稿等长且不超过 120 字
MIN_MOVED_LEN = 2    # 移位片段最少 2 字
MAX_MOVED_LEN = 12   # 移位片段最多 12 字
MIN_KNOWN_SAME = 2   # 移位片段至少 2 个两侧已知且相同的字


class TranspositionRequirementError(ValueError):
    """两稿不等长、超过 120 字，或不存在已知字冲突，不适用移位诊断。"""


class TranspositionNotFoundError(ValueError):
    """不存在使重排文本与参照稿逐字吻合的合格移位操作。"""


class TranspositionTieError(ValueError):
    """最短移位长度由多个不同操作并列取得（ties 为按序取的前两种操作）。"""

    def __init__(self, moved_len: int, total: int, ties: list[dict]):
        self.moved_len = moved_len
        self.ties = ties
        super().__init__(
            f"最短移位长度 {moved_len} 字的合格操作有 {total} 个并列，"
            f"无法唯一确定移位操作"
        )


def _compatible(a: str, b: str) -> bool:
    """逐字比较：相同字或任一侧为 ``?`` 算吻合。"""
    return a == b or a == WILDCARD or b == WILDCARD


def _known_same(a: str, b: str) -> bool:
    """两侧皆为已知字（非 ``?``）且相同。"""
    return a == b and a != WILDCARD


def audit_transposition(segments: list[str], reference: str) -> dict:
    """诊断拼接稿中一段连续的 2～12 字被移到另一位置的情形。

    返回唯一操作时的 ``{"text", "reference", "start", "end", "insert_at",
    "moved", "sources"}``；拼接阶段失败原样抛出
    :class:`~app.assembler.AssemblyError`，两稿不等长/超 120 字/无已知字冲突
    抛出 :class:`TranspositionRequirementError`，无合格操作抛出
    :class:`TranspositionNotFoundError`，最短长度多解抛出
    :class:`TranspositionTieError`。
    """
    if len(reference) > MAX_TEXT_LEN:
        raise TranspositionRequirementError(
            f"参照转写长度 {len(reference)} 字，超过 {MAX_TEXT_LEN} 字上限"
        )

    result = assemble(segments)
    text, sources = result["text"], result["sources"]
    n = len(text)
    if n > MAX_TEXT_LEN:
        raise TranspositionRequirementError(
            f"拼接稿 {n} 字，超过 {MAX_TEXT_LEN} 字上限，不适用移位诊断"
        )
    if len(reference) != n:
        raise TranspositionRequirementError(
            f"参照稿 {len(reference)} 字、拼接稿 {n} 字，"
            f"两稿须等长，不适用移位诊断"
        )

    conflicts = sum(
        1
        for p in range(n)
        if text[p] != WILDCARD
        and reference[p] != WILDCARD
        and text[p] != reference[p]
    )
    if conflicts == 0:
        raise TranspositionRequirementError(
            "拼接稿与参照稿不存在已知字冲突，不适用移位诊断"
        )

    max_len = min(MAX_MOVED_LEN, n)
    shortest: list[tuple[int, int, int]] = []
    for length in range(MIN_MOVED_LEN, max_len + 1):
        ops: list[tuple[int, int, int]] = []
        for s in range(0, n - length + 1):
            e = s + length
            moved = text[s:e]
            rem = text[:s] + text[e:]
            for i in range(0, n - length + 1):
                if i == s:
                    continue  # 原位：必然还原原文
                rearranged = rem[:i] + moved + rem[i:]
                if rearranged == text:
                    continue  # 重排后未改变文本
                if not all(
                    _compatible(a, b) for a, b in zip(rearranged, reference)
                ):
                    continue
                known_same = sum(
                    1
                    for p in range(i, i + length)
                    if _known_same(rearranged[p], reference[p])
                )
                if known_same < MIN_KNOWN_SAME:
                    continue
                ops.append((s, e, i))
        if ops:
            shortest = ops
            break

    if not shortest:
        raise TranspositionNotFoundError(
            f"枚举全部 {MIN_MOVED_LEN}～{max_len} 字连续区间的剪下重放后，"
            f"没有使重排文本与参照稿逐字吻合的合格移位操作"
        )

    def make_op(op: tuple[int, int, int]) -> dict:
        s, e, i = op
        return {
            "start": s,
            "end": e,
            "insert_at": i,
            "moved": text[s:e],
            "sources": [[dict(src) for src in slot] for slot in sources[s:e]],
        }

    if len(shortest) > 1:
        moved_len = shortest[0][1] - shortest[0][0]
        raise TranspositionTieError(
            moved_len, len(shortest), [make_op(op) for op in shortest[:2]]
        )

    return {"text": text, "reference": reference, **make_op(shortest[0])}
