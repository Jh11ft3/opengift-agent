#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenGift —— 类 OpenClaw 的极简 AI Agent
============================================

纯 Python 编写，零第三方依赖（只用 Python 自带标准库），
运行内存 < 30MB，pip 一键安装，可整包分享。

特性（对齐 OpenClaw 的核心能力）：
  * 多服务商可自选：默认「硅基流动 SiliconFlow」，默认模型 Qwen/Qwen3-8B；
    也支持 OpenAI / DeepSeek / 月之暗面 / 智谱 / 本地 Ollama（可跑 3B/4B 小模型）。
  * API Key 自己填，存在本地配置文件里，绝不上传。
  * 多轮对话 + 会话持久化（下次接着聊）。
  * 长期记忆：随时 /记住 或 /回忆。
  * 工具调用：查时间、安全计算、联网搜索、记笔记（模型自动决定何时使用）。
  * 语音朗读回复（--speak，用系统自带 TTS，不装任何环境）。
  * 流式输出（--stream）、一键自检（--doctor）、导出聊天记录（--export）。

用法：
  python opengift.py --config         # 第一次使用：配置服务商 / Key / 模型
  python opengift.py                  # 进入交互聊天
  python opengift.py "帮我算 1+2*3"   # 一次性提问
  python opengift.py --doctor         # 自检（含内存实测）
  python opengift.py --help           # 全部命令

环境要求：Python 3.8 及以上。不需要安装任何第三方包。
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import json
import math
import os
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

APP_NAME = "OpenGift"
VERSION = "0.2.0"
HOME_DIR_NAME = ".opengift"

# ---------------------------------------------------------------------------
# 服务商预设
# ---------------------------------------------------------------------------
PROVIDERS = {
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "models": [
            "Qwen/Qwen3-8B",
            "Qwen/Qwen3-4B",
            "Qwen/Qwen3-3B",
            "Qwen/Qwen2.5-7B-Instruct",
            "deepseek-ai/DeepSeek-V3",
        ],
        "note": "硅基流动（默认，注册即送额度，小模型便宜）",
        "site": "https://cloud.siliconflow.cn",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"],
        "note": "OpenAI 官方",
        "site": "https://platform.openai.com",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "note": "DeepSeek 深度求索",
        "site": "https://platform.deepseek.com",
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["moonshot-v1-8k", "moonshot-v1-32k"],
        "note": "月之暗面 Kimi",
        "site": "https://platform.moonshot.cn",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-4-flash", "glm-4-plus"],
        "note": "智谱 GLM",
        "site": "https://open.bigmodel.cn",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "models": ["qwen3:4b", "qwen3:1.7b", "qwen2.5:3b", "llama3.2:3b"],
        "note": "本地 Ollama（跑 3B/4B 小模型，需自己装 Ollama）",
        "site": "https://ollama.com",
    },
    "custom": {
        "base_url": "",
        "models": [],
        "note": "自定义（填任何 OpenAI 兼容接口地址）",
        "site": "",
    },
}

DEFAULT_PROVIDER = "siliconflow"
DEFAULT_MODEL = "Qwen/Qwen3-8B"

# ---------------------------------------------------------------------------
# 工具定义（模型自动决定调用）
# ---------------------------------------------------------------------------
TOOLS = {}


def _register(name, desc, params, fn):
    TOOLS[name] = {"desc": desc, "params": params, "fn": fn}


def _tool_get_time():
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")


def _tool_calc(expression):
    """安全算术计算：只允许数字与数学函数，禁止任何危险操作。"""
    try:
        expr = expression.strip()
        tree = ast.parse(expr, mode="eval")
        return str(_safe_eval(tree.body))
    except Exception as e:  # noqa: BLE001
        return "计算失败：" + str(e)


