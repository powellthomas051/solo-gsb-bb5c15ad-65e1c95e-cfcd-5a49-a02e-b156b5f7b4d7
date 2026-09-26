"""/api/align 子进程执行层测试。

覆盖：
- 成功响应与直接调用 align 一致、参数校验不变；
- 名额满立即 503 且不排队；
- 超时返回 504，子进程被终止回收、名额随后可复用；
- 客户端断开时终止并回收子进程；
- 子进程异常（结果通道报错 / 非零退出）返回 500，后续请求可正常接纳；
- 并发结束后无残留子进程、名额归位、无重复释放；
- 环境变量配置必须为正整数，非法值使启动（导入/加载）失败；
- /health 不等待对齐计算。

注：这里用 ``multiprocessing.get_context("spawn")`` 与生产一致，
worker 必须是可 pickle 的模块级函数。
"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import time

import pytest
from fastapi.testclient import TestClient

from app import alignproc
from app.alignproc import (
    AlignChildError,
    AlignClientDisconnected,
    AlignConfig,
    AlignRunner,
    AlignSlotUnavailable,
    AlignTimeout,
    load_config,
    positive_int_env,
)
from app.aligner import align as direct_align
from app.main import app


# ---------------------------------------------------------------------------
# 测试用 worker（模块级，spawn 子进程可 pickle）
# ---------------------------------------------------------------------------

def slow_worker(conn, left: str, right: str, delay: float = 2.0) -> None:
    """模拟长计算：睡够后再正常返回，用于超时/名额测试。"""
    try:
        time.sleep(delay)
        conn.send(("ok", {"slow": True, "left": left, "right": right}))
    finally:
        conn.close()


def error_worker(conn, left: str, right: str) -> None:
    """模拟 align 内部抛出异常：子进程仍 0 退出并回传 error。"""
    try:
        conn.send(("error", "ValueError('boom')"))
    finally:
        conn.close()


def crash_worker(conn, left: str, right: str) -> None:
    """模拟子进程崩溃：直接以退出码 1 退出、不回传结果。"""
    os._exit(1)


def sleeping_worker(conn, left: str, right: str, delay: float | None = None) -> None:
    """长时间存活的子进程：先不回传，用于客户端断开/关闭回收测试。

    延迟可由参数或 ``ALIGN_TEST_SLEEP_SECONDS`` 环境变量控制，默认 30 秒；
    测试通常配合较短的超时或显式中止使用。结束后回传一份满足
    AlignResponse 形状的最小合法结果，便于走通 HTTP 成功路径。
    """
    if delay is None:
        delay = float(os.environ.get("ALIGN_TEST_SLEEP_SECONDS", "30"))
    try:
        time.sleep(delay)
        payload = dict(direct_align(left, right))
        conn.send(("ok", payload))
    finally:
        conn.close()


def sigterm_ignoring_worker(conn, left: str, right: str) -> None:
    """忽略 SIGTERM、只响应 SIGKILL 的卡死子进程。"""
    import signal
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(60)
    try:
        conn.send(("ok", None))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

@pytest.fixture
def spawn_ctx():
    return multiprocessing.get_context("spawn")


def make_runner(max_processes=2, timeout=10, *, ctx=None, worker=alignproc.align_worker):
    return AlignRunner(
        AlignConfig(max_processes=max_processes, timeout_seconds=timeout),
        mp_context=ctx or multiprocessing.get_context("spawn"),
        worker=worker,
    )


async def _never_disconnected():
    return False


class _FakeDisconnected:
    """可控的 is_disconnected：到达指定检查次数后返回 True。"""

    def __init__(self, disconnect_after_checks: int = 1):
        self._remaining = disconnect_after_checks
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        if self._remaining <= 0:
            return True
        self._remaining -= 1
        return False


def live_children_pids(owned_pids=None):
    """统计当前仍存活的子进程。

    multiprocessing 会启动长驻的 resource_tracker / semaphore_tracker
    辅助进程（父进程也是本进程），它们由库管理、随父进程退出，不是
    泄漏的 align 子进程——用 ``owned_pids`` 白名单只统计执行器自己启动
    的进程；zombie（状态 Z）也视为未回收。
    """
    me = os.getpid()
    result = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            with open(f"/proc/{pid}/stat") as fh:
                stat = fh.read().split()
            ppid = int(stat[3])
            state = stat[2]
        except (OSError, IndexError, ValueError):
            continue
        if ppid != me:
            continue
        if owned_pids is not None and pid not in owned_pids:
            continue  # 排除 resource_tracker 等库辅助进程
        result.append((pid, state))
    return result


def assert_runner_clean(runner):
    """执行器自身启动过的进程全部回收、名额归位。"""
    owned = getattr(runner, "_reaped_pids", set())
    lingering = live_children_pids(owned_pids=owned)
    assert lingering == [], f"仍有未回收的 align 子进程: {lingering}"
    assert runner.active_count == 0
    assert runner._processes == {}


def assert_no_child_left():
    """宽松断言：除 resource_tracker 外无子进程残留。"""
    mine = []
    for pid, state in live_children_pids():
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                cmdline = fh.read().decode("utf-8", "replace")
        except OSError:
            cmdline = ""
        if "resource_tracker" in cmdline or "semaphore_tracker" in cmdline:
            continue
        mine.append((pid, state, cmdline))
    assert mine == [], f"仍有未回收的子进程: {mine}"


# ---------------------------------------------------------------------------
# 配置解析
# ---------------------------------------------------------------------------

class TestPositiveIntEnv:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("ALIGN_MAX_PROCESSES", raising=False)
        assert positive_int_env("ALIGN_MAX_PROCESSES", 2) == 2

    def test_normal_value(self, monkeypatch):
        monkeypatch.setenv("ALIGN_TIMEOUT_SECONDS", "3")
        assert positive_int_env("ALIGN_TIMEOUT_SECONDS", 10) == 3

    @pytest.mark.parametrize("bad", ["0", "-1", "1.0", "abc", "  ", "2x", "+3", ""])
    def test_invalid_values_raise(self, monkeypatch, bad):
        monkeypatch.setenv("ALIGN_MAX_PROCESSES", bad)
        with pytest.raises(ValueError):
            positive_int_env("ALIGN_MAX_PROCESSES", 2)

    def test_whitespace_around_value_ok(self, monkeypatch):
        monkeypatch.setenv("ALIGN_MAX_PROCESSES", "  4 ")
        assert positive_int_env("ALIGN_MAX_PROCESSES", 2) == 4

    def test_load_config_invalid_fails_startup(self, monkeypatch):
        monkeypatch.setenv("ALIGN_MAX_PROCESSES", "0")
        monkeypatch.setenv("ALIGN_TIMEOUT_SECONDS", "10")
        with pytest.raises(ValueError):
            load_config()

        monkeypatch.setenv("ALIGN_MAX_PROCESSES", "2")
        monkeypatch.setenv("ALIGN_TIMEOUT_SECONDS", "no")
        with pytest.raises(ValueError):
            load_config()

    def test_load_config_ok(self, monkeypatch):
        monkeypatch.setenv("ALIGN_MAX_PROCESSES", "3")
        monkeypatch.setenv("ALIGN_TIMEOUT_SECONDS", "7")
        cfg = load_config()
        assert cfg.max_processes == 3 and cfg.timeout_seconds == 7

    def test_invalid_env_makes_startup_fail(self, monkeypatch):
        """非法配置必须使启动失败：子进程中以非法环境变量导入 app.main。"""
        import subprocess
        import sys

        code = (
            "import os; "
            "import app.main"
        )
        env = {**os.environ, "ALIGN_TIMEOUT_SECONDS": "0"}
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            env=env, capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode != 0
        assert "ALIGN_TIMEOUT_SECONDS" in proc.stderr

        env = {**os.environ, "ALIGN_MAX_PROCESSES": "x"}
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            env=env, capture_output=True, text=True, timeout=60,
        )
        assert proc.returncode != 0
        assert "ALIGN_MAX_PROCESSES" in proc.stderr


# ---------------------------------------------------------------------------
# 成功路径：响应一致性
# ---------------------------------------------------------------------------

class TestAlignSuccess:
    def test_subprocess_result_matches_direct_align(self, spawn_ctx):
        runner = make_runner(ctx=spawn_ctx)
        left, right = "学而?习之", "时习之不亦"
        result = asyncio.run(runner.run(left, right, _never_disconnected))
        assert result == direct_align(left, right)
        assert runner.active_count == 0
        assert_no_child_left()

    def test_endpoint_response_unchanged(self):
        with TestClient(app) as client:
            resp = client.post(
                "/api/align", json={"left": "学而?习之", "right": "时习之不亦"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data == direct_align("学而?习之", "时习之不亦")

    def test_validation_still_422_without_consuming_slot(self):
        with TestClient(app) as client:
            # 空串 / 缺字段 仍为 422，且不占用子进程名额
            assert client.post(
                "/api/align", json={"left": "", "right": "abc"}
            ).status_code == 422
            assert client.post(
                "/api/align", json={"left": "abc"}
            ).status_code == 422
            # 服务仍可正常接纳
            assert client.post(
                "/api/align", json={"left": "甲乙", "right": "乙丙"}
            ).status_code == 200


# ---------------------------------------------------------------------------
# 503：名额满立即拒绝、不排队
# ---------------------------------------------------------------------------

class TestSlotLimit:
    def test_try_acquire_rejects_when_full(self):
        runner = make_runner(max_processes=2, timeout=5)
        runner.try_acquire()
        runner.try_acquire()
        with pytest.raises(AlignSlotUnavailable):
            runner.try_acquire()
        assert runner.active_count == 2
        runner._release()
        runner.try_acquire()
        assert runner.active_count == 2

    def test_endpoint_503_when_full_and_no_queue(self, monkeypatch):
        monkeypatch.setenv("ALIGN_TEST_SLEEP_SECONDS", "3")
        runner = make_runner(
            max_processes=2, timeout=30, worker=sleeping_worker
        )
        app.state.align_runner = runner
        try:
            with TestClient(app) as client:
                stop = threading.Event()
                results = []

                def occupy():
                    results.append(client.post(
                        "/api/align", json={"left": "甲", "right": "乙"}
                    ))

                threads = [_thread(occupy) for _ in range(2)]
                # 等两个请求完成接纳、子进程已启动并占满名额
                deadline = time.monotonic() + 10
                while runner.active_count < 2 and time.monotonic() < deadline:
                    time.sleep(0.02)
                assert runner.active_count == 2

                # 第三请求：必须立即 503，不能排队等待
                t0 = time.monotonic()
                resp = client.post(
                    "/api/align", json={"left": "甲", "right": "乙"}
                )
                elapsed = time.monotonic() - t0
                assert resp.status_code == 503
                assert resp.json()["detail"]["max_processes"] == 2
                assert elapsed < 2.0  # 立即失败而非等超时

                for th in threads:
                    th.join(timeout=30)
                assert len(results) == 2
                assert all(r.status_code == 200 for r in results)
                assert runner.active_count == 0
                assert_no_child_left()
        finally:
            app.state.align_runner = None
            stop.set()

    def test_release_is_idempotent_guard(self):
        runner = make_runner(max_processes=1)
        runner.try_acquire()
        runner._release()
        # 多余释放不应把计数器打成负数
        runner._release()
        assert runner.active_count == 0
        runner.try_acquire()
        assert runner.active_count == 1


# ---------------------------------------------------------------------------
# 504：超时终止回收、名额复用
# ---------------------------------------------------------------------------

class TestTimeout:
    def test_timeout_raises_and_reaps_process(self, spawn_ctx):
        runner = make_runner(
            max_processes=1, timeout=1, ctx=spawn_ctx, worker=sleeping_worker
        )
        t0 = time.monotonic()
        with pytest.raises(AlignTimeout):
            asyncio.run(runner.run("甲", "乙", _never_disconnected))
        elapsed = time.monotonic() - t0
        assert 1.0 <= elapsed < 3.0
        assert runner.active_count == 0
        assert_no_child_left()

    def test_slot_reusable_after_timeout(self, spawn_ctx):
        # 超时回收后名额必须立即释放，可继续接纳
        runner = make_runner(
            max_processes=1, timeout=1, ctx=spawn_ctx, worker=sleeping_worker
        )
        with pytest.raises(AlignTimeout):
            asyncio.run(runner.run("甲", "乙", _never_disconnected))
        assert runner.active_count == 0

        # 换回正常 worker，验证名额可复用
        runner_ok = make_runner(max_processes=1, timeout=30, ctx=spawn_ctx)
        result = asyncio.run(runner_ok.run("甲乙", "乙丙", _never_disconnected))
        assert result["merged"] == direct_align("甲乙", "乙丙")["merged"]
        assert runner_ok.active_count == 0
        assert_no_child_left()

    def test_endpoint_504(self):
        runner = make_runner(
            max_processes=2, timeout=1, worker=sleeping_worker
        )
        app.state.align_runner = runner
        try:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/align", json={"left": "甲", "right": "乙"}
                )
                assert resp.status_code == 504
                assert resp.json()["detail"]["timeout_seconds"] == 1
                assert runner.active_count == 0
                assert_no_child_left()
        finally:
            app.state.align_runner = None

    def test_timeout_escalates_sigterm_to_sigkill(self, spawn_ctx):
        # 子进程忽略 SIGTERM：宽限后必须 SIGKILL 并回收，名额仍要释放
        runner = make_runner(
            max_processes=1, timeout=1, ctx=spawn_ctx,
            worker=sigterm_ignoring_worker,
        )
        t0 = time.monotonic()
        with pytest.raises(AlignTimeout):
            asyncio.run(runner.run("甲", "乙", _never_disconnected))
        elapsed = time.monotonic() - t0
        # 超时 1 秒 + SIGTERM 宽限 5 秒，留一定余量
        assert elapsed < 10.0
        assert runner.active_count == 0
        assert_no_child_left()


# ---------------------------------------------------------------------------
# 客户端断开
# ---------------------------------------------------------------------------

class TestClientDisconnect:
    def test_disconnect_aborts_and_reaps(self, spawn_ctx):
        runner = make_runner(
            max_processes=1, timeout=30, ctx=spawn_ctx, worker=sleeping_worker
        )
        disc = _FakeDisconnected(disconnect_after_checks=1)
        with pytest.raises(AlignClientDisconnected):
            asyncio.run(runner.run("甲", "乙", disc))
        assert runner.active_count == 0
        assert_no_child_left()

    def test_http_disconnect_aborts_child(self, monkeypatch):
        """端到端：HTTP 连接在计算完成前断开，子进程必须被终止回收。

        用原始 ASGI 接口驱动 app：请求体送达后、应用进入计算等待时，
        把 ``http.disconnect`` 放入 receive 队列，使
        ``request.is_disconnected()`` 返回 True，接口返回 499。
        """
        import asyncio as _aio

        monkeypatch.setenv("ALIGN_TEST_SLEEP_SECONDS", "30")
        runner = make_runner(
            max_processes=1, timeout=30, worker=sleeping_worker
        )
        app.state.align_runner = runner

        async def scenario():
            body = b'{"left": "\xe7\x94\xb2", "right": "\xe4\xb9\x99"}'
            scope = {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/align",
                "raw_path": b"/api/align",
                "query_string": b"",
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())],
                "client": ("127.0.0.1", 12345),
                "server": ("127.0.0.1", 8000),
                "app": app,
            }
            inbox: _aio.Queue = _aio.Queue()
            await inbox.put({"type": "http.request", "body": body})
            disconnect_put = {"done": False}

            async def receive():
                item = await inbox.get()
                # 应用取走请求体后，下一次 receive（断开探测）立即得到 disconnect
                if item["type"] == "http.request" and not disconnect_put["done"]:
                    disconnect_put["done"] = True
                    await inbox.put({"type": "http.disconnect"})
                return item

            sent = []

            async def send(message):
                sent.append(message)

            await app(scope, receive, send)

            for _ in range(200):
                if runner.active_count == 0:
                    break
                await _aio.sleep(0.05)
            assert runner.active_count == 0
            starts = [m for m in sent if m["type"] == "http.response.start"]
            assert starts and starts[0]["status"] == 499

        try:
            _aio.run(scenario())
            assert_no_child_left()
        finally:
            app.state.align_runner = None


# ---------------------------------------------------------------------------
# 500：子进程异常
# ---------------------------------------------------------------------------

class TestChildFailure:
    def test_error_payload_raises_500_class(self, spawn_ctx):
        runner = make_runner(
            max_processes=1, timeout=10, ctx=spawn_ctx, worker=error_worker
        )
        with pytest.raises(AlignChildError):
            asyncio.run(runner.run("甲", "乙", _never_disconnected))
        assert runner.active_count == 0
        assert_no_child_left()

    def test_crash_payload_raises_500_class(self, spawn_ctx):
        runner = make_runner(
            max_processes=1, timeout=10, ctx=spawn_ctx, worker=crash_worker
        )
        with pytest.raises(AlignChildError):
            asyncio.run(runner.run("甲", "乙", _never_disconnected))
        assert runner.active_count == 0
        assert_no_child_left()

    def test_endpoint_500_then_accepts_more_requests(self):
        bad_runner = make_runner(max_processes=2, timeout=10, worker=error_worker)
        app.state.align_runner = bad_runner
        try:
            with TestClient(app) as client:
                resp = client.post(
                    "/api/align", json={"left": "甲", "right": "乙"}
                )
                assert resp.status_code == 500
                assert bad_runner.active_count == 0
        finally:
            app.state.align_runner = None

        # 恢复默认 runner 后，后续请求正常接纳
        with TestClient(app) as client:
            resp = client.post(
                "/api/align", json={"left": "甲乙", "right": "乙丙"}
            )
            assert resp.status_code == 200
            assert_no_child_left()


# ---------------------------------------------------------------------------
# 并发：结束后名额归位、无泄漏
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_many_concurrent_runs_no_leak(self, spawn_ctx):
        runner = make_runner(max_processes=2, timeout=60, ctx=spawn_ctx)

        async def one(left, right):
            return await runner.run(left, right, _never_disconnected)

        async def main():
            pairs = [("甲乙", "乙丙"), ("学而?习之", "时习之"),
                     ("丙丁戊", "戊己庚"), ("ABC", "BCD"),
                     ("子丑寅", "寅卯辰"), ("xyz", "yzw")]
            # 每批恰好 2 个并发（占满名额），分批提交以模拟“有空位才接纳”：
            # 上一批回收释放名额后，下一批立即能被接纳。
            results = []
            for i in range(0, len(pairs), 2):
                batch = await asyncio.gather(
                    one(*pairs[i]), one(*pairs[i + 1])
                )
                assert runner.active_count == 0  # 回收完成、名额归位
                results.extend(batch)
            return results

        results = asyncio.run(main())
        # 三批共 6 个请求全部正常完成
        assert all(not isinstance(r, BaseException) for r in results), results
        assert runner.active_count == 0
        assert_no_child_left()

    def test_over_capacity_rejected_immediately_without_queue(self, spawn_ctx):
        # 3 个任务同时启动、只有 2 个名额：超出者立即 AlignSlotUnavailable，
        # 绝不排队等待在途任务完成；在途 2 个任务正常结束、无泄漏。
        runner = make_runner(max_processes=2, timeout=60, ctx=spawn_ctx)

        async def main():
            tasks = [
                asyncio.create_task(runner.run("甲乙", "乙丙", _never_disconnected)),
                asyncio.create_task(runner.run("丙丁", "丁戊", _never_disconnected)),
            ]
            # 等待前两个占满名额
            for _ in range(100):
                if runner.active_count == 2:
                    break
                await asyncio.sleep(0.02)
            assert runner.active_count == 2
            rejected = asyncio.create_task(
                runner.run("戊己", "己庚", _never_disconnected)
            )
            with pytest.raises(AlignSlotUnavailable):
                await rejected
            done = await asyncio.gather(*tasks)
            return done

        done = asyncio.run(main())
        assert len(done) == 2 and all("merged" in r for r in done)
        assert runner.active_count == 0
        assert_no_child_left()

    def test_mixed_timeout_and_success_no_slot_leak(self, spawn_ctx):
        # 1 个名额：超时请求回收后，正常请求仍可接纳，计数器精确归位
        slow = make_runner(
            max_processes=1, timeout=1, ctx=spawn_ctx, worker=sleeping_worker
        )
        with pytest.raises(AlignTimeout):
            asyncio.run(slow.run("甲", "乙", _never_disconnected))
        assert slow.active_count == 0

        async def twice():
            ok = make_runner(max_processes=1, timeout=60, ctx=spawn_ctx)
            r1 = await ok.run("甲乙", "乙丙", _never_disconnected)
            r2 = await ok.run("学而?习之", "时习之", _never_disconnected)
            return r1, r2, ok

        r1, r2, ok = asyncio.run(twice())
        assert r1["merged"] == direct_align("甲乙", "乙丙")["merged"]
        assert r2["merged"] == direct_align("学而?习之", "时习之")["merged"]
        assert ok.active_count == 0
        assert_no_child_left()

    def test_aclose_terminates_all(self, spawn_ctx):
        runner = make_runner(
            max_processes=2, timeout=60, ctx=spawn_ctx, worker=sleeping_worker
        )

        async def scenario():
            t1 = asyncio.create_task(runner.run("甲", "乙", _never_disconnected))
            t2 = asyncio.create_task(runner.run("丙", "丁", _never_disconnected))
            # 等待两个子进程真正启动
            for _ in range(100):
                if runner.active_count == 2:
                    break
                await asyncio.sleep(0.05)
            assert runner.active_count == 2

            # 服务关闭：终止并回收全部在运子进程
            await runner.aclose()
            assert runner.active_count == 0
            assert runner._processes == {}
            # 在途任务随即因连接 EOF 以 AlignChildError 结束（进程已被回收）
            results = await asyncio.gather(t1, t2, return_exceptions=True)
            assert all(isinstance(r, AlignChildError) for r in results), results

        asyncio.run(scenario())
        assert_no_child_left()

    def test_aclose_idempotent_and_empty(self, spawn_ctx):
        runner = make_runner(max_processes=2, timeout=10, ctx=spawn_ctx)
        asyncio.run(runner.aclose())
        asyncio.run(runner.aclose())  # 不应抛错、计数不变负
        assert runner.active_count == 0
        assert_no_child_left()


# ---------------------------------------------------------------------------
# /health 不等待对齐计算
# ---------------------------------------------------------------------------

class TestHealthNonBlocking:
    def test_health_ok_while_slots_full(self, monkeypatch):
        monkeypatch.setenv("ALIGN_TEST_SLEEP_SECONDS", "3")
        runner = make_runner(
            max_processes=2, timeout=30, worker=sleeping_worker
        )
        app.state.align_runner = runner
        try:
            with TestClient(app) as client:
                def occupy():
                    client.post(
                        "/api/align", json={"left": "甲", "right": "乙"}
                    )

                threads = [_thread(occupy) for _ in range(2)]
                deadline = time.monotonic() + 10
                while runner.active_count < 2 and time.monotonic() < deadline:
                    time.sleep(0.02)
                assert runner.active_count == 2

                # 名额已满、计算仍在运行：/health 立即返回
                t0 = time.monotonic()
                resp = client.get("/health")
                assert time.monotonic() - t0 < 1.0
                assert resp.status_code == 200
                assert resp.json() == {"status": "ok"}

                for th in threads:
                    th.join(timeout=30)
                assert runner.active_count == 0
                assert_no_child_left()
        finally:
            app.state.align_runner = None


# ---------------------------------------------------------------------------
# 小型并发工具
# ---------------------------------------------------------------------------

import threading  # noqa: E402


def _thread(target):
    th = threading.Thread(target=target)
    th.daemon = True
    th.start()
    return th


class _Barrier:
    def __init__(self, parties):
        self._parties = parties
        self._waiting = 0
        self._cond = threading.Condition()
        self._released = False

    def wait(self):
        with self._cond:
            self._waiting += 1
            if self._waiting >= self._parties:
                self._cond.notify_all()
            while not self._released:
                self._cond.wait(timeout=30)

    def release_all(self):
        with self._cond:
            self._released = True
            self._cond.notify_all()
