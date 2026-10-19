"""상세 이미지 영문화(1084687 방식) 회귀 테스트 (2026-10-17).

OCR(tesseract) 이 없는 환경에서도 도는 부분만 기본으로 검사하고, 한글 OCR 이 있으면
합성 이미지로 '한글을 지우고 영문을 얹은 뒤 다시 읽어 한글이 남지 않는다' 까지 본다.
"""
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "daiso"))
import localize_detail_images as ldi  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402


def has_korean_ocr() -> bool:
    exe = shutil.which("tesseract")
    if not exe:
        return False
    out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True)
    return "kor" in (out.stdout + out.stderr)


def korean_font():
    for p in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"):
        if Path(p).exists():
            return p
    return None


class PanelCutTest(unittest.TestCase):
    def test_cuts_land_in_flat_bands_and_respect_bounds(self):
        rng = np.random.default_rng(0)
        img = rng.integers(0, 255, (5200, 300)).astype(np.float32)
        for y in (1200, 2500, 3800):
            img[y - 40:y + 40] = 240.0          # 균일 배경 띠
        cuts = ldi.panel_cuts(img)
        self.assertEqual(cuts[0], 0)
        self.assertEqual(cuts[-1], 5200)
        for a, b in zip(cuts, cuts[1:]):
            self.assertLessEqual(b - a, ldi.PANEL_MAX)
        for c in cuts[1:-1]:
            self.assertTrue(any(abs(c - y) <= 40 for y in (1200, 2500, 3800)), cuts)


class ClaimGuardTest(unittest.TestCase):
    def setUp(self):
        self.banned, self.safe = ldi.claim_rules()

    def test_safe_alternative_replaces_whitening(self):
        out, hits = ldi.guard_claims("Whitening capsule cream", self.banned, self.safe)
        self.assertNotIn("whitening", out.lower())
        self.assertEqual(hits, [])

    def test_unfixable_claim_is_reported(self):
        _, hits = ldi.guard_claims("FDA approved formula that treats eczema", self.banned, self.safe)
        self.assertIn("fda approved", hits)
        self.assertIn("eczema", hits)


class GroupingTest(unittest.TestCase):
    def test_paragraph_lines_group_but_badge_with_other_background_does_not(self):
        lines = [
            {"box": [100, 100, 500, 140], "ocr": "제목 첫줄", "conf": 90, "bg": [250, 240, 220]},
            {"box": [110, 150, 490, 190], "ocr": "제목 둘째줄", "conf": 90, "bg": [250, 240, 220]},
            {"box": [150, 200, 450, 240], "ocr": "#배지", "conf": 90, "bg": [232, 120, 24]},
            {"box": [600, 100, 700, 140], "ocr": "옆 단", "conf": 90, "bg": [250, 240, 220]},
        ]
        units = ldi.group_units(lines)
        sizes = sorted(len(u["lines"]) for u in units)
        self.assertEqual(sizes, [1, 1, 2])


