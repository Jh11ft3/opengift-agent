#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenGift 端到端冒烟测试（纯标准库，不需要真实 API Key）
=============================================================
在本地起一个 mock 的 OpenAI 兼容接口，验证：
  1. 默认配置（硅基流动 / Qwen/Qwen3-8B）
  2. 普通对话请求与解析
  3. 工具调用循环（模型要求调工具 → 执行 → 返回最终回答）
  4. 流式输出解析
  5. 安全计算器
  6. 长期记忆 记住/回忆
运行：python3 tests/test_smoke.py -v
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import opengift as oc  # noqa: E402


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静音
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        stream = body.get("stream", False)
        msgs = body.get("messages", [])
        has_tool_result = any(m.get("role") == "tool" for m in msgs)
        last_user = [m for m in msgs if m["role"] == "user"][-1]["content"]

        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()

            def chunk(text):
                payload = json.dumps(
                    {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]},
                    ensure_ascii=False,
                )
                self.wfile.write(("data: " + payload + "\n\n").encode("utf-8"))
                self.wfile.flush()

            if body.get("tools") and not has_tool_result:
                tc = {"id": "call_s1", "type": "function",
                      "function": {"name": "get_time", "arguments": "{}"}}
                payload = json.dumps(
                    {"choices": [{"index": 0, "delta": {"tool_calls": [tc]}, "finish_reason": "tool_calls"}]},
                    ensure_ascii=False,
                )
                self.wfile.write(("data: " + payload + "\n\n").encode("utf-8"))
                self.wfile.flush()
            else:
                text = "收到：" + last_user
                for i in range(0, len(text), 5):
                    chunk(text[i:i + 5])
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        if body.get("tools") and not has_tool_result:
            resp = {"choices": [{"index": 0, "message": {
                "role": "assistant", "content": "",
                "tool_calls": [{"id": "call_1", "type": "function",
                                "function": {"name": "get_time", "arguments": "{}"}}],
            }, "finish_reason": "tool_calls"}]}
        elif has_tool_result:
            tool_content = [m for m in msgs if m["role"] == "tool"][-1]["content"]
            resp = {"choices": [{"index": 0, "message": {
                "role": "assistant", "content": "我已经调用工具，结果：" + tool_content,
            }, "finish_reason": "stop"}]}
        else:
            resp = {"choices": [{"index": 0, "message": {
                "role": "assistant", "content": "收到：" + last_user,
            }, "finish_reason": "stop"}]}
        out = json.dumps(resp, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


class SmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="opengift-test-")
        os.environ["OPEN_GIFT_HOME"] = cls.tmp
        cls.server = HTTPServer(("127.0.0.1", 0), MockHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.cfg = {
            "provider": "custom",
            "model": "mock-model",
            "api_key": "test-key",
            "base_url": "http://127.0.0.1:%d/v1" % cls.port,
            "stream": False,
            "speak": False,
            "tools": True,
            "max_history": 24,
        }

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_01_default_config(self):
        cfg = oc.load_config()
        self.assertEqual(cfg["provider"], "siliconflow")
        self.assertEqual(cfg["model"], "Qwen/Qwen3-8B")
        self.assertIn("siliconflow.cn", cfg["base_url"])

    def test_02_plain_chat(self):
        reply, history = oc.chat_round(self.cfg, "你好呀", [], tools=False)
        self.assertEqual(reply, "收到：你好呀")
        self.assertEqual(history[-1]["role"], "assistant")
        self.assertEqual(history[0]["role"], "user")

    def test_03_tool_loop(self):
        reply, _ = oc.chat_round(self.cfg, "现在几点了？", [], tools=True)
        self.assertIn("我已经调用工具", reply)
        self.assertIn("202", reply)  # get_time 结果（年份）被模型转述

    def test_04_stream_chat(self):
        content, tool_calls = oc.llm_chat(self.cfg, [
            {"role": "user", "content": "流式你好"},
        ], tools=None, stream=True)
        self.assertEqual(content, "收到：流式你好")
        self.assertEqual(tool_calls, [])

    def test_05_stream_tool_call(self):
        content, tool_calls = oc.llm_chat(self.cfg, [
            {"role": "user", "content": "几点了"},
        ], tools=oc._tool_schemas(), stream=True)
        self.assertEqual(tool_calls[0]["name"], "get_time")

    def test_06_calc(self):
        self.assertEqual(oc._tool_calc("(1+2)*3"), "9")
        self.assertEqual(oc._tool_calc("sqrt(16)+2**3"), "12.0")
        r = oc._tool_calc("__import__('os').system('id')")
        self.assertIn("计算失败", r)  # 危险表达式被拒绝

    def test_07_memory(self):
        oc._tool_remember("用户叫小明，喜欢蓝色")
        r = oc._tool_recall("小明")
        self.assertIn("小明", r)
        self.assertIn("蓝色", r)

    def test_08_notes(self):
        oc._tool_note_save("购物清单", "牛奶 鸡蛋 面包")
        r = oc._tool_note_read("购物清单")
        self.assertIn("牛奶", r)
        self.assertIn("购物清单", oc._tool_note_list())


if __name__ == "__main__":
    unittest.main(verbosity=2)
