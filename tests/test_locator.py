"""引文定位（locate_quote）测试。"""

import random

import pytest

from app.assembler import AssemblyError
from app.locator import (
    MAX_COST,
    MAX_QUOTE_LEN,
    QuoteNotFoundError,
    QuoteTieError,
    _edit_cost,
    _enumerate_hits,
    locate_quote,
)

SEGMENTS = ["学而?习之", "时习之不", "之不亦乐乎"]
# 拼接结果：学而时习之不亦乐乎（9 字）
TEXT = "学而时习之不亦乐乎"


def test_exact_quote_returns_unique_interval():
    r = locate_quote(SEGMENTS, "时习之")
    assert r["text"] == TEXT
    assert r["quote"] == "时习之"
    assert (r["start"], r["end"]) == (2, 5)
    assert r["fragment"] == "时习之"
    assert r["cost"] == 0
    # 逐字 sources 与拼接结果对应区间一致
    assert r["sources"] == [
        [{"segment": 0, "pos": 2}, {"segment": 1, "pos": 0}],
        [{"segment": 0, "pos": 3}, {"segment": 1, "pos": 1}],
        [{"segment": 0, "pos": 4}, {"segment": 1, "pos": 2}, {"segment": 2, "pos": 0}],
    ]


def test_wildcard_on_either_side_is_cost_zero():
    # 引文带 ?，与拼接文本对应字免代价
    r = locate_quote(SEGMENTS, "时?之")
    assert (r["start"], r["end"], r["fragment"], r["cost"]) == (2, 5, "时习之", 0)
    # 拼接文本残留 ?（未被补字）的位置对引文已知字同样免代价
    r = locate_quote(["甲?丙丁", "丙丁戊"], "甲乙丙丁")
    assert (r["start"], r["end"], r["fragment"], r["cost"]) == (0, 4, "甲?丙丁", 0)


def test_substitution_insertion_deletion_each_cost_one_unique():
    # 替换：倒数第二字不同
    r = locate_quote(SEGMENTS, "学而时习之不亦悦乎")
    assert (r["start"], r["end"], r["fragment"], r["cost"]) == (0, 9, TEXT, 1)
    # 删除：引文缺一个区间字
    r = locate_quote(SEGMENTS, "学而时习不亦乐乎")
    assert (r["start"], r["end"], r["fragment"], r["cost"]) == (0, 9, TEXT, 1)
    # 插入：引文在开头多一个字（与区间前缀对齐后尾部自由）
    best, ivs = _enumerate_hits("甲乙丙丁戊", "X甲乙丙丁戊", MAX_COST)
    assert (best, ivs) == (1, [(0, 5)])


def test_cost_two_accepted_when_unique():
    # 两处替换，区间唯一
    r = locate_quote(["甲乙丙丁戊己", "戊己庚"], "甲X丙丁Y己庚")
    assert r["text"] == "甲乙丙丁戊己庚"
    assert (r["start"], r["end"], r["fragment"], r["cost"]) == (0, 7, "甲乙丙丁戊己庚", 2)
    assert len(r["sources"]) == 7


def test_no_acceptable_interval_raises():
    # 4 字引文与拼接文本毫无共同字：最小代价远超 2
    with pytest.raises(QuoteNotFoundError):
        locate_quote(SEGMENTS, "朋朋朋朋")
    # 最小代价大于 2（4 字窗口与 4 字引文完全不同，替换代价 4）
    assert _enumerate_hits("子丑寅卯", "戊己庚辛", MAX_COST) == (4, [])
    with pytest.raises(QuoteNotFoundError):
        locate_quote(SEGMENTS, "戊己庚辛")


def test_tie_zero_cost_lists_all_distinct_intervals():
    # 文本中两处完全相同的单字：引文 "甲" 同时命中 [0,1) 与 [5,6)，代价 0
    segs = ["甲子丙丁卯", "丁卯甲庚"]
    with pytest.raises(QuoteTieError) as exc:
        locate_quote(segs, "甲")
    assert exc.value.cost == 0
    hits = exc.value.hits
    assert [(h["start"], h["end"]) for h in hits] == [(0, 1), (5, 6)]
    assert all(h["fragment"] == "甲" and h["cost"] == 0 for h in hits)
    # 各命中带各自的逐字来源
    assert hits[0]["sources"] == [[{"segment": 0, "pos": 0}]]
    assert hits[1]["sources"] == [[{"segment": 1, "pos": 2}]]


