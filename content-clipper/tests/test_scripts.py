"""离线验证内容处理脚本：使用 unittest discover 运行，不请求模型或加载权重。"""

import builtins
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from contextlib import contextmanager, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _load_script(name):
    """按文件路径加载脚本，避免依赖工作目录或修改模块搜索路径。"""
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vision = _load_script("vision")
transcribe = _load_script("transcribe")


@contextmanager
def _frame_dir():
    """建好抽帧测试的目录骨架，产出 (source, output)。

    临时根目录在退出时自动清理；source 是已存在的占位视频文件，output 是
    已创建的空帧目录。调用方按需往 output 里放旧帧或目录，再自行注入故障。
    """
    with tempfile.TemporaryDirectory() as root:
        root = Path(root)
        source = root / "video.mp4"
        source.touch()
        output = root / "frames"
        output.mkdir()
        yield source, output


@contextmanager
def _simulate_missing_pillow():
    """让 numpy 与 PIL 的导入失败，模拟未装图片依赖的环境。

    只拦截 numpy/PIL 及其子模块，其余导入交给真实的 ``__import__``，
    以免影响测试自身或其他模块。
    """
    real_import = builtins.__import__

    def no_pillow(name, *args, **kwargs):
        """对 numpy/PIL 抛 ImportError，其余导入照常。"""
        if name in {"numpy", "PIL"} or name.startswith(("numpy.", "PIL.")):
            raise ImportError(f"simulated missing {name}")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=no_pillow):
        yield


