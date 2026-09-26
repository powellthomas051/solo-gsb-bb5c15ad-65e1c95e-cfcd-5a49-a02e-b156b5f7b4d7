"""核心对齐算法测试。"""

import pytest

from app.aligner import align


def test_exact_overlap():
    r = align("孔子曰未知", "未知生焉知死")
    assert r["score"] == 4                      # 未=未 +2，知=知 +2
    assert r["aligned_pairs"] == 2
    assert r["left_interval"] == {"start": 3, "end": 5, "text": "未知"}
    assert r["right_interval"] == {"start": 0, "end": 2, "text": "未知"}
    assert r["left_free_prefix"] == "孔子曰"
    assert r["right_free_suffix"] == "生焉知死"
    assert r["merged"] == "孔子曰未知生焉知死"
    assert r["conflicts"] == []


def test_wildcard_resolved_by_known_char():
    r = align("学而?习之", "时习之不亦")
    assert r["score"] == 4                      # ?/时 0，习/习 +2，之/之 +2
    assert r["aligned_pairs"] == 3
    assert r["left_interval"]["start"] == 2
    assert r["merged"] == "学而时习之不亦"      # "?" 以右段"时"补入
    assert r["resolved_wildcards"] == [
        {"segment": "left", "pos": 2, "resolved_char": "时"}
    ]
    assert r["conflicts"] == []


def test_mismatch_keeps_left_and_reports_both():
    r = align("甲乙丙丁", "丙戌戊")
    assert r["score"] == 0                      # 丙/丙 +2，丁/戌 -2
    assert r["aligned_pairs"] == 2
    assert r["merged"] == "甲乙丙丁戊"          # 异字保留左段"丁"
    assert r["conflicts"] == [
        {"left_pos": 3, "left_char": "丁", "right_pos": 1, "right_char": "戌"}
    ]


def test_gap_skips_right_char_for_better_match():
    # 右段的"戌"以空缺跳过，使左段"丁"对上右段"丁"
    r = align("甲乙丙丁", "丙戌丁戊")
    assert r["score"] == 1                      # 丙/丙 +2，空缺 -3，丁/丁 +2
    assert r["merged"] == "甲乙丙戌丁戊"
    assert [c["type"] for c in r["columns"]] == ["match", "gap_left", "match"]


def test_right_overhangs_left_costs_gap():
    r = align("bc", "abc")
    assert r["score"] == 1                      # 空缺 -3，b/b +2，c/c +2
    assert r["merged"] == "abc"
    assert r["columns"][0]["type"] == "gap_left"
    assert r["columns"][0]["score"] == -3       # 连续空缺首字 -3


def test_left_overhangs_right_costs_gap():
    r = align("abcde", "cd")
    assert r["score"] == 1                      # c/c +2，d/d +2，e/空缺 -3
    assert r["merged"] == "abcde"
    assert r["columns"][-1]["type"] == "gap_right"
    assert r["columns"][-1]["score"] == -3


def test_consecutive_gaps_extend_penalty():
    # 对齐 a/a、b/b 后，左段尾部 z、z、z 连续空缺：首字 -3、其余每字 -1
    r = align("abzzz", "ab")
    assert r["score"] == 2 + 2 - 3 - 1 - 1
    gap_cols = [c for c in r["columns"] if c["type"] == "gap_right"]
    assert [c["score"] for c in gap_cols] == [-3, -1, -1]


def test_tie_prefers_more_aligned_pairs():
    # 同分 2：起点 0 有 2 对（a/a、a/?），起点 1 仅 1 对（a/a）
    r = align("aa", "a?")
    assert r["score"] == 2
    assert r["aligned_pairs"] == 2
    assert r["left_interval"]["start"] == 0
    assert r["merged"] == "aa"


def test_tie_prefers_smaller_left_start():
    # 同分 4、同 2 对：起点 0 与起点 1 并列，取起点最小者
    r = align("aa", "aaa")
    assert r["score"] == 4
    assert r["aligned_pairs"] == 2
    assert r["left_interval"]["start"] == 0
    assert r["merged"] == "aaa"


def test_column_scores_sum_to_total():
    for left, right in [("学而?习之", "时习之不亦"), ("abcde", "cd"), ("bc", "abc")]:
        r = align(left, right)
        assert sum(c["score"] for c in r["columns"]) == r["score"]


def test_aligned_strings_cover_intervals():
    r = align("学而?习之", "时习之不亦")
    assert r["aligned_left"] == "?习之"
    assert r["aligned_right"] == "时习之"


def test_single_char_segments():
    r = align("甲", "甲")
    assert r["score"] == 2
    assert r["merged"] == "甲"
    r = align("?", "甲")
    assert r["score"] == 0
    assert r["merged"] == "甲"


def test_empty_segment_rejected():
    with pytest.raises(ValueError):
        align("", "abc")
    with pytest.raises(ValueError):
        align("abc", "")
