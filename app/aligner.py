"""古籍残页拼接核心算法。

只将左段的后缀与右段的前缀做半全局（重叠）对齐：

- 左段未参与对齐的前缀、右段未参与对齐的后缀不计分；
- 对齐区内至少包含一对字符（不允许纯空缺对齐）；
- 计分：相同字 +2；"?" 与任意字配对 0；异字 -2；
  连续空缺首字 -3、其余每字 -1（仿射空缺罚分）；
- 同分并列时，对齐字符对数多者优先；仍并列则左段起点小者优先。

拼接时以已知字替换 "?"，异字保留左段字并记录双方原文位置及字形。
"""

from __future__ import annotations

MATCH_SCORE = 2          # 相同字
WILDCARD_SCORE = 0       # "?" 与任意字配对
MISMATCH_SCORE = -2      # 异字（双方均已知且不同）
GAP_OPEN_SCORE = -3      # 连续空缺首字
GAP_EXTEND_SCORE = -1    # 连续空缺其余每字

WILDCARD = "?"
GAP_CHAR = "-"

# DP 状态：对齐区最后一列的形态
_PAIR = 0   # 字符对（左字 vs 右字）
_LGAP = 1   # 左字 vs 空缺（右段空缺）
_RGAP = 2   # 空缺 vs 右字（左段空缺）


def pair_score(a: str, b: str) -> int:
    """单对字符的得分。"""
    if a == WILDCARD or b == WILDCARD:
        return WILDCARD_SCORE
    return MATCH_SCORE if a == b else MISMATCH_SCORE


