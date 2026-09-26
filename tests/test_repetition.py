"""重复抄写发现（find_repetition）测试。"""

from app.assembler import AssemblyError
from app.repetition import (
    MIN_KNOWN_EQUAL,
    MIN_LENGTH,
    _best_window_in_run,
    find_repetition,
)


def _build(prefix: str, body: str, suffix: str, anchor: str = "朱雀"):
    """以两次出现的 anchor 把目标拼接文本切成三段（anchor 处重叠续接）。

    返回 (segments, 拼接后应为的文本)。
    """
    segments = [prefix + anchor, anchor + body + anchor, anchor + suffix]
    text = prefix + anchor + body + anchor + suffix
    return segments, text


def test_exact_duplicated_block_returns_pair():
    r = find_repetition(["学而时习之不亦朱雀", "朱雀玄武白虎腾蛇青龙学而时习之不亦"])
    assert r["text"] == "学而时习之不亦朱雀玄武白虎腾蛇青龙学而时习之不亦"
    rep = r["repeat"]
    assert rep is not None
    assert (rep["first"]["start"], rep["first"]["end"]) == (0, 7)
    assert (rep["second"]["start"], rep["second"]["end"]) == (17, 24)
    assert rep["first"]["fragment"] == rep["second"]["fragment"] == "学而时习之不亦"
    # 区间互不重叠（允许贴合）且等长
    assert rep["first"]["end"] <= rep["second"]["start"]
    assert rep["first"]["sources"] and len(rep["first"]["sources"]) == 7


def test_wildcard_pair_compatible_and_counts_known_only():
    # 第二处抄写带两个 ?：逐字兼容，已知相同位为 5（>=4）
    r = find_repetition(["甲乙丙丁戊己朱雀", "朱雀天地玄黄宇宙洪荒甲?丙丁戊?"])
    rep = r["repeat"]
    assert rep is not None
    assert rep["first"]["fragment"] == "甲乙丙丁戊己"
    assert rep["second"]["fragment"] == "甲?丙丁戊?"
    assert (rep["first"]["start"], rep["second"]["start"]) == (0, 16)


def test_three_identical_blocks_chooses_earliest_pair():
    b = "子丑寅卯辰巳"
    r = find_repetition([b + "午未" + b + "朱雀", "朱雀申酉" + b + "终"])
    rep = r["repeat"]
    assert rep is not None
    # 三对同为长度 6、6 个已知相同位，取两起点升序的首对（第一、二块：0 与 8）
    assert rep["first"]["start"] == 0
    assert rep["second"]["start"] == 8
    assert rep["first"]["fragment"] == rep["second"]["fragment"] == b


def test_same_length_more_known_equal_wins():
    # 长度同为 6：较早一对只有 4 个已知相同位，较晚一对 6 个 -> 取后者
    a1, a2 = "甲乙丙丁戊己", "甲乙?丁戊?"
    b1 = "子丑寅卯辰巳"
    segments, text = _build(
        a1 + "乾坤震巽坎",
        a2 + "白虎腾蛇青龙" + b1 + "腾蛇勾陈青鸾",
        b1,
    )
    r = find_repetition(segments)
    assert r["text"] == text
    rep = r["repeat"]
    assert rep is not None
    assert rep["first"]["fragment"] == rep["second"]["fragment"] == b1
    assert rep["first"]["start"] == 25
    assert rep["second"]["start"] == 39


def test_longer_interval_with_fewer_known_wins_on_length():
    # 长度 8（仅 4 个已知相同位）压过长度 6（6 个已知相同位）
    a, a8 = "甲乙丙丁戊己庚辛", "甲乙丙丁?己?辛"
    b1 = "子丑寅卯辰巳"
    segments, text = _build(
        a + "乾坤震巽坎艮",
        a8 + "白虎腾蛇青龙勾" + b1 + "朱雀白虎腾蛇青",
        b1,
    )
    r = find_repetition(segments)
    assert r["text"] == text
    rep = r["repeat"]
    assert rep is not None
    assert rep["first"]["fragment"] == a
    assert rep["second"]["fragment"] == a8
    assert (rep["first"]["start"], rep["second"]["start"]) == (0, 16)


def test_adjacent_intervals_allowed():
    b = "子丑寅卯辰巳"
    r = find_repetition([b + b + "朱雀", "朱雀尾"])
    rep = r["repeat"]
    assert rep is not None
    assert rep["first"]["end"] == rep["second"]["start"] == 6
    assert rep["first"]["fragment"] == rep["second"]["fragment"] == b


def test_periodic_short_repetition_returns_none():
    # 周期 3 的重复：任一兼容 run 的对角偏移量 d 都是 3 的倍数且 < 6，
    # 非重叠窗口最多 3 字，达不到 6 字门槛
    r = find_repetition(["甲乙丙甲乙丙朱雀", "朱雀玄武"])
    assert r["text"] == "甲乙丙甲乙丙朱雀玄武"
    assert r["repeat"] is None


def test_all_unique_text_returns_none():
    r = find_repetition(["甲乙丙丁戊己", "戊己庚辛壬"])
    assert r["repeat"] is None


def test_gate_failure_propagates_assembly_error():
    try:
        find_repetition(["孔子曰未知", "未知生焉", "完全无关文本"])
    except AssemblyError as exc:
        assert exc.failed_segment == 2
    else:
        raise AssertionError("应抛出 AssemblyError")


def test_best_window_in_run_thresholds():
    # d 小于最小区间长度：非重叠窗口长度不足
    assert _best_window_in_run("ABCABC", 0, 6, 3) is None
    # d == 6、run 长 6：整段窗口 6 个已知相同位
    assert _best_window_in_run("ABCDEFABCDEF", 0, 6, 6) == (6, 6, 0)
    # 长度 6 但仅 4 个已知相同位（两个 ? 配对）：合格
    hit = _best_window_in_run("abcdefab?d?f", 0, 6, 6)
    assert hit == (6, 4, 0)
    # 长度 6 但仅 3 个已知相同位：不合格
    assert _best_window_in_run("abcdefa?c?e?", 0, 6, 6) is None
    # 常量与接口约定一致
    assert MIN_LENGTH == 6
    assert MIN_KNOWN_EQUAL == 4
