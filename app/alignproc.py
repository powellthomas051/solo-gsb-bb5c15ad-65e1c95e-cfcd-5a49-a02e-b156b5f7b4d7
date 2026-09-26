"""/api/align 的子进程计算执行层。

每个被接纳的对齐请求在一个**独立子进程**中运行原始 ``align`` 纯计算，
主进程以 asyncio 异步等待结果，从而：

- 子进程内 CPU/内存异常（例如段错误、被 OOM 杀死）不会拖垮服务，
  主进程据其退出码返回 500，且后续请求仍可正常接纳；
- 用信号量式的计数器限制“运行中或清理中”的子进程数（默认 2），
  无空位时立即报错、绝不排队；
- 从接纳时刻起计时（默认 10 秒），超时返回 504；
- 超时或客户端断开时终止（SIGTERM，必要时 SIGKILL）并**回收**
  对应子进程，回收完成后才释放名额，杜绝僵尸进程与名额泄漏；
- 服务关闭时终止并回收所有仍在运行的子进程。

进程启动方式固定为 ``spawn``：子进程重新导入解释器与 ``app`` 包，
不继承主进程的锁/线程状态，FastAPI/uvicorn 主进程通常是多线程的，
``fork`` 在多线程进程中并不安全。
"""

from __future__ import annotations

import logging
import multiprocessing
import multiprocessing.context
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

from .aligner import align

logger = logging.getLogger("app.alignproc")

#: 终止子进程的 SIGTERM 宽限秒数，超时升级为 SIGKILL
_TERMINATE_GRACE_SECONDS = 5.0
#: 回收已自然退出子进程时的最长 join 等待秒数（正常应为瞬时）
_REAP_JOIN_SECONDS = 5.0

#: 默认配置
DEFAULT_MAX_PROCESSES = 2
DEFAULT_TIMEOUT_SECONDS = 10


class AlignSlotUnavailable(Exception):
    """没有空出的子进程名额：调用方应立即返回 503，不排队。"""


class AlignTimeout(Exception):
    """对齐计算从接纳起超过允许时长：调用方应返回 504。"""


class AlignClientDisconnected(Exception):
    """等待计算期间客户端已断开：调用方应中止并回收子进程。"""


class AlignChildError(Exception):
    """子进程异常退出（非零退出码、被杀或结果通道损坏）。"""


@dataclass(frozen=True)
class AlignConfig:
    """/api/align 子进程执行层配置。"""

    max_processes: int
    timeout_seconds: int


