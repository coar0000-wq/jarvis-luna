"""상세 이미지 영문화(1084687 방식) 회귀 테스트 (2026-10-17).

OCR(tesseract) 이 없는 환경에서도 도는 부분만 기본으로 검사하고, 한글 OCR 이 있으면
합성 이미지로 '한글을 지우고 영문을 얹은 뒤 다시 읽어 한글이 남지 않는다' 까지 본다.
"""
import io
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "daiso"))
import localize_detail_images as ldi  # noqa: E402
from scripts import gemini_stop_guard as stop_guard  # noqa: E402

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


class ReviewArtifactTest(unittest.TestCase):
    """Review storage is exact-byte evidence, never gallery or upload authorization."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "localized" / "1"
        fake_di = mock.Mock()
        fake_di.count_faces.return_value = 0
        for patcher in (mock.patch.object(ldi, "ensure_ocr_ready"),
                        mock.patch.object(ldi, "hangul_boxes", return_value=[]),
                        mock.patch.object(ldi, "residual_hangul", return_value=[]),
                        mock.patch.object(ldi, "info_panel", return_value=(None, "fixture")),
                        mock.patch.dict(sys.modules, {"daiso_images": fake_di})):
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def image_bytes(fmt="PNG"):
        buf = io.BytesIO()
        Image.new("RGB", (400, 900), "white").save(buf, fmt)
        return buf.getvalue()

    def run_sources(self, sources, out=None):
        return ldi.localize_product("1", "Fixture", out or self.out, object(), sources)

    def assert_failed(self, man):
        self.assertEqual(man["status"], "failed")
        self.assertFalse(man["gallery_complete"])
        self.assertEqual(man["gallery_status"], "review_required")
        self.assertFalse(man.get("upload_allowed", False))

    def test_exact_original_and_output_bytes_link_through_final_manifest(self):
        raw = self.image_bytes("PNG")
        url = "https://example.invalid/description/detail.jpg?size=original"
        man = self.run_sources([(url, raw)])
        self.assertEqual(man["status"], "ok")
        src, output, panel = man["sources"][0], man["outputs"][0], man["panels"][0]
        digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual(src["url"], url)
        self.assertEqual(src["sha256"], digest)
        self.assertEqual(src["format"], "PNG")
        self.assertEqual(src["source_file"], f"source-{digest}.bin")
        self.assertEqual(src["preservation_status"], "stored")
        self.assertEqual((self.out / src["source_file"]).read_bytes(), raw)
        for row in (output, panel):
            self.assertEqual(row["source_file"], src["source_file"])
            self.assertEqual(row["source_sha256"], digest)
        jpg = (self.out / output["file"]).read_bytes()
        self.assertEqual(output["sha256"], hashlib.sha256(jpg).hexdigest())
        self.assertEqual(output["bytes"], len(jpg))
        with Image.open(io.BytesIO(jpg)) as image:
            self.assertEqual(image.format, "JPEG")
        with mock.patch.object(ldi, "MANIFEST_DIR", Path(self.tmp.name) / "manifests"):
            saved = json.loads(ldi.write_manifest(man).read_text(encoding="utf-8"))
        self.assertEqual(saved, man)
        self.assertFalse(saved["gallery_complete"])
        self.assertEqual(saved["gallery_status"], "review_required")
        self.assertIn("role_rights_and_label_evidence_review_required", saved["gallery_review_reasons"])
        for record in (saved, src, output, panel):
            for key in ("upload_allowed", "rights_approved", "label_approved", "efficacy_approved"):
                self.assertNotIn(key, record)

    def test_formats_preserve_original_bytes_without_reencoding(self):
        for fmt in ("JPEG", "PNG", "WEBP", "GIF", "BMP"):
            with self.subTest(fmt=fmt):
                raw = self.image_bytes(fmt)
                man = self.run_sources([("source", raw)])
                self.assertEqual(man["status"], "ok")
                src = man["sources"][0]
                self.assertEqual(src["format"], fmt)
                self.assertEqual((self.out / src["source_file"]).read_bytes(), raw)

    def test_url_cannot_choose_a_source_filename(self):
        raw = self.image_bytes()
        man = self.run_sources([("../../outside.jpg?token=fixture", raw)])
        name = man["sources"][0]["source_file"]
        self.assertRegex(name, r"^source-[0-9a-f]{64}\.bin$")
        self.assertEqual((self.out / name).resolve().parent, self.out.resolve())
        self.assertFalse((Path(self.tmp.name) / "outside.jpg").exists())

    def test_missing_and_unsafe_sha_cannot_be_stored_or_succeed(self):
        for digest in (None, "", "../outside", "a" * 63, "Z" * 64):
            with self.subTest(digest=digest), mock.patch.object(ldi, "sha", return_value=digest):
                man = self.run_sources([("source", self.image_bytes())])
                self.assert_failed(man)
                self.assertEqual(man["outputs"], [])
                self.assertNotIn("source_file", man["sources"][0])
                self.assertIn("source_preservation_failed:source_sha256_invalid", man["reasons"])

    def test_source_file_symlink_does_not_overwrite_outside_file(self):
        self.out.mkdir(parents=True)
        raw = self.image_bytes()
        outside = Path(self.tmp.name) / "outside"
        outside.write_bytes(b"keep")
        (self.out / f"source-{hashlib.sha256(raw).hexdigest()}.bin").symlink_to(outside)
        man = self.run_sources([("source", raw)])
        self.assert_failed(man)
        self.assertEqual(outside.read_bytes(), b"keep")
        self.assertNotIn("source_file", man["sources"][0])

    def test_output_directory_symlink_and_traversal_fail_before_writing(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        link = Path(self.tmp.name) / "link"
        link.symlink_to(outside, target_is_directory=True)
        for out in (link / "1", outside / ".." / "other"):
            with self.subTest(out=out):
                man = self.run_sources([("source", self.image_bytes())], out=out)
                self.assert_failed(man)
                self.assertIn("detail_images_unavailable:unsafe_output_directory", man["reasons"])
        self.assertEqual(list(outside.iterdir()), [])

    def test_source_write_failure_does_not_produce_success_or_output(self):
        with mock.patch.object(ldi.tempfile, "NamedTemporaryFile", side_effect=OSError("fixture")):
            man = self.run_sources([("source", self.image_bytes())])
        self.assert_failed(man)
        self.assertEqual(man["outputs"], [])
        self.assertEqual(man["sources"][0]["preservation_status"], "failed")
        self.assertNotIn("source_file", man["sources"][0])
        self.assertIn("source_evidence_incomplete", man["gallery_review_reasons"])

    def test_failed_readback_or_replace_leaves_no_unverified_original(self):
        raw = self.image_bytes()
        for failure in ("readback", "replace"):
            with self.subTest(failure=failure):
                patcher = (mock.patch.object(ldi, "sha", side_effect=[hashlib.sha256(raw).hexdigest(), "0" * 64])
                           if failure == "readback" else
                           mock.patch.object(Path, "replace", side_effect=OSError("fixture")))
                with patcher:
                    man = self.run_sources([("source", raw)])
                self.assert_failed(man)
                self.assertNotIn("source_file", man["sources"][0])
                self.assertEqual(list(self.out.iterdir()), [])

    def test_corrupt_source_is_retained_but_does_not_claim_conversion_success(self):
        raw = b"not an image\x00\xff"
        man = self.run_sources([("broken", raw), ("valid", self.image_bytes())])
        self.assert_failed(man)
        self.assertEqual(man["summary"]["used"], 1)
        self.assertEqual((self.out / man["sources"][0]["source_file"]).read_bytes(), raw)
        self.assertTrue(man["sources"][0]["reason"].startswith("source_decode_failed:"))

    def test_source_is_retained_when_ocr_is_unavailable(self):
        raw = self.image_bytes()
        with mock.patch.object(ldi, "ensure_ocr_ready", side_effect=RuntimeError("fixture")):
            man = self.run_sources([("source", raw)])
        self.assert_failed(man)
        self.assertEqual((self.out / man["sources"][0]["source_file"]).read_bytes(), raw)

    def test_empty_source_and_source_byte_budget_fail_closed(self):
        for raw, limit in ((b"", 10), (self.image_bytes(), 10)):
            with self.subTest(limit=limit), mock.patch.object(ldi, "MAX_SOURCE_BYTES", limit):
                man = self.run_sources([("source", raw)])
                self.assert_failed(man)
                self.assertEqual(man["outputs"], [])
                self.assertNotIn("source_file", man["sources"][0])

    def test_source_count_and_total_budgets_are_bounded(self):
        raw = self.image_bytes()
        with mock.patch.object(ldi, "MAX_SOURCE_FILES", 1):
            man = self.run_sources([("a", raw), ("b", raw)])
        self.assert_failed(man)
        self.assertIn("source_count_budget_exceeded", man["reasons"])
        self.assertEqual(list(self.out.iterdir()), [])
        with mock.patch.object(ldi, "MAX_SOURCE_TOTAL_BYTES", len(raw)):
            man = self.run_sources([("a", raw), ("b", raw)])
        self.assert_failed(man)
        self.assertEqual((self.out / man["sources"][0]["source_file"]).read_bytes(), raw)
        self.assertNotIn("source_file", man["sources"][1])

    def test_pixel_budget_keeps_original_but_skips_ocr_and_conversion(self):
        with mock.patch.object(ldi, "MAX_SOURCE_PIXELS", 10), mock.patch.object(ldi, "hangul_boxes") as ocr:
            man = self.run_sources([("source", self.image_bytes())])
        self.assert_failed(man)
        self.assertEqual(man["outputs"], [])
        self.assertIn("source_decode_failed:source_pixel_budget_exceeded", man["reasons"])
        self.assertTrue((self.out / man["sources"][0]["source_file"]).is_file())
        ocr.assert_not_called()

    def test_download_is_bounded_and_never_returns_truncated_original(self):
        response = mock.MagicMock()
        response.__enter__.return_value.getheader.return_value = None
        response.__enter__.return_value.read.return_value = b"12345"
        with mock.patch.object(ldi, "MAX_SOURCE_BYTES", 4), \
                mock.patch.object(ldi.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "source_size_budget_exceeded"):
                ldi.download("https://example.invalid/image")
        response.__enter__.return_value.read.assert_called_once_with(5)

    def test_download_accepts_exact_byte_limit_without_changing_bytes(self):
        raw = b"1234"
        response = mock.MagicMock()
        response.__enter__.return_value.getheader.return_value = str(len(raw))
        response.__enter__.return_value.read.return_value = raw
        with mock.patch.object(ldi, "MAX_SOURCE_BYTES", len(raw)), \
                mock.patch.object(ldi.urllib.request, "urlopen", return_value=response):
            self.assertEqual(ldi.download("https://example.invalid/image"), raw)

    def test_invalid_or_oversized_content_length_fails_before_reading(self):
        for length in ("", "-1", "+4", "4.0", "4, 4", "NaN", str(ldi.MAX_SOURCE_BYTES + 1)):
            with self.subTest(length=length):
                response = mock.MagicMock()
                response.__enter__.return_value.getheader.return_value = length
                with mock.patch.object(ldi.urllib.request, "urlopen", return_value=response):
                    with self.assertRaises(ldi.SourceEvidenceError):
                        ldi.download("https://example.invalid/image")
                response.__enter__.return_value.read.assert_not_called()

    def test_truncated_but_decodable_http_png_cannot_be_stored_as_original(self):
        raw = self.image_bytes("PNG")
        truncated = raw[:-12]  # IEND is absent, but Pillow can still decode these pixels.
        with Image.open(io.BytesIO(truncated)) as image:
            self.assertEqual(image.convert("RGB").size, (400, 900))
        wire = (f"HTTP/1.1 200 OK\r\nContent-Length: {len(raw)}\r\n"
                "Content-Type: image/png\r\n\r\n").encode() + truncated
        sock = mock.Mock()
        sock.makefile.return_value = io.BytesIO(wire)
        response = http.client.HTTPResponse(sock)
        response.begin()
        with mock.patch.object(ldi, "rendered_detail_image_urls", return_value=["https://example.invalid/image"]), \
                mock.patch.object(ldi.urllib.request, "urlopen", return_value=response):
            man = self.run_sources(None)
        self.assert_failed(man)
        self.assertIn("source_preservation_failed:source_content_length_mismatch", man["reasons"])
        self.assertEqual(man["sources"][0]["preservation_status"], "failed")
        self.assertNotIn("source_file", man["sources"][0])
        self.assertEqual(man["outputs"], [])
        self.assertEqual(list(self.out.iterdir()), [])

    def test_partial_download_failure_keeps_already_downloaded_original(self):
        raw = self.image_bytes()
        with mock.patch.object(ldi, "rendered_detail_image_urls", return_value=["a", "b"]), \
                mock.patch.object(ldi, "download", side_effect=[raw, OSError("fixture")]):
            man = self.run_sources(None)
        self.assert_failed(man)
        self.assertEqual((self.out / man["sources"][0]["source_file"]).read_bytes(), raw)
        self.assertEqual(man["sources"][1]["preservation_status"], "failed")
        self.assertEqual(man["outputs"], [])

    def test_repeated_source_reuses_exact_hash_filename(self):
        raw = self.image_bytes()
        first = self.run_sources([("a", raw)])
        second = self.run_sources([("b", raw)])
        self.assertEqual(first["sources"][0]["source_file"], second["sources"][0]["source_file"])
        self.assertEqual(len(list(self.out.glob("source-*.bin"))), 1)

    def assert_review_upload_pin(self, section, manifest):
        # The reviewed manifest owns the pin. Do not copy another release SHA here,
        # or silently accept multiple (possibly stale) upload-artifact approvals.
        repository = "actions/upload-artifact"
        rows = [row for row in manifest["actions"] if row["repository"] == repository]
        self.assertEqual(len(rows), 1, "Require one authoritative upload-artifact approval")
        row = rows[0]
        self.assertRegex(row["sha"], r"\A[0-9a-f]{40}\Z")
        self.assertEqual(row["type"], "commit")
        self.assertEqual(row["ref"], f"{repository}@{row['tag']}")
        self.assertEqual(row["source"], f"https://api.github.com/repos/{repository}/git/ref/tags/{row['tag']}")
        refs = re.findall(r"(?m)^\s*uses:\s*([^\s#]+)", section)
        self.assertEqual(len(refs), 1, "Require exactly one executable upload action")
        self.assertRegex(refs[0], r"\Aactions/upload-artifact@[0-9a-f]{40}\Z")
        self.assertEqual(refs[0], f"{repository}@{row['sha']}")

    def test_review_upload_pin_tracks_manifest_and_rejects_unapproved_refs(self):
        # Synthetic approvals only: no provider lookup or second real pin table.
        repository = "actions/upload-artifact"
        old_sha, updated_sha = "1" * 40, "2" * 40
        row = {"repository": repository, "sha": updated_sha, "type": "commit",
               "tag": "v-next", "ref": f"{repository}@v-next",
               "source": f"https://api.github.com/repos/{repository}/git/ref/tags/v-next"}
        manifest = {"actions": [row]}
        section = f"        uses: {repository}@{updated_sha} # reviewed update\n"
        self.assert_review_upload_pin(section, manifest)
        for ref in (f"{repository}@{old_sha}", f"{repository}@v-next",
                    f"{repository}@{'3' * 40}", f"{repository}@{'2' * 39}",
                    f"other/upload-artifact@{updated_sha}"):
            with self.subTest(ref=ref), self.assertRaises(AssertionError):
                self.assert_review_upload_pin(f"        uses: {ref}\n", manifest)
        for invalid in (f"        # uses: {repository}@{updated_sha}\n", section + section):
            with self.subTest(section=invalid), self.assertRaises(AssertionError):
                self.assert_review_upload_pin(invalid, manifest)
        for rows in ([], [row, dict(row, sha=old_sha)]):
            with self.subTest(rows=rows), self.assertRaises(AssertionError):
                self.assert_review_upload_pin(section, {"actions": rows})
        for changes in ({"sha": "v-next"}, {"type": "tag"}, {"ref": "other@v-next"},
                        {"source": "https://unreviewed.invalid/tag"}):
            with self.subTest(changes=changes), self.assertRaises(AssertionError):
                self.assert_review_upload_pin(section, {"actions": [dict(row, **changes)]})

    def test_workflow_preserves_only_review_assets_always_for_30_days(self):
        workflow = (HERE.parent / ".github/workflows/daiso-daily-beauty-shopify.yml").read_text(encoding="utf-8")
        section = workflow.split("      - name: 상세 이미지 검토 자산 보관\n", 1)[1].split("      - name:", 1)[0]
        self.assertIn("if: ${{ always() }}", section)
        manifest = json.loads((HERE.parent / "requirements/lock-manifest.json").read_text(encoding="utf-8"))
        self.assert_review_upload_pin(section, manifest)
        self.assertIn("name: daiso-daily-beauty-image-review", section)
        self.assertIn("retention-days: 30", section)
        paths = section.split("          path: |\n", 1)[1].split("          if-no-files-found:", 1)[0]
        self.assertEqual([line.strip() for line in paths.splitlines()],
                         ["${{ runner.temp }}/localized/", "data/image_localization/*.json"])
        self.assertIn("group: daiso-daily-beauty-shopify\n  cancel-in-progress: false", workflow)
        for retained in ("name: daiso-daily-beauty-result", "name: body-shower-catalog-source",
                         "git add data/image_localization", "python -B scripts/test_localize_detail_images.py"):
            self.assertIn(retained, workflow)


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
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / "data").mkdir()
        self.state = self.root / "data/gosi.json"
        self.save_stops([])
        for patcher in (
            mock.patch.object(ldi, "ROOT", self.root),
            mock.patch("socket.create_connection", side_effect=AssertionError("network forbidden")),
            mock.patch("socket.socket.connect", side_effect=AssertionError("network forbidden")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        ldi.GeminiTranslator.calls, ldi.GeminiTranslator.stopped = 0, None

    def save_stops(self, stops, **extra):
        self.state.write_text(json.dumps(dict(items={}, provider_stops=stops, **extra)))

    def active_stop(self, **extra):
        return dict(provider="gemini", code=429, category="quota",
                    stopped_at=datetime.now(timezone.utc).isoformat(), **extra)

    def response(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": '{"items":[{"id":1,"en":"x"}]}'}]}}]
        }).encode()
        return response

    def test_call_budget_and_stop_on_quota(self):
        t = ldi.GeminiTranslator("k", "m")
        with mock.patch.object(ldi.GeminiTranslator, "MAX_CALLS", 2), \
                mock.patch.object(ldi.urllib.request, "urlopen", return_value=self.response()) as network:
            t.translate(b"", [], "T", "s")
            t.translate(b"", [], "T", "s")
            with self.assertRaises(RuntimeError):
                t.translate(b"", [], "T", "s")
            self.assertEqual(network.call_count, 2)
            self.assertEqual(ldi.GeminiTranslator.calls, 2)
        ldi.GeminiTranslator.calls = 0
        err = ldi.urllib.error.HTTPError("u", 429, "quota", {}, None)
        with mock.patch.object(ldi.urllib.request, "urlopen", side_effect=err) as network:
            with self.assertRaises(ldi.urllib.error.HTTPError):
                t.translate(b"", [], "T", "s")
            with self.assertRaises(RuntimeError):
                t.translate(b"", [], "T", "s")          # 429 뒤에는 더 부르지 않는다
            network.assert_called_once()

    def test_saved_stop_blocks_all_keys_models_before_count_and_network(self):
        for code, category in ((401, "auth"), (403, "auth"), (429, "quota")):
            stop = dict(self.active_stop(), code=code, category=category)
            self.save_stops([stop])
            before = self.state.read_bytes()
            with mock.patch.object(ldi.urllib.request, "urlopen") as network:
                for key, model in (("key-one", "gemini-flash-latest"), ("key-two", "gemini-flash-lite-latest")):
                    with self.subTest(code=code, model=model), self.assertRaises(stop_guard.ProviderStop):
                        ldi.GeminiTranslator(key, model).translate(b"", [], "T", "s")
                network.assert_not_called()
            self.assertEqual(ldi.GeminiTranslator.calls, 0)
            self.assertEqual(self.state.read_bytes(), before)

    def test_each_request_rereads_saved_state(self):
        translator = ldi.GeminiTranslator("k", "m")
        with mock.patch.object(ldi.urllib.request, "urlopen", return_value=self.response()) as network:
            self.assertEqual(translator.translate(b"", [], "T", "s"), {1: "x"})
            self.save_stops([self.active_stop()])
            with self.assertRaises(stop_guard.ProviderStop):
                translator.translate(b"", [], "T", "s")
            network.assert_called_once()
        self.assertEqual(ldi.GeminiTranslator.calls, 1)

    def test_stop_arriving_during_request_construction_is_checked_before_count(self):
        request = ldi.urllib.request.Request
        def build(*args, **kwargs):
            self.save_stops([self.active_stop()])
            return request(*args, **kwargs)
        with mock.patch.object(ldi.urllib.request, "Request", side_effect=build), \
             mock.patch.object(ldi.urllib.request, "urlopen") as network:
            with self.assertRaises(stop_guard.ProviderStop):
                ldi.GeminiTranslator("k", "m").translate(b"", [], "T", "s")
            network.assert_not_called()
        self.assertEqual(ldi.GeminiTranslator.calls, 0)

    def test_existing_expiry_boundary_is_read_only_including_history(self):
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        stop = dict(self.active_stop(), stopped_at=(now - timedelta(hours=24)).isoformat())
        self.save_stops([stop], provider_stop_history=[dict(stop, expired_at="prior")])
        before = self.state.read_bytes()
        with self.assertRaises(stop_guard.ProviderStop):
            stop_guard.assert_gemini_not_stopped(self.root, now=now - timedelta(microseconds=1))
        stop_guard.assert_gemini_not_stopped(self.root, now=now)
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(list((self.root / "data").iterdir()), [self.state])

    def test_future_missing_naive_and_invalid_clocks_remain_stopped(self):
        now = datetime(2026, 10, 23, tzinfo=timezone.utc)
        for value in ((now + timedelta(days=1)).isoformat(), None, "invalid", "2020-01-01T00:00:00"):
            with self.subTest(clock=value):
                self.save_stops([dict(self.active_stop(), stopped_at=value)])
                with self.assertRaises(stop_guard.ProviderStop):
                    stop_guard.assert_gemini_not_stopped(self.root, now=now)

    def test_other_provider_stops_do_not_disable_gemini(self):
        self.save_stops([dict(self.active_stop(), provider="daiso", code=403, category="auth")])
        with mock.patch.object(ldi.urllib.request, "urlopen", return_value=self.response()) as network:
            self.assertEqual(ldi.GeminiTranslator("k", "m").translate(b"", [], "T", "s"), {1: "x"})
            network.assert_called_once()

    def test_unavailable_malformed_oversize_state_fails_closed(self):
        invalid = (None, b"{", b"[]", b'{"items": []}', b'{"items": {}, "provider_stops": {}}',
                   b'{"items": {}, "provider_stops": [null]}',
                   b'{"items": {}, "provider_stops": [{}]}',
                   b'{"items": {}, "provider_stops": [{"provider": "gemini", "code": {}, "stopped_at": "2000-01-01T00:00:00Z"}]}',
                   b'{"items": {}, "provider_stops": [{"provider": "gemini", "category": []}]}',
                   b'{"items": {}, "provider_stop_history": {}}',
                   b'{"items": {}, "provider_stops": [], "provider_stops": []}',
                   b'{"items": {}, "value": NaN}')
        for raw in invalid:
            with self.subTest(raw=raw), mock.patch.object(ldi.urllib.request, "urlopen") as network:
                self.state.unlink(missing_ok=True)
                if raw is not None:
                    self.state.write_bytes(raw)
                with self.assertRaises(stop_guard.GeminiStopStateError):
                    ldi.GeminiTranslator("k", "m").translate(b"", [], "T", "s")
                network.assert_not_called()
                self.assertEqual(ldi.GeminiTranslator.calls, 0)
        self.state.write_bytes(b" " * 129)
        with mock.patch.object(stop_guard, "MAX_BYTES", 128):
            with self.assertRaises(stop_guard.GeminiStopStateError):
                stop_guard.assert_gemini_not_stopped(self.root)

    def test_unreadable_and_symlink_state_fails_closed(self):
        with mock.patch.object(stop_guard.os, "open", side_effect=PermissionError("fixture")):
            with self.assertRaises(stop_guard.GeminiStopStateError):
                stop_guard.assert_gemini_not_stopped(self.root)
        target = self.root / "retained.json"
        self.state.replace(target)
        self.state.symlink_to(target)
        with self.assertRaises(stop_guard.GeminiStopStateError):
            stop_guard.assert_gemini_not_stopped(self.root)

    def test_file_replaced_before_descriptor_open_is_rejected_without_reading(self):
        original_open = os.open
        for replacement in ("regular", "symlink", "directory", "fifo"):
            if replacement == "fifo" and not hasattr(os, "mkfifo"):
                continue
            with self.subTest(replacement=replacement):
                if self.state.is_dir():
                    self.state.rmdir()
                else:
                    self.state.unlink(missing_ok=True)
                self.save_stops([])
                target = self.root / "replacement.json"
                target.write_text(json.dumps({"items": {}, "provider_stops": []}))
                opened = []
                def replace_before_open(path, flags, *args, **kwargs):
                    self.assertEqual(Path(path), self.state)
                    if hasattr(os, "O_NONBLOCK"):
                        self.assertTrue(flags & os.O_NONBLOCK)
                    if hasattr(os, "O_NOFOLLOW"):
                        self.assertTrue(flags & os.O_NOFOLLOW)
                    self.state.unlink()
                    if replacement == "regular":
                        target.replace(self.state)
                    elif replacement == "symlink":
                        self.state.symlink_to(target)
                    elif replacement == "directory":
                        self.state.mkdir()
                    else:
                        os.mkfifo(self.state)
                    fd = original_open(path, flags, *args, **kwargs)
                    opened.append(fd)
                    return fd
                with mock.patch.object(stop_guard.os, "open", side_effect=replace_before_open), \
                     mock.patch.object(stop_guard.os, "fdopen") as reader:
                    with self.assertRaises(stop_guard.GeminiStopStateError):
                        stop_guard.assert_gemini_not_stopped(self.root)
                    reader.assert_not_called()
                for fd in opened:
                    with self.assertRaises(OSError):
                        os.fstat(fd)  # Failure paths close every descriptor.

    def test_oversize_descriptor_and_growth_during_read_fail_closed(self):
        original_open = os.open
        def grow_before_open(path, flags, *args, **kwargs):
            self.state.write_bytes(b" " * 129)
            return original_open(path, flags, *args, **kwargs)
        with mock.patch.object(stop_guard, "MAX_BYTES", 128), \
             mock.patch.object(stop_guard.os, "open", side_effect=grow_before_open), \
             mock.patch.object(stop_guard.os, "fdopen") as reader:
            with self.assertRaises(stop_guard.GeminiStopStateError):
                stop_guard.assert_gemini_not_stopped(self.root)
            reader.assert_not_called()
        self.save_stops([])
        original_fdopen = os.fdopen
        def growing_reader(fd, *args, **kwargs):
            stream = original_fdopen(fd, *args, **kwargs)
            wrapped = mock.MagicMock()
            def read(limit):
                self.assertEqual(limit, stop_guard.MAX_BYTES + 1)
                raw = stream.read(limit)
                with self.state.open("ab") as writer:
                    writer.write(b" ")
                return raw
            wrapped.__enter__.return_value.read.side_effect = read
            wrapped.__exit__.side_effect = lambda *exc: stream.close()
            return wrapped
        with mock.patch.object(stop_guard.os, "fdopen", side_effect=growing_reader):
            with self.assertRaises(stop_guard.GeminiStopStateError):
                stop_guard.assert_gemini_not_stopped(self.root)

    def test_replacement_after_descriptor_open_rejects_stale_state(self):
        original_fdopen = os.fdopen
        def replace_after_open(fd, *args, **kwargs):
            replacement = self.root / "new-stop.json"
            replacement.write_text(json.dumps({"items": {}, "provider_stops": [self.active_stop()]}))
            replacement.replace(self.state)
            return original_fdopen(fd, *args, **kwargs)
        with mock.patch.object(stop_guard.os, "fdopen", side_effect=replace_after_open):
            with self.assertRaises(stop_guard.GeminiStopStateError):
                stop_guard.assert_gemini_not_stopped(self.root)

    def test_github_actions_import_from_foreign_cwd_keeps_guard_active(self):
        self.save_stops([self.active_stop()])
        code = f'''
import importlib.util, socket, urllib.request
from pathlib import Path
def blocked(*args, **kwargs): raise AssertionError("network forbidden")
socket.create_connection = blocked
socket.socket.connect = blocked
urllib.request.urlopen = blocked
spec = importlib.util.spec_from_file_location("isolated_localize", {str(Path(ldi.__file__).resolve())!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.ROOT = Path({str(self.root)!r})
before = (module.ROOT / "data/gosi.json").read_bytes()
from scripts.gemini_stop_guard import ProviderStop
try:
    module.GeminiTranslator("offline-key", "fixture-model").translate(b"", [], "T", "s")
except ProviderStop:
    pass
else:
    raise AssertionError("persisted STOP was not applied")
assert module.GeminiTranslator.calls == 0
assert (module.ROOT / "data/gosi.json").read_bytes() == before
'''
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code], cwd=self.root,
                                env={**os.environ, "GITHUB_ACTIONS": "true", "PYTHONPATH": ""},
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reviewed_translation_is_independent_of_saved_gemini_stop(self):
        self.save_stops([self.active_stop()])
        path = self.root / "reviewed.json"
        path.write_text(json.dumps({"translator": "fixture", "panels": {"panel": {"1": "Reviewed"}}}))
        with mock.patch.object(ldi.urllib.request, "urlopen") as network:
            translator = ldi.translator_from_env(str(path))
            self.assertEqual(translator.translate(b"", [], "T", "panel"), {1: "Reviewed"})
            network.assert_not_called()
        self.assertEqual(ldi.GeminiTranslator.calls, 0)


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
