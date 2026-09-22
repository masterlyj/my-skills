# B站平台抓取细节

本文件是 `content-clipper` 的 B站专属参考。执行 B站链接前必须先读这一份，
**不要凭记忆推断参数**。

---

## 一、获取视频元数据

从链接提取 BVID（形如 `BV1CXet6gE6X`），调公开 view API：

```
https://api.bilibili.com/x/web-interface/view?bvid={BVID}
```

返回的 `data` 里可用字段：`title`、`owner.name`、`desc`、`pubdate`、
`duration`、`pages`、`stat.{view,like,favorite,danmaku,reply,coin,share}`、`cid`。

**注意**：`title` 与 `desc` 里含 HTML 实体（`&amp;` 等），要反转义。

标签另取：`https://api.bilibili.com/x/web-interface/view/detail/tag?bvid={BVID}`

**多 P 视频**：`pages` 有多项时，与用户确认要处理哪一 P，或全部处理。

---

## 二、获取字幕：BBDown 是唯一可靠方案

### 关键事实

**B站公开 API 全部不返回 AI 字幕**——`view`、`player/v2`、`player/wbi/v2`
均返回 `subtitles: []`，即使带正确 WBI 签名 + Cookie 也一样。
**唯一可靠方案是 BBDown。**

### 正确命令

```powershell
BBDown "<视频URL>" --sub-only --skip-ai false --work-dir "<临时目录>"
```

> ⚠️ **`--skip-ai false` 必须显式传**
> 该标志含义是「跳过 AI 字幕下载」，**默认值为 true**。不传就只会下载
> UP 主手动上传的 CC 字幕，AI 字幕会被跳过。
> - ❌ `BBDown <url> --sub-only`
> - ✅ `BBDown <url> --sub-only --skip-ai false`

**不需要登录**：BBDown 会提示「你尚未登录B站账号」，但 AI 字幕下载不受影响。
只有大会员专属视频才需要 `BBDown login` 扫码。

### 输出格式是 SRT

BBDown 输出标准 SRT（时间戳精度毫秒，如 `00:00:00,000`），**不是** JSON。
解析时按块分割：序号行 / 时间行 / 文本行。优先取 `*.ai-zh.srt`，
其次 `ai-en`，最后其他。

### 判断「视频没字幕」而不是「工具失败」

```powershell
BBDown "<视频URL>" --only-show-info
```

若输出里**只有视频轨和音频轨、没有任何字幕轨**，说明该视频本身没有 AI 字幕
（UP 主未开启，或视频太短）。**不要再重试 BBDown**，直接进入转录步骤。

---

## 三、B站常见错误与排查

| 现象 | 原因 | 处理 |
|------|------|------|
| BBDown 报「找不到可执行的 ffmpeg 文件」 | PATH 未刷新 | 重启终端，或显式把 ffmpeg 目录加进 PATH |
| BBDown 跑完没有字幕文件 | 视频本身无 AI 字幕 | 用 `--only-show-info` 确认后转录音频 |
| 只下到 CC 字幕、没有 AI 字幕 | 漏了 `--skip-ai false` | 补上该参数重跑 |
| 元数据 API 返回非 0 code | 视频不存在/私密/需登录 | 告知用户，不要反复重试 |

---

## 四、B站专属注意事项

1. **安装 BBDown**：`winget install nilaoda.BBDown`（winget 包会附带 ffmpeg）。
   安装后**必须重启终端**，否则 PATH 不生效。
2. **PowerShell here-string 与 Python 三引号冲突**：`@'...'@` 内不能出现 `"""`。
   解决方案是把 Python 脚本写入临时 `.py` 文件再执行，不要内联。
3. **yt-dlp 只是第三回退**：BBDown 失败后才考虑，且需另行安装。
   实际使用中很少需要。
4. **长视频转录耗时可观**：见主 SKILL.md 步骤 3 的性能参考。64 分钟视频
   在 RTX 4060 上 CUDA 转录约 4 分钟，CPU 则要长得多——优先确认 CUDA 可用。
5. **互动数据会随时间变化**：笔记里记录的是抓取当日的快照。

---

## 五、抓取后交给共享流程

B站抓取产出这两样，然后回到主 SKILL.md：

- **元数据**：标题、UP主、时长、发布日期、互动数据、标签
- **文本内容**：字幕文本（有）或音频转录（无字幕时走步骤 3）

画面理解（步骤 4）对 B站视频同样适用——技术视频的关键信息常在 PPT 与代码界面上。
