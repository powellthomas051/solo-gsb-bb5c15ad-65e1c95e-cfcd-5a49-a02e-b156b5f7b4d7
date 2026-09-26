"""移位审计（audit_transposition）测试。"""

import pytest

from app.assembler import AssemblyError, assemble
from app.transposition import (
    MAX_TEXT_LEN,
    TranspositionNotFoundError,
    TranspositionRequirementError,
    TranspositionTieError,
    audit_transposition,
)

# text = 甲乙丙丁戊己庚辛（8 字）
TWO_SEG = ["甲乙丙丁戊己", "戊己庚辛"]


def test_unique_solution_takes_shortest_moved_len():
    # 把 "丙丁" [2,4) 剪下后插入剩余文本 "甲乙戊己庚辛" 的下标 5
    # -> 甲乙戊己庚丙丁辛；等价的 "戊己庚" 左移为 3 字操作，最短长度 2 唯一
    r = audit_transposition(TWO_SEG, "甲乙戊己庚丙丁辛")
    assert r["text"] == "甲乙丙丁戊己庚辛"
    assert r["reference"] == "甲乙戊己庚丙丁辛"
    assert r["start"] == 2
    assert r["end"] == 4
    assert r["insert_at"] == 5
    assert r["moved"] == "丙丁"
    assert r["sources"] == [
        [{"segment": 0, "pos": 2}],
        [{"segment": 0, "pos": 3}],
    ]


def test_adjacent_swap_tie_returns_two_operations():
    # "丙丁" 右移两字与 "戊己" 左移两字同为 2 字操作，都使重排文本与参照稿吻合
    with pytest.raises(TranspositionTieError) as exc:
        audit_transposition(TWO_SEG, "甲乙戊己丙丁庚辛")
    assert exc.value.moved_len == 2
    ops = exc.value.ties
    assert len(ops) == 2
    assert [(o["start"], o["end"], o["insert_at"]) for o in ops] == [
        (2, 4, 4),
        (4, 6, 2),
    ]
    assert ops[0]["moved"] == "丙丁"
    assert ops[0]["sources"] == [
        [{"segment": 0, "pos": 2}],
        [{"segment": 0, "pos": 3}],
    ]
    assert ops[1]["moved"] == "戊己"
    assert ops[1]["sources"] == [
        [{"segment": 0, "pos": 4}, {"segment": 1, "pos": 0}],
        [{"segment": 0, "pos": 5}, {"segment": 1, "pos": 1}],
    ]


def test_move_suffix_to_front():
    # 插入下标 0：把末尾 "庚辛" 移到剩余文本最前
    r = audit_transposition(TWO_SEG, "庚辛甲乙丙丁戊己")
    assert (r["start"], r["end"], r["insert_at"]) == (6, 8, 0)
    assert r["moved"] == "庚辛"


def test_move_prefix_to_end():
    # 插入下标等于剩余文本长度：把开头 "甲乙" 移到剩余文本末尾
    r = audit_transposition(TWO_SEG, "丙丁戊己庚辛甲乙")
    assert (r["start"], r["end"], r["insert_at"]) == (0, 2, 6)
    assert r["moved"] == "甲乙"


def test_wildcard_in_reference_counts_as_match():
    # 参照稿第 7 字为 ?：与重排文本的 "丁" 免异字配对；
    # 2 字操作 (2,4,5) 的移位片段 "丙丁" 只剩 1 个两侧已知且相同的字，不合格，
    # 唯一解为 3 字操作 (4,7,2)
    r = audit_transposition(TWO_SEG, "甲乙戊己庚丙?辛")
    assert (r["start"], r["end"], r["insert_at"]) == (4, 7, 2)
    assert r["moved"] == "戊己庚"


def test_wildcard_in_text():
    # 拼接文本含 ?：? 与参照稿已知字免异字配对；
    # 2 字操作 (2,4,5) 的移位片段 "?丁" 只有 1 个两侧已知且相同的字，不合格
    segs = ["甲乙?丁戊己", "戊己庚辛"]
    assert assemble(segs)["text"] == "甲乙?丁戊己庚辛"
    r = audit_transposition(segs, "甲乙戊己庚?丁辛")
    assert (r["start"], r["end"], r["insert_at"]) == (4, 7, 2)
    assert r["moved"] == "戊己庚"


def test_single_char_move_not_allowed():
    # 交换末两字只需移动 1 字，但移位片段至少 2 字 -> 无解
    with pytest.raises(TranspositionNotFoundError):
        audit_transposition(TWO_SEG, "甲乙丙丁戊己辛庚")


def test_moved_len_over_max_not_allowed():
    # 参照稿需移动 13 字（或等价的 1 字）才能吻合，超出 2～12 字范围 -> 无解
    segs = ["甲乙丙丁戊己庚辛", "庚辛壬癸子丑寅卯"]
    assert assemble(segs)["text"] == "甲乙丙丁戊己庚辛壬癸子丑寅卯"
    with pytest.raises(TranspositionNotFoundError):
        audit_transposition(segs, "卯甲乙丙丁戊己庚辛壬癸子丑寅")


def test_no_solution_raises_not_found():
    # 参照稿含原稿没有的 "子"：任何移位都无法让该位置吻合
    with pytest.raises(TranspositionNotFoundError):
        audit_transposition(TWO_SEG, "甲乙丙丁戊己庚子")


def test_unequal_length_raises_requirement():
    with pytest.raises(TranspositionRequirementError):
        audit_transposition(TWO_SEG, "甲乙丙丁戊己庚辛壬")
    with pytest.raises(TranspositionRequirementError):
        audit_transposition(TWO_SEG, "甲乙丙丁戊己庚")


def test_no_known_conflict_raises_requirement():
    # 参照与原稿完全一致：无已知字冲突，不适用移位诊断
    with pytest.raises(TranspositionRequirementError):
        audit_transposition(TWO_SEG, "甲乙丙丁戊己庚辛")
    # 仅差 ?：? 与已知字免异字配对，仍无已知字冲突
    with pytest.raises(TranspositionRequirementError):
        audit_transposition(TWO_SEG, "甲乙丙?戊己庚辛")


def test_text_too_long_raises_requirement():
    left = "子丑寅卯" * 30                    # 120 字
    right = "寅卯" + "辰巳午未" * 30          # 122 字，重叠 "寅卯" 续接
    assert len(assemble([left, right])["text"]) == 240
    with pytest.raises(TranspositionRequirementError):
        audit_transposition([left, right], "字" * MAX_TEXT_LEN)


def test_reference_too_long_raises_before_assembly():
    with pytest.raises(TranspositionRequirementError):
        audit_transposition(TWO_SEG, "字" * (MAX_TEXT_LEN + 1))


def test_assembly_gate_failure_propagates():
    with pytest.raises(AssemblyError):
        audit_transposition(["孔子曰未知", "未知生焉", "完全无关文本"], "字" * 12)