class VisionTests(unittest.TestCase):
    """视觉请求和抽帧的外部边界回归测试。"""

    def test_missing_base_url_fails_before_request(self):
        """验证端点必须显式配置，缺失或空白时不发送请求。"""
        with tempfile.TemporaryDirectory() as root:
            image = Path(root) / "image.png"
            image.touch()
            for value in (None, "", "   "):
                env = {} if value is None else {"VISION_BASE_URL": value}
                with (
                    self.subTest(value=value),
                    patch.dict(vision.os.environ, env, clear=True),
                    patch.object(vision.urllib.request, "urlopen") as send,
                    self.assertRaisesRegex(RuntimeError, "VISION_BASE_URL"),
                ):
                    vision.ask_image(image, "描述图片")
                send.assert_not_called()

    def test_configured_base_url_is_used(self):
        """验证请求使用环境中的端点，且去掉末尾斜杠。"""
        with tempfile.TemporaryDirectory() as root:
            image = Path(root) / "image.png"
            image.touch()
            with (
                patch.dict(vision.os.environ, {
                    "VISION_BASE_URL": " https://example.test/v1/ ",
                    "VISION_API_KEY": "test-key",
                    "VISION_MODEL": "test-vision",
                }, clear=True),
                patch.object(vision, "_request_text", return_value="正文") as request,
            ):
                self.assertEqual(vision.ask_image(image, "描述图片"), "正文")
            self.assertEqual(request.call_args.args[0].full_url,
                             "https://example.test/v1/chat/completions")

    def test_model_selection_and_missing_configuration(self):
        """验证显式模型优先，环境值可回退，空模型在请求前失败。"""
        with tempfile.TemporaryDirectory() as root:
            image = Path(root) / "image.png"
            image.touch()
            cases = [
                (None, " env-vision ", "env-vision"),
                (" chosen-vision ", "env-vision", "chosen-vision"),
                (None, None, None),
                (None, "   ", None),
                ("   ", "env-vision", None),
            ]
            for explicit, configured, expected in cases:
                env = {"VISION_BASE_URL": "https://example.test/v1", "VISION_API_KEY": "test-key"}
                if configured is not None:
                    env["VISION_MODEL"] = configured
                with (
                    self.subTest(explicit=explicit, configured=configured),
                    patch.dict(vision.os.environ, env, clear=True),
                    patch.object(vision, "_request_text", return_value="正文") as request,
                ):
                    if expected is None:
                        with self.assertRaisesRegex(RuntimeError, "VISION_MODEL"):
                            vision.ask_image(image, "描述图片", model=explicit)
                        request.assert_not_called()
                    else:
                        vision.ask_image(image, "描述图片", model=explicit)
                        body = json.loads(request.call_args.args[0].data)
                        self.assertEqual(body["model"], expected)

    def test_cli_passes_model_to_image_request(self):
        """验证两种读图子命令都传递显式模型选择。"""
        with tempfile.TemporaryDirectory() as root:
            image = Path(root) / "image.png"
            image.touch()
            commands = [
                ["understand", str(image), "--model", "chosen-vision"],
                ["ask", str(image), "--question", "描述图片", "--model", "chosen-vision"],
            ]
            for argv in commands:
                with (
                    self.subTest(command=argv[0]),
                    patch.object(vision, "ask_image", return_value="正文") as ask,
                    patch.object(vision.sys, "stdout", io.StringIO()),
                    redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(vision.main(argv), 0)
                self.assertEqual(ask.call_args.kwargs["model"], "chosen-vision")

    def test_rate_limit_retries_then_returns_text(self):
        """验证限流恢复后返回文本，且只等待一次。"""
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "图片正文"}}]}
        ).encode()
        rate_limit = urllib.error.HTTPError("https://example.test", 429, "限流", {}, None)
        with (
            patch.object(vision.urllib.request, "urlopen", side_effect=[rate_limit, response]) as send,
            patch.object(vision.time, "sleep") as sleep,
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(vision._request_text(object(), 10), "图片正文")
        self.assertEqual(send.call_count, 2)
        sleep.assert_called_once_with(vision.RETRY_BACKOFF_SECONDS)

    def test_auth_error_is_not_retried(self):
        """验证凭据错误立即失败。"""
        error = urllib.error.HTTPError("https://example.test", 401, "未认证", {}, None)
        with (
            patch.object(vision.urllib.request, "urlopen", side_effect=error) as send,
            patch.object(vision.time, "sleep") as sleep,
            self.assertRaisesRegex(RuntimeError, "401"),
        ):
            vision._request_text(object(), 10)
        self.assertEqual(send.call_count, 1)
        sleep.assert_not_called()

    def test_invalid_responses_fail_explicitly(self):
        """验证空结果和异常结构不会被当成图片正文。"""
        for payload in (b"not json", b"{}", b'{"choices": []}',
                        b'{"choices": [{"message": {"content": null}}]}',
                        b'{"choices": [{"message": {"content": " "}}]}'):
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                vision._response_text(payload)

    def test_extraction_failure_preserves_previous_output(self):
        """验证抽帧失败保留旧结果并清理本轮临时文件。"""
        with _frame_dir() as (source, output):
            previous = output / "frame_0001.jpg"
            previous.write_bytes(b"previous")

            def fail_extract(src, dst, interval):
                """模拟 ffmpeg 先产出部分文件再失败。"""
                (dst / "cand_0001.jpg").touch()
                raise RuntimeError("decode failed")

            with (
                patch.object(vision, "_video_duration", return_value=30),
                patch.object(vision, "_extract_uniform", side_effect=fail_extract),
                self.assertRaises(RuntimeError),
            ):
                vision.extract_frames(source, output)
            self.assertEqual(previous.read_bytes(), b"previous")
            self.assertEqual(list(output.iterdir()), [previous])

    def test_invalid_count_has_no_filesystem_side_effect(self):
        """验证非法帧数在创建输出目录前被拒绝。"""
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "frames"
            with self.assertRaises(ValueError):
                vision.extract_frames("missing.mp4", output, 0)
            self.assertFalse(output.exists())

    def test_successful_extraction_replaces_only_owned_frames(self):
        """验证成功抽帧替换旧编号结果，并保留调用方的候选图文件。"""
        with _frame_dir() as (source, output):
            (output / "frame_0099.jpg").touch()
            unrelated = output / "cand_0001.jpg"
            unrelated.write_bytes(b"unrelated")

            def extract(src, dst, interval):
                """模拟两个已按时间排序的候选帧。"""
                paths = [dst / "cand_0001.jpg", dst / "cand_0002.jpg"]
                for index, path in enumerate(paths):
                    path.write_bytes(str(index).encode())
                return paths

            with (
                patch.object(vision, "_video_duration", return_value=30),
                patch.object(vision, "_extract_uniform", side_effect=extract),
            ):
                frames = vision.extract_frames(source, output, 2)
            self.assertEqual([Path(p).read_bytes() for p in frames], [b"0", b"1"])
            self.assertEqual(unrelated.read_bytes(), b"unrelated")
            self.assertEqual(sorted(p.name for p in output.iterdir()),
                             ["cand_0001.jpg", "frame_0001.jpg", "frame_0002.jpg"])

    def test_extra_stale_frames_removed_on_successful_rerun(self):
        """验证成功重跑删掉上一轮多余的 frame_*.jpg，不残留旧帧。"""
        with _frame_dir() as (source, output):
            for index in range(1, 6):
                (output / f"frame_{index:04d}.jpg").write_bytes(b"stale")

            def extract(src, dst, interval):
                """模拟本轮只产生两个候选帧。"""
                paths = [dst / "cand_0001.jpg", dst / "cand_0002.jpg"]
                for index, path in enumerate(paths):
                    path.write_bytes(str(index).encode())
                return paths

            with (
                patch.object(vision, "_video_duration", return_value=30),
                patch.object(vision, "_extract_uniform", side_effect=extract),
            ):
                frames = vision.extract_frames(source, output, 2)
            self.assertEqual([Path(p).name for p in frames],
                             ["frame_0001.jpg", "frame_0002.jpg"])
            self.assertEqual([p.name for p in output.iterdir()],
                             ["frame_0001.jpg", "frame_0002.jpg"])

    def test_frame_directories_are_not_deleted(self):
        """验证清理旧帧时不会误删名为 frame_*.jpg 的目录。"""
        with _frame_dir() as (source, output):
            decoy = output / "frame_9999.jpg"
            decoy.mkdir()
            (decoy / "keep.txt").write_bytes(b"keep")

            def extract(src, dst, interval):
                """模拟一个候选帧。"""
                path = dst / "cand_0001.jpg"
                path.write_bytes(b"new")
                return [path]

            with (
                patch.object(vision, "_video_duration", return_value=30),
                patch.object(vision, "_extract_uniform", side_effect=extract),
            ):
                vision.extract_frames(source, output, 1)
            self.assertTrue(decoy.is_dir())
            self.assertEqual((decoy / "keep.txt").read_bytes(), b"keep")

    def test_backup_failure_restores_previous_frames(self):
        """验证备份中途失败时旧帧原封不动，新帧未发布。"""
        with _frame_dir() as (source, output):
            first = output / "frame_0001.jpg"
            first.write_bytes(b"old-1")
            second = output / "frame_0002.jpg"
            second.write_bytes(b"old-2")
            far = output / "frame_0003.jpg"
            far.write_bytes(b"old-3")

            def extract(src, dst, interval):
                """模拟两个候选帧。"""
                paths = [dst / "cand_0001.jpg", dst / "cand_0002.jpg"]
                for index, path in enumerate(paths):
                    path.write_bytes(str(index).encode())
                return paths

            real_copy = vision.shutil.copy2

            def flaky_copy(src_path, dst_path):
                """备份到 frame_0003.jpg 时失败，模拟中途中断。"""
                if Path(dst_path).name == "frame_0003.jpg":
                    raise OSError("backup interrupted")
                return real_copy(src_path, dst_path)

            with (
                patch.object(vision, "_video_duration", return_value=30),
                patch.object(vision, "_extract_uniform", side_effect=extract),
                patch.object(vision.shutil, "copy2", side_effect=flaky_copy),
                self.assertRaises(OSError),
            ):
                vision.extract_frames(source, output, 2)
            self.assertEqual(first.read_bytes(), b"old-1")
            self.assertEqual(second.read_bytes(), b"old-2")
            self.assertEqual(far.read_bytes(), b"old-3")
            self.assertEqual(sorted(p.name for p in output.iterdir()),
                             ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"])

    def test_first_publish_failure_restores_previous_frames(self):
        """验证首帧发布失败时旧帧被恢复，且不残留新帧。"""
        with _frame_dir() as (source, output):
            first = output / "frame_0001.jpg"
            first.write_bytes(b"old-1")
            second = output / "frame_0002.jpg"
            second.write_bytes(b"old-2")

            def extract(src, dst, interval):
                """模拟两个候选帧。"""
                paths = [dst / "cand_0001.jpg", dst / "cand_0002.jpg"]
                for index, path in enumerate(paths):
                    path.write_bytes(str(index).encode())
                return paths

            real_replace = Path.replace

            def flaky_replace(self, target):
                """仅拦截候选帧发布，放行旧帧恢复。"""
                if Path(target).name == "frame_0001.jpg" and self.name.startswith("cand_"):
                    raise OSError("publish interrupted")
                return real_replace(self, target)

            with (
                patch.object(vision, "_video_duration", return_value=30),
                patch.object(vision, "_extract_uniform", side_effect=extract),
                patch.object(Path, "replace", flaky_replace),
                self.assertRaises(OSError),
            ):
                vision.extract_frames(source, output, 2)
            self.assertEqual(first.read_bytes(), b"old-1")
            self.assertEqual(second.read_bytes(), b"old-2")
            self.assertEqual(sorted(p.name for p in output.iterdir()),
                             ["frame_0001.jpg", "frame_0002.jpg"])

    def test_later_publish_failure_rolls_back_earlier_new_frames(self):
        """验证非首帧发布失败时已写入的新帧被清除并恢复旧帧。"""
        with _frame_dir() as (source, output):
            first = output / "frame_0001.jpg"
            first.write_bytes(b"old-1")
            second = output / "frame_0002.jpg"
            second.write_bytes(b"old-2")

            def extract(src, dst, interval):
                """模拟两个候选帧。"""
                paths = [dst / "cand_0001.jpg", dst / "cand_0002.jpg"]
                for index, path in enumerate(paths):
                    path.write_bytes(str(index).encode())
                return paths

            real_replace = Path.replace

            def flaky_replace(self, target):
                """仅拦截第二个候选帧的发布，放行旧帧恢复。"""
                if Path(target).name == "frame_0002.jpg" and self.name.startswith("cand_"):
                    raise OSError("publish interrupted")
                return real_replace(self, target)

            with (
                patch.object(vision, "_video_duration", return_value=30),
                patch.object(vision, "_extract_uniform", side_effect=extract),
                patch.object(Path, "replace", flaky_replace),
                self.assertRaises(OSError),
            ):
                vision.extract_frames(source, output, 2)
            self.assertEqual(first.read_bytes(), b"old-1")
            self.assertEqual(second.read_bytes(), b"old-2")
            self.assertEqual(sorted(p.name for p in output.iterdir()),
                             ["frame_0001.jpg", "frame_0002.jpg"])

    def test_failed_rollback_keeps_backup_recoverable(self):
        """验证回滚本身失败时旧帧备份仍完整保留，并提示保留路径。"""
        with _frame_dir() as (source, output):
            previous = output / "frame_0001.jpg"
            previous.write_bytes(b"old-1")

            def extract(src, dst, interval):
                """模拟两个候选帧。"""
                paths = [dst / "cand_0001.jpg", dst / "cand_0002.jpg"]
                for index, path in enumerate(paths):
                    path.write_bytes(str(index).encode())
                return paths

            real_replace = Path.replace
            real_copy = vision.shutil.copy2

            def flaky_replace(self, target):
                """发布首帧失败。"""
                if Path(target).name == "frame_0001.jpg" and self.name.startswith("cand_"):
                    raise OSError("publish interrupted")
                return real_replace(self, target)

            def flaky_copy(src_path, dst_path):
                """回滚阶段的复制恢复失败。"""
                if Path(dst_path).name == "frame_0001.jpg" and ".frame-backup-" in str(src_path):
                    raise OSError("restore interrupted")
                return real_copy(src_path, dst_path)

            with (
                patch.object(vision, "_video_duration", return_value=30),
                patch.object(vision, "_extract_uniform", side_effect=extract),
                patch.object(Path, "replace", flaky_replace),
                patch.object(vision.shutil, "copy2", side_effect=flaky_copy),
                redirect_stderr(io.StringIO()) as stderr,
                self.assertRaises(OSError),
            ):
                vision.extract_frames(source, output, 2)
            self.assertIn("旧帧备份保留在", stderr.getvalue())
            backups = list(output.glob(".frame-backup-*/frame_0001.jpg"))
            self.assertEqual(len(backups), 1, "回滚失败后应保留一份完整备份")
            self.assertEqual(backups[0].read_bytes(), b"old-1")

    def test_target_directory_conflict_rejected_before_backup(self):
        """验证目标被同名目录占用时发布前报错，目录内容与旧帧不变。"""
        with _frame_dir() as (source, output):
            keeper = output / "frame_0002.jpg"
            keeper.mkdir()
            (keeper / "keep.txt").write_bytes(b"keep")
            previous = output / "frame_0001.jpg"
            previous.write_bytes(b"old-1")

            def extract(src, dst, interval):
                """模拟两个候选帧。"""
                paths = [dst / "cand_0001.jpg", dst / "cand_0002.jpg"]
                for index, path in enumerate(paths):
                    path.write_bytes(str(index).encode())
                return paths

            with (
                patch.object(vision, "_video_duration", return_value=30),
                patch.object(vision, "_extract_uniform", side_effect=extract),
                self.assertRaises(RuntimeError),
            ):
                vision.extract_frames(source, output, 2)
            self.assertTrue(keeper.is_dir())
            self.assertEqual((keeper / "keep.txt").read_bytes(), b"keep")
            self.assertEqual(previous.read_bytes(), b"old-1")
            self.assertFalse(
                any(p.name.startswith(".frame-backup-") for p in output.iterdir())
            )


    def test_select_sharpest_requires_positive_target(self):
        """验证非法目标帧数在任何依赖或文件访问前被拒绝。"""
        with self.assertRaises(ValueError):
            vision.select_sharpest([], 0)

    def test_select_sharpest_returns_all_when_not_exceeding_target(self):
        """验证候选数不超过目标时原样返回，不触发评分与依赖导入。"""
        candidates = [Path(f"cand_{i:04d}.jpg") for i in range(1, 4)]
        self.assertEqual(vision.select_sharpest(candidates, 3), candidates)
        self.assertEqual(vision.select_sharpest(candidates, 5), candidates)

    def test_select_sharpest_degrades_when_pillow_missing(self):
        """验证 Pillow/numpy 缺失时退化为均匀下采样，仍产出目标数量。"""
        candidates = [Path(f"cand_{i:04d}.jpg") for i in range(1, 11)]

        with _simulate_missing_pillow():
            # 正向对照：确认模拟确实拦下了依赖导入，而非依赖本机恰好没装。
            with self.assertRaises(ImportError):
                __import__("numpy")
            selected = vision.select_sharpest(candidates, 4)
        self.assertEqual(len(selected), 4)
        self.assertTrue(all(p in candidates for p in selected))
        self.assertEqual(selected, [candidates[int(i * len(candidates) / 4)] for i in range(4)])

    def test_select_sharpest_degradation_preserves_candidate_order(self):
        """验证降级下采样按原候选顺序抽取，不重排时间顺序。"""
        candidates = [Path(f"cand_{i:04d}.jpg") for i in range(1, 8)]

        with _simulate_missing_pillow():
            selected = vision.select_sharpest(candidates, 3)
        self.assertEqual(selected, [candidates[0], candidates[2], candidates[4]])


class TranscribeTests(unittest.TestCase):
    """转录结果与命令行退出码的回归测试。"""

    def test_lazy_segments_ignore_blank_text_and_keep_timestamps(self):
        """验证惰性转录结果过滤空白段，并保留跨小时的时间戳。"""
        model = MagicMock()
        info = SimpleNamespace(language="zh", language_probability=1.0,
                               duration=4000.0, duration_after_vad=3900.0)
        model.transcribe.return_value = (
            iter([SimpleNamespace(start=0, text="  "),
                  SimpleNamespace(start=3661.9, text=" 正文 ")]), info,
        )
        factory = MagicMock(return_value=model)
        with (
            patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=factory)}),
            redirect_stderr(io.StringIO()),
        ):
            lines, duration, filtered = transcribe.transcribe("audio.wav", device="cpu")
        self.assertEqual(lines, ["[01:01:01] 正文"])
        self.assertEqual((duration, filtered), (4000.0, 3900.0))
        self.assertFalse(model.transcribe.call_args.kwargs["condition_on_previous_text"])

    def test_output_error_returns_failure(self):
        """验证写入失败以退出码报告，不泄漏未捕获异常。"""
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "audio.wav"
            source.touch()
            with (
                patch.object(transcribe, "transcribe", return_value=(["正文"], 1, 1)),
                patch.object(transcribe.sys, "platform", "linux"),
                redirect_stderr(io.StringIO()),
            ):
                code = transcribe.main([str(source), "--output", root])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
