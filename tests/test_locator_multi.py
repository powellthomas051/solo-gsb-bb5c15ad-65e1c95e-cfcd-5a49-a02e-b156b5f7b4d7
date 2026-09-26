"""多引文顺序定位（locate_quotes）测试。"""

import random

import pytest

from app.assembler import AssemblyError
from app.locator import (
    MAX_COST,
    MAX_QUOTES,
    MAX_QUOTE_LEN,
    MIN_QUOTES,
    QuotesNotFoundError,
    QuotesTieError,
    _enumerate_candidate_intervals,
    _locate_chain,
    locate_quotes,
)

SEGMENTS = ["学而?习之", "时习之不", "之不亦乐乎"]
# 拼接结果：学而时习之不亦乐乎（9 字）
TEXT = "学而时习之不亦乐乎"


def test_unique_chain_exact_matches():
    r = locate_quotes(SEGMENTS, ["学而", "时习之", "不亦乐乎"])
    assert r["text"] == TEXT
    assert r["quotes"] == ["学而", "时习之", "不亦乐乎"]
    assert r["total_cost"] == 0
    assert [(h["start"], h["end"], h["cost"], h["fragment"]) for h in r["hits"]] == [
        (0, 2, 0, "学而"),
        (2, 5, 0, "时习之"),
        (5, 9, 0, "不亦乐乎"),
    ]
    # sources 与拼接结果对应区间一致
    assert r["hits"][1]["sources"] == [
        [{"segment": 0, "pos": 2}, {"segment": 1, "pos": 0}],
        [{"segment": 0, "pos": 3}, {"segment": 1, "pos": 1}],
        [{"segment": 0, "pos": 4}, {"segment": 1, "pos": 2}, {"segment": 2, "pos": 0}],
    ]


def test_two_and_four_quotes_accepted():
    r2 = locate_quotes(SEGMENTS, ["学", "乎"])
    assert [h["fragment"] for h in r2["hits"]] == ["学", "乎"]
    four = ["学", "时", "之不", "乐乎"]
    r4 = locate_quotes(SEGMENTS, four)
    assert r4["quotes"] == four
    assert [(h["start"], h["end"]) for h in r4["hits"]] == [
        (0, 1),
        (2, 3),
        (4, 6),
        (7, 9),
    ]


def test_individually_cheapest_candidate_may_be_unusable():
    # 两段引文都是单字 "甲"：第二段单独的最低代价候选是 [0,1)，但它与第一段的
    # 唯一区间 [0,1) 重叠，无法接入；改取次优候选 [1,2)"乙"（? 免代价不可用时
    # 的替换，代价 1）才能成链。
    r = locate_quotes(["甲乙", "甲乙"], ["甲", "甲"])
    assert r["total_cost"] == 1
    assert [(h["start"], h["end"], h["fragment"], h["cost"]) for h in r["hits"]] == [
        (0, 1, "甲", 0),
        (1, 2, "乙", 1),
    ]


def test_costs_accumulate_across_chain():
    # 第一段引文替换 1 次（甲X丙丁→甲乙丙丁），第二段删除 1 字（戊己X庚→戊己庚）
    segs = ["甲乙丙丁戊己", "戊己庚"]  # 拼接文本：甲乙丙丁戊己庚
    r = locate_quotes(segs, ["甲X丙丁", "戊己X庚"])
    assert r["total_cost"] == 2
    assert [(h["start"], h["end"], h["cost"]) for h in r["hits"]] == [(0, 4, 1), (4, 7, 1)]


def test_touching_intervals_allowed():
    # 相邻区间贴合（前段 end == 后段 start）不算重叠
    r = locate_quotes(SEGMENTS, ["学而时习", "之不亦乐乎"])
    assert [(h["start"], h["end"]) for h in r["hits"]] == [(0, 4), (4, 9)]
    assert r["total_cost"] == 0


def test_tie_returns_two_distinct_chains_409():
    with pytest.raises(QuotesTieError) as exc:
        locate_quotes(["甲丙甲丙", "甲丙甲丙"], ["甲", "丙"])
    assert exc.value.cost == 0
    chains = exc.value.chains
    assert len(chains) == 2
    # 两条链第一段相同、第二段落在不同位置
    assert [[(h["start"], h["end"]) for h in ch] for ch in chains] == [
        [(0, 1), (1, 2)],
        [(0, 1), (3, 4)],
    ]
    for ch in chains:
        assert [h["cost"] for h in ch] == [0, 0]
        assert ch[1]["sources"][0][0]["segment"] == 0


def test_tie_only_between_distinct_chains():
    # 同一组区间即使内部对齐方式有多种（任一侧 ? 免代价），也只算同一条链
    r = locate_quotes(["甲?丙", "甲?丙"], ["甲", "甲"])
    assert r["total_cost"] == 0
    assert [(h["start"], h["end"]) for h in r["hits"]] == [(0, 1), (1, 2)]


