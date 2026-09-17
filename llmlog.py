#!/usr/bin/env python3
"""llmlog：看清 AI 编程工具每一轮到底给模型发了什么。

  llmlog.py fake     假端点，请求不出本机，不花额度，测厂商原始提示词
  llmlog.py proxy    真代理，抓真实会话，拿到回复、token 用量和缓存读写（--provider kimi 等）
  llmlog.py providers 列出内置的服务商
  llmlog.py report   一份抓包：每块占多少，消息区里自动附上的内容来自哪
  llmlog.py diff     两份抓包：缓存前缀从哪里开始不一样
  llmlog.py compare  多个模型的 system 正文逐节对比
  llmlog.py export   导出脱敏后可以公开的版本
"""
import argparse, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from providers import PROVIDERS, print_list


def main(argv=None):
    ap = argparse.ArgumentParser(prog="llmlog", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("fake", "proxy"):
        p = sub.add_parser(name)
        p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8787)))
        p.add_argument("--out", default="./cap")
        if name == "proxy":
            g = p.add_mutually_exclusive_group()
            g.add_argument("--provider", choices=sorted(PROVIDERS), help="服务商，见 llmlog.py providers")
            g.add_argument("--upstream", default="https://api.anthropic.com", help="任意兼容 Anthropic 格式的地址")
    sub.add_parser("providers")
    p = sub.add_parser("report")
    p.add_argument("capture")
    p.add_argument("--md", metavar="OUT", help="另存一份能直接读的 Markdown")
    p.add_argument("--scrub", action="store_true", help="Markdown 里抹掉路径、邮箱和标识")
    p.add_argument("--top", type=int, default=10)
    p = sub.add_parser("diff")
    p.add_argument("a")
    p.add_argument("b")
    p = sub.add_parser("compare")
    p.add_argument("cap_dir")
    p = sub.add_parser("export")
    p.add_argument("cap_dir")
    p.add_argument("out_dir")
    p.add_argument("--full", action="store_true", help="导出整份请求，不只是 system 正文")
    a = ap.parse_args(argv)

    if a.cmd == "fake":
        import fake
        fake.serve(a.port, a.out)
    elif a.cmd == "proxy":
        import proxy
        proxy.serve(a.port, a.out, a.upstream, a.provider)
    elif a.cmd == "providers":
        print_list()
    elif a.cmd == "report":
        import report
        report.print_report(a.capture, a.top)
        if a.md:
            report.write_markdown(a.capture, a.md, a.scrub)
    elif a.cmd == "diff":
        import diff
        diff.print_diff(a.a, a.b)
    elif a.cmd == "compare":
        import compare
        compare.print_compare(a.cap_dir)
    elif a.cmd == "export":
        import export
        export.export_dir(a.cap_dir, a.out_dir, a.full)


if __name__ == "__main__":
    main()
