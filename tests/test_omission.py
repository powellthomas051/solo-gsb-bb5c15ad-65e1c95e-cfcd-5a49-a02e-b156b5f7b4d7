"""脱漏审计（audit_omission）测试。"""

import pytest

from app.assembler import AssemblyError, assemble
from app.omission import (
    MAX_GAP,
    MAX_REFERENCE_LEN,
    OmissionNotFoundError,
    OmissionRequirementError,
    OmissionTieError,
    _find_seams,
    audit_omission,
)

# text = AXCD；接缝位于 2（X|C，段 0 终止、段 2 进入）与 3（C|D，段 1 终止）
THREE_SEG_SEAMS = ["AX", "AXC", "XCD"]
# text = 甲乙丙丁戊己庚辛；唯一接缝位于 6（己|庚）
TWO_SEG = ["甲乙丙丁戊己", "戊己庚辛"]


def test_assemble_fixtures():
    assert assemble(THREE_SEG_SEAMS)["text"] == "AXCD"
    assert _find_seams(assemble(THREE_SEG_SEAMS)["sources"]) == [2, 3]
    assert assemble(TWO_SEG)["text"] == "甲乙丙丁戊己庚辛"
    assert _find_seams(assemble(TWO_SEG)["sources"]) == [6]


def test_unique_scheme_returns_position_missing_diff_and_sides():
    r = audit_omission(TWO_SEG, "甲乙丙丁戊己X庚辛")
    assert r["text"] == "甲乙丙丁戊己庚辛"
    assert r["reference"] == "甲乙丙丁戊己X庚辛"
    assert r["pos"] == 6
    assert r["missing"] == "X"
    assert r["diff"] == 0
    assert r["left"] == {
        "char": "己",
        "sources": [
            {"segment": 0, "pos": 5},
            {"segment": 1, "pos": 1},
        ],
    }
    assert r["right"] == {
        "char": "庚",
        "sources": [{"segment": 1, "pos": 2}],
    }


def test_missing_string_is_reference_fragment_at_seam():
    # gap=3：缺文即参照稿在插入位置处的连续 3 字
    r = audit_omission(TWO_SEG, "甲乙丙丁戊己XYZ庚辛")
    assert r["pos"] == 6
    assert r["missing"] == "XYZ"
    assert r["diff"] == 0


def test_wildcard_pair_costs_zero():
    r = audit_omission(TWO_SEG, "?乙丙丁戊己X庚?")
    assert r["pos"] == 6
    assert r["missing"] == "X"
    assert r["diff"] == 0


def test_known_mismatch_counts_one_up_to_max():
    r = audit_omission(TWO_SEG, "子乙丙丁戊己X庚辛")
    assert r["diff"] == 1
    r2 = audit_omission(TWO_SEG, "子丑丙丁戊己X庚辛")
    assert r2["diff"] == 2


def test_three_mismatches_raises_not_found():
    with pytest.raises(OmissionNotFoundError):
        audit_omission(TWO_SEG, "子丑寅丁戊己X庚辛")


def test_different_seams_tie_raises_conflict():
    # 参照 AXCCD：在接缝 2（X|C）或接缝 3（C|D）补 C 都逐位相同
    with pytest.raises(OmissionTieError) as exc:
        audit_omission(THREE_SEG_SEAMS, "AXCCD")
    assert exc.value.diff == 0
    positions = [s["pos"] for s in exc.value.ties]
    assert positions == [2, 3]
    for s in exc.value.ties:
        assert s["missing"] == "C"
        assert s["diff"] == 0
        assert len(s["left"]["sources"]) >= 1
        assert len(s["right"]["sources"]) >= 1
    assert exc.value.ties[0]["left"]["char"] == "X"
    assert exc.value.ties[0]["right"]["char"] == "C"
    assert exc.value.ties[1]["left"]["char"] == "C"
    assert exc.value.ties[1]["right"]["char"] == "D"


def test_tie_uses_minimum_diff_only():
    # 参照 "AZZZD"：接缝 2（前缀 AX/AZ=1、后缀 CD/ZD=1）与
    # 接缝 3（前缀 AXC/AZZ=2、后缀 D/D=0）异字数同为 2
    with pytest.raises(OmissionTieError) as exc:
        audit_omission(THREE_SEG_SEAMS, "AZZZD")
    assert exc.value.diff == 2
    assert [s["pos"] for s in exc.value.ties] == [2, 3]


def test_best_scheme_chosen_among_seams():
    # 接缝 2 插入 0 异字、接缝 3 插入 1 异字 -> 唯一取接缝 2
    # 参照 AXZCD：接缝2 补 Z 全同（diff 0）；接缝3 补 Z：前缀 AXC/AXZ=1 -> 唯一
    r = audit_omission(THREE_SEG_SEAMS, "AXZCD")
    assert r["pos"] == 2
    assert r["missing"] == "Z"
    assert r["diff"] == 0


def test_no_seam_raises_not_found():
    # 两段完全重叠：拼接文本无段间接缝
    with pytest.raises(OmissionNotFoundError):
        audit_omission(["甲乙丙", "甲乙丙"], "甲乙丙X")


def test_gap_bounds():
    # 等长（多 0 字）
    with pytest.raises(OmissionRequirementError):
        audit_omission(TWO_SEG, "甲乙丙丁戊己庚辛")
    # 参照更短
    with pytest.raises(OmissionRequirementError):
        audit_omission(TWO_SEG, "甲乙丙丁戊己庚")
    # 多 41 字
    with pytest.raises(OmissionRequirementError):
        audit_omission(TWO_SEG, "甲乙丙丁戊己" + "X" * 41 + "庚辛")


def test_gap_at_max_boundary_accepted():
    left = "子丑寅卯" * 100                       # 400 字
    right = "寅卯" + "辰巳午未" * 99 + "申"       # 400 字，重叠续接
    result = assemble([left, right])
    seams = _find_seams(result["sources"])
    p = seams[0]
    assert len(seams) >= 1
    reference = result["text"][:p] + "X" * MAX_GAP + result["text"][p:]
    assert len(reference) <= MAX_REFERENCE_LEN
    r = audit_omission([left, right], reference)
    assert r["pos"] == p
    assert len(r["missing"]) == MAX_GAP
    assert r["diff"] == 0


def test_reference_too_long_raises_before_assembly():
    with pytest.raises(OmissionRequirementError):
        audit_omission(TWO_SEG, "字" * (MAX_REFERENCE_LEN + 1))


def test_assembly_gate_failure_propagates():
    with pytest.raises(AssemblyError):
        audit_omission(["孔子曰未知", "未知生焉", "完全无关文本"], "字" * 12)


def test_only_adjacent_segment_transitions_are_seams():
    # 拼接首字之前（0）与末字之后（n）不是接缝
    sources = assemble(TWO_SEG)["sources"]
    seams = _find_seams(sources)
    assert all(1 <= p < len(sources) for p in seams)


def test_diff_rule_known_vs_wildcard_both_sides():
    # 参照侧 ? 与拼接侧 ? 均与已知字免异字
    r = audit_omission(["甲?丙丁戊己", "戊己庚辛"], "甲乙丙丁戊己?庚辛")
    # text = 甲?丙丁戊己庚辛（? 由对方“乙”补字仍记 ? 输出？检查实际拼接）
    assert r["diff"] == 0
    assert set(r["missing"]) <= {"?"}
