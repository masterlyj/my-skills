"""图片理解与视频抽帧的公用脚本，供内容抓取类 skill 复用。

提供三类能力：

1. 图片理解：把图片交给多模态模型，**既转录文字、也解读图示与要点**。
2. 视频抽帧：均匀采样后按清晰度/亮度筛选，产出适合读图的关键帧。
3. 批量处理：小红书图文帖常有多张图，逐张解读后按顺序合并。

图片默认走**理解模式**：模型先概括本页主题，再完整转录文字，然后描述
图示与元素关系，最后给出本页要点。这比单纯 OCR 保留更多信息——PPT 的
版式、箭头、热力图分布等非文字内容同样携带语义。

模型调用走 OpenAI 兼容接口，凭据从环境变量 ``VISION_API_KEY`` 读取，
接口地址必须通过环境变量 ``VISION_BASE_URL`` 配置，不提供默认端点。
模型通过 ``--model`` 或 ``VISION_MODEL`` 指定，不提供默认模型。

典型用法::

    # 解读单图（文字 + 图示 + 要点）
    python vision.py understand screenshot.png

    # 批量解读（按文件名排序合并）
    python vision.py understand img/ --batch

    # 只要纯文字转录
    python vision.py understand screenshot.png --raw

    # 视频抽帧（均匀采样 + 清晰度筛选）
    python vision.py frames video.mp4 --outdir frames/ --count 30

    # 对单图提自定义问题
    python vision.py ask screenshot.png --question "这张架构图分了几层？"
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

DEFAULT_API_KEY_ENV = "VISION_API_KEY"

# 默认目标帧数。均匀采样下 30 帧足以覆盖 5-15 分钟视频；论文显示
# 长视频场景帧数越多越准，需要更高保真时可调高到 60-100。
DEFAULT_FRAME_COUNT = 30

# 接口重试：批量解读会连打几十次请求，服务端偶发 5xx 是常态。
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0

# 清晰度权重高于亮度：模糊帧对 OCR 的伤害远大于偏暗帧。
SHARPNESS_WEIGHT = 0.7
BRIGHTNESS_WEIGHT = 0.3

UNDERSTAND_PROMPT = (
    "请完整解读这张图片，按以下结构输出：\n"
    "1. **本页主题**：这一页/这张图在讲什么，一句话概括。\n"
    "2. **完整内容**：逐行转录图中出现的所有文字，保持原有层次；"
    "表格用 Markdown 表格还原，保留所有数值；代码保留缩进。\n"
    "3. **图示与关系**：如果图中有流程图、架构图、箭头、坐标图、热力图等，"
    "描述各元素之间如何连接、数据如何流动、图形呈现出什么规律或趋势。\n"
    "4. **本页要点**：这张图想说明的核心结论是什么，以及它为什么重要。\n"
    "不要翻译原文，不要加入图中没有的信息。若图中确实没有任何文字，"
    "第 2 项写「无文字」，其余项照常依据图形内容作答。"
)

# 纯文字转录指令。仅在 understand 显式加 --raw 时使用；默认走理解模式。
OCR_PROMPT = (
    "请逐行读出这张图片中的所有文字，原样输出，保持原有换行与层次结构。"
    "不要翻译，不要解释，不要添加任何额外说明。如果图片没有文字，只输出：无文字。"
)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _api_key() -> str:
    """从环境变量读取 API key，缺失时抛出带指引的异常。"""
    key = os.environ.get(DEFAULT_API_KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(
            f"未设置环境变量 {DEFAULT_API_KEY_ENV}。请先设置，例如：\n"
            f'  PowerShell: $env:{DEFAULT_API_KEY_ENV}="sk-..."\n'
            f"不要把 key 写进脚本或提交到仓库。"
        )
    return key


def _encode_image(path: Path) -> str:
    """把图片文件编码成 data URI，供多模态接口使用。

    Args:
        path: 图片文件路径。

    Returns:
        形如 ``data:image/png;base64,....`` 的字符串。
    """
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def ask_image(
    image_path: str | Path,
    question: str,
    model: str | None = None,
    timeout: int = 120,
) -> str:
    """就单张图片向多模态模型提问。

    Args:
        image_path: 图片路径。
        question: 要问的问题。也可直接传入 :data:`UNDERSTAND_PROMPT` 或
            :data:`OCR_PROMPT` 做整图解读。
        model: 当前接口支持的视觉模型 ID；省略时读取 VISION_MODEL，无默认值。
        timeout: 单次请求的超时秒数。

    Returns:
        模型返回的文本内容。

    Raises:
        FileNotFoundError: 图片文件不存在。
        ValueError: 问题为空或超时不是正数。
        RuntimeError: 缺少端点、模型或凭据，或接口请求失败、未返回非空文本。
    """
    if not question.strip() or timeout <= 0:
        raise ValueError("问题不能为空，timeout 必须大于 0。")
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到图片: {path}")

    base_url = os.environ.get("VISION_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        raise RuntimeError("未设置环境变量 VISION_BASE_URL，请配置 OpenAI 兼容接口的基础地址。")
    model = (os.environ.get("VISION_MODEL", "") if model is None else model).strip()
    if not model:
        raise RuntimeError("未指定视觉模型，请通过 --model 或 VISION_MODEL 设置支持图片输入的模型 ID。")
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url", "image_url": {"url": _encode_image(path)}},
                ],
            }
        ],
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    return _request_text(req, timeout)


def _response_text(payload: bytes) -> str:
    """校验接口响应，只接受非空文本，避免把错误响应写进笔记。"""
    try:
        data = json.loads(payload)
        text = data["choices"][0]["message"]["content"]
    except (ValueError, UnicodeDecodeError, KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("模型响应格式无效：缺少 choices[0].message.content 文本。") from exc
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("模型未返回非空文本，请检查模型的视觉能力与响应格式。")
    return text


def _request_text(req: urllib.request.Request, timeout: int) -> str:
    """发送视觉请求，对限流、服务端及网络错误进行有界退避重试。"""
    # 认证和参数错误不能靠重试解决；408/429 则可能在等待后恢复。
    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = resp.read()
            return _response_text(payload)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code < 500 and exc.code not in (408, 429):
                raise RuntimeError(
                    f"请求被拒绝（HTTP {exc.code}）: {exc.reason}。"
                    f"请检查 VISION_API_KEY 与模型名，重试不会解决。"
                ) from exc
            last_error = f"HTTP {exc.code} {exc.reason}"
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = f"网络错误 {exc}"
        except OSError as exc:
            # SSLError、连接重置等属于 OSError 但不属于 URLError，同样可重试。
            last_error = f"连接错误 {exc}"

        if attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF_SECONDS * (2**attempt)
            print(
                f"  请求失败（{last_error}），{wait:.0f}s 后重试 "
                f"({attempt + 1}/{MAX_RETRIES})...",
                file=sys.stderr,
            )
            time.sleep(wait)

    raise RuntimeError(f"请求失败，已重试 {MAX_RETRIES} 次: {last_error}")


def _video_duration(video_path: Path) -> float:
    """用 ffprobe 读取视频时长（秒）。

    Args:
        video_path: 视频文件路径。

    Returns:
        视频时长（秒）。读取失败时返回 0，由调用方按兜底间隔处理。
    """
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        return 0.0
    try:
        duration = float((result.stdout or "0").strip())
        return duration if math.isfinite(duration) and duration > 0 else 0.0
    except ValueError:
        return 0.0


def _even_interval(duration: float, frame_count: int) -> float:
    """按视频时长与采样帧数算出均匀采样间隔（秒）。

    时长很短时保证至少按 1 秒间隔，避免间隔过小而抽到大量重复帧。调用方
    传入的是采样帧数，不一定是最终目标帧数。

    Args:
        duration: 视频时长（秒）。
        frame_count: 期望采样出的帧数。

    Returns:
        采样间隔（秒）。
    """
    if duration <= 0 or frame_count <= 0:
        return 5.0
    return max(duration / frame_count, 1.0)


def _extract_uniform(src: Path, dst: Path, interval: float) -> list[Path]:
    """按固定时间间隔均匀抽取候选帧。

    Args:
        src: 视频路径。
        dst: 候选帧输出目录。
        interval: 采样间隔（秒）。

    Returns:
        按时间顺序排列的候选帧路径列表。
    """
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-map", "0:v:0", "-an", "-sn", "-dn",
        "-vf", f"fps=1/{interval}",
        "-q:v", "3",
        str(dst / "cand_%04d.jpg"),
    ]
    result = subprocess.run(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg 抽帧失败（返回码 {result.returncode}）。"
            f"请确认视频文件有效。\n{result.stderr[-2000:]}"
        )
    return sorted(dst.glob("cand_*.jpg"))


def select_sharpest(
    candidates: list[Path], target: int
) -> list[Path]:
    """按清晰度与亮度从候选帧中挑出最适合读图的帧。

    清晰度用灰度图的 Laplacian 方差衡量，亮度用平均灰度衡量，两者做
    z-score 归一化后加权求和（清晰度权重更高）。亮度项偏好较亮的画面，
    并不单独检测过曝；仅在候选帧多于目标数时执行评分。

    Pillow 或 numpy 缺失时退化为均匀下采样。

    Args:
        candidates: 候选帧路径列表。
        target: 期望保留的帧数。

    Returns:
        选中的帧路径，保持原有时间顺序。

    Raises:
        ValueError: 目标帧数不是正数，或图片尺寸不足以计算清晰度。
    """
    if target <= 0:
        raise ValueError("target 必须大于 0。")
    if len(candidates) <= target:
        return candidates

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        # 无 Pillow/numpy 时退化为均匀下采样，仍能保证时间覆盖。
        step = len(candidates) / target
        return [candidates[int(i * step)] for i in range(target)]

    sharpness: list[float] = []
    brightness: list[float] = []
    for path in candidates:
        with Image.open(path) as im:
            gray = np.asarray(im.convert("L"), dtype=np.float64)
        if min(gray.shape) < 3:
            raise ValueError(f"图片尺寸不足 3×3，无法计算清晰度: {path}")
        brightness.append(float(gray.mean()))
        # Laplacian 方差：值越大表示边缘越锐利。
        lap = (
            -4 * gray[1:-1, 1:-1]
            + gray[:-2, 1:-1] + gray[2:, 1:-1]
            + gray[1:-1, :-2] + gray[1:-1, 2:]
        )
        sharpness.append(float(lap.var()))

    def _zscore(values: list[float]) -> "np.ndarray":
        """标准化评分，所有值相同时返回零以避免除零。"""
        arr = np.asarray(values, dtype=np.float64)
        std = arr.std()
        return (arr - arr.mean()) / std if std > 0 else arr * 0.0

    combined = (
        SHARPNESS_WEIGHT * _zscore(sharpness)
        + BRIGHTNESS_WEIGHT * _zscore(brightness)
    )
    ranked = np.argsort(combined)[::-1][:target]
    return [candidates[int(i)] for i in sorted(ranked)]


def _publish_frames(dst: Path, selected: list[Path]) -> list[str]:
    """把新帧发布进输出目录，失败时尽力恢复原有 ``frame_*.jpg``。

    发布前先校验所有最终目标：若某个编号位置已被同名目录占用则直接报错，
    避免把候选帧移动进该目录。随后把旧帧备份到 ``dst`` 内的临时目录，
    再用 :meth:`Path.replace` 逐个写入新帧（候选与输出目录同盘，无需复制
    回退）。备份以「先复制成功再删除原件」的方式建立，复制中途失败时原件
    仍在，不会丢数据。

    回滚用 :func:`shutil.copy2` 把备份复制回原位，只有全部恢复成功才清理
    备份目录；恢复失败时保留完整备份并打印路径，由使用者手动处理。

    Args:
        dst: 输出目录。
        selected: 已按时间顺序排好的候选帧路径。

    Returns:
        发布后的帧文件路径列表。

    Raises:
        RuntimeError: 某个最终目标已被同名目录占用。
        OSError: 备份或写入失败。已尽力恢复旧帧；若恢复本身也失败，备份
            会保留，并在 stderr 打印其路径，不再抛出二次异常。
    """
    stale = sorted(p for p in dst.glob("frame_*.jpg") if p.is_file())

    # 发布前拒绝非文件目标，避免备份旧帧后才发现目标冲突。
    for i in range(1, len(selected) + 1):
        target = dst / f"frame_{i:04d}.jpg"
        if target.exists() and not target.is_file():
            raise RuntimeError(
                f"目标 {target} 已存在且不是文件，无法发布帧。"
                f"请先移走该目录后重试。"
            )

    # 备份目录是候选临时目录的兄弟：位于 dst 内、前缀不同，不会被
    # 候选的 TemporaryDirectory 清理，也无需占用系统临时目录。
    backup_root = Path(tempfile.mkdtemp(prefix=".frame-backup-", dir=dst))
    backed_up: list[Path] = []
    published: list[Path] = []
    try:
        for old in stale:
            backup = backup_root / old.name
            shutil.copy2(old, backup)  # 复制成功前不动原件
            backed_up.append(old)
            old.unlink()

        for i, path in enumerate(selected, 1):
            final = dst / f"frame_{i:04d}.jpg"
            path.replace(final)
            published.append(final)
    except Exception:
        rollback_failed = False
        try:
            for new in published:
                if new.is_file():
                    new.unlink()
            for old in backed_up:
                # 复制成功前保留备份，以便回滚中途失败后手动恢复。
                shutil.copy2(backup_root / old.name, old)
        except Exception as rollback_exc:
            # 回滚失败：只报告，不清理备份目录，完整副本仍可用于手动恢复。
            rollback_failed = True
            print(
                f"恢复旧帧失败: {rollback_exc}。旧帧备份保留在 {backup_root}，"
                f"请手动复制回 {dst}。",
                file=sys.stderr,
            )
        if not rollback_failed:
            shutil.rmtree(backup_root, ignore_errors=True)
        raise

    shutil.rmtree(backup_root, ignore_errors=True)
    return [str(p) for p in published]


def extract_frames(
    video_path: str | Path,
    outdir: str | Path,
    frame_count: int = DEFAULT_FRAME_COUNT,
) -> list[str]:
    """从视频抽取适合多模态读图的关键帧。

    策略为「均匀采样 + 清晰度筛选」：先按视频时长算出均匀间隔抽取候选帧，
    再按清晰度/亮度评分选出目标数量的帧。依据 arXiv:2509.14769，长视频
    问答任务上均匀采样优于自适应选帧；依据 arXiv:2506.00667，抽取后用
    清晰度评分二次筛选可剔除模糊帧。

    候选帧按目标数的 2 倍采样，为清晰度筛选留出余量：`select_sharpest`
    仅在候选多于目标时才评分，等量采样会让筛选形同虚设。采样间隔有 1 秒
    下限，短视频时长不足时候选可能达不到目标数的 2 倍甚至不多于目标数，
    此时 `select_sharpest` 原样返回全部候选。

    Args:
        video_path: 视频文件路径。
        outdir: 输出目录，不存在则创建；成功选帧后替换其中的 frame_*.jpg。
        frame_count: 最多保留的帧数，必须大于零。

    Returns:
        按时间顺序排列的帧文件路径列表。

    Raises:
        ValueError: 目标帧数不是正数。
        OSError: 输入或外部命令不存在，或文件读写失败。
        RuntimeError: ffmpeg 抽帧失败或未产出候选帧。
    """
    if frame_count <= 0:
        raise ValueError("frame_count 必须大于 0。")
    src = Path(video_path)
    if not src.is_file():
        raise FileNotFoundError(f"找不到视频: {src}")

    dst = Path(outdir)
    dst.mkdir(parents=True, exist_ok=True)
    duration = _video_duration(src)
    # 候选取目标的 2 倍，给清晰度筛选留余量；间隔的 1 秒下限由 _even_interval 保证。
    interval = _even_interval(duration, frame_count * 2)
    # 隔离候选帧：失败时保留旧结果，且不误删调用方的 cand_*.jpg。
    with TemporaryDirectory(prefix=".frames-", dir=dst) as workdir:
        candidates = _extract_uniform(src, Path(workdir), interval)
        if not candidates:
            raise RuntimeError("未能从视频读取到任何帧，请确认视频文件有效。")
        selected = _publish_frames(dst, select_sharpest(candidates, frame_count))
    return selected


def _iter_images(target: Path) -> list[Path]:
    """收集目标路径下的图片文件，目录则按文件名排序展开。"""
    if target.is_file():
        return [target]
    return sorted(
        p for p in target.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )


def _cmd_understand(args: argparse.Namespace) -> int:
    """understand 子命令：逐张解读图片（文字 + 图示 + 要点）。"""
    images = _iter_images(Path(args.target))
    if not images:
        print(f"未找到图片: {args.target}", file=sys.stderr)
        return 1

    prompt = OCR_PROMPT if args.raw else UNDERSTAND_PROMPT
    label = "OCR" if args.raw else "理解"
    results: list[str] = []
    for i, img in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {label}: {img.name}", file=sys.stderr)
        text = ask_image(img, prompt, model=args.model)
        if args.batch and len(images) > 1:
            results.append(f"--- 第 {i} 张：{img.name} ---\n{text}")
        else:
            results.append(text)

    payload = "\n\n".join(results)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        print(f"已写入 {args.output}", file=sys.stderr)
    else:
        print(payload)
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    """ask 子命令：对单图提出自定义问题。"""
    print(ask_image(args.image, args.question, model=args.model))
    return 0


def _cmd_frames(args: argparse.Namespace) -> int:
    """frames 子命令：从视频抽取关键帧。"""
    frames = extract_frames(args.video, args.outdir, frame_count=args.count)
    print(f"共抽取 {len(frames)} 帧 -> {args.outdir}")
    for f in frames:
        print(f)
    return 0


def main(argv: list[str] | None = None) -> int:
    """解析命令行参数并执行图片理解或抽帧。

    Args:
        argv: 命令行参数；省略时读取进程参数。

    Returns:
        0 表示成功，1 表示处理失败；参数解析错误由 argparse 以 2 退出。
    """
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="图片理解与视频抽帧公用脚本")
    sub = parser.add_subparsers(dest="command", required=True)

    p_und = sub.add_parser(
        "understand", help="解读图片：文字 + 图示关系 + 要点（默认）"
    )
    p_und.add_argument("target", help="图片文件或目录")
    p_und.add_argument("--batch", action="store_true", help="目录批量模式，标注每张来源")
    p_und.add_argument("--output", default=None, help="结果写入文件")
    p_und.add_argument("--model", help="视觉模型 ID；优先于 VISION_MODEL，无默认模型")
    p_und.add_argument(
        "--raw", action="store_true", help="退化为纯文字转录，不做图示解读"
    )
    p_und.set_defaults(func=_cmd_understand)

    p_ask = sub.add_parser("ask", help="对单图提问")
    p_ask.add_argument("image", help="图片路径")
    p_ask.add_argument("--question", required=True, help="问题内容")
    p_ask.add_argument("--model", help="视觉模型 ID；优先于 VISION_MODEL，无默认模型")
    p_ask.set_defaults(func=_cmd_ask)

    p_frames = sub.add_parser("frames", help="视频抽帧")
    p_frames.add_argument("video", help="视频路径")
    p_frames.add_argument("--outdir", required=True, help="帧输出目录")
    p_frames.add_argument(
        "--count", type=int, default=DEFAULT_FRAME_COUNT,
        help=f"目标帧数，默认 {DEFAULT_FRAME_COUNT}",
    )
    p_frames.set_defaults(func=_cmd_frames)

    args = parser.parse_args(argv)
    if args.command == "frames" and args.count <= 0:
        parser.error("--count 必须大于 0")
    try:
        return args.func(args)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
