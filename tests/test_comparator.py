"""双版本对勘（compare_editions）测试。"""

import pytest

from app.assembler import assemble
from app.comparator import (
    EditionAssemblyError,
    _edit_alignment,
    compare_editions,
)

LEFT3 = ["学而?习之", "时习之不", "之不亦乐乎"]  # 学而时习之不亦乐乎


def _blocks(left: str, right: str):
    """便捷封装：直接对两段已拼好的文本做对齐并返回 (代价, 歧义, 回溯列)。"""
    return _edit_alignment(left, right)


def test_identical_editions_have_no_blocks():
    r = compare_editions(LEFT3, LEFT3)
    # 段 0 的 ? 被同侧段 1 的“时”续接覆盖：版本文本保留前段 ?
    assert r["left_text"] == r["right_text"] == "学而?习之不亦乐乎"
    assert r["total_cost"] == 0
    assert r["ambiguous"] is False
    assert r["blocks"] == []


def test_wildcard_only_difference_is_zero_cost_no_blocks():
    # 左稿前段的 ? 被同侧后段“时”续接覆盖：版本文本保留 ?，
    # 与右稿已知字配对代价 0：视为完全一致，差异块为空
    r = compare_editions(["学而?习之", "时习之"], ["学而时习之", "时习之"])
    assert r["left_text"] == "学而?习之"
    assert r["right_text"] == "学而时习之"
    assert r["total_cost"] == 0
    assert r["ambiguous"] is False
    assert r["blocks"] == []


def test_covered_wildcard_not_rewritten_by_later_segment():
    # 左稿段 0 的 ? 被段 1 的“乙”覆盖：若改写成“乙”，与右稿 X 配对会误报
    # 代价 1 的替换块；保留 ? 后与已知字配对代价 0，零代价、无差异块
    r = compare_editions(["甲?丙丁", "乙丙丁"], ["甲X丙丁", "X丙丁"])
    assert r["left_text"] == "甲?丙丁"
    assert r["right_text"] == "甲X丙丁"
    assert r["total_cost"] == 0
    assert r["ambiguous"] is False
    assert r["blocks"] == []


def test_version_text_preserves_wildcard_but_keeps_assemble_sources():
    # 版本文本保留前段 ?，但逐字来源沿用 /api/assemble（? 与补字段双方都在）
    r = compare_editions(["学而?习之", "时习之不"], ["学而?习之", "时习之乎"])
    assert r["left_text"] == "学而?习之不"
    assert r["right_text"] == "学而?习之乎"
    assert r["total_cost"] == 1
    assert r["ambiguous"] is False
    # 差异块坐标、原文与 sources 与保留 ? 的输出文本一致
    block = r["blocks"][0]
    assert (block["left"]["start"], block["left"]["end"]) == (5, 6)
    assert block["left"]["fragment"] == "不"
    assert block["left"]["sources"] == [[{"segment": 1, "pos": 3}]]
    assert (block["right"]["start"], block["right"]["end"]) == (5, 6)
    assert block["right"]["fragment"] == "乎"
    assert block["right"]["sources"] == [[{"segment": 1, "pos": 3}]]
    # 拼接的补字行为不变：assemble 仍补为“时”，仅对勘版本文本保留 ?
    assert assemble(["学而?习之", "时习之不"])["text"] == "学而时习之不"


def test_substitution_block():
    r = compare_editions(
        ["甲乙丙丁戊己", "戊己庚辛"],       # 甲乙丙丁戊己庚辛
        ["甲乙丙X戊己", "戊己庚辛"],       # 甲乙丙X戊己庚辛
    )
    assert r["total_cost"] == 1
    assert r["ambiguous"] is False
    assert len(r["blocks"]) == 1
    block = r["blocks"][0]
    assert block["left"]["start"] == 3 and block["left"]["end"] == 4
    assert block["left"]["fragment"] == "丁"
    assert block["right"]["start"] == 3 and block["right"]["end"] == 4
    assert block["right"]["fragment"] == "X"
    assert len(block["left"]["sources"]) == len(block["right"]["sources"]) == 1


def test_deletion_block_left_only():
    r = compare_editions(
        ["甲乙丙丁戊己", "戊己庚辛"],       # 甲乙丙丁戊己庚辛
        ["甲乙丙戊己", "戊己庚辛"],         # 甲乙丙戊己庚辛
    )
    assert r["total_cost"] == 1
    assert r["ambiguous"] is False
    block = r["blocks"][0]
    assert (block["left"]["start"], block["left"]["end"]) == (3, 4)
    assert block["left"]["fragment"] == "丁"
    # 右侧在该块无字：空区间、空 sources
    assert (block["right"]["start"], block["right"]["end"]) == (3, 3)
    assert block["right"]["fragment"] == ""
    assert block["right"]["sources"] == []


def test_insertion_block_right_only():
    r = compare_editions(
        ["甲乙丙戊己", "戊己庚辛"],         # 甲乙丙戊己庚辛
        ["甲乙丙丁戊己", "戊己庚辛"],       # 甲乙丙丁戊己庚辛
    )
    assert r["total_cost"] == 1
    assert r["ambiguous"] is False
    block = r["blocks"][0]
    assert (block["left"]["start"], block["left"]["end"]) == (3, 3)
    assert block["left"]["fragment"] == ""
    assert block["left"]["sources"] == []
    assert (block["right"]["start"], block["right"]["end"]) == (3, 4)
    assert block["right"]["fragment"] == "丁"


