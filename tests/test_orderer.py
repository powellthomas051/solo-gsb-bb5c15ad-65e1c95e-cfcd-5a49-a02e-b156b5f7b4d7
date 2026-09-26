"""未排序转写阅读顺序穷举（orderer）测试。"""

import pytest

from app.orderer import (
    NoCompleteOrderError,
    OrderTieError,
    determine_order,
)


def test_three_unsorted_segments_recover_order():
    # 正确阅读顺序为原下标 [1, 2, 0]：学而时习之不亦乐乎
    r = determine_order(["之不亦乐乎", "学而?习之", "时习之不"])
    assert r["order"] == [1, 2, 0]
    assert r["text"] == "学而时习之不亦乐乎"
    # 总分 = 两步对齐得分之和（4 + 4），不是原段两两相似度
    assert r["score"] == 8
    assert len(r["sources"]) == len(r["text"])


def test_four_unsorted_segments_recover_order():
    a, b, c, d = "学而?习之", "时习之不", "之不亦乐乎", "乐乎有朋自远方来"
    r = determine_order([d, b, a, c])
    assert r["order"] == [2, 1, 3, 0]
    assert r["text"] == "学而时习之不亦乐乎有朋自远方来"
    assert r["score"] == 12


def test_sources_tagged_with_original_input_indices():
    segments = ["之不亦乐乎", "学而?习之", "时习之不"]
    r = determine_order(segments)
    # 每个来源标记必须指回原始输入段中真实存在的下标
    for ch, srcs in zip(r["text"], r["sources"]):
        assert srcs
        for s in srcs:
            seg, pos = s["segment"], s["pos"]
            assert 0 <= seg < len(segments)
            assert 0 <= pos < len(segments[seg])
    # 首字"学"仅来自原下标 1 的段
    assert r["sources"][0] == [{"segment": 1, "pos": 0}]
    # "?" 补字双方来源保留（段 1 的 ? 与段 2 的"时"）
    assert r["sources"][2] == [
        {"segment": 1, "pos": 2},
        {"segment": 2, "pos": 0},
    ]
    # "之"由三段共同贡献
    assert r["sources"][4] == [
        {"segment": 0, "pos": 0},
        {"segment": 1, "pos": 4},
        {"segment": 2, "pos": 2},
    ]


def test_no_complete_order_raises():
    with pytest.raises(NoCompleteOrderError):
        determine_order(["孔子曰未知", "完全无关文本甲", "另一无关内容乙"])


def test_tie_raises_with_all_tied_orders():
    # 两个完全相同的重叠段：[0,1,2] 与 [0,2,1] 累计得分相同
    with pytest.raises(OrderTieError) as exc:
        determine_order(["甲乙丙丁", "丙丁戊", "丙丁戊"])
    assert exc.value.score == 10
    orders = [t["order"] for t in exc.value.tied]
    assert orders == [[0, 1, 2], [0, 2, 1]]
    # 并列结果各自带完整拼接文本与来源
    for t in exc.value.tied:
        assert t["text"] == "甲乙丙丁戊"
        assert len(t["sources"]) == len(t["text"])
        # 两个相同段最终都并入同一文本，戊 由两段共同贡献
        assert t["sources"][4] == [
            {"segment": 1, "pos": 2},
            {"segment": 2, "pos": 2},
        ]


def test_incomplete_orders_skipped_not_counted():
    # 只有一条链能走通（[0,1,2]），其余排列中途断链应被静默丢弃
    r = determine_order(["学而时习之", "习之不亦", "不亦乐乎"])
    assert r["order"] == [0, 1, 2]


def test_segment_count_out_of_range():
    with pytest.raises(ValueError):
        determine_order(["abc"])
    with pytest.raises(ValueError):
        determine_order(["a", "b", "c", "d", "e"])
