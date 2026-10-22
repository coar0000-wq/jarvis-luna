#!/usr/bin/env python3
"""Regression checks for indexed normalization; all data lives in temporary vaults."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import normalize_obsidian_links as normalize


class NormalizeVaultTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.corpus = self.root / "corpus.jsonl"
        self.corpus.write_text("", encoding="utf-8")
        self.patch_corpus = mock.patch.object(normalize, "CORPUS", self.corpus)
        self.patch_raw = mock.patch.object(normalize, "RAW", self.root / "missing.json")
        self.patch_corpus.start()
        self.patch_raw.start()
        self.addCleanup(self.patch_corpus.stop)
        self.addCleanup(self.patch_raw.stop)

    def write(self, name, text="body\n"):
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def run_normalize(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = normalize.normalize_vault(self.vault)
        return result

    def test_title_fallback_preserves_heading_alias_and_unicode(self):
        self.write("Nested/Alpha-Title.md")
        self.write("Nested/한글-노트.md")
        hub = self.write("Hub.md", "[[Alpha.Title#Section|label]] [[한글.노트|한글]]\n")
        changed, unresolved, problems = self.run_normalize()
        self.assertEqual((changed, unresolved), (1, 0))
        self.assertEqual(hub.read_text(), "[[Alpha-Title#Section|label]] [[한글-노트|한글]]\n")
        self.assertEqual(problems, [
            "ambiguous-resolved: Hub.md -> Alpha.Title => Alpha-Title",
            "ambiguous-resolved: Hub.md -> 한글.노트 => 한글-노트",
        ])

    def test_exact_basename_encoded_paths_and_nfd_keep_prior_rules(self):
        self.write("Nested/Café note.md")
        hub = self.write("Hub.md", "[[./Nested/Caf%C3%A9%20note.md#A|B]] "
                         "[[elsewhere\\Café note.md]] [[Cafe\u0301 note]]\n")
        changed, unresolved, _ = self.run_normalize()
        self.assertEqual((changed, unresolved), (1, 0))
        self.assertEqual(hub.read_text(), "[[Café note#A|B]] [[Café note]] [[Café note]]\n")

    def test_ambiguous_titles_and_missing_payload_remain_unresolved(self):
        self.write("Alpha-Title.md")
        self.write("Alpha_Title.md")
        original = "[[Alpha.Title#A|B]] ![[BrainRuntime/payloads/aa/hash.bin|raw]]\n"
        hub = self.write("Hub.md", original)
        changed, unresolved, problems = self.run_normalize()
        self.assertEqual((changed, unresolved), (0, 2))
        self.assertEqual(hub.read_text(), original)
        self.assertEqual(problems, ["unresolved: Hub.md -> Alpha.Title",
                                   "unresolved: Hub.md -> BrainRuntime/payloads/aa/hash.bin"])

    def test_non_note_suffix_can_still_resolve_to_existing_note(self):
        self.write("hash.bin.md")
        hub = self.write("Hub.md", "[[BrainRuntime/payloads/aa/hash.bin]]\n")
        changed, unresolved, _ = self.run_normalize()
        self.assertEqual((changed, unresolved), (1, 0))
        self.assertEqual(hub.read_text(), "[[hash.bin]]\n")

    def test_corpus_migration_before_stable_note_exists_and_ambiguous_titles(self):
        row = {"title": "Future Title", "url": "https://example.test/future"}
        duplicates = [{"title": "Duplicate", "url": "https://example.test/" + str(i)} for i in range(2)]
        self.corpus.write_text("\n".join(json.dumps(r) for r in [row, *duplicates]), encoding="utf-8")
        self.write("Record-123--Future-Title.md")
        original = "[[Record-123--Future-Title#S|alias]] [[Duplicate]]\n"
        hub = self.write("Hub.md", original)
        changed, unresolved, _ = self.run_normalize()
        self.assertEqual((changed, unresolved), (1, 1))
        self.assertEqual(hub.read_text(), f"[[{normalize.record_stem(row)}#S|alias]] [[Duplicate]]\n")

    def test_repeated_invocations_rebuild_index_and_do_not_rewrite_unchanged(self):
        hub = self.write("Hub.md", "[[Fresh.Title]]\n")
        before = hub.stat().st_mtime_ns
        self.assertEqual(self.run_normalize()[:2], (0, 1))
        self.assertEqual(hub.stat().st_mtime_ns, before)
        self.write("Fresh-Title.md")
        self.assertEqual(self.run_normalize()[:2], (1, 0))
        before = hub.stat().st_mtime_ns
        self.assertEqual(self.run_normalize()[:2], (0, 0))
        self.assertEqual(hub.stat().st_mtime_ns, before)

    def test_fallback_normalizes_stems_once_instead_of_per_missing_link(self):
        for i in range(80):
            self.write(f"Known-Title-{i:03d}.md")
        self.write("Hub.md", "\n".join(f"[[Missing-Title-{i:03d}]]" for i in range(100)))
        original = normalize.title_key
        seen = []
        def count(value):
            seen.append(value)
            return original(value)
        with mock.patch.object(normalize, "title_key", side_effect=count):
            self.assertEqual(self.run_normalize()[:2], (0, 100))
        # note_maps, the fallback index and migration each process a stem once.
        # A per-link full scan would process this stem more than 100 times.
        self.assertEqual(seen.count("Known-Title-000"), 3)
        self.assertLess(len(seen), 600)

    def test_corpus_display_is_hashed_once_per_row(self):
        rows = [{"title": "Title " + str(i), "url": "https://example.test/" + str(i)} for i in range(4)]
        original = normalize.record_key
        with mock.patch.object(normalize, "record_key", wraps=original) as key:
            normalize.build_corpus_maps(rows)
        self.assertEqual(key.call_count, len(rows))

    def test_strict_and_allow_unresolved_exit_codes_are_unchanged(self):
        self.write("Hub.md", "[[BrainRuntime/payloads/aa/missing.bin]]\n")
        for flags, expected in [([], 0), (["--strict"], 1),
                                (["--strict", "--allow-unresolved"], 0)]:
            with self.subTest(flags=flags), mock.patch.object(
                sys, "argv", ["normalize", "--vault", str(self.vault), *flags]
            ), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(normalize.main(), expected)
                self.assertIn("unresolved links: 1", out.getvalue())


if __name__ == "__main__":
    unittest.main()
