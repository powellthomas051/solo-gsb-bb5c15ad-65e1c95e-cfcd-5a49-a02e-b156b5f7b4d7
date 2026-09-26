"""通读证据路径（trace_reading）测试。"""

import pytest

from app.assembler import AssemblyError, assemble
from app.tracer import TraceReadingError, trace_reading

SEGS = ["学而?习之", "时习之不", "之不亦乐乎"]  # 学而时习之不亦乐乎
TEXT = "学而时习之不亦乐乎"


def test_reuses_assemble_text_and_sources():
    r = trace_reading(SEGS, 0, len(TEXT))
    assert r["text"] == assemble(SEGS)["text"] == TEXT
    assert r["start"] == 0 and r["end"] == 9
    assert r["interval_text"] == TEXT


def test_single_segment_interval_has_no_switch():
    # 区间 [2,6) 时习之不 完全可由段 1 连续覆盖
    r = trace_reading(SEGS, 2, 6)
    assert r["interval_text"] == "时习之不"
    assert r["switch_count"] == 0
    assert r["question_count"] == 0
    assert r["ambiguous"] is False
    assert len(r["legs"]) == 1
    leg = r["legs"][0]
    assert leg["segment"] == 1
    assert (leg["merged"]["start"], leg["merged"]["end"]) == (2, 6)
    assert leg["merged"]["fragment"] == "时习之不"
    assert (leg["original"]["start"], leg["original"]["end"]) == (0, 4)
    assert leg["original"]["fragment"] == "时习之不"
    # merged/original 等长且各自逐字来源为路径所选的唯一项
    assert len(leg["merged"]["sources"]) == len(leg["original"]["sources"]) == 4
    assert leg["merged"]["sources"] == [
        [{"segment": 1, "pos": p}] for p in range(4)
    ]
    assert r["switch_positions"] == []
    assert r["question_positions"] == []


def test_full_interval_min_switches_then_min_questions():
    r = trace_reading(SEGS, 0, 9)
    # 必须 0→1→2 两次换段；段 0 的 ? 必选一次（最早换段 0→1 也在重叠区内，
    # 但段 0 前缀“学而时习”含一个 ?），最少 ? 数为 1
    assert r["switch_count"] == 2
    assert r["question_count"] == 1
    assert [l["segment"] for l in r["legs"]] == [0, 1, 2]
    # 段 0 路径尽量长（字典序按段序号优先）：merged [0,4) 学而时习
    assert (r["legs"][0]["merged"]["start"], r["legs"][0]["merged"]["end"]) == (0, 4)
    assert r["legs"][0]["original"]["fragment"] == "学而?习"
    # 段 1 仅取重叠“之”
    assert r["legs"][1]["segment"] == 1
    assert r["legs"][1]["merged"]["fragment"] == "之"
    assert r["legs"][1]["original"]["fragment"] == "之"
    # 段 2 取后缀
    assert r["legs"][2]["merged"]["fragment"] == "不亦乐乎"
    assert r["legs"][2]["original"]["fragment"] == "不亦乐乎"
    # 换段交界：text[3]|text[4]（pos=4）与 text[4]|text[5]（pos=5）
    assert r["switch_positions"] == [
        {"pos": 4, "from_segment": 0, "to_segment": 1},
        {"pos": 5, "from_segment": 1, "to_segment": 2},
    ]
    # 所选 ? 位于拼接稿下标 2（段 0 原文下标 2，输出字“时”）
    assert r["question_positions"] == [
        {"pos": 2, "segment": 0, "original_pos": 2, "output_char": "时"}
    ]


def test_ambiguous_flags_other_equal_cost_path():
    # 换段 0→1 可发生在重叠区任一交界（pos=4 或 pos=5），两条路径同为
    # 2 换段、1 个 ?；返回按段序号序列取首者，ambiguous 为 True
    r = trace_reading(SEGS, 0, 9)
    assert r["ambiguous"] is True


