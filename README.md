# OpenGift · 轻量 AI Agent

> 纯 Python 编写 · **零第三方依赖** · 运行内存 **< 30MB** · pip 一键安装 / curl 一键下载 · 可整包分享

一个像 **OpenClaw** 一样的个人 AI 智能体：能聊天、能记住事、能调用工具干活，跑在你自己的电脑上。
但它是**极简版**：只有一个 Python 文件，不装任何第三方包、不装 Node、不装 Docker，老电脑、小内存设备都能带得动。

---

## 一、它能干什么（与 OpenClaw 功能对照）

| 能力 | OpenClaw（原版） | OpenGift（本程序） |
|---|---|---|
| 多服务商自选 | ✅ | ✅ 硅基流动（默认）/ OpenAI / DeepSeek / Kimi / 智谱 / 本地 Ollama |
| API Key 自己填 | ✅ | ✅ 写在本地配置，不上传 |
| 多轮对话 | ✅ | ✅ |
| 会话持久化（下次接着聊） | ✅ | ✅ |
| 长期记忆（记住/回忆） | ✅ | ✅ `/remember`、`/memory`、自动调工具 |
| 工具调用 | ✅ | ✅ 查时间、安全计算、记笔记、联网搜索 |
| 语音朗读 | ✅ | ✅ `--speak`（系统自带 TTS，不装环境） |
| 流式输出 | ✅ | ✅ `--stream` |
| 导出聊天记录 | ✅ | ✅ `--export` |
| 联网渠道（微信/WhatsApp 等） | ✅ | ❌ 极简版只在命令行里聊天 |
| 运行内存 | 较大 | **< 30MB**（实测 ≈24MB） |

## 二、为什么内存这么小

- 只用 **Python 自带标准库**（urllib/json/argparse…），零第三方包；
- 没有 GUI、没有浏览器内核、没有数据库；
- 所有数据是本地几个 JSON/文本小文件（`~/.opengift/`）；
- 模型推理全在云端（或你自己的本地 Ollama），本地进程只做“收发消息 + 调工具”。

## 三、环境要求

- Python **3.8 及以上**（Windows / macOS / Linux 都行；手机上用 Termux 也能跑）
- **不需要** 安装任何第三方 Python 包、Node、Docker 等环境

检查方法：命令行输入 `python3 --version`（Windows 输 `python --version`）。

## 四、三步上手

### 第 1 步：拿到程序（curl 下载 或 pip 安装）

网页版：访问部署好的 OpenGift 网页，直接复制下面的命令：

```bash
# 方式 A：curl 一键下载脚本（最简单，免安装）
curl -fsSL https://你的域名/opengift.py -o opengift.py
python3 opengift.py --help

# 方式 B：curl 下载 wheel + pip 一键安装成全局命令（推荐）
curl -fsSL https://你的域名/opengift-0.2.0-py3-none-any.whl -o opengift-0.2.0-py3-none-any.whl
pip install opengift-0.2.0-py3-none-any.whl
opengift --help

# 方式 C：一键安装脚本（自动下载并提示下一步）
curl -fsSL https://你的域名/install.sh -o install.sh && sh install.sh
```

> 分享给朋友：把 `opengift` 文件夹（或 zip）发过去，对方解压后同样三步即可。

### 第 2 步：配置 Key（只做一次）

```bash
opengift --config
```

按向导走：
1. 选择服务商（回车默认 **硅基流动 siliconflow**）
2. 粘贴你的 API Key —— 去 `https://cloud.siliconflow.cn` 注册，控制台 → API 密钥 → 新建，复制即可（新用户送额度，小模型几乎免费）
3. 选择模型（回车默认 **Qwen/Qwen3-8B**）

也可以不进入向导直接写入配置：

```bash
opengift --set-key sk-你的key --set-model Qwen/Qwen3-8B --set-provider siliconflow
```

### 第 3 步：开始聊天

```bash
opengift                          # 交互聊天（下次打开自动续上次的会话）
opengift "帮我算 1+2*3 等于多少"   # 一次性提问
opengift --doctor                 # 自检：配置、网络、内存实测
```

