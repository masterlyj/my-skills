---
name: content-clipper
description: 抓取 B站视频、小红书帖子等内容，转录语音、解读画面，整理为 Markdown 笔记并保存。
disable-model-invocation: true
metadata:
  opencode/autoinvoke: false
---

# content-clipper

把 B站视频、小红书帖子等内容抓下来，转成结构化 Markdown 笔记，落到项目里的
`clips/` 目录。

**这个 skill 不是「复制链接」，而是「读懂内容」**：视频会转录语音、读关键画面，
图文帖会解读长文截图与信息图，最终形成可直接使用的笔记。

> **这是项目级 skill，需要手动加载。**
> - Claude Code 用 `/content-clipper` 调用
> - OpenCode 里直接说出 `content-clipper` 这个名字
> - 两个客户端都**不会自动触发**（frontmatter 里已关闭）

## 适用与不适用

**适用**：用户给出 B站视频链接/BV 号，或小红书帖子链接，要求总结、整理、收藏、归档。

**不适用**：只要标题不要内容（不必走完整流程）；纯本地文件处理（不走抓取步骤）。

---

## 步骤 0：环境自检（必做）

**本 skill 不提供 Python 环境，也不假定它装在哪。** 请先自行准备环境并激活，
再执行后续步骤。

需要装的东西：

```powershell
# 在项目根建环境（名称随意，下面统一用 .venv 举例）
uv venv .venv
uv pip install --python .venv\Scripts\python.exe Pillow numpy faster-whisper

# 需要 GPU 加速转录时，额外装 CUDA 运行库
uv pip install --python .venv\Scripts\python.exe nvidia-cublas-cu12 nvidia-cudnn-cu12

# 激活
.venv\Scripts\Activate.ps1
```

外部命令依赖：

| 依赖 | 检测 | 缺失处理 |
|------|------|---------|
| Python 3.10+ | `python --version` | 先装并激活环境 |
| ffmpeg / ffprobe | `Get-Command ffmpeg` | `winget install Gyan.FFmpeg` |
| BBDown（仅 B站） | `Get-Command BBDown` | `winget install nilaoda.BBDown` |
| curl | `Get-Command curl.exe` | Windows 10+ 自带 |
| `VISION_API_KEY` | `$env:VISION_API_KEY` | 画面理解需要；未设置则跳过并说明 |

> ⚠️ **ffmpeg PATH 陷阱**：winget 新装的 ffmpeg 对**已打开的 shell 不可见**，
> BBDown 内部调用会直接报「找不到 ffmpeg」。**重启终端**，或把 ffmpeg 目录
> 显式加进当前进程 PATH。
>
> ⚠️ **CUDA 库陷阱**：`pip` 装的 nvidia 库不会自动进 PATH，转录前需要：
> ```powershell
> $sp = (python -c "import site; print(site.getsitepackages()[0])")
> $env:PATH = "$sp\nvidia\cublas\bin;$sp\nvidia\cudnn\bin;$sp\nvidia\cuda_nvrtc\bin;$env:PATH"
> ```
> 报 `cublas64_12.dll is not found` 就是这一步没做。

**这个仓库的某个项目里可能已经搭好环境**——先看看项目根有没有 `.venv/`，
有就激活它，不必重建。

### 路径约定（重要）

`scripts/` 与 `references/` 都是**相对本 SKILL.md 所在目录**的。执行脚本前，
要先切到 skill 目录，否则 `python scripts/vision.py` 会因为工作目录不对而找不到文件：

```powershell
# 切到 skill 目录（Claude Code / OpenCode 的项目级挂载点）
cd <项目>\.claude\skills\content-clipper

# 或直接用变量的方式，避免记路径
$skill = "<项目>\.claude\skills\content-clipper"
python "$skill\scripts\vision.py" ...
```

本文档后面所有 `python scripts/xxx.py` 都**默认当前目录是 skill 目录**。

---

## 步骤 1：识别来源

从链接判断平台，决定后续读取哪份参考：

| 链接特征 | 平台 | 需读参考 |
|---------|------|---------|
| `bilibili.com/video/BV...` 或 `BV` 号 | B站 | `references/platform-bilibili.md` |
| `xiaohongshu.com` / `xhslink.com` | 小红书 | `references/platform-xhs.md` |

> ⚠️ **平台抓取细节必须读参考文件，不要凭记忆推断参数。**
> 两个平台的抓取方式完全不同，参数与常见错误都记在对应 reference 里。

---

## 步骤 2：抓取内容

按下表拿到「原始素材」——B站要元数据+字幕，小红书要帖子正文+图片。

