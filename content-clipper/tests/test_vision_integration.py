"""真实依赖集成测试：用真 Pillow/numpy/ffmpeg 验证 vision.py 的评分与抽帧。

本模块**不读取 .env、不访问网络**——视觉模型的真实调用属人工测试，见 tests/README.md。
所有用例在缺少 Pillow/numpy/ffmpeg/ffprobe 时自动 skip，绝不安装依赖。

运行（标准库 unittest discover，在 skill 目录下的 tests/ 执行）::

    python -B -m unittest discover -s tests -p "test_vision_integration.py" -v

Pillow/numpy 缺失：`select_sharpest` 评分用例 skip。
ffmpeg/ffprobe 缺失：`extract_frames` 用例 skip。
"""

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

# 探测可选依赖，不导入失败即中止；缺失时在下面对应用例 skip。
try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
    _PIL_NUMPY = True
except ImportError:  # pragma: no cover - 环境相关分支
    _PIL_NUMPY = False

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")
_FFMPEG_OK = bool(_FFMPEG and _FFPROBE)


def _load_script(name):
    """按文件路径加载脚本，避免依赖工作目录或修改模块搜索路径。"""
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vision = _load_script("vision")


def _make_text_image(text="1234", blur=0.0, level=128, size=(320, 240)):
    """生成带数字与刻度线的合成图，可选高斯模糊。"""
    canvas = Image.fromarray(np.full((size[1], size[0], 3), level, dtype=np.uint8))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([10, 10, size[0] - 10, size[1] - 10], outline=(255, 255, 255), width=3)
    draw.text((40, 50), text, fill=(255, 255, 255))
    for x in range(30, size[0], 30):
        draw.line([(x, size[1] - 60), (x, size[1] - 20)], fill=(255, 255, 255), width=2)
    if blur > 0:
        canvas = canvas.filter(ImageFilter.GaussianBlur(blur))
    return canvas