def test_no_chain_when_only_overlapping_candidates_422():
    # 两段引文各自都有代价 ≤ 2 的区间，但可行区间顺序相反、无法不重叠
    with pytest.raises(QuotesNotFoundError):
        locate_quotes(["甲甲乙乙", "甲甲乙乙"], ["乙乙XX", "甲甲XX"])


def test_one_quote_without_acceptable_interval_422():
    with pytest.raises(QuotesNotFoundError) as exc:
        locate_quotes(SEGMENTS, ["学", "朋朋朋朋"])
    assert "第 2 段引文" in str(exc.value)


def test_chain_uses_later_candidate_when_earliest_does_not_complete():
    # 第一段只有结尾区间可与第二段的开头区间贴合：两段独立候选很多，但完整链
    # 必须兼顾两侧，验证 DP 考虑各段全部合格候选而非只取各自最优。
    segs = ["乙甲甲乙", "乙甲甲乙"]  # 拼接文本即 "乙甲甲乙"
    r = locate_quotes(segs, ["乙", "甲甲"])
    # "甲甲" 代价 0 区间为 [1,3)；"乙" 取 [0,1) 成链，总代价 0
    assert [(h["start"], h["end"], h["cost"]) for h in r["hits"]] == [
        (0, 1, 0),
        (1, 3, 0),
    ]


def test_assembly_gate_failure_propagates():
    with pytest.raises(AssemblyError) as exc:
        locate_quotes(
            ["孔子曰未知", "未知生焉", "完全无关文本"],
            ["孔子", "未知"],
        )
    assert exc.value.failed_segment == 2


def test_quote_count_and_length_validated():
    with pytest.raises(ValueError):
        locate_quotes(SEGMENTS, ["学"])  # 仅 1 段
    with pytest.raises(ValueError):
        locate_quotes(SEGMENTS, ["学"] * (MAX_QUOTES + 1))
    with pytest.raises(ValueError):
        locate_quotes(SEGMENTS, ["", "学"])
    with pytest.raises(ValueError):
        locate_quotes(SEGMENTS, ["学", "字" * (MAX_QUOTE_LEN + 1)])
    # 恰好 4 段、每段恰好 80 字通过参数校验（800 字同字文本必产生并列链 -> 409）
    segs = ["字" * 400, "字" * 400]
    with pytest.raises(QuotesTieError):
        locate_quotes(segs, ["字" * 80] * 2)


def test_candidate_intervals_enumerates_all_within_cap():
    # 单字 "?" 与每个字免代价：全部单字区间均为候选（代价 0）
    cands = _enumerate_candidate_intervals(TEXT, "?", MAX_COST)
    singles = [(s, e) for s, e, c in cands if c == 0]
    assert singles == [(i, i + 1) for i in range(len(TEXT))]
    # 代价 1/2 的更长窗口（插入）也保留
    assert (0, 2, 1) in cands and (0, 3, 2) in cands
    # 长度差超过 2 的窗口不枚举
    assert _enumerate_candidate_intervals("甲乙丙", "甲乙丙丁戊己", MAX_COST) == []


def _brute_chain(text, quotes):
    """朴素全链枚举：(最低总代价, 全部最优链)，链为 (start,end,cost) 列表。"""
    layers = [_enumerate_candidate_intervals(text, q, MAX_COST) for q in quotes]
    if any(not layer for layer in layers):
        return None

    best, chains = None, []

    def rec(k, pos, total, acc):
        nonlocal best, chains
        if k == len(layers):
            if best is None or total < best:
                best, chains = total, [acc]
            elif total == best:
                chains.append(acc)
            return
        for s, e, cost in layers[k]:
            if s >= pos:
                rec(k + 1, e, total + cost, [*acc, (s, e, cost)])

    rec(0, 0, 0, [])
    if best is None:
        return None
    chains.sort(key=lambda ch: [(s, e) for s, e, _ in ch])
    return best, chains


def test_locate_chain_matches_brute_force():
    random.seed(2026)
    for _ in range(400):
        text = "".join(random.choice("甲乙丙?") for _ in range(random.randint(2, 8)))
        k = random.randint(2, 3)
        quotes = [
            "".join(random.choice("甲乙丙?") for _ in range(random.randint(1, 4)))
            for _ in range(k)
        ]
        layers = [_enumerate_candidate_intervals(text, q, MAX_COST) for q in quotes]
        got = _locate_chain(layers)
        exp = _brute_chain(text, quotes)
        if exp is None:
            assert got is None
        else:
            assert got is not None
            assert got[0] == exp[0]
            # 接口只需两条按区间字典序最小的不同最优链
            assert got[1] == exp[1][:2]
