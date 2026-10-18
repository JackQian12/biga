# -*- coding: utf-8 -*-
"""手动生成《市场信息快报.md》（行情数据 + 市场新闻）。

用法：python gen_report.py
"""
from app.services.report import generate_report


def main() -> None:
    md = generate_report()
    # 只打印摘要，避免 GBK 控制台打印 emoji 崩溃
    print(f"已生成市场信息快报（{len(md)} 字符）")


if __name__ == "__main__":
    main()
