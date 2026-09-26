"""脱漏审计：在拼接文本的段间接缝处比对独立参照转写，查找可能漏抄的连续缺文。

提交与 :func:`app.assembler.assemble` 相同的有序 segments 与一段独立参照转写
``reference``（最长 :data:`MAX_REFERENCE_LEN` = 840 字），先复用其拼接得到
拼接文本与逐字来源（沿用段数/长度限制与续接失败规则）。

**接缝（只检查这类位置）**：拼接文本相邻两字 ``text[p-1]`` 与 ``text[p]``
之间，左字的逐字来源中含某原始段 ``k``，而右字的来源中不含 ``k``、却含
更晚的原始段（序号大于 ``k``）——即阅读由较早段跨入更晚段的段间接缝。
只有接缝位置允许补字，``p`` 即插入位置（补在 ``text[p-1]`` 与 ``text[p]``
之间）。

**参照长度**：参照稿须比拼接稿恰好多 :data:`MIN_GAP`～:data:`MAX_GAP`
（1～40）字，否则视为不适用本审计（:class:`OmissionRequirementError`）。

**枚举方案**：对每条接缝，把参照稿中占据插入后对应位置的连续片段
``reference[p:p+gap]`` 补入接缝，补入后两稿等长（长度均为 ``m``），逐位
对齐计分：相同字、或任一侧为 ``?``（未辨认字）记 0，双方皆为已知且异字
记 1。由于补入片段与参照稿同位的一段逐字相同，该方案的整稿异字数恰为

    前缀 ``text[0:p]`` 对 ``reference[0:p]`` 的异字数
  + 后缀 ``text[p:n]`` 对 ``reference[p+gap:m]`` 的异字数；

接缝处补入的缺文字串即 ``reference[p:p+gap]``。整稿异字数不超过
:data:`MAX_DIFF`（2）的方案才合格，取异字数最少的方案。

- 异字数最少的接缝唯一：返回插入位置、缺文字串、异字数及接缝两侧 sources；
- 多条**不同接缝**（不同缺文位置）以同一最少异字数并列：抛出
  :class:`OmissionTieError`，由接口层转为 409；
- 无接缝或所有接缝的异字数都超过 2：抛出 :class:`OmissionNotFoundError`，
  由接口层转为 422。

前缀异字数用逐位前缀和、后缀异字数用逐位后缀和预处理，每条接缝 O(1)，
整体 O(n)。

本模块只供人工复核，绝不改写拼接文本。
"""

from __future__ import annotations

from .aligner import WILDCARD
from .assembler import assemble

MAX_REFERENCE_LEN = 840  # 参照转写最大长度
MIN_GAP = 1              # 参照稿须比拼接稿多的最少字数
MAX_GAP = 40             # 参照稿须比拼接稿多的最多字数
MAX_DIFF = 2             # 整稿逐位对齐允许的最大异字数


class OmissionRequirementError(ValueError):
    """参照稿长度不满足“比拼接稿恰好多 1～40 字”的前提。"""


class OmissionNotFoundError(ValueError):
    """不存在异字数不超过 :data:`MAX_DIFF` 的接缝补字方案。"""


class OmissionTieError(ValueError):
    """最少异字数由多个不同接缝（不同缺文位置）并列取得。"""

    def __init__(self, diff: int, ties: list[dict]):
        self.diff = diff
        self.ties = ties
        super().__init__(
            f"参照稿的连续缺文可补入 {len(ties)} 个不同接缝且最少异字数同为 "
            f"{diff}，无法唯一确定缺文位置"
        )


def _differs(a: str, b: str) -> int:
    """逐位对齐时一对字符的异字数：相同字或任一侧为 ``?`` 记 0，否则记 1。"""
    if a == WILDCARD or b == WILDCARD or a == b:
        return 0
    return 1


def _find_seams(sources: list[list[dict]]) -> list[int]:
    """在逐字来源中找出全部段间接缝，返回插入位置列表（升序、去重）。

    插入位置 ``p``（1 <= p < n）表示接缝位于 ``text[p-1]`` 与 ``text[p]``
    之间：左字来源含某原始段 ``k``，右字来源不含 ``k`` 而含更晚的原始段
    （序号 > k）。同一位置只计一次。
    """
    seams: list[int] = []
    for p in range(1, len(sources)):
        left_segs = {s["segment"] for s in sources[p - 1]}
        right_segs = {s["segment"] for s in sources[p]}
        if any(
            k in left_segs
            and k not in right_segs
            and any(j > k for j in right_segs)
            for k in left_segs
        ):
            seams.append(p)
    return seams


def audit_omission(segments: list[str], reference: str) -> dict:
    """在拼接文本的段间接缝处审计参照稿多出的连续缺文。

    返回唯一方案时的 ``{"text", "reference", "pos", "missing", "diff",
    "left", "right"}``；拼接阶段失败原样抛出
    :class:`~app.assembler.AssemblyError`，参照长度前提不满足抛出
    :class:`OmissionRequirementError`，无合格方案抛出
    :class:`OmissionNotFoundError`，多个不同接缝并列抛出
    :class:`OmissionTieError`。
    """
    if len(reference) > MAX_REFERENCE_LEN:
        raise OmissionRequirementError(
            f"参照转写长度 {len(reference)} 字，超过 {MAX_REFERENCE_LEN} 字上限"
        )

    result = assemble(segments)
    text, sources = result["text"], result["sources"]
    n, m = len(text), len(reference)
    gap = m - n
    if not MIN_GAP <= gap <= MAX_GAP:
        raise OmissionRequirementError(
            f"参照稿 {m} 字、拼接稿 {n} 字，参照稿须恰好多 "
            f"{MIN_GAP}～{MAX_GAP} 字（实际多 {gap} 字），不适用脱漏审计"
        )

    seams = _find_seams(sources)
    if not seams:
        raise OmissionNotFoundError("拼接文本中不存在段间接缝，无脱漏可补")

    # 前缀逐位异字：pre[p] = text[0:p] 与 reference[0:p] 的异字数
    pre = [0] * (n + 1)
    for i in range(n):
        pre[i + 1] = pre[i] + _differs(text[i], reference[i])
    # 后缀逐位异字：suf[p] = text[p:n] 与 reference[p+gap:n+gap] 的异字数
    suf = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suf[i] = suf[i + 1] + _differs(text[i], reference[i + gap])

    candidates: list[dict] = []
    best_diff = MAX_DIFF + 1
    for p in seams:
        diff = pre[p] + suf[p]
        if diff > MAX_DIFF:
            continue
        if diff < best_diff:
            best_diff = diff
            candidates = [{"pos": p, "diff": diff}]
        elif diff == best_diff:
            candidates.append({"pos": p, "diff": diff})

    if best_diff > MAX_DIFF:
        raise OmissionNotFoundError(
            f"全部 {len(seams)} 个段间接缝补入参照稿连续缺文后，整稿异字数均"
            f"超过 {MAX_DIFF}，无合格脱漏方案"
        )

    def make_scheme(c: dict) -> dict:
        p, diff = c["pos"], c["diff"]
        return {
            "pos": p,
            "missing": reference[p : p + gap],
            "diff": diff,
            "left": {
                "char": text[p - 1],
                "sources": [dict(src) for src in sources[p - 1]],
            },
            "right": {
                "char": text[p],
                "sources": [dict(src) for src in sources[p]],
            },
        }

    schemes = [make_scheme(c) for c in sorted(candidates, key=lambda c: c["pos"])]
    if len(schemes) > 1:
        raise OmissionTieError(best_diff, schemes)

    return {"text": text, "reference": reference, **schemes[0]}
