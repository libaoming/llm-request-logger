"""读一份抓包：每一块占多少字符，消息区里自动附上的内容分别来自哪。可另存成能直接读的 Markdown。"""
import json, re

from common import dumps, load, scrub, split_sections, system_blocks

# 消息区里自动附上的内容靠这些开头识别。顺序无关，按出现位置切段
MARKERS = [
    (re.compile(r"Contents of (.+?)(?= \(|:?\n|$)", re.M), lambda m: f"规则文件 {m.group(1).strip()}"),
    (re.compile(r"The following skills are available"), lambda m: "skill 目录"),
    (re.compile(r"The following deferred tools are now available"), lambda m: "延迟加载的工具名单"),
    (re.compile(r"Available agent types"), lambda m: "子 agent 类型介绍"),
    (re.compile(r"# MCP Server Instructions"), lambda m: "MCP 使用说明"),
    (re.compile(r"# gitStatus"), lambda m: "git 状态"),
    (re.compile(r"# userEmail"), lambda m: "账号邮箱"),
    (re.compile(r"# currentDate"), lambda m: "当前日期"),
    (re.compile(r"Attribution for git commits"), lambda m: "提交署名要求"),
]
REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def cut_by_markers(text, fallback):
    hits = sorted((m.start(), label(m)) for pat, label in MARKERS for m in pat.finditer(text))
    if not hits:
        return [(fallback, len(text))] if text.strip() else []
    out = []
    if text[:hits[0][0]].strip():
        out.append((fallback, hits[0][0]))
    for (pos, name), nxt in zip(hits, hits[1:] + [(len(text), None)]):
        out.append((name, nxt[0] - pos))
    return out


def attribute_text(text, role):
    """把一个文本块切成 [(来源, 字符数)]。提醒块之外的文字，才是这个角色自己说的话。"""
    out, last = [], 0
    own = "你输入的内容" if role == "user" else f"{role} 正文"
    # 用户自己打的字里出现 "# gitStatus" 之类的字样不算注入，所以提醒块之外的 user 文本不按标记切
    outside = (lambda t: [(own, len(t))] if t.strip() else []) if role == "user" else (
        lambda t: cut_by_markers(t, own))
    for m in REMINDER.finditer(text):
        out += outside(text[last:m.start()])
        out += cut_by_markers(m.group(0), "其他自动提醒")
        last = m.end()
    return out + outside(text[last:])


def attribute_messages(req):
    rows = []
    for i, msg in enumerate(req.get("messages") or []):
        role, content = msg.get("role", "?"), msg.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
        for b in blocks:
            if b.get("type") == "text":
                rows += [(i, role, name, n) for name, n in attribute_text(b.get("text", ""), role)]
            else:
                rows.append((i, role, f"{b.get('type')} 块", len(dumps(b))))
    return rows


def merge(rows):
    """同一来源的多段合并，按字符数从大到小排。"""
    total = {}
    for _, _, name, n in rows:
        total[name] = total.get(name, 0) + n
    return sorted(total.items(), key=lambda kv: -kv[1])


def analyze(env):
    req = env["request"]
    tools = req.get("tools") or []
    sizes = {"tools": len(dumps(tools)), "system": len(dumps(system_blocks(req))),
             "messages": len(dumps(req.get("messages") or []))}
    return {
        "model": req.get("model"),
        "sizes": sizes,
        "tools": sorted(((t.get("name", "?"), len(dumps(t))) for t in tools), key=lambda x: -x[1]),
        "system": [(len(b.get("text", "")), bool(b.get("cache_control")),
                    (b.get("text", "").strip().splitlines() or [""])[0][:60]) for b in system_blocks(req)],
        "sections": split_sections(max((b.get("text", "") for b in system_blocks(req)), key=len, default="")),
        "messages": merge(attribute_messages(req)),
        "n_messages": len(req.get("messages") or []),
        "usage": (env.get("response") or {}).get("usage") or {},
    }