def test_identical_overlapping_segments_ambiguous_but_zero_switches():
    r = trace_reading(["甲乙丙", "甲乙丙"], 0, 3)
    assert r["interval_text"] == "甲乙丙"
    assert r["switch_count"] == 0
    assert r["question_count"] == 0
    assert r["ambiguous"] is True  # 全程选段 0 或段 1 都同分
    # 字典序取首：全程段 0
    assert [l["segment"] for l in r["legs"]] == [0]
    assert r["legs"][0]["original"]["fragment"] == "甲乙丙"


def test_question_minimized_when_known_segment_available():
    # 段 0 的 ? 被段 1 已知字续接覆盖：全程走段 1 可不选任何 ?
    r = trace_reading(["甲?丙", "甲乙丙"], 0, 3)
    assert r["interval_text"] == "甲乙丙"
    assert r["switch_count"] == 0
    assert r["question_count"] == 0
    assert r["ambiguous"] is False
    assert [l["segment"] for l in r["legs"]] == [1]


def test_switches_minimized_before_questions():
    # 全程段 0：0 换段但选 1 个 ?；走段 1 可免 ? 却无法以更少换段做到覆盖
    # 全部字（X 仅段 0 有），故最优为 0 换段、1 个 ?
    r = trace_reading(["甲?丙X", "甲乙丙"], 0, 4)
    assert r["interval_text"] == "甲乙丙X"
    assert r["switch_count"] == 0
    assert r["question_count"] == 1
    assert [l["segment"] for l in r["legs"]] == [0]
    assert r["question_positions"] == [
        {"pos": 1, "segment": 0, "original_pos": 1, "output_char": "乙"}
    ]


def test_same_segment_positions_must_increment_by_one():
    # 段内有两个“甲”：连续取同段时原文下标须逐次 +1，不能跳字后又回到该段
    r = trace_reading(["甲甲乙", "甲甲乙"], 0, 3)
    assert r["interval_text"] == "甲甲乙"
    assert r["switch_count"] == 0
    assert [l["segment"] for l in r["legs"]] == [0]
    leg = r["legs"][0]
    assert (leg["original"]["start"], leg["original"]["end"]) == (0, 3)
    # 选段 0 或段 1 全程等价
    assert r["ambiguous"] is True


def test_switch_requires_double_coverage_on_both_sides():
    # 拼接 甲乙丙Y丙：seg0=甲乙丙 与 seg1=甲乙XY丙 对齐时，seg1 的 X 为空缺列、
    # Y 插入（pos3 仅段 1 有，且 Y 之后段 1 从 pos4“丙”继续，无法以原文下标逐次
    # +1 从 Y 接到任一“丙”——Y 前一段 1 的“丙”在 pos2，跳不到 pos4）；共同覆盖
    # 仅甲乙丙(pos0-2)，换入段 1 覆盖 Y 后，换后侧再无 0/1 共同覆盖字可作换段
    # 见证，整条区间无完整路径
    with pytest.raises(TraceReadingError):
        trace_reading(["甲乙丙", "甲乙XY丙"], 0, 5)


def test_gap_island_subinterval_also_untraceable():
    # 区间 [1,5) 乙丙Y丙 同样包含孤岛 Y，无完整路径
    with pytest.raises(TraceReadingError):
        trace_reading(["甲乙丙", "甲乙XY丙"], 1, 5)