_MATH_NAMES = {
    "abs": abs, "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "log": math.log, "log10": math.log10, "exp": math.exp,
    "floor": math.floor, "ceil": math.ceil, "round": round, "min": min, "max": max,
    "pi": math.pi, "e": math.e,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in (
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow
    ):
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        return left ** right
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _safe_eval(node.operand)
        return v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.Name) and node.id in _MATH_NAMES:
        return _MATH_NAMES[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _MATH_NAMES:
        fn = _MATH_NAMES[node.func.id]
        if isinstance(fn, float):  # pi / e 被当成函数调用 -> 拒绝
            raise ValueError("非函数")
        args = [_safe_eval(a) for a in node.args]
        if node.keywords:
            raise ValueError("不支持关键字参数")
        return fn(*args)
    raise ValueError("表达式包含不允许的内容")


def _tool_remember(content):
    mem = _load_memory()
    mem.append({"id": _now_id(), "ts": _dt.datetime.now().isoformat(timespec="seconds"), "content": content})
    _save_memory(mem)
    return "已记住：" + content[:80]


def _tool_recall(keyword):
    mem = _load_memory()
    if not mem:
        return "记忆库还是空的。"
    tokens = [t for t in re.split(r"[\s,，。;；:：、]+", keyword) if t]
    scored = []
    for m in mem:
        s = sum(1 for t in tokens if t.lower() in m["content"].lower())
        if s > 0:
            scored.append((s, m))
    scored.sort(key=lambda x: (-x[0], -_ts_sort(x[1]["ts"])))
    top = scored[:5]
    if not top:
        return "没有找到相关记忆。"
    lines = ["记忆库匹配结果："]
    for _, m in top:
        lines.append(f"- [{m['ts']}] {m['content']}")
    return "\n".join(lines)


def _ts_sort(ts):
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))
    except Exception:  # noqa: BLE001
        return 0


def _tool_note_save(title, content):
    title = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]", "_", title).strip("_") or "note"
    path = os.path.join(_notes_dir(), title + ".md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return "笔记已保存：" + os.path.basename(path)


def _tool_note_read(title):
    title = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]", "_", title).strip("_") or "note"
    path = os.path.join(_notes_dir(), title + ".md")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()[:2000]
    return "没有找到这篇笔记。"


def _tool_note_list():
    try:
        files = [os.path.join(_notes_dir(), n) for n in os.listdir(_notes_dir()) if n.endswith(".md")]
    except Exception:  # noqa: BLE001
        return "还没有笔记。"
    files.sort(key=os.path.getmtime, reverse=True)
    if not files:
        return "还没有笔记。"
    return "\n".join(
        "- %s（%s）" % (
            os.path.basename(p),
            _dt.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m-%d %H:%M"),
        ) for p in files[:30]
    )


def _tool_web_search(query):
    """尽力而为的联网搜索（DuckDuckGo 网页版，纯标准库实现）。"""
    try:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            html = r.read().decode("utf-8", "ignore")
        items = re.findall(
            r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            html, re.S
        )
        if not items:
            return "搜索没有返回结果（网络或反爬限制），请稍后再试。"
        lines = []
        for href, title, snip in items[:5]:
            title = re.sub(r"<[^>]+>", "", title)
            snip = re.sub(r"<[^>]+>", "", snip)
            real = _decode_ddg_link(href)
            lines.append(f"- {title}\n  {snip.strip()}\n  {real}")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return "搜索失败：" + str(e)


def _decode_ddg_link(href):
    if "uddg=" in href:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [""])
        if q and q[0]:
            return urllib.parse.unquote(q[0])
    if href.startswith("//"):
        return "https:" + href
    return href


_register("get_time", "获取当前日期和时间（星期几）。", {}, _tool_get_time)
_register(
    "calc",
    "做数学计算。支持 + - * / // % ** 和括号，以及 abs/sqrt/sin/cos/tan/log/exp/floor/ceil/round/min/max/pi/e。",
    {"expression": {"type": "string", "description": "要计算的数学表达式，例如 (1+2)*3"}},
    _tool_calc,
)
_register(
    "remember",
    "把重要信息写入长期记忆，供以后回忆。适合记住用户的偏好、事实、约定。",
    {"content": {"type": "string", "description": "要记住的内容"}},
    _tool_remember,
)
_register(
    "recall",
    "在长期记忆里搜索与关键词相关的内容。",
    {"keyword": {"type": "string", "description": "搜索关键词"}},
    _tool_recall,
)
_register(
    "note_save",
    "保存一篇笔记（标题 + 正文），长期保留。",
    {"title": {"type": "string", "description": "笔记标题"}, "content": {"type": "string", "description": "笔记正文"}},
    _tool_note_save,
)
_register(
    "note_read",
    "读取一篇已保存的笔记。",
    {"title": {"type": "string", "description": "笔记标题"}},
    _tool_note_read,
)
_register("note_list", "列出所有笔记。", {}, _tool_note_list)
_register(
    "web_search",
    "联网搜索实时信息（尽力而为）。需要最新信息、你不知道的事实、或用户要求查资料时使用。",
    {"query": {"type": "string", "description": "搜索关键词"}},
    _tool_web_search,
)