class TranslatorTest(unittest.TestCase):
    def test_file_translator_requires_exact_panel(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.json"
            p.write_text(json.dumps({"translator": "test", "panels": {"abc": {"1": "Hello"}}}), encoding="utf-8")
            t = ldi.FileTranslator(p)
            self.assertEqual(t.translate(b"", [], "", "abc"), {1: "Hello"})
            with self.assertRaises(LookupError):
                t.translate(b"", [], "", "other")

    def test_no_key_means_no_translator(self):
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            self.assertIsNone(ldi.translator_from_env())


class PipelineWithoutOcrTest(unittest.TestCase):
    """OCR 를 바꿔 끼워 흐름만 본다: 얼굴 패널·번역 누락·금칙어·한글 잔존이 모두 걸러지는지."""

    def run_pipeline(self, translate, residual=lambda *a, **k: [], faces=0, boxes=None):
        img = Image.new("RGB", (400, 900), (250, 245, 235))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        units = boxes if boxes is not None else [
            {"id": 1, "box": [40, 40, 360, 80], "ocr": "한글", "align": "center",
             "lines": [{"box": [40, 40, 360, 80], "ocr": "한글", "conf": 90}]}]

        class T:
            name = "stub"

            def translate(self, *a):
                return translate()

        fake_di = mock.Mock()
        fake_di.count_faces.return_value = faces
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ldi, "ensure_ocr_ready", return_value=None), \
                mock.patch.object(ldi, "hangul_boxes", return_value=units), \
                mock.patch.object(ldi, "residual_hangul", side_effect=residual), \
                mock.patch.dict(sys.modules, {"daiso_images": fake_di}):
            return ldi.localize_product("1", "Test Cream", Path(d), T(), [("src", buf.getvalue())])

    def test_clean_translation_is_used_with_alt_and_hash(self):
        man = self.run_pipeline(lambda: {1: "Mix your way"})
        self.assertEqual(man["status"], "ok")
        self.assertFalse(man["gallery_complete"])
        self.assertEqual(man["gallery_status"], "review_required")
        self.assertIn("role_rights_and_label_evidence_review_required", man["gallery_review_reasons"])
        out = man["outputs"][0]
        self.assertTrue(out["file"].startswith("01-mix-your-way"))
        self.assertIn("Test Cream", out["alt"])
        self.assertRegex(out["sha256"], r"^[0-9a-f]{64}$")

    def test_face_panel_is_excluded(self):
        man = self.run_pipeline(lambda: {1: "x"}, faces=1)
        self.assertEqual(man["status"], "failed")
        self.assertEqual(man["panels"][0]["reason"], "human_face")

    def test_missing_translation_is_excluded_not_invented(self):
        man = self.run_pipeline(lambda: {})
        self.assertTrue(man["panels"][0]["reason"].startswith("translation_incomplete"))

    def test_banned_claim_drops_panel(self):
        man = self.run_pipeline(lambda: {1: "FDA approved cream"})
        self.assertTrue(man["panels"][0]["reason"].startswith("claim_terms"))

    def test_residual_korean_drops_panel(self):
        man = self.run_pipeline(lambda: {1: "Mix"}, residual=lambda *a, **k: ["남은 글"])
        self.assertEqual(man["panels"][0]["reason"], "korean_text_remaining")

    def test_regulatory_panel_is_excluded(self):
        units = [{"id": 1, "box": [40, 40, 360, 80], "ocr": "식약처 심사 보고서", "align": "auto",
                  "lines": [{"box": [40, 40, 360, 80], "ocr": "식약처", "conf": 90}]}]
        man = self.run_pipeline(lambda: {1: "x"}, boxes=units)
        self.assertEqual(man["panels"][0]["reason"], "korean_regulatory_panel")

    def test_no_translator_localizes_nothing(self):
        img = Image.new("RGB", (400, 900), (250, 245, 235))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        units = [{"id": 1, "box": [40, 40, 360, 80], "ocr": "한글", "align": "auto",
                  "lines": [{"box": [40, 40, 360, 80], "ocr": "한글", "conf": 90}]}]
        fake_di = mock.Mock()
        fake_di.count_faces.return_value = 0
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ldi, "ensure_ocr_ready", return_value=None), \
                mock.patch.object(ldi, "hangul_boxes", return_value=units), \
                mock.patch.dict(sys.modules, {"daiso_images": fake_di}):
            man = ldi.localize_product("1", "T", Path(d), None, [("src", buf.getvalue())])
        self.assertEqual(man["status"], "failed")
        self.assertIn("translator_unavailable", man["reasons"])


class FailClosedTest(unittest.TestCase):
    """2026-10-17: kor.traineddata 가 깨져 있으면 tesseract 는 종료 코드 0 으로 영어만 읽는다.
    그때 한글이 그대로 박힌 1084687 패널 11장이 '-en' 으로 통과했다. 다시는 그러지 않는다."""

    def test_unloadable_language_raises_instead_of_reading_nothing(self):
        bad = subprocess.CompletedProcess([], 0, stdout=b"level\ttext\n",
                                          stderr=b"Failed loading language 'kor'\n")
        with mock.patch.object(ldi.shutil, "which", return_value="/usr/bin/tesseract"), \
                mock.patch.object(ldi.subprocess, "run", return_value=bad):
            with self.assertRaises(RuntimeError):
                ldi._tess(["-l", "kor"], b"x", 5)

    def test_pipeline_stops_when_ocr_is_not_ready(self):
        img = Image.new("RGB", (400, 900), (250, 245, 235))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ldi, "ensure_ocr_ready", side_effect=RuntimeError("tesseract_kor_unloadable")):
            man = ldi.localize_product("1", "T", Path(d), object(), [("src", buf.getvalue())])
        self.assertEqual(man["status"], "failed")
        self.assertEqual(man["outputs"], [])
        self.assertTrue(any(r.startswith("ocr_unavailable") for r in man["reasons"]))


