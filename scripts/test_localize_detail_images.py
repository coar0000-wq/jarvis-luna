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