试一下让它干活：

```
你 > 记住我的名字是小明
你 > 你还记得我叫什么吗？
你 > 帮我查一下今天几号
你 > 记一篇笔记，标题：购物清单，内容：牛奶、鸡蛋、面包
```

## 五、怎么选模型（含 3B/4B 小模型）

默认：**硅基流动 + Qwen/Qwen3-8B**。想更省、更快可换成小模型：

| 场景 | 服务商 | 模型名 |
|---|---|---|
| 默认（推荐） | 硅基流动 | `Qwen/Qwen3-8B` |
| 更小更便宜 | 硅基流动 | `Qwen/Qwen3-4B` |
| 最小最省 | 硅基流动 | `Qwen/Qwen3-3B` |
| 本地跑 3B/4B（要装 Ollama） | 本地 Ollama | `qwen3:4b` / `qwen2.5:3b` |
| 深度思考 | DeepSeek | `deepseek-reasoner` |

切换方式：`opengift --set-model Qwen/Qwen3-4B`，或聊天中 `/model Qwen/Qwen3-4B`，或 `--provider ollama`。

## 六、语音朗读（发语音）

```bash
opengift --speak                  # 每次回复都朗读
opengift --speak "今天天气不错"    # 一次性提问并朗读
```

- macOS：自带 `say`，直接可用；
- Windows：自带 PowerShell TTS，直接可用；
- Linux：需要系统有 `espeak-ng` 或 `espeak`（多数发行版自带，没有则 `sudo apt install espeak-ng`）。
- 说明：当前版本是“**让 agent 开口说话**”（离线 TTS）；“说话→文字”的语音输入需要额外的转写服务，暂未内置。

## 七、常用命令速查

```bash
opengift                     # 交互聊天
opengift "问题"               # 一次性提问
opengift --config            # 配置向导
opengift --doctor            # 自检（含内存实测）
opengift --new               # 强制新开会话
opengift --list-sessions     # 历史会话列表
opengift --memory            # 查看长期记忆
opengift --stream            # 流式输出
opengift --speak             # 语音朗读
opengift --export chat.md    # 导出上次会话
opengift --set-key sk-xxx    # 直接写 Key
```

聊天中的斜杠命令：`/help` `/new` `/clear` `/memory` `/remember 内容` `/speak` `/stream` `/model 模型名` `/provider 服务商` `/export 路径` `/exit`

## 八、常见问题

**1. 报“没有配置 API Key”** → 先 `opengift --config` 填 Key。

**2. 报网络/HTTP 错误** → 检查：Key 是否正确、是否复制了多余空格、服务商是否欠费/无额度、电脑能不能联网。`opengift --doctor` 会帮你测连通性。

**3. 报“工具/function”相关 400 错误** → 该模型不支持工具调用，程序会自动去掉工具重试；也可用 `--no-tools`。

**4. 想在手机 Termux 上跑？** → Termux 里装好 Python 后，把 `opengift.py` 放进去，直接 `python opengift.py --config` 即可，内存照样 < 30MB。

**5. 数据都存在哪？** → `~/.opengift/` 目录（config.json 配置、sessions/ 会话、memory.json 记忆、notes/ 笔记），全在本机，删掉即重置。

## 九、内存实测

在 Linux 上运行 `opengift --doctor` 报告的峰值内存（RSS）：

```
内存占用(峰值): 23.9 MB   ← 目标 < 30MB
```

> 实测方法：`/usr/bin/time -v python3 opengift.py --doctor 2>&1 | grep "Maximum resident"`（Linux）。

## 十、部署网页版（让别人也能 curl 下载）

把 `opengift-site/` 文件夹里的内容上传到任意静态托管（GitHub Pages / Vercel / Netlify），
别人访问网页即可复制 curl 命令下载 OpenGift。详见 `opengift-site/部署说明.md`。

---

MIT License · 可自由分享、修改。数据不上云，Key 只存本机。
