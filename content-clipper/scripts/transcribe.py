"""用 faster-whisper 把音视频文件转录为带时间戳的文本。

内容抓取类 skill 的公用转录环节：B站视频无 AI 字幕时、小红书视频帖无平台字幕时，
都用它把音频转成逐字稿。

它假定调用方已经把音视频转成了 16kHz 单声道 wav（见 content-clipper skill 的
ffmpeg 步骤），并已把 CUDA 运行时库目录加进 PATH（否则会报 cublas 加载失败）。

典型用法::

    # 直接输出到 stdout
    python transcribe.py audio.wav --model small

    # 写入文件
    python transcribe.py audio.wav --model small --output transcript.txt

    # 非中文素材：务必用 auto，否则会被强行按中文解码
    python transcribe.py audio.wav --language auto

    # 纯音乐/演唱素材：关闭 VAD 静音过滤
    python transcribe.py audio.wav --no-vad

    # CUDA 库不可用时退回 CPU
    python transcribe.py audio.wav --device cpu

输出默认写 stdout；指定 ``--output`` 时写文件而不打印正文。进度与诊断信息
一律走 stderr。

退出码：0 成功，1 输入或结果为空，2 参数、转录或输出失败。报告的耗时包含模型加载，
首次运行还会包含模型下载——判断模型规格开销时请以第二次运行为准。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 显式固定计算精度，避免不同设备的默认精度改变性能与显存需求。
GPU_COMPUTE_TYPE = "float16"
CPU_COMPUTE_TYPE = "int8"


def transcribe(
    wav_path: str,
    model_size: str = "small",
    device: str = "cuda",
    language: str | None = "zh",
    beam_size: int = 5,
    vad_filter: bool = True,
) -> tuple[list[str], float, float]:
    """把 wav 文件转录为带时间戳的文本行。

    Args:
        wav_path: 待转录的 wav 文件路径（应为 16kHz 单声道）。
        model_size: faster-whisper 模型规格，如 ``tiny``/``base``/``small``/``medium``/``large-v3``。
            越大越准也越慢。
        device: ``cuda`` 或 ``cpu``。不做自动降级——CUDA 环境异常会直接抛出异常，由调用方改用 ``cpu`` 重试。
        language: 语言代码，中文为 ``zh``；传 ``None`` 走自动检测。
            **非中文素材务必传 None**：强制 ``zh`` 会让 whisper 把其他语言也按中文解码，
            产出通顺但与内容无关的幻觉文本，极难察觉。
        beam_size: 束搜索宽度，越大越准但越慢。
        vad_filter: 是否用 VAD 先剔除静音段。纯音乐/演唱类素材建议关闭。

    Returns:
        ``(lines, duration, duration_after_vad)`` 三元组：文本行列表，以及音频的
        总时长与经 VAD 过滤后的有效时长（秒）。``lines`` **可能为空**，此时比较
        两个时长可了解 VAD 过滤量，但不能仅凭时长断定无语音或文件损坏。

    Raises:
        ValueError: 设备不受支持或束搜索宽度不是正数。
        ImportError: 当前 Python 环境未安装 faster-whisper。
        OSError: 音频或模型文件无法读取。
        RuntimeError: 模型加载或转录失败。
    """
    if device not in {"cuda", "cpu"} or beam_size <= 0:
        raise ValueError("device 必须是 cuda 或 cpu，beam_size 必须大于 0。")
    from faster_whisper import WhisperModel

    compute_type = GPU_COMPUTE_TYPE if device == "cuda" else CPU_COMPUTE_TYPE
    # 首次运行会联网下载模型，耗时可能达数分钟，这里给出提示避免用户误以为卡死。
    print(f"加载模型 {model_size}（首次运行需下载）...", file=sys.stderr)
    load_started = time.perf_counter()
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    print(f"模型就绪，耗时 {time.perf_counter() - load_started:.1f}s", file=sys.stderr)
    segments, info = model.transcribe(
        wav_path,
        language=language,
        vad_filter=vad_filter,
        beam_size=beam_size,
        # 关闭「用前文当提示」：开启时静音段会以前文为条件解码，产出语法通顺但
        # 凭空捏造的文本。用 --no-vad 处理静音素材时尤其危险。
        condition_on_previous_text=False,
    )

    print(
        f"检测语言: {info.language} (prob={info.language_probability:.2f})",
        file=sys.stderr,
    )

    lines: list[str] = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        hours, rem = divmod(int(seg.start), 3600)
        minutes, seconds = divmod(rem, 60)
        stamp = f"[{hours:02d}:{minutes:02d}:{seconds:02d}]"
        lines.append(f"{stamp} {text}")
    return lines, info.duration, info.duration_after_vad


def _describe_error(exc: Exception, device: str) -> str:
    """把底层异常翻译成可照做的排查提示。

    不按异常类型猜病因——faster-whisper 与 ctranslate2 在不同失败路径上会抛出
    相同类型但含义完全不同的异常。按异常消息特征分流，避免给出误导提示。

    Args:
        exc: 捕获到的异常。
        device: 本次使用的计算设备。

    Returns:
        面向用户的排查提示；未知 CUDA 错误仅补充设备信息，其余返回空字符串。
    """
    msg = str(exc).lower()
    if "cublas" in msg or "cudnn" in msg:
        return (
            "CUDA 运行库缺失。请确认 nvidia cublas/cudnn 的 bin 目录已加入 PATH，"
            "或改用 --device cpu 重试。"
        )
    if "invalid model" in msg or "is not a valid language" in msg:
        return "模型规格或语言代码不合法，请检查 --model 与 --language 的取值。"
    # 兜底不再猜测病因：未知错误提示换 CPU 往往答非所问（例如语言码笔误），
    # 只保留设备信息供使用者自行判断。
    return f"（当前 --device {device}，原始错误见上）" if device == "cuda" else ""


def main(argv: list[str] | None = None) -> int:
    """解析命令行参数、执行转录并输出结果。

    Args:
        argv: 命令行参数；省略时读取进程参数。

    Returns:
        进程退出码：0 成功，1 输入或结果为空，2 转录或输出失败。
    """
    if sys.platform == "win32":
        # 在解析参数前设置编码，让帮助和参数错误也能正确输出中文。
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="faster-whisper 音视频转录")
    parser.add_argument("wav", help="待转录的 wav 文件路径")
    parser.add_argument("--model", default="small", help="模型规格，默认 small")
    parser.add_argument(
        "--device",
        default="cuda",
        choices=["cuda", "cpu"],
        help="计算设备，默认 cuda（失败时请手动改 cpu）",
    )
    parser.add_argument(
        "--language",
        default="zh",
        help="语言代码，默认 zh；传 auto 走自动检测（非中文素材务必用 auto）",
    )
    parser.add_argument(
        "--beam-size", type=int, default=5, help="束搜索宽度，默认 5，越大越准但越慢"
    )
    parser.add_argument(
        "--no-vad",
        action="store_true",
        help="关闭 VAD 静音过滤（纯音乐、演唱类素材需要）",
    )
    parser.add_argument(
        "--output", default=None, help="结果写入的文件，默认写 stdout"
    )
    args = parser.parse_args(argv)
    if args.beam_size <= 0:
        parser.error("--beam-size 必须大于 0")

    if not Path(args.wav).is_file():
        print(f"错误: 找不到文件 {args.wav}", file=sys.stderr)
        return 1

    # faster-whisper 的语言码严格区分大小写，统一转小写避免 --language ZH 这类笔误。
    normalized = args.language.lower()
    language = None if normalized == "auto" else normalized

    started = time.perf_counter()
    try:
        lines, duration, duration_after_vad = transcribe(
            args.wav,
            model_size=args.model,
            device=args.device,
            language=language,
            beam_size=args.beam_size,
            vad_filter=not args.no_vad,
        )
    except ImportError as exc:
        print(f"转录依赖不可用: {exc}。请检查当前 Python 环境。", file=sys.stderr)
        return 2
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"转录失败: {exc}", file=sys.stderr)
        hint = _describe_error(exc, args.device)
        if hint:
            print(f"提示: {hint}", file=sys.stderr)
        return 2

    elapsed = time.perf_counter() - started

    # 空结果必须当成失败：否则下游会把「没转出内容」误当作「该音频无语音」，
    # 进而写出一份空笔记。
    if not lines:
        print("转录失败: 未得到任何文本段。", file=sys.stderr)
        # 用 VAD 过滤量区分两种情况，避免给出无效建议。
        removed = duration - duration_after_vad
        if removed > 1.0:
            print(
                f"提示: 总时长 {duration:.0f}s，VAD 过滤后仅剩 {duration_after_vad:.1f}s，"
                "请核对原音频是否有语音；确认有语音后可用 --no-vad 对比。",
                file=sys.stderr,
            )
        else:
            print(
                f"提示: 总时长 {duration:.1f}s，VAD 过滤量不明显。请检查音频内容与语言设置。",
                file=sys.stderr,
            )
        return 1

    payload = "\n".join(lines)
    if args.output:
        try:
            Path(args.output).write_text(payload, encoding="utf-8")
        except OSError as exc:
            print(f"写入转录结果失败: {exc}", file=sys.stderr)
            return 2
        print(f"已写入 {args.output}（{len(lines)} 段）", file=sys.stderr)
    else:
        print(payload)
    print(f"完成: {len(lines)} 段，总耗时 {elapsed:.1f}s（含模型加载）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