def positive_int_env(name: str, default: int) -> int:
    """读取环境变量并校验为**十进制正整数字符串**。

    未设置（或设置为空串）时取默认值；任何非法值（含 0、负数、
    小数、空白、前导符号等）都抛出 ValueError，供启动期直接失败。
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip()
    if not value.isascii() or not value.isdigit() or int(value) <= 0:
        raise ValueError(
            f"环境变量 {name} 必须为正整数，当前值为 {raw!r}，服务启动失败"
        )
    return int(value)


def load_config() -> AlignConfig:
    """从环境变量加载配置；非法值使启动失败。"""
    return AlignConfig(
        max_processes=positive_int_env(
            "ALIGN_MAX_PROCESSES", DEFAULT_MAX_PROCESSES
        ),
        timeout_seconds=positive_int_env(
            "ALIGN_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS
        ),
    )


def align_worker(conn, left: str, right: str) -> None:
    """子进程入口：运行原始 align，把结果或异常描述经管道送回主进程。

    结果协议（仅一次）：
      ``("ok", result_dict)``        —— 正常返回；
      ``("error", repr_string)``     —— align 抛出异常。
    随后进程以退出码 0 结束；进程本身崩溃（段错误、OOM 等）则无消息、
    退出码非 0，由主进程统一判定为子进程异常。
    """
    try:
        conn.send(("ok", align(left, right)))
    except Exception as exc:  # 任何计算异常都序列化回传，不让子进程非零退出
        try:
            conn.send(("error", repr(exc)))
        except Exception:  # 结果通道自身损坏时交由退出码路径处理
            logger.exception("align 子进程回传异常失败")
    finally:
        conn.close()


class AlignRunner:
    """以独立子进程执行 align 的受限并发执行器。

    所有公共方法都在 asyncio 事件循环单线程内调用，计数器
    （运行中 + 清理中的子进程数）无需加锁。名额在接纳（计数 +1）时
    占用，在子进程终止并回收完成后才释放（计数 -1），保证
    “无空位立即 503、不排队”。
    """

    def __init__(
        self,
        config: AlignConfig,
        *,
        mp_context: multiprocessing.context.BaseContext | None = None,
        worker: Callable[..., None] = align_worker,
    ) -> None:
        self._config = config
        self._mp_context = mp_context or multiprocessing.get_context("spawn")
        self._worker = worker
        #: 已占用名额（运行中或清理中的子进程）
        self._active_slots = 0
        #: 活跃子进程 pid -> Process，服务关闭时逐个终止回收
        self._processes: dict[int, multiprocessing.process.BaseProcess] = {}

    @property
    def config(self) -> AlignConfig:
        return self._config

    @property
    def active_count(self) -> int:
        """运行中或清理中的子进程占用名额数。"""
        return self._active_slots

    def try_acquire(self) -> None:
        """尝试立即占用一个名额；已满则抛 AlignSlotUnavailable，不排队。"""
        if self._active_slots >= self._config.max_processes:
            raise AlignSlotUnavailable(self._config.max_processes)
        self._active_slots += 1

    def _release(self) -> None:
        if self._active_slots > 0:
            self._active_slots -= 1
        else:  # 防御性保护：名额释放与占用必须严格配对
            logger.error("align 名额释放次数超过占用次数，已忽略多余释放")

    async def run(self, left: str, right: str, is_disconnected) -> dict:
        """在独立子进程中执行一次对齐。

        ``is_disconnected`` 为返回 bool 的可调用对象（通常是
        ``request.is_disconnected``），主进程借此在等待期间感知客户端
        断开。正常返回 align 的结果字典；无名额、超时、客户端断开、
        子进程异常分别抛出对应异常，且任何路径都不会泄漏子进程或名额。
        """
        self.try_acquire()
        slot_released = False
        process: multiprocessing.process.BaseProcess | None = None
        parent_conn = child_conn = None
        # 从接纳（占用名额）起计时，包含进程启动耗时
        deadline = time.monotonic() + self._config.timeout_seconds

        def release_once() -> None:
            nonlocal slot_released
            if not slot_released:
                self._release()
                slot_released = True

        try:
            parent_conn, child_conn = self._mp_context.Pipe(duplex=False)
            process = self._mp_context.Process(
                target=self._worker,
                args=(child_conn, left, right),
                daemon=True,
            )
            process.start()
            child_conn.close()  # 主进程这一端只保留 parent_conn
            self._processes[process.pid] = process

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    await self._abort(process, parent_conn)
                    release_once()
                    raise AlignTimeout(self._config.timeout_seconds)
                if await is_disconnected():
                    await self._abort(process, parent_conn)
                    release_once()
                    raise AlignClientDisconnected
                if await run_in_threadpool(parent_conn.poll):
                    result = await self._collect(process, parent_conn)
                    release_once()
                    return result
                # 轮询等待：既能及时响应超时与客户端断开，又不阻塞事件循环
                await _sleep_or_ready(parent_conn, min(remaining, 0.1))
        except (AlignTimeout, AlignClientDisconnected, AlignChildError):
            raise
        except BaseException:
            # 启动失败等任何意外：尽力终止回收，绝不泄漏进程或名额
            if process is not None:
                await self._abort_if_alive(process)
                await self._reap(process)
            raise
        finally:
            if process is not None:
                self._forget(process)
                # 兜底：正常路径 _collect、异常路径 _abort 均已回收；
                # 仅在二者未覆盖的意外分支再回收一次。
                if process.exitcode is None:
                    await self._abort_if_alive(process)
                    await self._reap(process)
            release_once()
            if parent_conn is not None:
                _silent_close(parent_conn)

    async def _collect(self, process, conn) -> dict:
        """读取已结束子进程的结果，并在线程池中回收子进程。"""
        def receive():
            try:
                return conn.recv()
            except (EOFError, OSError) as exc:
                raise AlignChildError(
                    "align 子进程结果通道已关闭，未返回结果"
                ) from exc

        kind, payload = await run_in_threadpool(receive)
        # 结果已送达，子进程应随即退出；join 回收，避免僵尸进程
        exitcode = await run_in_threadpool(_join_blocking, process, _REAP_JOIN_SECONDS)
        if exitcode is None:
            # 已产出结果却长期不退出：交由外层终止并按异常处理
            raise AlignChildError("align 子进程返回结果后未正常退出")
        if exitcode != 0:
            raise AlignChildError(f"align 子进程以退出码 {exitcode} 异常退出")
        if kind == "ok":
            return payload
        raise AlignChildError(f"align 子进程计算失败：{payload}")

    async def _abort(self, process, conn) -> None:
        """终止并回收子进程；回收完成后才由调用方释放名额。"""
        await self._abort_if_alive(process)
        await self._reap(process)
        # 关闭管道使仍在线程池阻塞的 poll/recv 尽快结束（随后即 EOF）
        _silent_close(conn)

    async def _abort_if_alive(self, process) -> None:
        if not process.is_alive():
            return
        try:
            process.terminate()  # SIGTERM
        except Exception:
            logger.exception("终止 align 子进程（SIGTERM）失败")

        def _wait_grace() -> int | None:
            return _join_blocking(process, _TERMINATE_GRACE_SECONDS)

        exitcode = await run_in_threadpool(_wait_grace)
        if exitcode is not None:
            return
        logger.warning(
            "align 子进程 pid=%s 在 SIGTERM 后 %.0f 秒内未退出，升级为 SIGKILL",
            process.pid, _TERMINATE_GRACE_SECONDS,
        )
        try:
            process.kill()  # SIGKILL
        except Exception:
            logger.exception("强杀 align 子进程（SIGKILL）失败")
        await self._reap(process)

    async def _reap(self, process) -> None:
        """join 直至子进程彻底退出（回收僵尸进程）。"""
        if process.exitcode is not None:
            return
        await run_in_threadpool(_join_blocking, process, _REAP_JOIN_SECONDS)
        if process.exitcode is None:
            # SIGKILL 后仍不退出几乎不可能；再给一次 join 机会
            await run_in_threadpool(_join_blocking, process, _REAP_JOIN_SECONDS)

    def _forget(self, process) -> None:
        if process.pid is not None:
            self._processes.pop(process.pid, None)

    async def aclose(self) -> None:
        """服务关闭：终止并回收全部仍在运行的子进程（幂等）。"""
        procs = list(self._processes.values())
        self._processes.clear()
        for process in procs:
            await self._abort_if_alive(process)
            await self._reap(process)
            self._release()  # 每个在管子进程都占用过一个名额


def _join_blocking(process, timeout: float) -> int | None:
    """在线程池中执行的阻塞 join，返回退出码（仍在运行返回 None）。"""
    process.join(timeout)
    return process.exitcode


async def _sleep_or_ready(conn, timeout: float) -> None:
    """至多等待 ``timeout`` 秒；管道可读时提前返回。

    poll() 为阻塞调用，放到线程池执行以避免阻塞事件循环。
    """
    try:
        ready = await run_in_threadpool(conn.poll, timeout)
    except OSError:
        # 管道在并发清理中被关闭：下一轮由 collect/abort 路径处理
        ready = True
    if not ready:
        return


def _silent_close(conn) -> None:
    try:
        conn.close()
    except Exception:
        pass
