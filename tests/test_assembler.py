"""多段顺序拼接（assemble）测试。"""

import pytest

from app.assembler import AssemblyError, assemble


def test_two_segments_chain():
    r = assemble(["学而?习之", "时习之不亦"])
    assert r["text"] == "学而时习之不亦"
    sources = r["sources"]
    assert len(sources) == len(r["text"]) == 7
    # "?" 以新段"时"补字：补字双方来源均保留
    assert sources[2] == [{"segment": 0, "pos": 2}, {"segment": 1, "pos": 0}]
    assert sources[3] == [{"segment": 0, "pos": 3}, {"segment": 1, "pos": 1}]
    assert sources[4] == [{"segment": 0, "pos": 4}, {"segment": 1, "pos": 2}]
    assert sources[5] == [{"segment": 1, "pos": 3}]
    assert sources[6] == [{"segment": 1, "pos": 4}]
    # 仅首段独有的前缀
    assert sources[0] == [{"segment": 0, "pos": 0}]
    assert sources[1] == [{"segment": 0, "pos": 1}]


def test_three_segments_accumulate_sources():
    r = assemble(["甲乙丙丁", "丙丁戊", "丁戊己庚"])
    assert r["text"] == "甲乙丙丁戊己庚"
    sources = r["sources"]
    assert len(sources) == 7
    # "丁"由三段共同贡献
    assert sources[3] == [
        {"segment": 0, "pos": 3},
        {"segment": 1, "pos": 1},
        {"segment": 2, "pos": 0},
    ]
    # "戊"由后两段贡献
    assert sources[4] == [{"segment": 1, "pos": 2}, {"segment": 2, "pos": 1}]
    assert sources[6] == [{"segment": 2, "pos": 3}]


def test_sources_point_back_to_original_chars():
    segments = ["学而?习之", "时习之不", "之不亦乐乎"]
    r = assemble(segments)
    # 每个来源标记必须指回原始段中真实存在的下标
    for ch, srcs in zip(r["text"], r["sources"]):
        assert srcs  # 每个字至少有一个来源
        for s in srcs:
            seg, pos = s["segment"], s["pos"]
            assert 0 <= seg < len(segments)
            assert 0 <= pos < len(segments[seg])


def test_mismatch_conflict_keeps_both_sources():
    # 丙/丙 +2、丁/戌 异字 -2、戊/戊 +2：保留左字"丁"，冲突双方来源都保留
    r = assemble(["甲乙丙丁戊", "丙戌戊"])
    assert r["text"] == "甲乙丙丁戊"
    ding = r["sources"][3]
    assert {"segment": 0, "pos": 3} in ding  # 左段"丁"
    assert {"segment": 1, "pos": 1} in ding  # 右段"戌"


def test_unresolved_wildcard_preserved_with_source():
    r = assemble(["甲?丙丁", "丙丁戊"])
    assert r["text"] == "甲?丙丁戊"
    assert r["sources"][1] == [{"segment": 0, "pos": 1}]


def test_gate_requires_two_same_known_pairs():
    # 仅一对相同字（乙/乙）：score 为 2 但 match 列只有 1 个，拒绝
    with pytest.raises(AssemblyError) as exc:
        assemble(["甲乙丙", "乙"])
    assert exc.value.failed_segment == 1


def test_gate_non_positive_score_rejected():
    with pytest.raises(AssemblyError) as exc:
        assemble(["aa", "bb"])
    assert exc.value.failed_segment == 1


def test_failed_segment_index_is_zero_based():
    # 前两段可拼接，第三段无关：失败段序号为 2
    with pytest.raises(AssemblyError) as exc:
        assemble(["孔子曰未知", "未知生焉", "完全无关文本"])
    assert exc.value.failed_segment == 2


def test_no_fewer_than_two_segments():
    with pytest.raises(ValueError):
        assemble(["学而时习之"])
