"""各家服务商的 Anthropic 兼容地址。模型名是 2026-09 的示例，更新得快，以各家官方文档为准。"""

# name: (显示名, 上游地址, 示例模型, 官方文档)
PROVIDERS = {
    "anthropic":      ("Anthropic 官方", "https://api.anthropic.com", None,
                       "https://code.claude.com/docs"),
    "kimi":           ("Kimi 月之暗面（国内站）", "https://api.moonshot.cn/anthropic", "kimi-k3",
                       "https://platform.kimi.ai/docs/guide/claude-code-kimi"),
    "kimi-global":    ("Kimi Moonshot（国际站）", "https://api.moonshot.ai/anthropic", "kimi-k3",
                       "https://platform.kimi.ai/docs/guide/claude-code-kimi"),
    "glm":            ("智谱 GLM（国内站 bigmodel.cn）", "https://open.bigmodel.cn/api/anthropic", "glm-5.1",
                       "https://github.com/MetaGLM/glm-cookbook/blob/main/vibecoding/glm-4.5-claude-code-integration.md"),
    "glm-global":     ("智谱 GLM（国际站 z.ai）", "https://api.z.ai/api/anthropic", "glm-5.1",
                       "https://docs.z.ai/devpack/tool/claude"),
    "deepseek":       ("DeepSeek", "https://api.deepseek.com/anthropic", "deepseek-v4-pro",
                       "https://api-docs.deepseek.com/guides/anthropic_api"),
    "minimax":        ("MiniMax（国内站）", "https://api.minimaxi.com/anthropic", "MiniMax-M3",
                       "https://platform.minimax.io/docs/guides/text-ai-coding-tools"),
    "minimax-global": ("MiniMax（国际站）", "https://api.minimax.io/anthropic", "MiniMax-M3",
                       "https://platform.minimax.io/docs/guides/text-ai-coding-tools"),
    "qwen":           ("阿里云百炼 Qwen（Coding Plan）", "https://coding.dashscope.aliyuncs.com/apps/anthropic",
                       "qwen3.7-plus", "https://help.aliyun.com/zh/model-studio/claude-code"),
    "doubao":         ("火山方舟 豆包（Coding Plan）", "https://ark.cn-beijing.volces.com/api/coding",
                       "ark-code-latest", "https://www.volcengine.com/docs/82379/2373740"),
}


def agent_command(name, port):
    """另一个终端里要运行的命令。"""
    local = f"http://127.0.0.1:{port}"
    if name == "anthropic":
        # 只有官方需要这个开关：地址不是官方的，Claude Code 会关掉工具按需加载，抓到的包比平时大。
        return f"ANTHROPIC_BASE_URL={local} ENABLE_TOOL_SEARCH=true claude"
    # 第三方服务平时就不走官方地址，Claude Code 平时就是全量写入工具定义，所以不加开关才是真实流量。
    model = PROVIDERS[name][2]
    return (f"ANTHROPIC_BASE_URL={local} ANTHROPIC_AUTH_TOKEN=<你的 API key> \\\n"
            f"  ANTHROPIC_MODEL={model} ANTHROPIC_DEFAULT_OPUS_MODEL={model} \\\n"
            f"  ANTHROPIC_DEFAULT_SONNET_MODEL={model} ANTHROPIC_DEFAULT_HAIKU_MODEL={model} claude")


def print_list():
    print(f"{'--provider':<16} {'服务商':<28} 上游地址")
    for k, (label, url, _, _) in PROVIDERS.items():
        print(f"{k:<16} {label:<28} {url}")
    print("\n不在表里的服务，只要兼容 Anthropic Messages 格式，用 --upstream <地址> 接入。")
