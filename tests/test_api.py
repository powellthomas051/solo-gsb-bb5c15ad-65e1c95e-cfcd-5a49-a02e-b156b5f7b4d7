"""API 接口测试。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_align_endpoint():
    resp = client.post("/api/align", json={"left": "学而?习之", "right": "时习之不亦"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 4
    assert data["merged"] == "学而时习之不亦"
    assert data["left_interval"] == {"start": 2, "end": 5, "text": "?习之"}
    assert data["right_interval"] == {"start": 0, "end": 3, "text": "时习之"}
    assert len(data["columns"]) == 3
    assert data["resolved_wildcards"] == [
        {"segment": "left", "pos": 2, "resolved_char": "时"}
    ]


def test_align_endpoint_with_conflict():
    resp = client.post("/api/align", json={"left": "甲乙丙丁", "right": "丙戌戊"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["merged"] == "甲乙丙丁戊"
    assert data["conflicts"] == [
        {"left_pos": 3, "left_char": "丁", "right_pos": 1, "right_char": "戌"}
    ]


def test_empty_segment_rejected():
    resp = client.post("/api/align", json={"left": "", "right": "abc"})
    assert resp.status_code == 422
    resp = client.post("/api/align", json={"left": "abc", "right": ""})
    assert resp.status_code == 422


def test_missing_field_rejected():
    resp = client.post("/api/align", json={"left": "abc"})
    assert resp.status_code == 422


def test_assemble_endpoint():
    resp = client.post(
        "/api/assemble",
        json={"segments": ["学而?习之", "时习之不", "之不亦乐乎"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "学而时习之不亦乐乎"
    sources = data["sources"]
    assert len(sources) == len(data["text"]) == 9
    # 相同字累积来源
    assert sources[4] == [
        {"segment": 0, "pos": 4},
        {"segment": 1, "pos": 2},
        {"segment": 2, "pos": 0},
    ]
    # "?" 补字双方来源保留
    assert sources[2] == [{"segment": 0, "pos": 2}, {"segment": 1, "pos": 0}]


def test_assemble_gate_failure_returns_422_with_segment_index():
    resp = client.post(
        "/api/assemble",
        json={"segments": ["孔子曰未知", "未知生焉", "完全无关文本"]},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["failed_segment"] == 2


def test_assemble_two_same_pairs_required():
    # 仅一对相同字：422 且指出失败的是第 2 段（序号 1）
    resp = client.post("/api/assemble", json={"segments": ["甲乙丙", "乙"]})
    assert resp.status_code == 422
    assert resp.json()["detail"]["failed_segment"] == 1


def test_assemble_too_few_or_many_segments_rejected():
    resp = client.post("/api/assemble", json={"segments": ["abc"]})
    assert resp.status_code == 422
    resp = client.post(
        "/api/assemble",
        json={"segments": ["aa", "bb", "cc", "dd", "ee", "ff"]},
    )
    assert resp.status_code == 422


def test_assemble_individual_segment_too_long_rejected():
    resp = client.post(
        "/api/assemble",
        json={"segments": ["a" * 500, "b" * 501]},
    )
    assert resp.status_code == 422


def test_assemble_total_too_long_rejected():
    resp = client.post(
        "/api/assemble",
        json={"segments": ["字" * 400, "字" * 401]},
    )
    assert resp.status_code == 422


def test_assemble_empty_segment_rejected():
    resp = client.post("/api/assemble", json={"segments": ["abc", ""]})
    assert resp.status_code == 422


def test_collate_endpoint_returns_variants():
    resp = client.post(
        "/api/collate",
        json={"segments": ["甲乙丙丁戊己", "甲乙丙艮戊己", "甲乙丙丁戊己庚辛"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "甲乙丙丁戊己庚辛"
    assert data["variants"] == [
        {
            "pos": 3,
            "current": "丁",
            "candidates": [
                {"char": "丁", "segments": [0, 2]},
                {"char": "艮", "segments": [1]},
            ],
            "suggestion": "丁",
        }
    ]


def test_collate_tie_suggestion_null():
    resp = client.post(
        "/api/collate",
        json={"segments": ["甲乙丙丁戊己", "甲乙丙艮戊己"]},
    )
    assert resp.status_code == 200
    v = resp.json()["variants"][0]
    assert v["suggestion"] is None
    assert [c["segments"] for c in v["candidates"]] == [[0], [1]]


def test_collate_wildcard_fill_not_listed():
    resp = client.post(
        "/api/collate",
        json={"segments": ["学而?习之", "时习之"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "学而时习之"
    assert data["variants"] == []


def test_collate_gate_failure_returns_422_with_segment_index():
    resp = client.post(
        "/api/collate",
        json={"segments": ["孔子曰未知", "未知生焉", "完全无关文本"]},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["failed_segment"] == 2


def test_collate_reuses_assemble_segment_limits():
    # 段数不足 / 超上限
    assert client.post("/api/collate", json={"segments": ["abc"]}).status_code == 422
    assert client.post(
        "/api/collate",
        json={"segments": ["aa", "bb", "cc", "dd", "ee", "ff"]},
    ).status_code == 422
    # 单段过长
    assert client.post(
        "/api/collate",
        json={"segments": ["a" * 500, "b" * 501]},
    ).status_code == 422
    # 总长超限
    assert client.post(
        "/api/collate",
        json={"segments": ["字" * 400, "字" * 401]},
    ).status_code == 422
    # 空段
    assert client.post("/api/collate", json={"segments": ["abc", ""]}).status_code == 422
    # 缺字段
    assert client.post("/api/collate", json={}).status_code == 422


def test_order_endpoint_recovers_order():
    resp = client.post(
        "/api/order",
        json={"segments": ["之不亦乐乎", "学而?习之", "时习之不"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["order"] == [1, 2, 0]
    assert data["score"] == 8
    assert data["text"] == "学而时习之不亦乐乎"
    assert len(data["sources"]) == len(data["text"])
    # 来源按原输入下标标记：首字仅来自原下标 1 的段
    assert data["sources"][0] == [{"segment": 1, "pos": 0}]


def test_order_endpoint_accepts_four_segments():
    resp = client.post(
        "/api/order",
        json={
            "segments": [
                "乐乎有朋自远方来",
                "时习之不",
                "学而?习之",
                "之不亦乐乎",
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["order"] == [2, 1, 3, 0]
    assert data["text"] == "学而时习之不亦乐乎有朋自远方来"


def test_order_tie_returns_409_with_all_orders():
    resp = client.post(
        "/api/order",
        json={"segments": ["甲乙丙丁", "丙丁戊", "丙丁戊"]},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["score"] == 10
    assert [t["order"] for t in detail["ties"]] == [[0, 1, 2], [0, 2, 1]]
    for t in detail["ties"]:
        assert t["score"] == 10
        assert t["text"] == "甲乙丙丁戊"
        assert len(t["sources"]) == len(t["text"])


def test_order_no_complete_order_returns_422():
    resp = client.post(
        "/api/order",
        json={"segments": ["孔子曰未知", "完全无关文本甲", "另一无关内容乙"]},
    )
    assert resp.status_code == 422
    assert "message" in resp.json()["detail"]


def test_order_segment_limits_validated():
    # 段数不足 / 超上限（2～4 段）
    assert client.post("/api/order", json={"segments": ["abc"]}).status_code == 422
    assert client.post(
        "/api/order",
        json={"segments": ["aa", "bb", "cc", "dd", "ee"]},
    ).status_code == 422
    # 单段超过 100 字
    assert client.post(
        "/api/order",
        json={"segments": ["a" * 101, "bb"]},
    ).status_code == 422
    # 总长超过 240 字
    assert client.post(
        "/api/order",
        json={"segments": ["字" * 90, "字" * 90, "字" * 61]},
    ).status_code == 422
    # 空段 / 缺字段
    assert client.post("/api/order", json={"segments": ["abc", ""]}).status_code == 422
    assert client.post("/api/order", json={}).status_code == 422


def test_order_boundary_lengths_accepted():
    # 单段恰好 100 字、总长恰好 240 字可通过参数校验
    resp = client.post(
        "/api/order",
        json={"segments": ["字" * 100, "字" * 100, "字" * 40]},
    )
    # 参数合法；三段同为重复字，排列必有并列 -> 409
    assert resp.status_code == 409


def test_revise_endpoint():
    resp = client.post(
        "/api/revise",
        json={
            "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
            "edits": [{"segment": 2, "pos": 0, "char": "知"}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "学而时习知不亦乐乎"
    # sources 沿用 /api/assemble 的拼接结果
    assert data["sources"] == client.post(
        "/api/assemble",
        json={"segments": ["学而?习之", "时习之不", "之不亦乐乎"]},
    ).json()["sources"]
    assert data["changes"] == [{
        "pos": 4,
        "from_char": "之",
        "to_char": "知",
        "edits": [{"index": 0, "segment": 2, "pos": 0, "char": "知"}],
    }]


def test_revise_merges_overlapping_edits_with_same_char():
    # 位置 4 "之" 由段 0/1/2 重叠贡献，三项校订改字相同 -> 合并为一处修改
    resp = client.post(
        "/api/revise",
        json={
            "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
            "edits": [
                {"segment": 0, "pos": 4, "char": "知"},
                {"segment": 1, "pos": 2, "char": "知"},
                {"segment": 2, "pos": 0, "char": "知"},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "学而时习知不亦乐乎"
    assert len(data["changes"]) == 1
    assert [e["index"] for e in data["changes"][0]["edits"]] == [0, 1, 2]


def test_revise_conflict_returns_409():
    # 同一输出位置被指向不同改字
    resp = client.post(
        "/api/revise",
        json={
            "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
            "edits": [
                {"segment": 0, "pos": 4, "char": "甲"},
                {"segment": 1, "pos": 2, "char": "乙"},
            ],
        },
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert [c["pos"] for c in detail["conflicts"]] == [4]
    assert detail["conflicts"][0]["edits"] == [
        {"index": 0, "segment": 0, "pos": 4, "char": "甲"},
        {"index": 1, "segment": 1, "pos": 2, "char": "乙"},
    ]


def test_revise_out_of_range_coordinate_returns_422():
    base = {"segments": ["学而?习之", "时习之不", "之不亦乐乎"]}
    # 段序号越界
    resp = client.post("/api/revise", json={**base, "edits": [{"segment": 3, "pos": 0, "char": "甲"}]})
    assert resp.status_code == 422
    # 原文下标越界（段 0 仅 5 字）
    resp = client.post("/api/revise", json={**base, "edits": [{"segment": 0, "pos": 5, "char": "甲"}]})
    assert resp.status_code == 422


def test_revise_invalid_edit_rejected_422():
    base = {"segments": ["学而?习之", "时习之不", "之不亦乐乎"]}
    # 替换字为 "?"
    assert client.post(
        "/api/revise", json={**base, "edits": [{"segment": 0, "pos": 0, "char": "?"}]}
    ).status_code == 422
    # 替换字不是单个字符
    assert client.post(
        "/api/revise", json={**base, "edits": [{"segment": 0, "pos": 0, "char": "甲乙"}]}
    ).status_code == 422
    assert client.post(
        "/api/revise", json={**base, "edits": [{"segment": 0, "pos": 0, "char": ""}]}
    ).status_code == 422
    # 段序号 / 下标为负数
    assert client.post(
        "/api/revise", json={**base, "edits": [{"segment": -1, "pos": 0, "char": "甲"}]}
    ).status_code == 422
    assert client.post(
        "/api/revise", json={**base, "edits": [{"segment": 0, "pos": -1, "char": "甲"}]}
    ).status_code == 422
    # 缺 edits 字段
    assert client.post("/api/revise", json=base).status_code == 422


def test_revise_no_partial_revision_on_invalid_edit():
    # 第一项合法、第二项越界：整体 422，不返回修订文本
    resp = client.post(
        "/api/revise",
        json={
            "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
            "edits": [
                {"segment": 0, "pos": 0, "char": "孔"},
                {"segment": 9, "pos": 0, "char": "甲"},
            ],
        },
    )
    assert resp.status_code == 422
    assert "text" not in resp.json()


def test_revise_empty_edits_returns_assembled_text():
    resp = client.post(
        "/api/revise",
        json={"segments": ["学而?习之", "时习之不", "之不亦乐乎"], "edits": []},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "学而时习之不亦乐乎"
    assert data["changes"] == []


def test_revise_gate_failure_returns_422_with_failed_segment():
    resp = client.post(
        "/api/revise",
        json={
            "segments": ["孔子曰未知", "未知生焉", "完全无关文本"],
            "edits": [{"segment": 0, "pos": 0, "char": "甲"}],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["failed_segment"] == 2


def test_locate_quote_endpoint_unique_hit():
    resp = client.post(
        "/api/locate-quote",
        json={
            "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
            "quote": "时习之",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "学而时习之不亦乐乎"
    assert data["quote"] == "时习之"
    assert data["start"] == 2 and data["end"] == 5
    assert data["fragment"] == "时习之"
    assert data["cost"] == 0
    assert len(data["sources"]) == 3
    # sources 与 /api/assemble 对应区间一致
    assert data["sources"] == client.post(
        "/api/assemble",
        json={"segments": ["学而?习之", "时习之不", "之不亦乐乎"]},
    ).json()["sources"][2:5]


def test_locate_quote_endpoint_wildcard_and_cost():
    # 任一侧 ? 代价 0
    resp = client.post(
        "/api/locate-quote",
        json={"segments": ["甲?丙丁", "丙丁戊"], "quote": "甲乙丙丁"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["fragment"] == "甲?丙丁" and data["cost"] == 0

    # 代价 1 的替换唯一命中
    resp = client.post(
        "/api/locate-quote",
        json={
            "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
            "quote": "学而时习之不亦悦乎",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["cost"] == 1
    assert (resp.json()["start"], resp.json()["end"]) == (0, 9)


def test_locate_quote_tie_returns_409():
    resp = client.post(
        "/api/locate-quote",
        json={"segments": ["甲子丙丁卯", "丁卯甲庚"], "quote": "甲"},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["cost"] == 0
    assert [(t["start"], t["end"]) for t in detail["ties"]] == [(0, 1), (5, 6)]
    for t in detail["ties"]:
        assert t["fragment"] == "甲" and t["cost"] == 0
        assert len(t["sources"]) == 1


def test_locate_quote_no_match_returns_422():
    resp = client.post(
        "/api/locate-quote",
        json={
            "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
            "quote": "朋朋朋朋",
        },
    )
    assert resp.status_code == 422
    assert "message" in resp.json()["detail"]


def test_locate_quote_gate_failure_returns_422_with_failed_segment():
    resp = client.post(
        "/api/locate-quote",
        json={
            "segments": ["孔子曰未知", "未知生焉", "完全无关文本"],
            "quote": "孔子",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["failed_segment"] == 2


def test_locate_quote_reuses_assemble_segment_limits():
    # 段数不足 / 超上限
    assert client.post(
        "/api/locate-quote", json={"segments": ["abc"], "quote": "a"}
    ).status_code == 422
    assert client.post(
        "/api/locate-quote",
        json={"segments": ["aa", "bb", "cc", "dd", "ee", "ff"], "quote": "a"},
    ).status_code == 422
    # 单段过长 / 总长超限 / 空段
    assert client.post(
        "/api/locate-quote",
        json={"segments": ["a" * 500, "b" * 501], "quote": "a"},
    ).status_code == 422
    assert client.post(
        "/api/locate-quote",
        json={"segments": ["字" * 400, "字" * 401], "quote": "a"},
    ).status_code == 422
    assert client.post(
        "/api/locate-quote", json={"segments": ["abc", ""], "quote": "a"}
    ).status_code == 422


def test_locate_quote_quote_length_validated():
    base = {"segments": ["学而?习之", "时习之不"]}
    # 缺 quote 字段
    assert client.post("/api/locate-quote", json=base).status_code == 422
    # 空 quote
    assert client.post(
        "/api/locate-quote", json={**base, "quote": ""}
    ).status_code == 422
    # 81 字
    assert client.post(
        "/api/locate-quote", json={**base, "quote": "字" * 81}
    ).status_code == 422
    # 恰好 80 字可通过参数校验（是否命中不影响 422 校验语义）
    resp = client.post("/api/locate-quote", json={**base, "quote": "字" * 80})
    assert resp.status_code in (200, 409, 422)


def test_locate_quotes_endpoint_unique_chain():
    resp = client.post(
        "/api/locate-quotes",
        json={
            "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
            "quotes": ["学而", "时习之", "不亦乐乎"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "学而时习之不亦乐乎"
    assert data["quotes"] == ["学而", "时习之", "不亦乐乎"]
    assert data["total_cost"] == 0
    assert [(h["start"], h["end"], h["fragment"], h["cost"]) for h in data["hits"]] == [
        (0, 2, "学而", 0),
        (2, 5, "时习之", 0),
        (5, 9, "不亦乐乎", 0),
    ]
    # sources 与 /api/assemble 对应区间一致
    sources = client.post(
        "/api/assemble",
        json={"segments": ["学而?习之", "时习之不", "之不亦乐乎"]},
    ).json()["sources"]
    assert data["hits"][1]["sources"] == sources[2:5]


def test_locate_quotes_individual_best_unusable_still_completes():
    # 第二段引文单独的代价 0 候选 [0,1) 与第一段重叠，须改取代价 1 的 [1,2)
    resp = client.post(
        "/api/locate-quotes",
        json={"segments": ["甲乙", "甲乙"], "quotes": ["甲", "甲"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost"] == 1
    assert [(h["start"], h["end"], h["cost"]) for h in data["hits"]] == [
        (0, 1, 0),
        (1, 2, 1),
    ]


def test_locate_quotes_tie_returns_409_with_two_chains():
    resp = client.post(
        "/api/locate-quotes",
        json={"segments": ["甲丙甲丙", "甲丙甲丙"], "quotes": ["甲", "丙"]},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["cost"] == 0
    ties = detail["ties"]
    assert len(ties) == 2
    assert [[(h["start"], h["end"]) for h in ch] for ch in ties] == [
        [(0, 1), (1, 2)],
        [(0, 1), (3, 4)],
    ]
    for chain in ties:
        assert [h["fragment"] for h in chain] in (["甲", "丙"],)
        assert all(len(h["sources"]) == 1 for h in chain)


def test_locate_quotes_no_chain_returns_422():
    # 两段引文各自有 ≤2 的区间，但可行区间顺序相反、无法不重叠
    resp = client.post(
        "/api/locate-quotes",
        json={"segments": ["甲甲乙乙", "甲甲乙乙"], "quotes": ["乙乙XX", "甲甲XX"]},
    )
    assert resp.status_code == 422
    assert "message" in resp.json()["detail"]


def test_locate_quotes_one_quote_unmatchable_returns_422():
    resp = client.post(
        "/api/locate-quotes",
        json={
            "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
            "quotes": ["学", "朋朋朋朋"],
        },
    )
    assert resp.status_code == 422
    assert "第 2 段引文" in resp.json()["detail"]["message"]


def test_locate_quotes_gate_failure_returns_422_with_failed_segment():
    resp = client.post(
        "/api/locate-quotes",
        json={
            "segments": ["孔子曰未知", "未知生焉", "完全无关文本"],
            "quotes": ["孔子", "未知"],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["failed_segment"] == 2


def test_locate_quotes_reuses_assemble_segment_limits():
    body = {"quotes": ["甲", "乙"]}
    # 段数不足 / 超上限
    assert client.post("/api/locate-quotes", json={"segments": ["abc"], **body}).status_code == 422
    assert client.post(
        "/api/locate-quotes",
        json={"segments": ["aa", "bb", "cc", "dd", "ee", "ff"], **body},
    ).status_code == 422
    # 单段过长 / 总长超限 / 空段
    assert client.post(
        "/api/locate-quotes", json={"segments": ["a" * 500, "b" * 501], **body}
    ).status_code == 422
    assert client.post(
        "/api/locate-quotes", json={"segments": ["字" * 400, "字" * 401], **body}
    ).status_code == 422
    assert client.post(
        "/api/locate-quotes", json={"segments": ["abc", ""], **body}
    ).status_code == 422


def test_locate_quotes_quote_limits_validated():
    base = {"segments": ["学而?习之", "时习之不"]}
    # 缺 quotes 字段
    assert client.post("/api/locate-quotes", json=base).status_code == 422
    # 仅 1 段 / 5 段
    assert client.post("/api/locate-quotes", json={**base, "quotes": ["学"]}).status_code == 422
    assert client.post(
        "/api/locate-quotes", json={**base, "quotes": ["学"] * 5}
    ).status_code == 422
    # 空引文 / 81 字引文
    assert client.post(
        "/api/locate-quotes", json={**base, "quotes": ["", "学"]}
    ).status_code == 422
    assert client.post(
        "/api/locate-quotes", json={**base, "quotes": ["学", "字" * 81]}
    ).status_code == 422
    # 恰好 4 段、每段恰好 80 字可通过参数校验
    resp = client.post(
        "/api/locate-quotes", json={**base, "quotes": ["字" * 80] * 4}
    )
    assert resp.status_code in (200, 409, 422)


def test_find_repetition_endpoint_returns_pair():
    resp = client.post(
        "/api/find-repetition",
        json={"segments": ["学而时习之不亦朱雀", "朱雀玄武白虎腾蛇青龙学而时习之不亦"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "学而时习之不亦朱雀玄武白虎腾蛇青龙学而时习之不亦"
    rep = data["repeat"]
    assert rep is not None
    first, second = rep["first"], rep["second"]
    assert (first["start"], first["end"]) == (0, 7)
    assert (second["start"], second["end"]) == (17, 24)
    assert first["fragment"] == second["fragment"] == "学而时习之不亦"
    assert first["end"] <= second["start"]
    assert len(first["sources"]) == len(second["sources"]) == 7
    # 与 /api/assemble 的逐字来源一致
    sources = client.post(
        "/api/assemble",
        json={"segments": ["学而时习之不亦朱雀", "朱雀玄武白虎腾蛇青龙学而时习之不亦"]},
    ).json()["sources"]
    assert first["sources"] == sources[0:7]
    assert second["sources"] == sources[17:24]


def test_find_repetition_wildcard_pair():
    resp = client.post(
        "/api/find-repetition",
        json={"segments": ["甲乙丙丁戊己朱雀", "朱雀天地玄黄宇宙洪荒甲?丙丁戊?"]},
    )
    assert resp.status_code == 200
    rep = resp.json()["repeat"]
    assert rep is not None
    assert rep["first"]["fragment"] == "甲乙丙丁戊己"
    assert rep["second"]["fragment"] == "甲?丙丁戊?"


def test_find_repetition_none_returns_null():
    resp = client.post(
        "/api/find-repetition",
        json={"segments": ["甲乙丙丁戊己", "戊己庚辛壬"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "甲乙丙丁戊己庚辛壬"
    assert data["repeat"] is None


def test_find_repetition_gate_failure_returns_422():
    resp = client.post(
        "/api/find-repetition",
        json={"segments": ["孔子曰未知", "未知生焉", "完全无关文本"]},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["failed_segment"] == 2


def test_find_repetition_reuses_assemble_segment_limits():
    # 段数不足 / 超上限
    assert client.post("/api/find-repetition", json={"segments": ["abc"]}).status_code == 422
    assert client.post(
        "/api/find-repetition",
        json={"segments": ["aa", "bb", "cc", "dd", "ee", "ff"]},
    ).status_code == 422
    # 单段过长 / 总长超限 / 空段
    assert client.post(
        "/api/find-repetition",
        json={"segments": ["a" * 500, "b" * 501]},
    ).status_code == 422
    assert client.post(
        "/api/find-repetition",
        json={"segments": ["字" * 400, "字" * 401]},
    ).status_code == 422
    assert client.post(
        "/api/find-repetition", json={"segments": ["abc", ""]}
    ).status_code == 422


def test_audit_omission_endpoint_unique_scheme():
    resp = client.post(
        "/api/audit-omission",
        json={
            "segments": ["甲乙丙丁戊己", "戊己庚辛"],
            "reference": "甲乙丙丁戊己X庚辛",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "甲乙丙丁戊己庚辛"
    assert data["reference"] == "甲乙丙丁戊己X庚辛"
    assert data["pos"] == 6
    assert data["missing"] == "X"
    assert data["diff"] == 0
    assert data["left"] == {
        "char": "己",
        "sources": [
            {"segment": 0, "pos": 5},
            {"segment": 1, "pos": 1},
        ],
    }
    assert data["right"] == {
        "char": "庚",
        "sources": [{"segment": 1, "pos": 2}],
    }
    # 拼接文本与 /api/assemble 一致，接口不改写
    assert data["text"] == client.post(
        "/api/assemble", json={"segments": ["甲乙丙丁戊己", "戊己庚辛"]}
    ).json()["text"]


def test_audit_omission_multi_char_missing_and_diff():
    # 缺文 3 字；另带 1 个已知异字 -> diff 1
    resp = client.post(
        "/api/audit-omission",
        json={
            "segments": ["甲乙丙丁戊己", "戊己庚辛"],
            "reference": "子乙丙丁戊己XYZ庚辛",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["pos"] == 6
    assert data["missing"] == "XYZ"
    assert data["diff"] == 1


def test_audit_omission_wildcard_costs_zero():
    resp = client.post(
        "/api/audit-omission",
        json={
            "segments": ["甲乙丙丁戊己", "戊己庚辛"],
            "reference": "?乙丙丁戊己X庚?",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["diff"] == 0


def test_audit_omission_tie_returns_409():
    # text=AXCD，参照 AXCCD：接缝 2（X|C）、3（C|D）补 C 均 0 异字
    resp = client.post(
        "/api/audit-omission",
        json={"segments": ["AX", "AXC", "XCD"], "reference": "AXCCD"},
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["diff"] == 0
    assert [t["pos"] for t in detail["ties"]] == [2, 3]
    for t in detail["ties"]:
        assert t["missing"] == "C" and t["diff"] == 0
        assert t["left"]["char"] and t["right"]["char"]
        assert len(t["left"]["sources"]) >= 1
        assert len(t["right"]["sources"]) >= 1


def test_audit_omission_no_scheme_returns_422():
    # 参照与拼接稿字表完全不相交：任一接缝补入后异字数都超过 2
    resp = client.post(
        "/api/audit-omission",
        json={"segments": ["AX", "AXC", "XCD"], "reference": "子子子子子"},
    )
    assert resp.status_code == 422
    assert "message" in resp.json()["detail"]


def test_audit_omission_no_seam_returns_422():
    # 两段完全重叠：拼接文本无段间接缝
    resp = client.post(
        "/api/audit-omission",
        json={"segments": ["甲乙丙", "甲乙丙"], "reference": "甲乙丙X"},
    )
    assert resp.status_code == 422
    assert "接缝" in resp.json()["detail"]["message"]


def test_audit_omission_length_gap_validated():
    base = {"segments": ["甲乙丙丁戊己", "戊己庚辛"]}
    # 等长（多 0 字）/ 参照更短 / 多 41 字
    assert client.post(
        "/api/audit-omission", json={**base, "reference": "甲乙丙丁戊己庚辛"}
    ).status_code == 422
    assert client.post(
        "/api/audit-omission", json={**base, "reference": "甲乙丙丁戊己庚"}
    ).status_code == 422
    assert client.post(
        "/api/audit-omission",
        json={**base, "reference": "甲乙丙丁戊己" + "X" * 41 + "庚辛"},
    ).status_code == 422


def test_audit_omission_reference_limits_validated():
    base = {"segments": ["甲乙丙丁戊己", "戊己庚辛"]}
    # 缺 reference / 空 reference / 超 840 字
    assert client.post("/api/audit-omission", json=base).status_code == 422
    assert client.post(
        "/api/audit-omission", json={**base, "reference": ""}
    ).status_code == 422
    assert client.post(
        "/api/audit-omission", json={**base, "reference": "字" * 841}
    ).status_code == 422
    # 恰好 840 字可通过参数校验（长度差是否合格不影响 422 校验语义；
    # 该拼接仅 8 字，差 832 字 -> 语义 422）
    resp = client.post(
        "/api/audit-omission", json={**base, "reference": "字" * 840}
    )
    assert resp.status_code == 422


def test_audit_omission_reuses_assemble_segment_limits():
    body = {"reference": "甲乙丙丁戊己X庚辛"}
    # 段数不足 / 超上限
    assert client.post(
        "/api/audit-omission", json={"segments": ["abc"], **body}
    ).status_code == 422
    assert client.post(
        "/api/audit-omission",
        json={"segments": ["aa", "bb", "cc", "dd", "ee", "ff"], **body},
    ).status_code == 422
    # 单段过长 / 总长超限 / 空段
    assert client.post(
        "/api/audit-omission",
        json={"segments": ["a" * 500, "b" * 501], "reference": "a" * 9},
    ).status_code == 422
    assert client.post(
        "/api/audit-omission",
        json={"segments": ["字" * 400, "字" * 401], "reference": "字" * 9},
    ).status_code == 422
    assert client.post(
        "/api/audit-omission",
        json={"segments": ["abc", ""], **body},
    ).status_code == 422


def test_audit_omission_gate_failure_returns_422_with_failed_segment():
    resp = client.post(
        "/api/audit-omission",
        json={
            "segments": ["孔子曰未知", "未知生焉", "完全无关文本"],
            "reference": "孔子曰未知生焉X",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["failed_segment"] == 2


def test_audit_omission_index_lists_endpoint():
    info = client.get("/").json()
    assert info["audit_omission"] == "POST /api/audit-omission"


def test_compare_editions_endpoint_identical():
    body = ["学而?习之", "时习之不", "之不亦乐乎"]
    resp = client.post(
        "/api/compare-editions",
        json={"left_segments": body, "right_segments": body},
    )
    assert resp.status_code == 200
    data = resp.json()
    # 段 0 的 ? 被同侧段 1 的“时”续接覆盖：版本文本保留前段 ?
    assert data["left_text"] == data["right_text"] == "学而?习之不亦乐乎"
    assert data["total_cost"] == 0
    assert data["ambiguous"] is False
    assert data["blocks"] == []


def test_compare_editions_endpoint_substitution_block():
    resp = client.post(
        "/api/compare-editions",
        json={
            "left_segments": ["甲乙丙丁戊己", "戊己庚辛"],
            "right_segments": ["甲乙丙X戊己", "戊己庚辛"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost"] == 1
    assert data["ambiguous"] is False
    assert len(data["blocks"]) == 1
    block = data["blocks"][0]
    assert block["left"] == {
        "start": 3,
        "end": 4,
        "fragment": "丁",
        "sources": [[{"segment": 0, "pos": 3}]],
    }
    assert block["right"]["start"] == 3 and block["right"]["end"] == 4
    assert block["right"]["fragment"] == "X"
    assert len(block["right"]["sources"]) == 1


def test_compare_editions_endpoint_insertion_block():
    resp = client.post(
        "/api/compare-editions",
        json={
            "left_segments": ["甲乙丙戊己", "戊己庚辛"],
            "right_segments": ["甲乙丙丁戊己", "戊己庚辛"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost"] == 1 and data["ambiguous"] is False
    block = data["blocks"][0]
    assert block["left"] == {
        "start": 3,
        "end": 3,
        "fragment": "",
        "sources": [],
    }
    assert block["right"]["start"] == 3 and block["right"]["end"] == 4
    assert block["right"]["fragment"] == "丁"


def test_compare_editions_wildcard_is_zero_cost():
    resp = client.post(
        "/api/compare-editions",
        json={
            "left_segments": ["学而?习之", "时习之"],
            "right_segments": ["学而时习之", "时习之"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    # 左稿前段的 ? 被同侧后段“时”覆盖：版本文本保留 ?，与右稿已知字配对代价 0
    assert data["left_text"] == "学而?习之"
    assert data["right_text"] == "学而时习之"
    assert data["total_cost"] == 0 and data["blocks"] == []
    assert data["ambiguous"] is False


def test_compare_editions_covered_wildcard_not_rewritten():
    # 左稿段 0 的 ? 被段 1 的“乙”续接覆盖：保留 ? 后与右稿 X 配对代价 0；
    # 若改写成“乙”则会误报代价 1 的替换块
    resp = client.post(
        "/api/compare-editions",
        json={
            "left_segments": ["甲?丙丁", "乙丙丁"],
            "right_segments": ["甲X丙丁", "X丙丁"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["left_text"] == "甲?丙丁"
    assert data["right_text"] == "甲X丙丁"
    assert data["total_cost"] == 0
    assert data["ambiguous"] is False
    assert data["blocks"] == []


def test_compare_editions_preserves_wildcard_with_block_elsewhere():
    # 版本文本保留前段 ?，差异块坐标/原文/sources 与保留 ? 的输出文本一致
    resp = client.post(
        "/api/compare-editions",
        json={
            "left_segments": ["学而?习之", "时习之不"],
            "right_segments": ["学而?习之", "时习之乎"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["left_text"] == "学而?习之不"
    assert data["right_text"] == "学而?习之乎"
    assert data["total_cost"] == 1
    assert data["ambiguous"] is False
    assert data["blocks"] == [
        {
            "left": {
                "start": 5,
                "end": 6,
                "fragment": "不",
                "sources": [[{"segment": 1, "pos": 3}]],
            },
            "right": {
                "start": 5,
                "end": 6,
                "fragment": "乎",
                "sources": [[{"segment": 1, "pos": 3}]],
            },
        }
    ]
    # /api/assemble 的补字行为不变
    assert client.post(
        "/api/assemble", json={"segments": ["学而?习之", "时习之不"]}
    ).json()["text"] == "学而时习之不"


def test_compare_editions_consecutive_nonzero_columns_merge():
    resp = client.post(
        "/api/compare-editions",
        json={
            "left_segments": ["甲XY丙丁", "丙丁"],
            "right_segments": ["甲丙丁", "丙丁"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost"] == 2 and data["ambiguous"] is False
    assert len(data["blocks"]) == 1
    block = data["blocks"][0]
    assert block["left"]["fragment"] == "XY"
    assert block["right"]["fragment"] == ""
    assert (block["left"]["start"], block["left"]["end"]) == (1, 3)
    assert (block["right"]["start"], block["right"]["end"]) == (1, 1)


def test_compare_editions_ambiguous_flag():
    # 拼接稿 甲乙 vs 乙甲：两条最优路径（替换/替换 与 删除+插入+删除的等价形态）
    resp = client.post(
        "/api/compare-editions",
        json={
            "left_segments": ["甲乙戊己", "戊己"],
            "right_segments": ["乙甲戊己", "戊己"],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_cost"] == 2
    assert data["ambiguous"] is True
    # 固定择优（对角优先）：一个差异块，两侧各取一替换字
    assert len(data["blocks"]) == 1
    block = data["blocks"][0]
    assert block["left"]["fragment"] == "甲乙"
    assert block["right"]["fragment"] == "乙甲"


def test_compare_editions_gate_failure_returns_422_with_side():
    bad = ["孔子曰未知", "未知生焉", "完全无关文本"]
    good = ["学而?习之", "时习之不", "之不亦乐乎"]
    resp = client.post(
        "/api/compare-editions",
        json={"left_segments": bad, "right_segments": good},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["side"] == "left"
    assert detail["failed_segment"] == 2

    resp = client.post(
        "/api/compare-editions",
        json={"left_segments": good, "right_segments": bad},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["side"] == "right"
    assert detail["failed_segment"] == 2


def test_compare_editions_reuses_assemble_segment_limits():
    body = ["学而?习之", "时习之"]
    # left_segments 段数不足 / 超上限
    assert client.post(
        "/api/compare-editions",
        json={"left_segments": ["abc"], "right_segments": body},
    ).status_code == 422
    assert client.post(
        "/api/compare-editions",
        json={"left_segments": ["aa", "bb", "cc", "dd", "ee", "ff"],
              "right_segments": body},
    ).status_code == 422
    # right_segments 段数不足
    assert client.post(
        "/api/compare-editions",
        json={"left_segments": body, "right_segments": ["abc"]},
    ).status_code == 422
    # 单段过长 / 总长超限 / 空段（任一侧）
    assert client.post(
        "/api/compare-editions",
        json={"left_segments": ["a" * 500, "b" * 501], "right_segments": body},
    ).status_code == 422
    assert client.post(
        "/api/compare-editions",
        json={"left_segments": body, "right_segments": ["字" * 400, "字" * 401]},
    ).status_code == 422
    assert client.post(
        "/api/compare-editions",
        json={"left_segments": body, "right_segments": ["abc", ""]},
    ).status_code == 422
    # 缺字段
    assert client.post(
        "/api/compare-editions", json={"left_segments": body}
    ).status_code == 422
    assert client.post("/api/compare-editions", json={}).status_code == 422


def test_compare_editions_index_lists_endpoint():
    info = client.get("/").json()
    assert info["compare_editions"] == "POST /api/compare-editions"


def test_trace_reading_endpoint_single_segment_leg():
    resp = client.post(
        "/api/trace-reading",
        json={
            "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
            "start": 2,
            "end": 6,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "学而时习之不亦乐乎"
    assert (data["start"], data["end"]) == (2, 6)
    assert data["interval_text"] == "时习之不"
    assert data["switch_count"] == 0
    assert data["question_count"] == 0
    assert data["ambiguous"] is False
    assert data["switch_positions"] == []
    assert data["question_positions"] == []
    assert len(data["legs"]) == 1
    leg = data["legs"][0]
    assert leg["segment"] == 1
    assert leg["merged"] == {
        "start": 2,
        "end": 6,
        "fragment": "时习之不",
        "sources": [[{"segment": 1, "pos": p}] for p in range(4)],
    }
    assert leg["original"]["start"] == 0 and leg["original"]["end"] == 4
    assert leg["original"]["fragment"] == "时习之不"


def test_trace_reading_endpoint_full_interval():
    resp = client.post(
        "/api/trace-reading",
        json={
            "segments": ["学而?习之", "时习之不", "之不亦乐乎"],
            "start": 0,
            "end": 9,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["interval_text"] == "学而时习之不亦乐乎"
    assert data["switch_count"] == 2
    assert data["question_count"] == 1
    assert data["ambiguous"] is True
    assert [l["segment"] for l in data["legs"]] == [0, 1, 2]
    assert data["switch_positions"] == [
        {"pos": 4, "from_segment": 0, "to_segment": 1},
        {"pos": 5, "from_segment": 1, "to_segment": 2},
    ]
    assert data["question_positions"] == [
        {"pos": 2, "segment": 0, "original_pos": 2, "output_char": "时"}
    ]
    # 路径段拼接稿区间首尾相接，覆盖整个区间
    bounds = [(l["merged"]["start"], l["merged"]["end"]) for l in data["legs"]]
    assert bounds == [(0, 4), (4, 5), (5, 9)]


def test_trace_reading_question_minimization():
    # 段 1 已知字全程覆盖，无须选段 0 的 ?
    resp = client.post(
        "/api/trace-reading",
        json={"segments": ["甲?丙", "甲乙丙"], "start": 0, "end": 3},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["switch_count"] == 0
    assert data["question_count"] == 0
    assert data["ambiguous"] is False
    assert [l["segment"] for l in data["legs"]] == [1]


def test_trace_reading_no_complete_path_returns_422():
    # 拼接 甲乙丙Y丙：插入字 Y（仅段 1）与后续“丙”在段 1 原文不连续，
    # 换后侧又无 0/1 共同覆盖见证，整条区间无完整证据路径
    resp = client.post(
        "/api/trace-reading",
        json={"segments": ["甲乙丙", "甲乙XY丙"], "start": 0, "end": 5},
    )
    assert resp.status_code == 422
    assert "message" in resp.json()["detail"]


def test_trace_reading_invalid_interval_returns_422():
    body = {"segments": ["甲乙丙丁戊己", "戊己庚辛"]}
    # 空区间
    assert client.post("/api/trace-reading", json={**body, "start": 0, "end": 0}).status_code == 422
    # start == end（中部）
    assert client.post("/api/trace-reading", json={**body, "start": 3, "end": 3}).status_code == 422
    # start > end
    assert client.post("/api/trace-reading", json={**body, "start": 5, "end": 3}).status_code == 422
    # end 越界
    assert client.post("/api/trace-reading", json={**body, "start": 0, "end": 9}).status_code == 422


def test_trace_reading_negative_or_missing_interval_returns_422():
    body = {"segments": ["甲乙丙丁戊己", "戊己庚辛"]}
    assert client.post("/api/trace-reading", json={**body, "start": -1, "end": 3}).status_code == 422
    assert client.post("/api/trace-reading", json={**body, "start": 0, "end": -1}).status_code == 422
    # 缺字段
    assert client.post("/api/trace-reading", json=body).status_code == 422
    assert client.post("/api/trace-reading", json={"start": 0, "end": 3}).status_code == 422
    # 布尔值不被接受为整数下标
    assert client.post(
        "/api/trace-reading", json={**body, "start": True, "end": 3}
    ).status_code == 422


def test_trace_reading_gate_failure_returns_422_with_failed_segment():
    resp = client.post(
        "/api/trace-reading",
        json={
            "segments": ["孔子曰未知", "未知生焉", "完全无关文本"],
            "start": 0,
            "end": 3,
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["failed_segment"] == 2


def test_trace_reading_reuses_assemble_segment_limits():
    body = {"start": 0, "end": 1}
    # 段数不足 / 超上限
    assert client.post("/api/trace-reading", json={"segments": ["abc"], **body}).status_code == 422
    assert client.post(
        "/api/trace-reading",
        json={"segments": ["aa", "bb", "cc", "dd", "ee", "ff"], **body},
    ).status_code == 422
    # 单段过长 / 总长超限 / 空段
    assert client.post(
        "/api/trace-reading", json={"segments": ["a" * 500, "b" * 501], **body}
    ).status_code == 422
    assert client.post(
        "/api/trace-reading", json={"segments": ["字" * 400, "字" * 401], **body}
    ).status_code == 422
    assert client.post(
        "/api/trace-reading", json={"segments": ["abc", ""], **body}
    ).status_code == 422


def test_trace_reading_index_lists_endpoint():
    info = client.get("/").json()
    assert info["trace_reading"] == "POST /api/trace-reading"


def test_audit_transposition_endpoint_unique_solution():
    resp = client.post(
        "/api/audit-transposition",
        json={
            "segments": ["甲乙丙丁戊己", "戊己庚辛"],
            "reference": "甲乙戊己庚丙丁辛",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "甲乙丙丁戊己庚辛"
    assert data["reference"] == "甲乙戊己庚丙丁辛"
    assert data["start"] == 2
    assert data["end"] == 4
    assert data["insert_at"] == 5
    assert data["moved"] == "丙丁"
    assert data["sources"] == [
        [{"segment": 0, "pos": 2}],
        [{"segment": 0, "pos": 3}],
    ]
    # 拼接文本与 /api/assemble 一致，接口不改写
    assert data["text"] == client.post(
        "/api/assemble", json={"segments": ["甲乙丙丁戊己", "戊己庚辛"]}
    ).json()["text"]


def test_audit_transposition_wildcard_compatible():
    # 参照稿第 7 字为 ?：2 字操作的移位片段只剩 1 个两侧已知且相同的字，
    # 唯一解为 3 字操作 (4,7,2)
    resp = client.post(
        "/api/audit-transposition",
        json={
            "segments": ["甲乙丙丁戊己", "戊己庚辛"],
            "reference": "甲乙戊己庚丙?辛",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert (data["start"], data["end"], data["insert_at"]) == (4, 7, 2)
    assert data["moved"] == "戊己庚"


def test_audit_transposition_tie_returns_409():
    # "丙丁" 右移与 "戊己" 左移同为 2 字操作且都还原参照稿
    resp = client.post(
        "/api/audit-transposition",
        json={
            "segments": ["甲乙丙丁戊己", "戊己庚辛"],
            "reference": "甲乙戊己丙丁庚辛",
        },
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["moved_len"] == 2
    ops = detail["ties"]
    assert len(ops) == 2
    assert [(o["start"], o["end"], o["insert_at"]) for o in ops] == [
        (2, 4, 4),
        (4, 6, 2),
    ]
    assert ops[0]["moved"] == "丙丁"
    assert ops[1]["moved"] == "戊己"
    for op in ops:
        assert len(op["sources"]) == 2


def test_audit_transposition_no_solution_returns_422():
    # 参照稿含原稿没有的 "子"：任何移位都无法让该位置吻合
    resp = client.post(
        "/api/audit-transposition",
        json={
            "segments": ["甲乙丙丁戊己", "戊己庚辛"],
            "reference": "甲乙丙丁戊己庚子",
        },
    )
    assert resp.status_code == 422
    assert "message" in resp.json()["detail"]


def test_audit_transposition_requirements_validated():
    base = {"segments": ["甲乙丙丁戊己", "戊己庚辛"]}
    # 两稿不等长
    assert client.post(
        "/api/audit-transposition",
        json={**base, "reference": "甲乙丙丁戊己庚辛壬"},
    ).status_code == 422
    # 等长但无已知字冲突（完全一致 / 仅差 ?）
    assert client.post(
        "/api/audit-transposition",
        json={**base, "reference": "甲乙丙丁戊己庚辛"},
    ).status_code == 422
    assert client.post(
        "/api/audit-transposition",
        json={**base, "reference": "甲乙丙?戊己庚辛"},
    ).status_code == 422
    # 缺 reference / 空 reference / 超 120 字
    assert client.post("/api/audit-transposition", json=base).status_code == 422
    assert client.post(
        "/api/audit-transposition", json={**base, "reference": ""}
    ).status_code == 422
    assert client.post(
        "/api/audit-transposition", json={**base, "reference": "字" * 121}
    ).status_code == 422


def test_audit_transposition_assembly_failure_returns_422():
    resp = client.post(
        "/api/audit-transposition",
        json={
            "segments": ["孔子曰未知", "未知生焉", "完全无关文本"],
            "reference": "字字字字字字字字字字字字",
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["failed_segment"] == 2


def test_audit_transposition_reuses_assemble_segment_limits():
    ref = "甲乙戊己庚丙丁辛"
    # 段数不足 / 超上限
    assert client.post(
        "/api/audit-transposition", json={"segments": ["abc"], "reference": ref}
    ).status_code == 422
    assert client.post(
        "/api/audit-transposition",
        json={"segments": ["aa", "bb", "cc", "dd", "ee", "ff"], "reference": ref},
    ).status_code == 422
    # 单段过长 / 总长超限 / 空段
    assert client.post(
        "/api/audit-transposition",
        json={"segments": ["a" * 500, "b" * 501], "reference": ref},
    ).status_code == 422
    assert client.post(
        "/api/audit-transposition",
        json={"segments": ["字" * 400, "字" * 401], "reference": ref},
    ).status_code == 422
    assert client.post(
        "/api/audit-transposition",
        json={"segments": ["abc", ""], "reference": ref},
    ).status_code == 422


def test_audit_transposition_index_lists_endpoint():
    info = client.get("/").json()
    assert info["audit_transposition"] == "POST /api/audit-transposition"
