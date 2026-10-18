# -*- coding: utf-8 -*-
"""命令行入口：python run.py [--port 8000] [--reload]"""
from __future__ import annotations

import argparse

import uvicorn

from app.config import load_config
from app.main import create_app


def main():
    parser = argparse.ArgumentParser(description="A-Share Info Collector")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--reload", action="store_true", help="开发热重载（需安装 uvicorn[standard]）")
    parser.add_argument("--config", default=None, help="配置文件路径（默认 config.yaml）")
    args = parser.parse_args()

    config = load_config(args.config)
    app = create_app(config)
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