def align(left: str, right: str) -> dict:
    """对两段转写文本做最优重叠拼接，返回对齐与拼接结果。

    位置均为从 0 开始的下标；区间为左闭右开 [start, end)。
    """
    m, n = len(left), len(right)
    if m == 0 or n == 0:
        raise ValueError("左右两段文本均不能为空")

    # dp[i][j][state][flag]：已消耗左段前 i 字、右段前 j 字、末列形态为 state、
    # flag 标记是否已出现字符对 的最优条目，
    # 值为 (score, pairs, start, parent) 或 None。
    #   score  —— 对齐区累计得分
    #   pairs  —— 已对齐的字符对数
    #   start  —— 左段起点（其前的左段前缀不计分）
    #   parent —— 前驱 (state, flag)；None 表示从“自由前缀”直接起步
    dp = [[[[None, None], [None, None], [None, None]]
           for _ in range(n + 1)] for _ in range(m + 1)]

    def better(e, f):
        """按 (分数, 字符对数, -左段起点) 字典序取优。"""
        if e is None:
            return f
        if f is None:
            return e
        ke = (e[0], e[1], -e[2])
        kf = (f[0], f[1], -f[2])
        return e if ke >= kf else f

    for i in range(m + 1):
        for j in range(n + 1):
            if i == 0 and j == 0:
                continue
            cell = dp[i][j]

            # 末列为字符对 (left[i-1], right[j-1])
            if i >= 1 and j >= 1:
                s = pair_score(left[i - 1], right[j - 1])
                best = None
                prev = dp[i - 1][j - 1]
                for ps in (_PAIR, _LGAP, _RGAP):
                    for fl in (0, 1):
                        e = prev[ps][fl]
                        if e is not None:
                            best = better(best, (e[0] + s, e[1] + 1, e[2], (ps, fl)))
                if j == 1:
                    # 左段前 i-1 字为不计分的自由前缀，由此起步
                    best = better(best, (s, 1, i - 1, None))
                cell[_PAIR][1] = best

            # 末列为 (左字, 空缺)
            if i >= 1 and j >= 1:
                prev = dp[i - 1][j]
                for fl in (0, 1):
                    best = None
                    for ps in (_PAIR, _RGAP):      # 开启新的空缺段
                        e = prev[ps][fl]
                        if e is not None:
                            best = better(best, (e[0] + GAP_OPEN_SCORE, e[1], e[2], (ps, fl)))
                    e = prev[_LGAP][fl]            # 延续空缺段
                    if e is not None:
                        best = better(best, (e[0] + GAP_EXTEND_SCORE, e[1], e[2], (_LGAP, fl)))
                    cell[_LGAP][fl] = best

            # 末列为 (空缺, 右字)
            if j >= 1:
                prev = dp[i][j - 1]
                for fl in (0, 1):
                    best = None
                    for ps in (_PAIR, _LGAP):      # 开启新的空缺段
                        e = prev[ps][fl]
                        if e is not None:
                            best = better(best, (e[0] + GAP_OPEN_SCORE, e[1], e[2], (ps, fl)))
                    e = prev[_RGAP][fl]            # 延续空缺段
                    if e is not None:
                        best = better(best, (e[0] + GAP_EXTEND_SCORE, e[1], e[2], (_RGAP, fl)))
                    if j == 1 and fl == 0:
                        # 右段首字对齐空缺（右段探出左段左端）
                        best = better(best, (GAP_OPEN_SCORE, 0, i, None))
                    cell[_RGAP][fl] = best

    # 终点：左段全部消耗（i = m），右段前 j 字参与对齐、其余为不计分的自由后缀，
    # 且至少含一对字符（flag = 1）。
    final = None
    end_j = end_state = 0
    for j in range(1, n + 1):
        for st in (_PAIR, _LGAP, _RGAP):
            e = dp[m][j][st][1]
            if e is None:
                continue
            if final is None or (e[0], e[1], -e[2]) > (final[0], final[1], -final[2]):
                final, end_j, end_state = e, j, st

    score, pairs, start, _ = final

    # 回溯，得到逐列对齐（左字, 右字, 左位置, 右位置），空缺处为 None
    columns = []
    i, j, st, fl = m, end_j, end_state, 1
    while True:
        e = dp[i][j][st][fl]
        if st == _PAIR:
            columns.append((left[i - 1], right[j - 1], i - 1, j - 1))
            i, j = i - 1, j - 1
        elif st == _LGAP:
            columns.append((left[i - 1], None, i - 1, None))
            i -= 1
        else:
            columns.append((None, right[j - 1], None, j - 1))
            j -= 1
        if e[3] is None:
            break
        st, fl = e[3]
    columns.reverse()

    # 逐列整理、拼接文本、异字冲突与 "?" 补字记录
    cols = []
    merged_mid = []
    conflicts = []
    resolved = []
    prev_gap = None  # 上一列空缺方向："left"=左段空缺 / "right"=右段空缺
    for lc, rc, lp, rp in columns:
        if lc is not None and rc is not None:
            prev_gap = None
            s = pair_score(lc, rc)
            if lc == WILDCARD and rc == WILDCARD:
                ctype, ch = "wildcard", WILDCARD
            elif lc == WILDCARD:
                ctype, ch = "wildcard", rc
                resolved.append({"segment": "left", "pos": lp, "resolved_char": rc})
            elif rc == WILDCARD:
                ctype, ch = "wildcard", lc
                resolved.append({"segment": "right", "pos": rp, "resolved_char": lc})
            elif lc == rc:
                ctype, ch = "match", lc
            else:
                ctype, ch = "mismatch", lc  # 异字保留左段字
                conflicts.append({
                    "left_pos": lp, "left_char": lc,
                    "right_pos": rp, "right_char": rc,
                })
        elif lc is not None:  # 右段空缺
            s = GAP_EXTEND_SCORE if prev_gap == "right" else GAP_OPEN_SCORE
            prev_gap, ctype, ch = "right", "gap_right", lc
        else:                 # 左段空缺
            s = GAP_EXTEND_SCORE if prev_gap == "left" else GAP_OPEN_SCORE
            prev_gap, ctype, ch = "left", "gap_left", rc
        merged_mid.append(ch)
        cols.append({
            "left_pos": lp, "left_char": lc,
            "right_pos": rp, "right_char": rc,
            "type": ctype, "score": s,
        })

    merged = left[:start] + "".join(merged_mid) + right[end_j:]
    aligned_left = "".join(c[0] if c[0] is not None else GAP_CHAR for c in columns)
    aligned_right = "".join(c[1] if c[1] is not None else GAP_CHAR for c in columns)

    return {
        "score": score,
        "aligned_pairs": pairs,
        "left_interval": {"start": start, "end": m, "text": left[start:]},
        "right_interval": {"start": 0, "end": end_j, "text": right[:end_j]},
        "left_free_prefix": left[:start],
        "right_free_suffix": right[end_j:],
        "aligned_left": aligned_left,
        "aligned_right": aligned_right,
        "columns": cols,
        "merged": merged,
        "conflicts": conflicts,
        "resolved_wildcards": resolved,
    }