class OcrBudgetTest(unittest.TestCase):
    def test_timeout_retries_same_pixels_with_single_thread(self):
        ok = subprocess.CompletedProcess([], 0, stdout=b"text", stderr=b"")
        with mock.patch.object(ldi.shutil, "which", return_value="tesseract"), \
                mock.patch.object(ldi.subprocess, "run", side_effect=[subprocess.TimeoutExpired("tesseract", 30), ok]) as run:
            self.assertEqual(ldi._tess(["-l", "kor"], b"original pixels", 60), b"text")
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs["input"], b"original pixels")
            self.assertEqual(call.kwargs["env"]["OMP_THREAD_LIMIT"], "1")
            self.assertEqual(call.kwargs["env"]["OMP_NUM_THREADS"], "1")
        self.assertLessEqual(run.call_args_list[0].kwargs["timeout"], 30)

    def test_repeated_timeout_fails_after_two_attempts(self):
        with mock.patch.object(ldi.shutil, "which", return_value="tesseract"), \
                mock.patch.object(ldi.subprocess, "run", side_effect=subprocess.TimeoutExpired("tesseract", 30)) as run:
            with self.assertRaisesRegex(RuntimeError, "ocr_timeout_after_retry"):
                ldi._tess([], b"x", 60)
        self.assertEqual(run.call_count, 2)

    def test_deadline_exhaustion_never_launches_ocr(self):
        with mock.patch.object(ldi.shutil, "which", return_value="tesseract"), \
                mock.patch.object(ldi.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "ocr_budget_exhausted"):
                ldi._tess([], b"x", 60, deadline=0)
        run.assert_not_called()

    def test_real_subprocess_timeout_is_bounded_and_reaped(self):
        import os
        import time
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "slow-ocr"
            pidfile = Path(d) / "pids"
            exe.write_text(f"#!{sys.executable}\nimport os, time\nwith open({str(pidfile)!r}, 'a') as f: f.write(str(os.getpid()) + '\\n')\ntime.sleep(10)\n")
            exe.chmod(0o700)
            start = time.monotonic()
            with mock.patch.object(ldi.shutil, "which", return_value=str(exe)):
                with self.assertRaisesRegex(RuntimeError, "ocr_timeout_after_retry"):
                    ldi._tess([], b"pixels", 0.4)
            self.assertLess(time.monotonic() - start, 2)
            pids = pidfile.read_text().splitlines()
            self.assertEqual(len(pids), 2)
            for pid in pids:
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(pid), 0)

    def test_nonzero_exit_is_not_empty_text(self):
        bad = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"failure")
        with mock.patch.object(ldi.shutil, "which", return_value="tesseract"), \
                mock.patch.object(ldi.subprocess, "run", return_value=bad) as run:
            with self.assertRaisesRegex(RuntimeError, "tesseract_exit:1"):
                ldi._tess([], b"x", 60)
        self.assertEqual(run.call_count, 1)

    def test_line_size_limit_fails_before_ocr(self):
        with mock.patch.object(ldi, "OCR_MAX_LINE_PIXELS", 10), \
                mock.patch.object(ldi.shutil, "which", return_value="tesseract"), \
                mock.patch.object(ldi, "_tess") as read:
            with self.assertRaisesRegex(RuntimeError, "ocr_line_size_budget_exceeded"):
                ldi.ocr_line(np.zeros((20, 60, 3), dtype=np.uint8), [0, 0, 60, 20])
        read.assert_not_called()

    def test_queued_line_stops_before_image_processing_when_panel_budget_expires(self):
        with mock.patch.object(ldi.shutil, "which", return_value="tesseract"), \
                mock.patch.object(ldi, "_tess") as read:
            with self.assertRaisesRegex(RuntimeError, "ocr_budget_exhausted"):
                ldi.ocr_line(np.zeros((20, 60, 3), dtype=np.uint8), [0, 0, 60, 20], deadline=0)
        read.assert_not_called()

    def test_panel_size_limit_refuses_without_dropping_pixels(self):
        with mock.patch.object(ldi, "OCR_MAX_PANEL_PIXELS", 10), \
                mock.patch.object(ldi, "text_line_boxes") as boxes:
            with self.assertRaisesRegex(RuntimeError, "ocr_panel_size_budget_exceeded"):
                ldi.korean_lines(np.zeros((4, 4, 3), dtype=np.uint8))
        boxes.assert_not_called()

    def test_extraction_caps_candidates_before_quadratic_merge(self):
        import cv2
        stats = np.array([[0, 0, 20, 10, 200]] * 4)
        with mock.patch.object(ldi, "OCR_MAX_BOXES", 2), \
                mock.patch.object(cv2, "connectedComponentsWithStats", return_value=(4, None, stats, None)):
            with self.assertRaisesRegex(RuntimeError, "ocr_line_count_budget_exceeded"):
                ldi.text_line_boxes(np.zeros((20, 20, 3), dtype=np.uint8))

    def test_extraction_honors_panel_deadline(self):
        import cv2
        stats = np.array([[0, 0, 20, 10, 200]] * 2)
        with mock.patch.object(cv2, "connectedComponentsWithStats", return_value=(2, None, stats, None)):
            with self.assertRaisesRegex(RuntimeError, "ocr_budget_exhausted"):
                ldi.text_line_boxes(np.zeros((20, 20, 3), dtype=np.uint8), deadline=0)

    def test_candidate_limit_refuses_instead_of_truncating(self):
        with mock.patch.object(ldi, "OCR_MAX_BOXES", 1), \
                mock.patch.object(ldi, "text_line_boxes", return_value=[[0, 0, 2, 2]] * 2), \
                mock.patch.object(ldi, "ocr_line") as read:
            with self.assertRaisesRegex(RuntimeError, "ocr_line_count_budget_exceeded"):
                ldi.korean_lines(np.zeros((4, 4, 3), dtype=np.uint8))
        read.assert_not_called()

    def test_empty_extraction_cannot_bypass_expired_budget(self):
        with mock.patch.object(ldi, "text_line_boxes", return_value=[]), \
                mock.patch.object(ldi.time, "monotonic", side_effect=[0, 181]):
            with self.assertRaisesRegex(RuntimeError, "ocr_budget_exhausted"):
                ldi.korean_lines(np.zeros((4, 4, 3), dtype=np.uint8))

    def test_pool_shares_one_deadline_preserving_every_box(self):
        boxes = [[0, 0, 2, 2], [2, 2, 4, 4]]
        with mock.patch.object(ldi, "text_line_boxes", return_value=boxes), \
                mock.patch.object(ldi, "ocr_line", return_value=("", 0)) as read:
            self.assertEqual(ldi.korean_lines(np.zeros((4, 4, 3), dtype=np.uint8)), [])
        self.assertEqual(read.call_count, 2)
        self.assertEqual(read.call_args_list[0].kwargs["deadline"], read.call_args_list[1].kwargs["deadline"])

    def test_residual_timeout_returns_failed_manifest_not_exception(self):
        fixture = PipelineWithoutOcrTest()
        def fail(*a, **kw):
            raise RuntimeError("ocr_timeout_after_retry")
        man = fixture.run_pipeline(lambda: {1: "Mix"}, residual=fail)
        self.assertEqual(man["status"], "failed")
        self.assertEqual(man["outputs"], [])
        self.assertIn("ocr_inspection_incomplete", man["reasons"])
        self.assertIn("ocr_inspection_incomplete", man["gallery_review_reasons"])
        self.assertFalse(man["gallery_complete"])
        self.assertTrue(man["panels"][0]["reason"].startswith("residual_inspection_failed"))

    def test_one_failed_panel_does_not_abort_other_panels_or_claim_success(self):
        img = Image.new("RGB", (400, 900), "white")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        fake_di = mock.Mock()
        fake_di.count_faces.return_value = 0
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ldi, "ensure_ocr_ready"), \
                mock.patch.object(ldi, "hangul_boxes", return_value=[]), \
                mock.patch.object(ldi, "residual_hangul", side_effect=[RuntimeError("ocr_timeout_after_retry"), []]), \
                mock.patch.object(ldi, "info_panel", return_value=(None, "test")), \
                mock.patch.dict(sys.modules, {"daiso_images": fake_di}):
            man = ldi.localize_product("1", "T", Path(d), object(), [("a", buf.getvalue()), ("b", buf.getvalue())])
        self.assertEqual(man["summary"]["used"], 1)
        self.assertEqual(len(man["outputs"]), 1)
        self.assertEqual(man["status"], "failed")
        self.assertEqual(man["gallery_status"], "review_required")

    def test_initial_timeout_is_also_incomplete(self):
        img = Image.new("RGB", (400, 900), "white")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        fake_di = mock.Mock()
        fake_di.count_faces.return_value = 0
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ldi, "ensure_ocr_ready"), \
                mock.patch.object(ldi, "hangul_boxes", side_effect=RuntimeError("ocr_timeout_after_retry")), \
                mock.patch.object(ldi, "info_panel", return_value=(None, "test")), \
                mock.patch.dict(sys.modules, {"daiso_images": fake_di}):
            man = ldi.localize_product("1", "T", Path(d), object(), [("a", buf.getvalue())])
        self.assertEqual(man["status"], "failed")
        self.assertIn("ocr_inspection_incomplete", man["reasons"])


