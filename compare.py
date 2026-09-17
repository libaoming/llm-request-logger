"""多个模型并排：system 正文逐节字符数。环境注入的节排除在外，只数厂商手写的策略正文。"""
import glob, os

from common import load, main_system_text, split_sections

# 这些节由本机环境注入，随机器变，不随模型变
ENV_SECS = {"# auto memory", "# Environment", "# claudeMd", "# Session-specific guidance"}


def collect(cap_dir):
    """每个模型取最新的一份抓包。"""
    rows = {}
    for f in sorted(glob.glob(os.path.join(cap_dir, "*.json"))):
        req = load(f)["request"]
        if not isinstance(req, dict) or "system" not in req:
            continue
        body = main_system_text(req)
        secs = dict(split_sections(body))
        rows[req.get("model", os.path.basename(f))] = {
            "total": len(body), "secs": secs, "tools": len(req.get("tools") or []),
            "hand": sum(n for h, n in secs.items() if h not in ENV_SECS),
            "route": "new" if "# Harness" in secs else "legacy"}
    return rows


def print_compare(cap_dir):
    rows = collect(cap_dir)
    if not rows:
        print(f"{cap_dir} 里没有可用的抓包")
        return rows
    print(f"{'model':<30} {'system 总':>9} {'手写正文':>9} {'tools':>6}  路由")
    for m, r in rows.items():
        print(f"{m:<30} {r['total']:>9,} {r['hand']:>9,} {r['tools']:>6}  {r['route']}")
    heads = []
    for r in rows.values():
        heads += [h for h in r["secs"] if h not in heads and h not in ENV_SECS]
    print(f"\n{'节':<46}" + "".join(f"{m.replace('claude-', '')[:12]:>14}" for m in rows))
    for h in heads:
        print(f"{h:<46}" + "".join(f"{r['secs'].get(h) or '-':>14}" for r in rows.values()))
    return rows
