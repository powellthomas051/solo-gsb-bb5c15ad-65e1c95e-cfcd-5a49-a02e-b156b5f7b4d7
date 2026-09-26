"""异文校勘（collate）测试。"""

import pytest

from app.assembler import AssemblyError, assemble
from app.collator import _votes_at_position, collate


def test_no_variants_when_all_known_chars_agree():
    r = collate(["甲乙丙丁", "丙丁戊", "丁戊己庚"])
    assert r["text"] == "甲乙丙丁戊己庚"
    assert r["variants"] == []


def test_wildcard_fill_without_variant_excluded():
    # 段0 的 "?" 由段1 的 "时" 补入：只有一种已知字，补字位置不列入
    r = collate(["学而?习之", "时习之"])
    assert r["text"] == "学而时习之"
    assert r["variants"] == []


def test_question_mark_source_does_not_vote():
    # 输出仍为 "?"，所有来源原字都是 "?"，无已知字，不列入
    r = collate(["甲?丙丁", "丙丁戊"])
    assert r["text"] == "甲?丙丁戊"
    assert all(v["pos"] != 1 for v in r["variants"])


def test_two_way_variant_unique_majority_suggestion():
    r = collate(["甲乙丙丁戊己", "甲乙丙艮戊己", "甲乙丙丁戊己庚辛"])
    assert r["text"] == "甲乙丙丁戊己庚辛"
    assert len(r["variants"]) == 1
    v = r["variants"][0]
    assert v["pos"] == 3
    assert v["current"] == "丁"                    # 拼接保留左段字
    assert v["candidates"] == [
        {"char": "丁", "segments": [0, 2]},
        {"char": "艮", "segments": [1]},
    ]
    assert v["suggestion"] == "丁"                # 唯一最高票


def test_two_way_tie_suggestion_is_null():
    r = collate(["甲乙丙丁戊己", "甲乙丙艮戊己"])
    assert r["text"] == "甲乙丙丁戊己"
    v = r["variants"][0]
    assert v["pos"] == 3
    assert v["candidates"] == [
        {"char": "丁", "segments": [0]},
        {"char": "艮", "segments": [1]},
    ]
    assert v["suggestion"] is None                # 并列最高票


def test_three_way_variant_unique_top_and_ordering():
    r = collate(["甲乙丙丁戊", "甲乙丙丁戊", "甲乙丙艮戊", "甲乙丙辰戊"])
    v = r["variants"][0]
    assert v["pos"] == 3
    assert [c["char"] for c in v["candidates"]] == ["丁", "艮", "辰"]
    assert v["candidates"][0]["segments"] == [0, 1]
    assert v["suggestion"] == "丁"


def test_suggestion_can_differ_from_current_char():
    # 庚位由后加入的段主导（康 2 票 > 庚 1 票），但拼接文本仍是 "庚"
    r = collate(
        ["甲乙丙丁戊己", "甲乙丙艮戊己", "甲乙丙丁戊己庚辛", "戊己康辛", "戊己康辛"]
    )
    assert r["text"] == "甲乙丙丁戊己庚辛"
    positions = {v["pos"]: v for v in r["variants"]}
    at_3, at_6 = positions[3], positions[6]
    assert at_3["current"] == "丁" and at_3["suggestion"] == "丁"
    assert at_6["current"] == "庚"
    assert at_6["candidates"] == [
        {"char": "康", "segments": [3, 4]},
        {"char": "庚", "segments": [2]},
    ]
    assert at_6["suggestion"] == "康"             # 建议不等于当前字，且文本不改写


def test_candidates_ordered_by_votes_then_min_segment():
    # 1:1 并列时按最小支持段序号升序：丁(段0) 在 艮(段1) 前
    r = collate(["甲乙丙丁戊己", "甲乙丙艮戊己"])
    chars = [c["char"] for c in r["variants"][0]["candidates"]]
    assert chars == ["丁", "艮"]


def test_vote_uses_segment_as_unit_duplicate_source_counts_once():
    # 同段在同一输出位置的多个来源标记只计一次；"?" 不投票。
    # 按段去重先于 "?" 过滤（防御性：同一聚合位置上同段原字应一致）。
    segments = ["甲?丙", "甲丁丙"]
    votes = _votes_at_position(segments, [
        {"segment": 0, "pos": 1},  # "?"：不投票
        {"segment": 1, "pos": 1},  # 丁
        {"segment": 1, "pos": 1},  # 同段重复来源：忽略
    ])
    assert votes == {1: "丁"}
    votes = _votes_at_position(segments, [
        {"segment": 1, "pos": 1},
        {"segment": 1, "pos": 1},
    ])
    assert votes == {1: "丁"}


def test_votes_point_back_to_original_chars():
    segments = ["甲乙丙丁戊己", "甲乙丙艮戊己", "甲乙丙丁戊己庚辛"]
    r = collate(segments)
    sources = assemble(segments)["sources"]
    for v in r["variants"]:
        assert v["current"] == r["text"][v["pos"]]
        for c in v["candidates"]:
            for seg in c["segments"]:
                # 该支持段在此位置的来源所指原字必须就是候选字
                poses = [s["pos"] for s in sources[v["pos"]] if s["segment"] == seg]
                assert poses
                assert all(segments[seg][p] == c["char"] for p in poses)


def test_gate_failure_propagates_assembly_error():
    with pytest.raises(AssemblyError) as exc:
        collate(["孔子曰未知", "未知生焉", "完全无关文本"])
    assert exc.value.failed_segment == 2