def print_report(path, top=10):
    env = load(path)
    if not isinstance(env["request"], dict) or "_unparsed" in env["request"]:
        print(f"文件   {path}\n这份请求不是 JSON 对象，无法分析。用 --md 导出原文查看。")
        return None
    a = analyze(env)
    total = sum(a["sizes"].values()) or 1
    print(f"文件   {path}")
    print(f"模型   {a['model']}    模式 {env['mode']}    状态 {env.get('status')}")
    print("\n== 三大块（按缓存前缀顺序；各块重新序列化成 JSON 后的字符数，不是字节数）==")
    for k in ("tools", "system", "messages"):
        print(f"  {k:<9} {a['sizes'][k]:>9,} 字符  {a['sizes'][k] / total:>5.1%}")
    print(f"\n== tools：{len(a['tools'])} 个，最大的 {min(top, len(a['tools']))} 个 ==")
    for name, n in a["tools"][:top]:
        print(f"  {n:>8,}  {name}")
    print(f"\n== system：{len(a['system'])} 块 ==")
    for n, cached, first in a["system"]:
        print(f"  {n:>8,}  {'缓存断点' if cached else '        '}  {first}")
    if a["sections"]:
        print("  -- 正文分节 --")
        for h, n in a["sections"]:
            print(f"  {n:>8,}  {h}")
    print(f"\n== messages：{a['n_messages']} 条，按来源归并（文本按原文字符数计，所以合计小于上面 JSON 口径的总数）==")
    for name, n in a["messages"]:
        print(f"  {n:>8,}  {name}")
    if a["usage"]:
        print("\n== token 用量（服务器返回的真实值）==")
        for k, v in a["usage"].items():
            if isinstance(v, (int, float)):
                print(f"  {k:<32} {v:>8,}")
    return a


# ---------- 可读的 Markdown ----------

def render_block(b):
    t = b.get("type")
    if t == "text":
        return b.get("text", "")
    if t == "tool_use":
        return f"**tool_use** `{b.get('name')}`\n\n```json\n{json.dumps(b.get('input'), ensure_ascii=False, indent=2)}\n```"
    if t == "tool_result":
        c = b.get("content")
        body = c if isinstance(c, str) else "\n".join(render_block(x) for x in c or [])
        return f"**tool_result**\n\n{body}"
    if t == "image":
        return "*[图片已省略]*"
    return f"```json\n{json.dumps(b, ensure_ascii=False, indent=2)}\n```"


def to_markdown(env, do_scrub=False):
    req, resp = env["request"], env.get("response") or {}
    params = {k: v for k, v in req.items() if k not in ("system", "tools", "messages", "metadata")}
    out = [f"<meta>\n\n- 时间: {env.get('timestamp')}\n- 模式: {env['mode']}\n- 模型: {req.get('model')}\n"
           f"- 路径: {env.get('method')} {env.get('path')}\n- 状态: {env.get('status')}\n\n</meta>",
           f"<params>\n\n```json\n{json.dumps(params, ensure_ascii=False, indent=2)}\n```\n\n</params>",
           "<system-prompt>\n\n" + "\n\n<!-- 块边界 -->\n\n".join(
               b.get("text", "") + ("\n\n<!-- cache_control 断点 -->" if b.get("cache_control") else "")
               for b in system_blocks(req)) + "\n\n</system-prompt>",
           "<tools>\n\n" + "\n\n".join(
               f"### {t.get('name')}\n\n{t.get('description', '')}\n\n```json\n"
               f"{json.dumps(t.get('input_schema'), ensure_ascii=False, indent=2)}\n```"
               for t in req.get("tools") or []) + "\n\n</tools>"]
    msgs = []
    for i, m in enumerate(req.get("messages") or [], 1):
        c = m.get("content")
        body = c if isinstance(c, str) else "\n\n".join(render_block(b) for b in c or [])
        msgs.append(f'<message index="{i}" role="{m.get("role")}">\n\n{body}\n\n</message>')
    out.append("<messages>\n\n" + "\n\n".join(msgs) + "\n\n</messages>")
    out.append(f"<response>\n\n- stop_reason: {resp.get('stop_reason')}\n- 内容块: {resp.get('blocks') or []}\n- usage: "
               f"{json.dumps(resp.get('usage') or {}, ensure_ascii=False)}\n\n{resp.get('text') or ''}\n\n</response>")
    text = "\n\n".join(out) + "\n"
    return scrub(text) if do_scrub else text


def write_markdown(path, dest, do_scrub=False):
    with open(dest, "w") as f:
        f.write(to_markdown(load(path), do_scrub))
    print(f"\n可读版已写出 -> {dest}" + (
        "\n已抹掉路径、用户名、邮箱和各种标识。规则文件正文、git 状态、MCP 服务名这些内容还在，公开前自己再看一遍。"
        if do_scrub else "（未脱敏，别公开）"))
