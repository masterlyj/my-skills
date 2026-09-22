# 小红书平台抓取细节

本文件是 `content-clipper` 的小红书专属参考。执行小红书链接前必须先读这一份，
**不要凭记忆推断参数**。

---

## 一、Cookies（首次使用需配一次）

小红书帖子详情**必须带登录态**才能抓。cookie 文件放在用户目录下，
路径由脚本参数传入，不写死在代码里。

### 导出步骤

1. 在 Chrome 打开 `xiaohongshu.com` 并确认已登录
2. F12 打开 DevTools → Console，运行以下代码（把 cookies 复制到剪贴板）：

```javascript
copy(JSON.stringify(document.cookie.split('; ').map(c => {
  const [name, ...rest] = c.split('=');
  return { name, value: rest.join('='), domain: '.xiaohongshu.com', path: '/' };
})))
```

3. 把剪贴板内容保存到 `~/.cookies/xhs-cookies.json`（目录不存在先创建）
4. **终止当前流程**，等用户配好后重新运行

> 只保留 `name` / `value` / `domain` / `path` 四个字段即可。
> DevTools 直接复制的完整对象里那些 `sameParty`、`sourceScheme`、
> `priority` 等 Chromium 内部字段服务端不校验，属冗余。

### 过期判断

请求被重定向到 404 或错误页 —— 说明 cookies 过期，提示用户按上面重新导出。

---

## 二、解析链接

从 URL 提取：
- **帖子 ID**：24 位十六进制字符串（`/explore/<id>` 或 `/discovery/item/<id>`）
- **xsec_token**：查询参数，部分请求需要带上

短链 `xhslink.com` 需先跟随重定向拿到真实 URL。

---

## 三、获取帖子内容

带 cookies 请求帖子页 HTML，从 `window.__INITIAL_STATE__` 解析 JSON：

```python
import json, re, ssl, urllib.request

# cookies_file 与 url 由调用方传入，不要硬编码路径
with open(cookies_file, encoding="utf-8") as f:
    cookies = json.load(f)
cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

req = urllib.request.Request(url)
req.add_header("Cookie", cookie_str)
# 用统一的桌面 UA，不要按开发机系统写死
req.add_header("User-Agent",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
    html = resp.read().decode("utf-8", errors="ignore")

m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\})\s*</script>", html, re.DOTALL)
raw = m.group(1).replace("undefined", "null")   # 页面里会有裸 undefined
data = json.loads(raw)

# 数据路径：data['note']['noteDetailMap'][<key>]['note']
# 字段：title, desc, type, time, user, imageList, video, interactInfo, ipLocation
```

**`type` 字段决定后续分支**：`normal` 是图文帖，`video` 是视频帖。

---

## 四、视频帖：优先平台字幕

若 `type == "video"`，**先用平台内嵌字幕**，没有才转录（转录走主 SKILL.md 步骤 3）。

### 找字幕

```
note['video']['media'] 或 note['video']['mediaV2']（JSON 字符串，需二次解析）
→ 查 subtitles 字段
→ 优先级：source > zh-CN > en-US
→ 取对应语言的 SRT URL
```

### 下载字幕

```powershell
# 字幕 CDN 域名必须用 HTTPS（HTTP 会超时）
curl.exe -sL --connect-timeout 10 -o "<临时目录>\xhs_<帖子ID>.srt" `
  -H "User-Agent: Mozilla/5.0" `
  -H "Referer: https://www.xiaohongshu.com/" `
  "<字幕URL 确保 https://>"
```

解析 SRT（同 B站：按块分割，去序号与时间戳），合并为连续文本，按语义断句。
**平台字幕比语音转录更准，还能省去下载视频，务必优先**。

### 无字幕时的转录

下载视频 → 抽出音频 → 走主 SKILL.md 步骤 3 的转录流程。

- 视频 URL：`note['video']['media']['stream']`，按 `h264 > h265 > av1` 取第一个的 `masterUrl`
- 下载时带 `Referer: https://www.xiaohongshu.com/`

---

## 五、图文帖：图片解读

`type == "normal"` 时，帖子正文常以**图片**为载体（长文截图、PPT 翻拍、信息图）。

**是否需要解读**：若 `desc` 已含完整正文（>500 字）通常不用；若 `desc` 很短
（只有标题或引言）而图片 ≥3 张，则图片就是正文，需要解读。

### 下载图片

从 `imageList` 取每张的 `urlDefault`：

```powershell
# 关键：把 http:// 换成 https://，否则连小红书 CDN 会超时
curl.exe -sL --connect-timeout 10 -o "<临时目录>\img_00.jpg" `
  -H "Referer: https://www.xiaohongshu.com/" `
  -H "User-Agent: Mozilla/5.0" `
  "<图片URL 确保 https://>"
```

### 解读

用共享脚本（详见主 SKILL.md 步骤 4 与 `vision-usage.md`）：

```powershell
python scripts/vision.py understand "<图片目录>" --batch --output "<临时目录>\imgs.txt"
```

解读结果按图片顺序拼接为完整文章，并修复跨图的断句（上一张最后一行可能与
下一张第一行是同一句）。含大量文字的图片，嵌入**解读出的文字**而非图片 URL。

---

## 六、小红书专属注意事项

1. **临时目录不要写死 `/tmp`**：Windows 上不存在该路径。统一用系统临时目录
   （脚本里可由调用方传入，或走标准库的临时目录）。
2. **删除临时文件用 PowerShell 语法**：`Remove-Item -Recurse -Force`，
   不要用 Unix 的 `rm -f`。
3. **删掉 `mlx_whisper` 相关代码**：那是 Apple Silicon 专属，本机不可用。
   本机转录一律走共享 `transcribe.py`（faster-whisper + CUDA）。
4. **UA 统一**：全文用同一个桌面 UA，不要在不同步骤写不同 UA，
   也不要伪装成 macOS。
5. **`curl` 在 PowerShell 里是别名**：`curl` 会被解析成 `Invoke-WebRequest`，
   参数不兼容。**必须用 `curl.exe`**。
6. **图片 URL 必须 HTTPS**：小红书 CDN 用 HTTP 会超时，这是高频坑。
7. **cookie 含敏感信息**：不要提交到仓库，不要写进笔记，不要打印完整内容。

---

## 七、抓取后交给共享流程

小红书抓取产出这两样，然后回到主 SKILL.md：

- **元数据**：标题、作者、发布时间、互动数据、标签、`type`
- **内容**：图文帖的图片解读结果，或视频帖的字幕/转录文本