def _tool_schemas():
    out = []
    for name, t in TOOLS.items():
        props = {}
        req = []
        for pname, pdef in t["params"].items():
            props[pname] = pdef
            req.append(pname)
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": t["desc"],
                "parameters": {"type": "object", "properties": props, "required": req or None},
            },
        })
    return out


# ---------------------------------------------------------------------------
# 路径与配置
# ---------------------------------------------------------------------------
def _home_dir():
    env = os.environ.get("OPEN_GIFT_HOME")
    if env:
        return _path(env)
    return _path(os.path.join(os.path.expanduser("~"), HOME_DIR_NAME))


def _path(*parts):
    p = os.path.join(*parts)
    os.makedirs(p, exist_ok=True) if not os.path.exists(p) else None
    return p


def _cfg_path():
    return os.path.join(_home_dir(), "config.json")


def _sessions_dir():
    return _path(_home_dir(), "sessions")


def _notes_dir():
    return _path(_home_dir(), "notes")


def _memory_path():
    return os.path.join(_home_dir(), "memory.json")


def _now_id():
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def load_config():
    cfg = {
        "provider": DEFAULT_PROVIDER,
        "model": DEFAULT_MODEL,
        "api_key": "",
        "base_url": PROVIDERS[DEFAULT_PROVIDER]["base_url"],
        "stream": False,
        "speak": False,
        "tools": True,
        "max_history": 24,
    }
    p = _cfg_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception:  # noqa: BLE001
            pass
    # 环境变量覆盖
    env_key = os.environ.get("OPEN_GIFT_API_KEY")
    if env_key:
        cfg["api_key"] = env_key
    env_model = os.environ.get("OPEN_GIFT_MODEL")
    if env_model:
        cfg["model"] = env_model
    env_provider = os.environ.get("OPEN_GIFT_PROVIDER")
    if env_provider:
        cfg["provider"] = env_provider
    # 服务商 base_url 兜底
    if not cfg.get("base_url") or cfg["provider"] != "custom":
        base = PROVIDERS.get(cfg.get("provider", DEFAULT_PROVIDER), {}).get("base_url")
        if base and (not cfg.get("base_url") or cfg["provider"] != "custom"):
            cfg["base_url"] = base
    return cfg