def test_tie_between_different_edit_shapes():
    # "时习知"：[2,5)"时习之"（替换，1）与 [2,4)"时习"（尾部删除，1）并列
    with pytest.raises(QuoteTieError) as exc:
        locate_quote(SEGMENTS, "时习知")
    assert exc.value.cost == 1
    assert [(h["start"], h["end"], h["fragment"]) for h in exc.value.hits] == [
        (2, 4, "时习"),
        (2, 5, "时习之"),
    ]


def test_tie_wildcards_many_windows():
    # 引文为单个 ?：与每个字都免代价配对，全部单字区间代价 0 并列
    with pytest.raises(QuoteTieError) as exc:
        locate_quote(SEGMENTS, "?")
    assert exc.value.cost == 0
    assert [(h["start"], h["end"]) for h in exc.value.hits] == [
        (i, i + 1) for i in range(len(TEXT))
    ]


def test_whole_text_match():
    r = locate_quote(SEGMENTS, TEXT)
    assert (r["start"], r["end"], r["cost"]) == (0, 9, 0)
    assert r["fragment"] == TEXT
    assert len(r["sources"]) == 9


def test_assembly_gate_failure_propagates():
    with pytest.raises(AssemblyError) as exc:
        locate_quote(["孔子曰未知", "未知生焉", "完全无关文本"], "孔子")
    assert exc.value.failed_segment == 2


def test_quote_length_validated():
    locate_quote(SEGMENTS, "学")  # 1 字、唯一命中可以
    with pytest.raises(ValueError):
        locate_quote(SEGMENTS, "")  # 空引文不接受（区间比较无意义）
    with pytest.raises(ValueError):
        locate_quote(SEGMENTS, "学" * (MAX_QUOTE_LEN + 1))
    # 恰好 80 字、且 segments 恰好触及总长上限 800：可通过参数与续接门槛
    # （引文为 80 个 ?，对 800 字同字文本必有多个代价 0 区间并列）
    with pytest.raises(QuoteTieError):
        locate_quote(["字" * 400, "字" * 400], "?" * MAX_QUOTE_LEN)


def test_edit_cost_matches_levenshtein_with_wildcards():
    assert _edit_cost("甲乙", "甲?", MAX_COST) == 0
    assert _edit_cost("?", "甲", MAX_COST) == 0
    assert _edit_cost("甲乙", "甲丙", MAX_COST) == 1
    assert _edit_cost("甲乙丙", "甲丙", MAX_COST) == 1
    assert _edit_cost("甲丙", "甲乙丙", MAX_COST) == 1
    assert _edit_cost("甲乙丙丁", "戊己庚辛", 4) == 4


def _brute_min_intervals(text, quote):
    """朴素全区间枚举：(最小代价, 取得最小代价的全部区间)。"""
    from app.locator import _pair_cost

    best, ivs = None, []
    for s in range(len(text)):
        for e in range(s + 1, len(text) + 1):
            frag = text[s:e]
            m, n = len(quote), len(frag)
            dp = list(range(n + 1))
            for i in range(1, m + 1):
                ndp = [i] + [0] * n
                for j in range(1, n + 1):
                    pc = _pair_cost(quote[i - 1], frag[j - 1])
                    ndp[j] = min(dp[j] + 1, ndp[j - 1] + 1, dp[j - 1] + pc)
                dp = ndp
            c = dp[n]
            if best is None or c < best:
                best, ivs = c, [(s, e)]
            elif c == best:
                ivs.append((s, e))
    return best, sorted(ivs)


def test_enumerate_hits_matches_brute_force():
    random.seed(42)
    pool = "甲乙丙?"
    for _ in range(300):
        text = "".join(random.choice(pool) for _ in range(random.randint(1, 12)))
        quote = "".join(random.choice(pool) for _ in range(random.randint(1, 8)))
        got_best, got_ivs = _enumerate_hits(text, quote, MAX_COST)
        exp_best, exp_ivs = _brute_min_intervals(text, quote)
        assert got_best == exp_best
        assert got_ivs == (exp_ivs if exp_best <= MAX_COST else [])
