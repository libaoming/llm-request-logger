"""导出可以公开的版本：剔除本机注入的节，抹掉路径、邮箱、设备和会话标识。"""
import glob, os

from common import iter_sections, load, main_system_text, safe_name, scrub
from report import to_markdown

# 本机环境注入的整节，不属于厂商的提示词，导出时整节剔除
DROP_SECTIONS = {"# auto memory", "# claudeMd"}


# 已知的厂商手写节。被剔除的节里如果自带一级标题（比如你的 CLAUDE.md 里写了 "# 我的笔记"），
# 只按标题切会把后半截漏出来。所以剔除一节之后，一直剔到下一个已知的厂商标题为止，宁可多删。
VENDOR_SECTIONS = {
    "# System", "# Doing tasks", "# Executing actions with care", "# Using your tools", "# Tone and style",
    "# Text output (does not apply to tool calls)", "# Harness", "# Memory", "# Delivering work",
    "# Corrections", "# Communicating with the user", "# Context management", "# Environment",
    "# Session-specific guidance",
}


def strip_sections(body):
    out, dropping = [], False
    for head, text in iter_sections(body):
        name = head.strip() if head else None
        if name in DROP_SECTIONS:
            dropping = True
        elif name in VENDOR_SECTIONS or name is None:
            dropping = False
        if not dropping:
            out.append((head or "") + text)
    return "".join(out)


def export_dir(cap_dir, out_dir, full=False):
    """默认只导出 system 正文；full=True 时导出整份请求的可读版（同样脱敏）。"""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for f in sorted(glob.glob(os.path.join(cap_dir, "*.json"))):
        env = load(f)
        req = env["request"]
        if not isinstance(req, dict) or "system" not in req:
            continue
        if full:
            text = to_markdown(env, do_scrub=True)
            dest = os.path.join(out_dir, os.path.basename(f)[:-5] + ".md")
        else:
            text = scrub(strip_sections(main_system_text(req)))
            dest = os.path.join(out_dir, f"{safe_name(req.get('model'))}.md")
        with open(dest, "w") as fh:
            fh.write(text)
        written.append(dest)
        print(f"{req.get('model', '?'):<30} {len(text):>8,} 字符  -> {dest}")
    return written