def test_switch_witness_need_not_be_adjacent_to_boundary():
    # 交界两侧的共同覆盖见证字不必紧贴交界（“至少一字”是对两侧整段的存在性）。
    # 拼接 甲乙丙丁戌戊：pos4“戌”仅段 1 有（冲突位），pos3“丁”/pos5“戊”都同时
    # 有两段来源；走段 0[甲乙丙丁] → 段 1[戌戊] 时，换前侧共同覆盖见证可在交界
    # pos4 之前的丁、换后侧共同覆盖见证可在交界之后的戊，故整条路径合法。
    r = trace_reading(["甲乙丙丁戊", "丁戌戊"], 0, 6)
    assert r["interval_text"] == "甲乙丙丁戌戊"
    assert r["switch_count"] == 1
    assert r["question_count"] == 0
    assert [l["segment"] for l in r["legs"]] == [0, 1]
    assert r["legs"][0]["merged"]["fragment"] == "甲乙丙丁"
    assert r["legs"][1]["merged"]["fragment"] == "戌戊"
    assert r["switch_positions"] == [
        {"pos": 4, "from_segment": 0, "to_segment": 1}
    ]


def test_subinterval_conflict_char_only_traceable_inside_overlap():
    # 区间 [3,6) 丁戌戊 内“戌”虽仅段 1 有，但走段 1 丁戌戊（pos0,1,2）连续
    r = trace_reading(["甲乙丙丁戊", "丁戌戊"], 3, 6)
    assert r["interval_text"] == "丁戌戊"
    assert r["switch_count"] == 0
    assert [l["segment"] for l in r["legs"]] == [1]
    assert r["legs"][0]["original"]["fragment"] == "丁戌戊"


def test_conflict_char_can_only_be_evidenced_by_its_own_segment():
    # pos5“戊”：段 0 pos4 与段 1 pos2 皆为合格来源，字典序取段 0
    r = trace_reading(["甲乙丙丁戊", "丁戌戊"], 5, 6)
    assert r["interval_text"] == "戊"
    assert r["legs"][0]["segment"] == 0
    # pos4“戌”：仅段 1 pos1 合格（段 0 该来源原字“戊”为异字，不可作证据）
    r2 = trace_reading(["甲乙丙丁戊", "丁戌戊"], 4, 5)
    assert r2["interval_text"] == "戌"
    assert r2["legs"][0]["segment"] == 1
    assert r2["legs"][0]["original"]["fragment"] == "戌"


def test_empty_interval_rejected():
    with pytest.raises(TraceReadingError):
        trace_reading(["甲乙丙丁戊己", "戊己庚辛"], 0, 0)
    with pytest.raises(TraceReadingError):
        trace_reading(["甲乙丙丁戊己", "戊己庚辛"], 3, 3)


def test_end_past_text_length_rejected():
    with pytest.raises(TraceReadingError):
        trace_reading(["甲乙丙丁戊己", "戊己庚辛"], 0, 9)


def test_negative_interval_rejected():
    with pytest.raises(TraceReadingError):
        trace_reading(["甲乙丙丁戊己", "戊己庚辛"], -1, 3)
    with pytest.raises(TraceReadingError):
        trace_reading(["甲乙丙丁戊己", "戊己庚辛"], 0, -2)


def test_assembly_failure_propagates():
    with pytest.raises(AssemblyError) as exc:
        trace_reading(["孔子曰未知", "未知生焉", "完全无关文本"], 0, 3)
    assert exc.value.failed_segment == 2


def test_legs_cover_interval_without_gap_or_overlap():
    r = trace_reading(SEGS, 0, 9)
    # 各路径段拼接稿区间首尾相接、恰好覆盖 [0,9)
    bounds = [(l["merged"]["start"], l["merged"]["end"]) for l in r["legs"]]
    assert bounds[0][0] == 0 and bounds[-1][1] == 9
    for (_, e1), (s2, _) in zip(bounds, bounds[1:]):
        assert e1 == s2
    # 原文区间长度与拼接稿区间长度一致，且原文下标连续
    for leg in r["legs"]:
        m, o = leg["merged"], leg["original"]
        assert m["end"] - m["start"] == o["end"] - o["start"]
        assert all(
            src == [{"segment": leg["segment"], "pos": o["start"] + k}]
            for k, src in enumerate(o["sources"])
        )