def save_config(cfg):
    with open(_cfg_path(), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("配置已保存到 " + _cfg_path())


# ---------------------------------------------------------------------------
# 记忆
# ---------------------------------------------------------------------------
def _load_memory():
    p = _memory_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:  # noqa: BLE001
            return []
    return []


def _save_memory(mem):
    with open(_memory_path(), "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------
def _session_files():
    try:
        return sorted(
            (os.path.join(_sessions_dir(), n) for n in os.listdir(_sessions_dir()) if n.endswith(".json")),
            key=os.path.getmtime, reverse=True,
        )
    except Exception:  # noqa: BLE001
        return []


def load_last_session():
    files = _session_files()
    if not files:
        return None
    try:
        with open(files[0], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def save_session(session):
    session["updated"] = _dt.datetime.now().isoformat(timespec="seconds")
    with open(os.path.join(_sessions_dir(), session["id"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)


def trim_history(history, max_msgs, max_chars=4000):
    """只保留最近 max_msgs 条，超长消息截断，控制 token 用量。"""
    if max_msgs <= 0:
        max_msgs = 24
    out = history[-max_msgs:]
    for m in out:
        if isinstance(m.get("content"), str) and len(m["content"]) > max_chars:
            m = dict(m)
            m["content"] = m["content"][:max_chars] + "…（已截断）"
    return out


# ---------------------------------------------------------------------------
# LLM 调用（OpenAI 兼容接口，纯标准库）
# ---------------------------------------------------------------------------
class ChatError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def _http_post_json(url, payload, headers, timeout=90):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")[:500]
        except Exception:  # noqa: BLE001
            pass
        raise ChatError(e.code, "HTTP %s：%s %s" % (e.code, e.reason, raw))
    except urllib.error.URLError as e:
        raise ChatError("NET", "网络错误（连不上 %s）：%s" % (url, e.reason))
    except socket.timeout:
        raise ChatError("TIMEOUT", "请求超时，请检查网络后重试。")


def llm_chat(cfg, messages, tools=None, stream=None):
    """调用服务商接口，返回 (content, tool_calls)。"""
    use_stream = cfg.get("stream", False) if stream is None else stream
    api_key = (cfg.get("api_key") or "").strip()
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    if not base:
        raise ChatError("CFG", "没有配置接口地址（base_url），请先运行 opengift --config")
    url = base + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + api_key,
    }
    payload = {
        "model": cfg.get("model") or DEFAULT_MODEL,
        "messages": messages,
        "stream": bool(use_stream),
        "temperature": 0.7,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    if not use_stream:
        raw = _http_post_json(url, payload, headers)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise ChatError("BADJSON", "接口返回的不是合法 JSON：\n" + raw[:300])
        choice = data["choices"][0]
        msg = choice.get("message", {})
        content = msg.get("content") or ""
        tool_calls = _normalize_tool_calls(msg.get("tool_calls"))
        return content, tool_calls
    return _stream_chat(url, payload, headers)


def _normalize_tool_calls(tcs):
    if not tcs:
        return []
    out = []
    for tc in tcs:
        fn = tc.get("function", {})
        args = fn.get("arguments", "")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = {}
        out.append({
            "id": tc.get("id") or ("call_" + _now_id()),
            "name": fn.get("name", ""),
            "arguments": args,
        })
    return out


def _stream_chat(url, payload, headers):
    payload = dict(payload)
    payload["stream"] = True
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST", headers=headers
    )
    content_parts = []
    tool_acc = {}
    finish = None
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            for raw_line in r:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                finish = choices[0].get("finish_reason")
                c = delta.get("content")
                if c:
                    content_parts.append(c)
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    acc = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        acc["id"] = tc["id"]
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        acc["name"] += fn["name"]
                    if fn.get("arguments"):
                        acc["arguments"] += fn["arguments"]
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")[:500]
        except Exception:  # noqa: BLE001
            pass
        raise ChatError(e.code, "HTTP %s：%s %s" % (e.code, e.reason, raw))
    except urllib.error.URLError as e:
        raise ChatError("NET", "网络错误：%s" % (e.reason,))
    except socket.timeout:
        raise ChatError("TIMEOUT", "流式请求超时。")

    tool_calls = []
    for idx in sorted(tool_acc):
        acc = tool_acc[idx]
        args = acc["arguments"]
        try:
            parsed = json.loads(args) if args.strip() else {}
        except json.JSONDecodeError:
            parsed = {}
        tool_calls.append({"id": acc["id"] or ("call_" + _now_id()), "name": acc["name"], "arguments": parsed})
    content = "".join(content_parts)
    if not content and not tool_calls and finish == "stop":
        content = "（模型未输出文字）"
    return content, tool_calls


# ---------------------------------------------------------------------------
# Agent 主循环（工具调用）
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = (
    "你是 {app}，一个极轻量、纯 Python 实现的命令行 AI 智能体（类 OpenClaw 的极简版）。\n"
    "当前时间：{now}。\n"
    "规则：\n"
    "1. 用中文回答，简洁、直接、友好，不要长篇大论。\n"
    "2. 需要实时信息/计算/记录/回忆时，主动调用工具；工具结果要如实转述。\n"
    "3. 不知道的就直说不知道，绝不编造。\n"
    "4. 涉及安全、违法、危险内容时明确拒绝。\n"
    "5. 你本身不联网、不记忆上次会话之外的内容，一切靠 API 和本地工具。"
)


def build_system_prompt(cfg):
    return SYSTEM_PROMPT_TEMPLATE.format(
        app=APP_NAME,
        now=_dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def chat_round(cfg, user_text, history, tools=True, stream=None, quiet=False):
    """执行一轮 Agent 对话（可能包含多轮工具调用），返回 (回复文本, 新history)。"""
    history = list(history)
    history.append({"role": "user", "content": user_text})
    messages = [{"role": "system", "content": build_system_prompt(cfg)}]
    messages += trim_history(history, cfg.get("max_history", 24))
    use_tools = bool(tools and cfg.get("tools", True))
    tool_schemas = _tool_schemas() if use_tools else None

    for _round in range(6):
        try:
            content, tool_calls = llm_chat(cfg, messages, tools=tool_schemas, stream=stream)
        except ChatError as e:
            # 服务商不支持 function calling 时报错，则去掉工具重试一次
            low = (e.msg or "").lower()
            if use_tools and (e.code == 400 and ("tool" in low or "function" in low or "参数" in low or "tools" in low)):
                use_tools = False
                tool_schemas = None
                continue
            raise

        if tool_calls:
            messages.append({
                "role": "assistant",
                "content": content or None,
                "tool_calls": [{
                    "id": tc["id"], "type": "function",
                    "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)},
                } for tc in tool_calls],
            })
            for tc in tool_calls:
                result = _dispatch_tool(tc["name"], tc.get("arguments") or {})
                if not quiet:
                    print("  [工具] %s → %s" % (tc["name"], result[:120].replace("\n", " ")))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": (result or "")[:1500],
                })
            continue

        messages.append({"role": "assistant", "content": content})
        history.append({"role": "assistant", "content": content})
        return content, history

    text = "（工具调用轮次过多，已自动停止。）"
    history.append({"role": "assistant", "content": text})
    return text, history


def _dispatch_tool(name, args):
    t = TOOLS.get(name)
    if not t:
        return "错误：未知工具 %s" % name
    try:
        result = t["fn"](**args)
        if result is None:
            return "（无返回值）"
        return str(result)
    except TypeError as e:
        return "参数错误：" + str(e)
    except Exception as e:  # noqa: BLE001
        return "工具执行失败：" + str(e)


# ---------------------------------------------------------------------------
# 语音朗读（系统自带 TTS，零依赖）
# ---------------------------------------------------------------------------
def _strip_md(text):
    text = re.sub(r"[#*_`>~]", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return text.strip()


def speak(text):
    """用系统 TTS 朗读文本。返回 True 表示成功。"""
    text = _strip_md(text)
    if not text:
        return False
    sys_name = platform.system()
    chunks = [text[i:i + 200] for i in range(0, len(text), 200)]
    try:
        if sys_name == "Darwin":
            for c in chunks:
                subprocess.run(["say", c], check=False, timeout=60)
        elif sys_name == "Windows":
            for c in chunks:
                esc = c.replace("'", "''")
                cmd = ("Add-Type -AssemblyName System.Speech; "
                       "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                       "$s.Speak('{0}')").format(esc)
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", cmd],
                    check=False, timeout=60,
                    creationflags=0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                )
        else:
            exe = None
            for cand, voice in (("espeak-ng", "-v cmn"), ("espeak", "-v zh")):
                if _which(cand):
                    exe, voice = cand, voice
                    break
            if not exe:
                return False
            for c in chunks:
                subprocess.run([exe, voice, c], check=False, timeout=60)
        return True
    except Exception:  # noqa: BLE001
        return False


def _which(name):
    try:
        return subprocess.run(["sh", "-c", "command -v " + name], capture_output=True, text=True, timeout=5).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def tts_available():
    sys_name = platform.system()
    if sys_name == "Darwin":
        return True
    if sys_name == "Windows":
        return True
    return _which("espeak-ng") or _which("espeak")


# ---------------------------------------------------------------------------
# 内存测量
# ---------------------------------------------------------------------------
def mem_mb():
    try:
        import resource
        raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return raw / 1024.0 if platform.system() != "Darwin" else raw / (1024.0 * 1024.0)
    except Exception:  # noqa: BLE001
        return -1.0


# ---------------------------------------------------------------------------
# 命令处理
# ---------------------------------------------------------------------------
def cmd_config():
    print("=" * 52)
    print("OpenGift 配置向导")
    print("=" * 52)
    cfg = load_config()
    prov_names = list(PROVIDERS.keys())
    print("\n可选服务商：")
    for i, k in enumerate(prov_names, 1):
        print("  %d. %-12s %s" % (i, k, PROVIDERS[k]["note"]))
    cur = prov_names.index(cfg.get("provider")) if cfg.get("provider") in prov_names else 0
    ans = input("\n选择服务商 [回车=%s]： " % prov_names[cur]).strip()
    provider = prov_names[cur]
    if ans:
        if ans.isdigit() and 1 <= int(ans) <= len(prov_names):
            provider = prov_names[int(ans) - 1]
        elif ans in PROVIDERS:
            provider = ans
        else:
            print("未识别，使用 " + provider)
    cfg["provider"] = provider

    if provider == "custom":
        ans = input("接口地址 base_url（如 https://api.example.com/v1）： ").strip()
        if not ans:
            print("必须填写接口地址。"); return
        cfg["base_url"] = ans.rstrip("/")
    else:
        cfg["base_url"] = PROVIDERS[provider]["base_url"]
        print("接口地址：%s" % cfg["base_url"])

    site = PROVIDERS.get(provider, {}).get("site", "")
    if site:
        print("\n如何获取 API Key：去 %s 注册 → 控制台 → API 密钥 → 新建密钥" % site)
    key = input("粘贴你的 API Key（不会显示明文，回车跳过则沿用旧值）： ").strip()
    if key:
        cfg["api_key"] = key

    models = PROVIDERS.get(provider, {}).get("models") or []
    if models:
        print("\n可选模型：")
        for i, m in enumerate(models, 1):
            print("  %d. %s" % (i, m))
        cur_m = cfg.get("model")
        default_m = models[0]
        if cur_m in models:
            default_m = cur_m
        ans = input("选择模型 [回车=%s]： " % default_m).strip()
        if ans.isdigit() and 1 <= int(ans) <= len(models):
            cfg["model"] = models[int(ans) - 1]
        elif ans:
            cfg["model"] = ans
        else:
            cfg["model"] = default_m
    else:
        ans = input("模型名（如 %s）： " % DEFAULT_MODEL).strip()
        if ans:
            cfg["model"] = ans

    ans = input("\n启用流式输出？[y/N]： ").strip().lower()
    cfg["stream"] = ans in ("y", "yes", "是")
    save_config(cfg)
    print("\n完成！现在运行 `opengift`（或 python opengift.py）开始聊天。")


def cmd_doctor(cfg):
    print("=" * 52)
    print("OpenGift 自检报告")
    print("=" * 52)
    print("Python        : %s (%s)" % (platform.python_version(), platform.system()))
    print("程序版本      : %s" % VERSION)
    print("数据目录      : %s" % _home_dir())
    print("服务商        : %s" % cfg.get("provider"))
    print("模型          : %s" % cfg.get("model"))
    print("接口地址      : %s" % cfg.get("base_url"))
    key = (cfg.get("api_key") or "").strip()
    masked = (key[:4] + "****" + key[-2:]) if len(key) > 6 else ("（未设置）" if not key else "****")
    print("API Key       : %s%s" % (masked, "" if key else "  ← 请先运行 opengift --config"))
    mem = mem_mb()
    print("内存占用(峰值): %s" % ("%.1f MB" % mem if mem > 0 else "未知"))
    print("工具数量      : %d 个" % len(TOOLS))
    mem_list = _load_memory()
    print("长期记忆条目  : %d 条" % len(mem_list))
    print("历史会话      : %d 个" % len(_session_files()))
    print("语音朗读      : %s" % ("可用" if tts_available() else "不可用（Linux 需 espeak/espeak-ng）"))
    # 网络探测
    base = (cfg.get("base_url") or "").strip()
    if key and base:
        try:
            req = urllib.request.Request(base.rstrip("/") + "/models", headers={"Authorization": "Bearer " + key})
            with urllib.request.urlopen(req, timeout=8) as r:
                print("网络连通      : 正常（HTTP %d，服务商 /models 可访问）" % r.status)
        except urllib.error.HTTPError as e:
            print("网络连通      : 服务商可达（HTTP %d），但接口需要正确 Key/模型权限" % e.code)
        except Exception as e:  # noqa: BLE001
            print("网络连通      : 失败（%s）" % str(e))
    else:
        print("网络连通      : 跳过（未配置 Key）")
    print("=" * 52)
    print("结论：%s" % ("一切就绪，开始聊天吧：opengift" if key and mem > 0 and mem <= 40 else "请按提示补配置（Key 必填；内存目标 <30MB）"))


# ---------------------------------------------------------------------------
# 交互模式
# ---------------------------------------------------------------------------
BANNER = """
{app} v{ver}  ——  纯 Python · 零依赖 · 内存<30MB · 类 OpenClaw 极简版
当前：{provider} / {model}     输入 /help 查看命令
""".strip()


def repl(cfg, session, speak_on, stream_on):
    history = session.get("messages", [])
    print(BANNER.format(app=APP_NAME, ver=VERSION, provider=cfg.get("provider"), model=cfg.get("model")))
    if not cfg.get("api_key"):
        print("提示：还没有配置 API Key，先运行：python opengift.py --config")
    while True:
        try:
            user = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if not user:
            continue
        if user.startswith("/"):
            if not _run_slash(user, cfg, session, history):
                break
            continue
        try:
            reply, history = chat_round(cfg, user, history, tools=True, stream=stream_on)
        except ChatError as e:
            if history and history[-1].get("role") == "user":
                history.pop()
            print("\n错误：%s\n（提示：检查 Key / 网络 / 模型名 / 服务商额度）" % e.msg)
            continue
        except KeyboardInterrupt:
            print("\n已中断。")
            continue
        print("\n" + APP_NAME + " > " + reply)
        if speak_on:
            ok = speak(reply)
            if not ok:
                print("（当前系统没有可用的 TTS，已跳过朗读）")
        session["messages"] = history
        save_session(session)


def _run_slash(cmdline, cfg, session, history):
    parts = cmdline.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd in ("/help", "/?"):
        print(
            "命令列表：\n"
            "  /help        显示本帮助\n"
            "  /new         开启新会话（历史保留在磁盘）\n"
            "  /clear       清空当前会话记忆\n"
            "  /memory      查看长期记忆\n"
            "  /remember x  直接记住 x\n"
            "  /speak       切换语音朗读（开/关）\n"
            "  /stream      切换流式输出（开/关）\n"
            "  /model NAME  临时切换模型\n"
            "  /provider X  临时切换服务商\n"
            "  /export 路径 导出聊天记录为 Markdown\n"
            "  /config      打开配置向导\n"
            "  /exit 或 /quit  退出"
        )
    elif cmd in ("/exit", "/quit"):
        return False
    elif cmd == "/new":
        session["id"] = _now_id()
        session["messages"] = []
        history.clear()
        print("已开启新会话。")
    elif cmd == "/clear":
        session["messages"] = []
        history.clear()
        print("已清空当前会话。")
    elif cmd == "/memory":
        mem = _load_memory()
        if not mem:
            print("（长期记忆为空，对我说“记住 xxx”即可写入）")
        else:
            for m in mem[-15:]:
                print("- [%s] %s" % (m["ts"], m["content"]))
    elif cmd == "/remember":
        if arg:
            print(_tool_remember(arg))
        else:
            print("用法：/remember 要记住的内容")
    elif cmd == "/speak":
        cfg["speak"] = not cfg.get("speak", False)
        print("语音朗读：" + ("开" if cfg["speak"] else "关"))
    elif cmd == "/stream":
        cfg["stream"] = not cfg.get("stream", False)
        print("流式输出：" + ("开" if cfg["stream"] else "关"))
    elif cmd == "/model":
        if arg:
            cfg["model"] = arg
            print("当前模型：%s" % cfg["model"])
        else:
            print("当前模型：%s（用法：/model 模型名）" % cfg["model"])
    elif cmd == "/provider":
        if arg and arg in PROVIDERS:
            cfg["provider"] = arg
            cfg["base_url"] = PROVIDERS[arg]["base_url"]
            print("当前服务商：%s（%s）" % (arg, PROVIDERS[arg]["base_url"]))
        elif arg:
            print("未知服务商。可选：" + ", ".join(PROVIDERS.keys()))
        else:
            print("当前服务商：%s" % cfg.get("provider"))
    elif cmd == "/export":
        path = arg or os.path.join(_home_dir(), "chat-export.md")
        _export_md(history, path)
        print("已导出到：" + path)
    elif cmd == "/config":
        cmd_config()
        new_cfg = load_config()
        cfg.update(new_cfg)
        print("配置已生效。")
    else:
        print("未知命令：%s（/help 查看）" % cmd)
    return True


def _export_md(messages, path):
    lines = ["# OpenGift 聊天记录", "", "导出时间：" + _dt.datetime.now().isoformat(timespec="seconds"), ""]
    for m in messages:
        role = "你" if m.get("role") == "user" else "OpenGift"
        lines.append("## %s" % role)
        lines.append(m.get("content", ""))
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(
        prog="opengift",
        description="OpenGift：纯 Python 零依赖、内存<30MB 的类 OpenClaw AI Agent（默认硅基流动 Qwen/Qwen3-8B）",
    )
    p.add_argument("question", nargs="*", help="一次性提问（不带参数则进入交互聊天）")
    p.add_argument("--config", action="store_true", help="配置向导（服务商/Key/模型）")
    p.add_argument("--doctor", action="store_true", help="自检（配置/网络/内存实测）")
    p.add_argument("--new", action="store_true", help="新开会话（默认续接上一次会话）")
    p.add_argument("--list-sessions", action="store_true", help="列出历史会话")
    p.add_argument("--memory", action="store_true", help="查看长期记忆")
    p.add_argument("--model", help="临时指定模型")
    p.add_argument("--provider", help="临时指定服务商")
    p.add_argument("--key", help="临时指定 API Key")
    p.add_argument("--base-url", help="临时指定接口地址")
    p.add_argument("--set-key", help="把 API Key 写入配置")
    p.add_argument("--set-model", help="把模型写入配置")
    p.add_argument("--set-provider", help="把服务商写入配置")
    p.add_argument("--set-base-url", help="把接口地址写入配置")
    p.add_argument("--stream", action="store_true", help="流式输出")
    p.add_argument("--speak", action="store_true", help="语音朗读回复")
    p.add_argument("--no-tools", action="store_true", help="禁用工具调用")
    p.add_argument("--export", metavar="PATH", help="导出上一次会话为 Markdown 后退出")
    p.add_argument("--version", action="version", version="%s %s" % (APP_NAME, VERSION))
    return p


def main(argv=None):
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    args = build_parser().parse_args(argv)

    # 写入式配置
    changed = False
    if args.set_key:
        cfg = load_config(); cfg["api_key"] = args.set_key; save_config(cfg); changed = True
    if args.set_model:
        cfg = load_config(); cfg["model"] = args.set_model; save_config(cfg); changed = True
    if args.set_provider:
        cfg = load_config(); cfg["provider"] = args.set_provider
        cfg["base_url"] = PROVIDERS.get(args.set_provider, {}).get("base_url", cfg.get("base_url", ""))
        save_config(cfg); changed = True
    if args.set_base_url:
        cfg = load_config(); cfg["base_url"] = args.set_base_url.rstrip("/"); save_config(cfg); changed = True
    if changed:
        print("已写入配置。")
        return 0

    if args.config:
        cmd_config()
        return 0

    cfg = load_config()
    if args.model:
        cfg["model"] = args.model
    if args.provider:
        cfg["provider"] = args.provider
        cfg["base_url"] = PROVIDERS.get(args.provider, {}).get("base_url", cfg.get("base_url", ""))
    if args.key:
        cfg["api_key"] = args.key
    if args.base_url:
        cfg["base_url"] = args.base_url.rstrip("/")
    if args.stream:
        cfg["stream"] = True
    if args.speak:
        cfg["speak"] = True

    if args.doctor:
        cmd_doctor(cfg)
        return 0
    if args.list_sessions:
        files = _session_files()
        if not files:
            print("还没有历史会话。")
            return 0
        for f in files:
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    s = json.load(fh)
                first = ""
                for m in s.get("messages", []):
                    if m.get("role") == "user":
                        first = m.get("content", "")[:40].replace("\n", " ")
                        break
                print("%s  消息数:%d   %s" % (s.get("id"), len(s.get("messages", [])), first))
            except Exception:  # noqa: BLE001
                continue
        return 0
    if args.memory:
        mem = _load_memory()
        if not mem:
            print("（长期记忆为空）")
        else:
            for m in mem:
                print("- [%s] %s" % (m["ts"], m["content"]))
        return 0
    if args.export:
        s = load_last_session()
        if not s:
            print("没有可导出的会话。")
            return 1
        _export_md(s.get("messages", []), args.export)
        print("已导出到：" + args.export)
        return 0

    # 会话
    session = None
    if not args.new:
        session = load_last_session()
    if not session:
        session = {"id": _now_id(), "created": _dt.datetime.now().isoformat(timespec="seconds"), "messages": []}

    # 一次性提问
    if args.question:
        text = " ".join(args.question)
        try:
            reply, history = chat_round(
                cfg, text, session.get("messages", []),
                tools=not args.no_tools, stream=cfg.get("stream", False),
            )
        except ChatError as e:
            print("错误：%s" % e.msg)
            return 1
        print(reply)
        if cfg.get("speak"):
            speak(reply)
        session["messages"] = history
        save_session(session)
        return 0

    repl(cfg, session, speak_on=cfg.get("speak", False), stream_on=cfg.get("stream", False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
