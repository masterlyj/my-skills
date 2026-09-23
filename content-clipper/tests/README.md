# content-clipper 测试

本目录包含两类测试，均**不读取 `.env`、不访问网络**。

## 文件

| 文件 | 内容 | 依赖 |
|------|------|------|
| `test_scripts.py` | 脚本外部边界的离线回归测试（用 mock 拦截请求） | 标准库 |
| `test_vision_integration.py` | 用真实依赖验证 `vision.py` 的清晰度评分与视频抽帧 | Pillow / numpy / ffmpeg / ffprobe |

两类测试的模块加载都按文件路径 `importlib` 加载 `scripts/*.py`，因此不受工作目录影响。

## 运行

在 **skill 根目录**（即含 `scripts/`、`tests/` 的目录）下执行。用你自己的 Python
解释器路径替换 `<python>`，用 `&` 调用可正确处理带空格的路径：

```powershell
# 无依赖测试（推荐先跑）
& "<python>" -B -m unittest discover -s tests -p "test_scripts.py" -v

# 只跑集成测试
& "<python>" -B -m unittest discover -s tests -p "test_vision_integration.py" -v

# 全套（无依赖 + 可选集成测试；缺少 Pillow/numpy/ffmpeg 时集成用例自动 skip）
& "<python>" -B -m unittest discover -s tests -v
```

`-B` 阻止写入 `__pycache__`，保持仓库干净。

## 依赖与自动 skip

集成测试不安装任何依赖，缺库时自动 `skip`：

| 缺失项 | 影响 |
|--------|------|
| Pillow 或 numpy | `select_sharpest` 评分用例整体 skip |
| ffmpeg 或 ffprobe | `extract_frames` 抽帧用例整体 skip |

即使全部缺失，`unittest discover` 仍能正常收集并全绿（显示为 skipped），不会报错。

由 testsrc2 合成的测试视频会用到 ffmpeg；用例不依赖 `drawtext`，因此不受
本机 fontconfig 缺省配置影响。所有临时文件通过 `TemporaryDirectory` 自动清理。

## 人工真实 API 测试

`test_vision_integration.py` **不调用模型接口**；`vision.py` 的真实视觉调用属人工测试。
需要自行把环境变量注入当前进程后再手动执行脚本（脚本本身不读 `.env`）：

```powershell
# 从你的密钥管理方式注入，不要把值写进仓库
$env:VISION_BASE_URL = "<服务商提供的基础地址>"
$env:VISION_API_KEY  = "<你的 key>"
$env:VISION_MODEL    = "<当前接口可用的视觉模型 ID>"

& "<python>" -B scripts/vision.py ask "<图片>" --question "这张图里有什么？"
```

脚本不自动加载 `.env`；上述变量需由调用者注入当前进程环境（或在 shell 中从文件加载）。
