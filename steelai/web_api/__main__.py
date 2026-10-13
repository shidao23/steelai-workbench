"""WO-31 §3 — 薄 API 的启动入口（仅 loopback）。

``python -m steelai.web_api --port 8760``

* 只绑定 ``127.0.0.1``，不是对外服务；
* 端口被占用时**明确报错退出**，不换随机端口、不全机扫端口；
* 同源提供已构建的前端，因此页面与 API 之间不需要跨源凭据。
"""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

from steelai.paths import ROOT

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8760


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        return probe.connect_ex((host, port)) == 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m steelai.web_api",
                                     description="SteelAI 科研薄 API（loopback only）")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--reload", action="store_true", help="开发用自动重载")
    parser.add_argument("--check", action="store_true", help="只检查端口与依赖后退出")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.host not in {"127.0.0.1", "localhost", "::1"}:
        print(f"拒绝：只允许 loopback 绑定，收到 {arguments.host}", file=sys.stderr)
        return 2
    if port_in_use(arguments.host, arguments.port):
        print(f"端口已被占用：{arguments.host}:{arguments.port}。"
              f"请先停止占用进程，或显式换一个 --port。", file=sys.stderr)
        return 3
    try:
        import uvicorn  # noqa: PLC0415
    except ImportError:
        print("缺少 uvicorn：请在 .venv-web 中安装 requirements-web.txt", file=sys.stderr)
        return 4
    dist = ROOT / "frontend" / "dist"
    print(f"前端构建：{'已就绪' if dist.is_dir() else '未构建（仅 API 可用）'} -> {dist}")
    if arguments.check:
        print("检查通过。")
        return 0
    uvicorn.run("steelai.web_api.app:app", host=arguments.host, port=arguments.port,
                reload=arguments.reload, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