| 平台 | 目标 | 方法（详见对应 reference） |
|------|------|--------------------------|
| B站 | 元数据（标题/UP主/时长/互动） | 公开 view API |
| B站 | 字幕 | **BBDown**（`--skip-ai false`） |
| 小红书 | 正文与图片列表 | cookies + 页面 `__INITIAL_STATE__` |
| 小红书 | 视频帖字幕 | 平台内嵌字幕优先 |

**关键判断**：BBDown 跑完没有字幕文件、且 `--only-show-info` 里只有视频轨和
音频轨 —— 说明**该视频没有 AI 字幕**（不是工具失败），**不要重试**，进入步骤 3。

抓取结果统一落到一个临时工作目录，后续步骤都在那里处理。

---

## 步骤 3：转录（无字幕时）

当视频既无平台字幕、也无 UP 主上传字幕，而用户需要正文内容时，用音频转录。

**流程**（三小步）：

```powershell
# 1. 下载音频（B站用 BBDown；小红书见其 reference）
BBDown "<视频URL>" --audio-only --work-dir "<临时目录>"

# 2. 转 16k 单声道 wav
ffmpeg -y -i "<音频>" -vn -acodec pcm_s16le -ar 16000 -ac 1 "<临时目录>\audio.wav"

# 3. 转录（前提：已激活环境；用 CUDA 时先按步骤 0 把 nvidia 库加进 PATH）
python scripts/transcribe.py "<临时目录>\audio.wav" --model small --output "<临时目录>\transcript.txt"
```

**性能参考（实测）**：RTX 4060 Laptop 上，6分50秒音频 CPU 需 166 秒、CUDA 仅 24 秒；
64 分钟音频 CUDA 约 229 秒。

**何时不该转录**：纯画面/纯 BGM 无解说；用户只想要标题级信息；视频超长且用户未明确要求。

**转录后**：small 模型对专有名词有误差（实测 `SQLite`→`C口`、`PostgreSQL`→`PulseGray`），
整理笔记时应结合标题/标签/画面 OCR **相互校验修正**。

---

## 步骤 4：画面理解（补充字幕之外的信息）

字幕只记录「说了什么」，而技术内容的关键常在**画面上**——代码、架构图、PPT、演示界面。

```powershell
$env:VISION_API_KEY = "<你的 key>"

# 1. 抽帧（均匀采样 + 清晰度筛选）
python scripts/vision.py frames "<视频>" --outdir "<帧目录>" --count 30

# 2. 逐帧解读（文字 + 图示关系 + 要点）
python scripts/vision.py understand "<帧目录>" --batch --output "<临时目录>\frames.txt"
```

> ⚠️ **解读前先读 `references/vision-usage.md`**：里面有抽帧策略的依据、
> 参数含义，以及「为什么不能按场景分数选帧」的实测原因。不要凭直觉调参。

**何时启用**：有代码演示、图表讲解、架构设计、教程操作；或字幕提到「如图」但字幕本身没有内容。

**何时跳过**：纯口播访谈、播客类；已有高质量字幕且不涉及图表。

---

## 步骤 5：生成笔记

把三份材料合并：**元数据 + 转录/字幕 + 画面解读**。

**默认用中性 Markdown**（标准引用块、标准链接），输出到 `clips/<平台>/`。

> 如需 Obsidian 的折叠 callout 效果，改用 `references/note-template-obsidian.md`
> 里的模板——那是可选的替代格式，默认路径不使用。

**写作要求**：
- 标题是**洞察或判断**，不是「XX视频的总结」
- 结构化提取信息，**不要整段贴**转录原文
- 表格数据照实引用；代码提炼为关键思路
- 画面解读里的「图示与关系」「本页要点」直接补进结构化部分
- 标注**字幕来源**（平台字幕 / 本地转录 / 无字幕）

**可信度纪律**：所有数字、专有名词，若转录与画面解读不一致，以**画面 OCR 为准**
（文字比语音识别更可靠），并在笔记中避免臆测。

---

## 步骤 6：保存与索引

1. 笔记存到 `clips/<平台>/{YYYY-MM-DD} {短标题}.md`，短标题不超过 15 字
2. 更新同目录的 `📋 索引.md`：按日期倒序，每行 `- [[笔记名]] — 核心洞察 \`#标签\``
3. 清理临时工作目录（下载的音视频、抽出的帧、中间文件）

---

## ⚠️ 维护须知

- **不要改回「按场景分数选帧」**：实测教程类视频 scene 分数极低（P99 仅 0.03），
  且高分段是过渡帧（运动模糊），最不适合读图。详见 `references/vision-usage.md`
- **不要退化成纯 OCR**：`understand` 默认解读图示关系与要点，`--raw` 仅在确需纯文字时用
- **平台参数以 reference 为准**：BBDown 的 `--skip-ai false` 等参数可能随版本变化
- 改动任何平台抓取逻辑，同步更新对应 `references/platform-*.md`
