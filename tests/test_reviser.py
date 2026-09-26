"""人工校订（revise）测试。"""

import pytest

from app.assembler import AssemblyError, assemble
from app.reviser import (
    EditConflictError,
    EditLocationError,
    _locate_edits,
    revise,
)

SEGMENTS = ["学而?习之", "时习之不", "之不亦乐乎"]
# 拼接结果：学而时习之不亦乐乎
# 位置 4 "之" 的来源为 (0,4)、(1,2)、(2,0) 三段重叠


def test_single_edit_applies_and_sources_unchanged():
    r = revise(SEGMENTS, [{"segment": 2, "pos": 0, "char": "知"}])
    assert r["text"] == "学而时习知不亦乐乎"
    assert r["sources"] == assemble(SEGMENTS)["sources"]  # 沿用拼接来源
    assert r["changes"] == [{
        "pos": 4,
        "from_char": "之",
        "to_char": "知",
        "edits": [{"index": 0, "segment": 2, "pos": 0, "char": "知"}],
    }]


def test_overlapping_edits_same_char_merge_into_one_change():
    edits = [
        {"segment": 0, "pos": 4, "char": "知"},
        {"segment": 1, "pos": 2, "char": "知"},
        {"segment": 2, "pos": 0, "char": "知"},
    ]
    r = revise(SEGMENTS, edits)
    assert r["text"] == "学而时习知不亦乐乎"
    assert len(r["changes"]) == 1
    change = r["changes"][0]
    assert change["pos"] == 4 and change["from_char"] == "之" and change["to_char"] == "知"
    # 三项校订全部关联到同一处修改
    assert change["edits"] == [
        {"index": 0, "segment": 0, "pos": 4, "char": "知"},
        {"index": 1, "segment": 1, "pos": 2, "char": "知"},
        {"index": 2, "segment": 2, "pos": 0, "char": "知"},
    ]


def test_conflicting_edits_raise_conflict_error():
    edits = [
        {"segment": 0, "pos": 4, "char": "甲"},
        {"segment": 1, "pos": 2, "char": "乙"},  # 与上一项指向同一输出位置
        {"segment": 2, "pos": 4, "char": "丙"},  # 另一位置的正常校订不受影响地参与定位
    ]
    with pytest.raises(EditConflictError) as exc:
        revise(SEGMENTS, edits)
    conflicts = exc.value.conflicts
    assert len(conflicts) == 1
    assert conflicts[0]["pos"] == 4
    assert conflicts[0]["edits"] == [
        {"index": 0, "segment": 0, "pos": 4, "char": "甲"},
        {"index": 1, "segment": 1, "pos": 2, "char": "乙"},
    ]


def test_multiple_conflict_positions_reported_together():
    edits = [
        {"segment": 0, "pos": 4, "char": "甲"},
        {"segment": 2, "pos": 0, "char": "乙"},   # 位置 4 冲突
        {"segment": 1, "pos": 3, "char": "丙"},
        {"segment": 2, "pos": 1, "char": "丁"},   # 位置 5 冲突
    ]
    with pytest.raises(EditConflictError) as exc:
        revise(SEGMENTS, edits)
    assert [c["pos"] for c in exc.value.conflicts] == [4, 5]


def test_changes_sorted_by_position_regardless_of_edit_order():
    edits = [
        {"segment": 2, "pos": 4, "char": "哉"},   # 位置 8
        {"segment": 0, "pos": 0, "char": "孔"},   # 位置 0
    ]
    r = revise(SEGMENTS, edits)
    assert r["text"] == "孔而时习之不亦乐哉"
    assert [c["pos"] for c in r["changes"]] == [0, 8]
    assert r["changes"][0]["from_char"] == "学"
    assert r["changes"][1]["from_char"] == "乎"


def test_untouched_positions_keep_original_chars():
    r = revise(SEGMENTS, [{"segment": 0, "pos": 0, "char": "孔"}])
    assert r["text"][1:] == assemble(SEGMENTS)["text"][1:]


def test_edit_on_unresolved_wildcard_position():
    # 拼接文本在位置 1 仍是 "?"，校订可直接落实
    r = revise(["甲?丙丁", "丙丁戊"], [{"segment": 0, "pos": 1, "char": "乙"}])
    assert r["text"] == "甲乙丙丁戊"
    assert r["changes"][0]["from_char"] == "?"


def test_empty_edits_return_text_unchanged():
    r = revise(SEGMENTS, [])
    assert r["text"] == assemble(SEGMENTS)["text"]
    assert r["changes"] == []


def test_segment_index_out_of_range():
    with pytest.raises(EditLocationError):
        revise(SEGMENTS, [{"segment": 3, "pos": 0, "char": "甲"}])


def test_pos_out_of_range():
    with pytest.raises(EditLocationError):
        revise(SEGMENTS, [{"segment": 0, "pos": 5, "char": "甲"}])  # 段 0 仅 5 字


def test_any_invalid_edit_aborts_whole_revision():
    # 第一项合法、第二项越界：整体失败，不产生部分修订
    with pytest.raises(EditLocationError):
        revise(SEGMENTS, [
            {"segment": 0, "pos": 0, "char": "孔"},
            {"segment": 9, "pos": 0, "char": "甲"},
        ])


def test_unmapped_coordinate_rejected():
    # 防御性：坐标合法但不在逐字来源中（未映射）
    with pytest.raises(EditLocationError):
        _locate_edits(
            ["甲乙"],
            [[{"segment": 0, "pos": 0}]],
            [{"segment": 0, "pos": 1, "char": "丙"}],
        )


def test_multi_mapped_coordinate_rejected():
    # 防御性：同一坐标出现在多个输出位置的来源中（多重映射）
    with pytest.raises(EditLocationError):
        _locate_edits(
            ["甲乙"],
            [[{"segment": 0, "pos": 0}], [{"segment": 0, "pos": 0}]],
            [{"segment": 0, "pos": 0, "char": "丙"}],
        )


def test_gate_failure_propagates_assembly_error():
    with pytest.raises(AssemblyError) as exc:
        revise(["孔子曰未知", "未知生焉", "完全无关文本"], [])
    assert exc.value.failed_segment == 2