@unittest.skipUnless(_PIL_NUMPY, "需要 Pillow 与 numpy")
class SelectSharpestTests(unittest.TestCase):
    """用真 Pillow/numpy 验证 select_sharpest 的评分与排序契约。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _save(self, name, blur=0.0, level=128):
        path = self.root / name
        _make_text_image(blur=blur, level=level).save(path, quality=95)
        return path

    def test_sharp_candidates_preferred_over_blurred(self):
        """模糊应被剔除：候选多于目标时，清晰帧排在模糊帧之前被选中。"""
        sharp_a = self._save("s_a.jpg", blur=0.0, level=110)
        sharp_b = self._save("s_b.jpg", blur=0.0, level=200)
        blurred = [self._save(f"b_{i}.jpg", blur=7.0, level=lvl)
                   for i, lvl in enumerate((80, 140, 200))]
        candidates = [sharp_a, blurred[0], sharp_b, blurred[1], blurred[2]]

        selected = vision.select_sharpest(candidates, target=2)

        self.assertEqual(set(selected), {sharp_a, sharp_b})

    def test_selection_preserves_candidate_order(self):
        """返回顺序必须是候选原顺序的子序列，不能按分数重排。"""
        candidates = [
            self._save("s_a.jpg", blur=0.0, level=100),
            self._save("b_c.jpg", blur=7.0, level=100),
            self._save("s_b.jpg", blur=0.0, level=210),
            self._save("b_d.jpg", blur=7.0, level=60),
        ]

        selected = vision.select_sharpest(candidates, target=3)

        indices = [candidates.index(p) for p in selected]
        self.assertEqual(indices, sorted(indices))
        self.assertLessEqual(len(selected), 3)

    def test_identical_images_return_expected_count_and_order(self):
        """相同内容导致评分同分：不崩溃，返回数量与顺序仍正确。

        同分时选哪几张由实现决定（argsort 的稳定性/顺序），本用例只锁定
        「数量正确 + 顺序为原顺序子序列」两个契约，不锁定具体是后两张。
        """
        candidates = [self._save(f"eq_{i}.jpg", blur=0.0, level=128) for i in range(4)]

        selected = vision.select_sharpest(candidates, target=2)

        self.assertEqual(len(selected), 2)
        self.assertEqual(len(set(selected)), 2)
        indices = [candidates.index(p) for p in selected]
        self.assertEqual(indices, sorted(indices))

    def test_more_targets_than_candidates_returns_all(self):
        """目标数不少于候选数时原样返回，不做评分。"""
        candidates = [self._save(f"c_{i}.jpg", blur=0.0, level=128) for i in range(3)]

        self.assertEqual(vision.select_sharpest(candidates, target=3), candidates)
        self.assertEqual(vision.select_sharpest(candidates, target=10), candidates)

    def test_non_positive_target_rejected(self):
        """目标数为零或负数必须报错。"""
        candidates = [self._save(f"c_{i}.jpg") for i in range(3)]
        for target in (0, -1):
            with self.subTest(target=target), self.assertRaises(ValueError):
                vision.select_sharpest(candidates, target)

    def test_too_small_image_rejected_when_scoring(self):
        """需要评分时，边长不足 3 像素的图无法算 Laplacian，应报错。"""
        tiny = self.root / "tiny_2x2.png"
        Image.new("RGB", (2, 2), "gray").save(tiny)
        candidates = [tiny, tiny, tiny]

        with self.assertRaises(ValueError):
            vision.select_sharpest(candidates, target=1)


@unittest.skipUnless(_FFMPEG_OK, "需要 ffmpeg 与 ffprobe")
class ExtractFramesTests(unittest.TestCase):
    """用真 ffmpeg 验证 extract_frames 的产出、重发布与目录清理。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_video(self, seconds=6):
        """用 testsrc2 合成短视频，避免 drawtext 对 fontconfig 的依赖。"""
        video = self.root / "clip.mp4"
        cmd = [
            _FFMPEG, "-y", "-f", "lavfi",
            "-i", f"testsrc2=size=320x240:rate=10:duration={seconds}",
            "-pix_fmt", "yuv420p", str(video),
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return video

    def _readable(self, path):
        """用 ffprobe 确认文件是可解码的图片。"""
        cmd = [_FFPROBE, "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height",
               "-of", "csv=p=0", str(path)]
        result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        return result.returncode == 0 and result.stdout.strip() != ""

    def test_extract_and_reextract_with_fewer_frames(self):
        """首次抽帧产出可解码帧；重跑更少帧数时旧帧被清理、无关文件保留。"""
        video = self._make_video(seconds=6)
        outdir = self.root / "frames"
        outdir.mkdir()
        unrelated = outdir / "notes.txt"
        unrelated.write_text("keep me", encoding="utf-8")

        first = vision.extract_frames(video, outdir, frame_count=5)

        self.assertEqual(len(first), 5)
        for path in first:
            self.assertTrue(Path(path).is_file())
            self.assertTrue(self._readable(path), f"不可解码: {path}")

        second = vision.extract_frames(video, outdir, frame_count=2)

        self.assertEqual(len(second), 2)
        for path in second:
            self.assertTrue(self._readable(path), f"不可解码: {path}")
        # 旧的 frame_0003..0005 应被清理，只剩本次 2 张
        remaining = sorted(p.name for p in outdir.glob("frame_*.jpg"))
        self.assertEqual(remaining, ["frame_0001.jpg", "frame_0002.jpg"])
        # 无关文件保留
        self.assertTrue(unrelated.is_file())
        # 候选临时目录与备份目录都不应残留
        leftovers = [p.name for p in outdir.iterdir()
                     if p.is_dir() and (p.name.startswith(".frames-")
                                        or p.name.startswith(".frame-backup-"))]
        self.assertEqual(leftovers, [])

    def test_sharpness_filter_actually_runs(self):
        """正常视频下候选数须多于目标数，清晰度筛选才真正执行。

        `_even_interval` 按目标数采样会产出等量候选，导致 `select_sharpest`
        在 `len(candidates) <= target` 时原样返回、评分从不执行。用 12 秒
        视频 + count=3/5 覆盖「1 秒下限不生效」的常态时长，通过包装公开
        `select_sharpest`（内部调用原函数）记录其收到的候选数量，断言候选
        多于目标、且最终产出不超过 count。不锁定私有间隔或精确帧数。
        """
        video = self._make_video(seconds=12)
        real_select = vision.select_sharpest
        seen = []

        def spy(candidates, target):
            seen.append((len(candidates), target))
            return real_select(candidates, target)

        vision.select_sharpest = spy
        try:
            for count in (3, 5):
                outdir = self.root / f"frames_{count}"
                result = vision.extract_frames(video, outdir, frame_count=count)
                candidates_n, target = seen[-1]
                with self.subTest(count=count):
                    self.assertGreater(
                        candidates_n, target,
                        f"count={count}: 候选 {candidates_n} 未多于目标 {target}，"
                        f"清晰度筛选不会执行",
                    )
                    self.assertLessEqual(len(result), count)
        finally:
            vision.select_sharpest = real_select

    def test_missing_video_raises(self):
        """视频不存在时明确报错。"""
        with self.assertRaises(FileNotFoundError):
            vision.extract_frames(self.root / "nope.mp4", self.root / "out", frame_count=3)

    def test_non_positive_frame_count_raises(self):
        """目标帧数非正数时报错，且不触达 ffmpeg。"""
        video = self._make_video(seconds=3)
        with self.assertRaises(ValueError):
            vision.extract_frames(video, self.root / "out", frame_count=0)


if __name__ == "__main__":
    unittest.main()