class FitAndResidualTest(unittest.TestCase):
    def test_single_line_badge_shrinks_or_refuses_never_wraps(self):
        img = Image.new("RGB", (600, 100), (240, 120, 30))
        d = ImageDraw.Draw(img)
        fit = ldi._fit(d, "#BrighteningCare #Glutathione #LactoExosome", 440, 48, True, 48, single_line=True)
        self.assertIsNotNone(fit)
        self.assertEqual(len(fit[1]), 1)
        self.assertIsNone(ldi._fit(d, "x" * 400, 60, 20, True, 20, single_line=True))

    def test_overflowing_unit_drops_panel(self):
        unit = {"id": 1, "box": [10, 10, 60, 30], "align": "auto", "ocr": "한",
                "lines": [{"box": [10, 10, 60, 30], "ocr": "한", "conf": 90}]}
        with self.assertRaises(ldi.TextOverflow):
            ldi.composite(Image.new("RGB", (80, 60), (250, 250, 250)), [unit], {1: "w" * 300})

    def test_low_confidence_noise_outside_translated_area_is_not_residual(self):
        lines = [{"box": [220, 1103, 284, 1141], "ocr": "나그", "conf": 19.7},      # 용기 반사 잡음 (실측)
                 {"box": [10, 10, 200, 40], "ocr": "남은 글", "conf": 30.0},        # 번역한 자리 안
                 {"box": [300, 500, 600, 540], "ocr": "선명한 한글", "conf": 92.0}]   # 자리 밖 고신뢰도
        img = Image.new("RGB", (850, 1200), (255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        with mock.patch.object(ldi, "korean_lines", return_value=lines), \
                mock.patch.object(ldi, "page_hangul", return_value=[]):
            left = ldi.residual_hangul(buf.getvalue(), [], [[0, 0, 210, 50]])
        self.assertEqual(left, ["남은 글", "선명한 한글"])


class TranslatorBudgetTest(unittest.TestCase):
    def setUp(self):
        ldi.GeminiTranslator.calls, ldi.GeminiTranslator.stopped = 0, None

    tearDown = setUp

    def test_call_budget_and_stop_on_quota(self):
        t = ldi.GeminiTranslator("k", "m")
        with mock.patch.object(ldi.GeminiTranslator, "MAX_CALLS", 2), \
                mock.patch.object(t, "_translate", return_value={1: "x"}):
            t.translate(b"", [], "T", "s")
            t.translate(b"", [], "T", "s")
            with self.assertRaises(RuntimeError):
                t.translate(b"", [], "T", "s")
        ldi.GeminiTranslator.calls = 0
        err = ldi.urllib.error.HTTPError("u", 429, "quota", {}, None)
        with mock.patch.object(t, "_translate", side_effect=err):
            with self.assertRaises(ldi.urllib.error.HTTPError):
                t.translate(b"", [], "T", "s")
        with self.assertRaises(RuntimeError):
            t.translate(b"", [], "T", "s")          # 429 뒤에는 더 부르지 않는다


@unittest.skipUnless(has_korean_ocr() and korean_font(), "Korean OCR or font not installed")
class RealOcrTest(unittest.TestCase):
    def test_korean_line_is_found_erased_and_not_left_behind(self):
        img = Image.new("RGB", (850, 420), (252, 240, 215))
        d = ImageDraw.Draw(img)
        d.text((150, 120), "피부 컨디션에 맞게 맞춤 케어", font=ImageFont.truetype(korean_font(), 40), fill=(230, 110, 20))
        d.text((150, 240), "LACTO EXOSOME", font=ImageFont.truetype(ldi.font_path(True), 34), fill=(40, 40, 40))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        units = ldi.hangul_boxes(buf.getvalue())
        self.assertEqual(len(units), 1, units)           # 영문 줄은 한글로 잡히지 않는다
        out = ldi.composite(img, units, {units[0]["id"]: "Custom care for your skin"})
        ob = io.BytesIO()
        out.save(ob, "JPEG", quality=92)
        self.assertEqual(ldi.residual_hangul(ob.getvalue()), [])


if __name__ == "__main__":
    unittest.main()
