"""对齐计算子进程入口：在独立子进程中运行 ``app.aligner.align``。

主进程（``app.align_executor``）以 ``python -m app.align_worker`` 拉起本模块：
从标准输入读入 ``{"left": ..., "right": ...}`` JSON，在子进程内执行对齐，
把结果 JSON 写到标准输出；任何异常都写到标准错误并以非零码退出，由主进程
映射为 500。stdin/stdout 均按 UTF-8 字节流读写，不依赖子进程区域设置。
"""

import json
import sys

from app.aligner import align


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        result = align(payload["left"], payload["right"])
    except Exception as exc:  # 子进程内任何异常都转为非零退出，由主进程映射
        message = f"{type(exc).__name__}: {exc}\n"
        sys.stderr.buffer.write(message.encode("utf-8", "replace"))
        return 1
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