def test_nonzero_runs_merge_consecutive_columns():
    # 甲X丙Y vs 甲乙丙丁：X/乙 一块、Y/丁 一块，中间 丙 为零代价列用于分块
    cost, cols, _ = _blocks("甲X丙Y", "甲乙丙丁")
    assert cost == 2
    nonzero_idx = [k for k, c in enumerate(cols) if c[2] != 0]
    assert nonzero_idx == [1, 3]

    r = compare_editions(["甲X丙Y己庚辛", "己庚辛"], ["甲乙丙丁己庚辛", "己庚辛"])
    assert r["total_cost"] == 2
    assert len(r["blocks"]) == 2
    b1, b2 = r["blocks"]
    assert b1["left"]["fragment"] == "X" and b1["right"]["fragment"] == "乙"
    assert b2["left"]["fragment"] == "Y" and b2["right"]["fragment"] == "丁"
    # 两块位置中间隔一个零代价字 丙（下标 2）
    assert b1["left"]["end"] <= b2["left"]["start"]


def test_consecutive_indel_columns_merge_into_one_block():
    # 左稿 甲XY丙丁、右稿 甲丙丁：连续两列删除必须合并为同一个差异块
    r = compare_editions(["甲XY丙丁", "丙丁"], ["甲丙丁", "丙丁"])
    assert r["total_cost"] == 2
    assert len(r["blocks"]) == 1
    block = r["blocks"][0]
    assert (block["left"]["start"], block["left"]["end"]) == (1, 3)
    assert block["left"]["fragment"] == "XY"
    assert (block["right"]["start"], block["right"]["end"]) == (1, 1)
    assert block["right"]["fragment"] == ""


def test_block_slices_match_source_intervals():
    r = compare_editions(
        ["甲乙丙丁戊己", "戊己庚辛"],
        ["甲乙丙丁戊己", "戊己庚辛壬"],   # 尾部多一“壬”
    )
    assert r["total_cost"] == 1
    block = r["blocks"][0]
    assert (block["left"]["start"], block["left"]["end"]) == (8, 8)
    assert block["left"]["fragment"] == ""
    assert (block["right"]["start"], block["right"]["end"]) == (8, 9)
    assert block["right"]["fragment"] == "壬"
    assert block["right"]["sources"] == [[{"segment": 1, "pos": 4}]]


def test_ambiguous_alignment_flagged():
    # 甲乙 vs 乙甲：替换替换 与 删除+插入 同为代价 2，存在多条最优路径
    cost, cols, ambiguous = _blocks("甲乙", "乙甲")
    assert cost == 2
    assert ambiguous is True
    # 固定择优（对角优先）：回溯为两列替换
    assert [(lp, rp) for lp, rp, c in cols] == [(0, 0), (1, 1)]


def test_tie_prefers_diagonal_then_delete_then_insert():
    # 甲丙 vs 甲乙丙：对角（甲-甲 0）后，乙 可有插入列与替换列同分，
    # 固定择优给出“插入乙”而非替换；该例唯一最优，不歧义。
    cost, cols, ambiguous = _blocks("甲丙", "甲乙丙")
    assert cost == 1 and ambiguous is False
    assert cols == [(0, 0, 0), (None, 1, 1), (1, 2, 0)]

    # 构造删除/插入同分并列：甲甲乙 vs 甲乙 —— 删除首“甲”或第二个“甲”
    # 两条删除路径代价均为 1。
    cost, cols, ambiguous = _blocks("甲甲乙", "甲乙")
    assert cost == 1 and ambiguous is True
    # 回溯起点优先消耗更早左字（删除先于对角仅在同分时按入边择优）
    assert sum(c for _, _, c in cols) == 1


def test_wildcard_pair_cost_zero_in_dp():
    cost, cols, ambiguous = _blocks("甲?丙", "甲乙丙")
    assert cost == 0 and ambiguous is False
    assert all(c == 0 for _, _, c in cols)


def test_assembly_failure_is_wrapped_with_side():
    with pytest.raises(EditionAssemblyError) as exc:
        compare_editions(
            ["孔子曰未知", "未知生焉", "完全无关文本"],
            LEFT3,
        )
    assert exc.value.side == "left"
    assert exc.value.failed_segment == 2

    with pytest.raises(EditionAssemblyError) as exc:
        compare_editions(
            LEFT3,
            ["孔子曰未知", "未知生焉", "完全无关文本"],
        )
    assert exc.value.side == "right"
    assert exc.value.failed_segment == 2


def test_sources_independent_between_sides():
    # 两侧段数不同，各自拼接、各自标记逐字来源，互不影响
    r = compare_editions(
        ["甲乙丙丁戊己", "丁戊己"],          # 甲乙丙丁戊己
        ["甲乙丙丁戊己", "丁戊己", "戊己庚"],  # 甲乙丙丁戊己庚
    )
    assert r["left_text"] == "甲乙丙丁戊己"
    assert r["right_text"] == "甲乙丙丁戊己庚"
    assert r["total_cost"] == 1
    block = r["blocks"][0]
    assert block["left"]["fragment"] == ""
    assert block["right"]["fragment"] == "庚"
    assert block["right"]["sources"] == [[{"segment": 2, "pos": 2}]]
