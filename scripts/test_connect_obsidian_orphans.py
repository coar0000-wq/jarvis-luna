#!/usr/bin/env python3
"""Tests for scripts/connect_obsidian_orphans.py (stdlib unittest; no real vault is touched).

Run:  python -m unittest scripts/test_connect_obsidian_orphans.py -v
  or: python scripts/test_connect_obsidian_orphans.py
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import connect_obsidian_orphans as co  # noqa: E402

PRIVATE_SECRET = "SECRET-DIARY-BODY-9137"


def snapshot_tree(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def write(root: Path, rel: str, text: str | bytes = "") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        p.write_bytes(text)
    else:
        p.write_text(text, encoding="utf-8", newline="\n")
    return p


def run_cli(*argv: str) -> tuple[int, dict | None, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = co.main(list(argv))
    text = out.getvalue()
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    return code, data, text + err.getvalue()


class VaultCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="orph-test-"))
        self.vault = self.tmp / "vault"
        self.backup = self.tmp / "backup"
        self.vault.mkdir()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.build_vault()

    def build_vault(self):
        v = self.vault
        write(v, ".obsidian/graph.json", json.dumps({"search": "-path:Knowledge/Records", "showOrphans": True}))
        write(v, ".obsidian/app.json", "{}")
        write(v, "Knowledge/Topics/뷰티스킨케어.md", "# 뷰티\n")
        write(v, "Knowledge/Sources/Source--arXiv.md", "# arxiv\n")
        write(v, "Knowledge/Orgs/기관--OpenAI.md", "# openai\n")
        write(v, "Concepts/Skin Barrier.md", "# Skin Barrier\n[[Knowledge/Topics/뷰티스킨케어]]\n")
        # records: orphans with declared metadata
        write(v, "Knowledge/Records/Record-1.md",
              '---\ntitle: "Record 1"\ntags: [record, real-data]\nsource: "arXiv"\ntopics: ["뷰티스킨케어"]\n---\nbody\n')
        write(v, "Knowledge/Records/Record-2.md",
              '---\ntitle: "Record 2"\nsource: "arXiv"\norg: "OpenAI"\ntopics: ["없는주제"]\n---\nbody\n')
        # note that is linked (not orphan): wikilink with alias + heading
        write(v, "Hub.md", "[[Linked Note#Heading|alias text]] and ![[pic.png]]\n")
        write(v, "Linked Note.md", "plain\n")
        write(v, "Attachments/pic.png", b"\x89PNG\r\n")
        write(v, "Attachments/unreferenced.pdf", b"%PDF-1.4")
        write(v, "Attachments/Skin Barrier.png", b"\x89PNG")           # same name as a note -> inferred
        # tag + title + folder-only orphans
        write(v, "Ideas/a.md", "---\ntags: [project-x]\n---\ntext\n")
        write(v, "Ideas/b.md", "---\ntags: [project-x]\n---\ntext\n")
        write(v, "Ideas/Notes about Skin Barrier research.md", "text without links\n")
        write(v, "Loose/lonely.md", "no links here\n")
        # private (Personal/) with a secret body and duplicate basenames in two folders
        write(v, "Personal/diary.md", f"{PRIVATE_SECRET}\n")
        write(v, "Personal/a/dup.md", "one\n")
        write(v, "Personal/b/dup.md", "two\n")
        write(v, "Personal/weird #1 [x].md", "odd name\n")
        write(v, "Personal/한글 노트.md", "한글\n")

    def analyse(self, include_private=False, safe=False):
        return co.analyse(self.vault, "Navigation", ("Personal",), 500, include_private, safe)


class ParsingTests(unittest.TestCase):
    def test_wikilink_embed_alias_heading_block_escaped_pipe(self):
        text = ("[[A]] [[B|alias]] [[C#Head]] [[D^blk]] [[E#h|x]] ![[img.png]] ![[F|300]] "
                "| [[G\\|alias]] |\n[[#local]]")
        got = [(l.target, l.embed) for l in co.extract_links(text)]
        self.assertEqual(got, [("A", False), ("B", False), ("C", False), ("D", False), ("E", False),
                               ("img.png", True), ("F", True), ("G", False), ("", False)])

    def test_markdown_links(self):
        text = ("[t](Folder/My%20Note.md) ![i](<img with space.png>) [ext](https://x.y/z.md) "
                "[mail](mailto:a@b.c) [frag](#h) [f2](Note.md#sec) [enc](a%23b.md)")
        got = [l.target for l in co.extract_links(text)]
        self.assertEqual(got, ["Folder/My Note.md", "img with space.png", "Note.md", "a#b.md"])

    def test_code_is_ignored_and_frontmatter_links_count(self):
        text = '---\nrel: "[[FM Target]]"\n---\n`[[inline]]`\n```\n[[fenced]]\n```\n[[real]]\n'
        self.assertEqual([l.target for l in co.extract_links(text)], ["FM Target", "real"])

    def test_frontmatter_forms_and_broken_tags(self):
        fm, _, _ = co.parse_frontmatter(
            "\ufeff---\r\ntitle: \"T\"\r\ntags: [a, \"b c\"]\r\nlist:\r\n  - x\r\n  - y\r\n---\r\nbody")
        self.assertEqual(fm["title"], "T")
        self.assertEqual(fm["tags"], ["a", "b c"])
        self.assertEqual(fm["list"], ["x", "y"])
        # the generator bug seen in the real vault must not produce tags
        self.assertEqual(co.clean_tags({"tags": ["{'", "'.join(tags)}", "record", "keep"]}), ["keep"])

    def test_decode_errors_do_not_crash(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        write(tmp, "bad.md", b"\xff\xfe[[x]] \xc3(")
        nodes, stats = co.scan_vault(tmp, "Navigation", ())
        self.assertEqual(stats["decode_errors"], 1)
        self.assertEqual(len(nodes), 1)


class ResolverTests(unittest.TestCase):
    def mk(self, rels):
        return co.Resolver(rels)

    def test_case_insensitive_name_path_suffix_and_ext(self):
        r = self.mk(["Notes/Alpha Beta.md", "Img/Pic.PNG", "x/y/z.md"])
        L = co.RawLink
        self.assertEqual(r.resolve("s.md", L("alpha beta", False, False)), "Notes/Alpha Beta.md")
        self.assertEqual(r.resolve("s.md", L("notes/alpha beta", False, False)), "Notes/Alpha Beta.md")
        self.assertEqual(r.resolve("s.md", L("y/z", False, False)), "x/y/z.md")
        self.assertEqual(r.resolve("s.md", L("pic.png", False, False)), "Img/Pic.PNG")
        self.assertEqual(r.resolve("s.md", L("Alpha Beta.md", False, False)), "Notes/Alpha Beta.md")
        self.assertIsNone(r.resolve("s.md", L("missing", False, False)))
        self.assertEqual(r.resolve("s.md", L("", False, False)), "")

    def test_markdown_relative_paths(self):
        r = self.mk(["a/b/n.md", "a/img.png", "n.md"])
        L = co.RawLink
        self.assertEqual(r.resolve("a/b/src.md", L("n.md", True, False)), "a/b/n.md")
        self.assertEqual(r.resolve("a/b/src.md", L("../img.png", True, False)), "a/img.png")
        self.assertEqual(r.resolve("a/b/src.md", L("/n.md", True, False)), "n.md")

    def test_ambiguity_prefers_same_folder_then_shallowest(self):
        r = self.mk(["p/a/dup.md", "p/b/dup.md", "dup.md"])
        L = co.RawLink
        self.assertEqual(r.resolve("p/b/src.md", L("dup", False, False)), "p/b/dup.md")
        self.assertEqual(r.resolve("q/src.md", L("dup", False, False)), "dup.md")
        self.assertEqual(r.resolve("q/src.md", L("a/dup", False, False)), "p/a/dup.md")
        self.assertGreaterEqual(r.ambiguous, 2)

    def test_unicode_normalisation(self):
        import unicodedata
        nfd = unicodedata.normalize("NFD", "한글 노트")
        r = self.mk(["한글 노트.md"])
        self.assertEqual(r.resolve("s.md", co.RawLink(nfd, False, False)), "한글 노트.md")


class LinkRoundTripTests(unittest.TestCase):
    def test_generated_links_resolve_to_exact_file(self):
        rels = ["Personal/a/dup.md", "Personal/b/dup.md", "Personal/weird #1 [x].md", "한글/노트 ^1.md",
                "100% sure & more.md", "dir/trailing .md", "Attachments/x y.PDF", "Attachments/p|q.png".replace("|", "_")]
        r = co.Resolver(rels)
        for rel in rels:
            link = co.make_link(rel, "lab|el [x]")
            found = co.extract_links(link)
            self.assertEqual(len(found), 1, link)
            self.assertEqual(r.resolve("Navigation/hub.md", found[0]), rel, link)


class PlanTests(VaultCase):
    def test_baseline_orphans_and_attachments(self):
        res = self.analyse()
        orphan_rels = {n.rel for n in res["orphans"]}
        self.assertNotIn("Linked Note.md", orphan_rels)           # linked via alias+heading
        self.assertNotIn("Attachments/pic.png", orphan_rels)      # embedded
        self.assertIn("Attachments/unreferenced.pdf", orphan_rels)
        self.assertIn("Knowledge/Records/Record-1.md", orphan_rels)
        self.assertNotIn("Knowledge/Topics/뷰티스킨케어.md", orphan_rels)   # linked from a concept
        s = res["summary"]["orphans_baseline"]
        self.assertEqual(s["attachments"], 2)   # unreferenced.pdf + Skin Barrier.png
        self.assertEqual(s["graph_visible_total"], s["total"] - 2)   # two Records hidden by graph filter

    def test_tiers_are_distinguished_and_honest(self):
        res = self.analyse()
        by = {(g.tier, g.family, g.name): g for g in res["groups"]}
        self.assertIn("Knowledge/Records/Record-1.md", by[(co.TIER_DIRECT, "topic", "뷰티스킨케어")].members)
        # Record-2: unknown topic -> falls back to org (declared), not to topic
        self.assertIn("Knowledge/Records/Record-2.md", by[(co.TIER_DIRECT, "org", "기관--OpenAI")].members)
        tag = [g for g in res["groups"] if g.tier == co.TIER_TAG and not g.private]
        self.assertEqual(len(tag), 1)
        self.assertEqual(sorted(tag[0].members), ["Ideas/a.md", "Ideas/b.md"])
        title = [g for g in res["groups"] if g.tier == co.TIER_TITLE and not g.private]
        members = {m for g in title for m in g.members}
        self.assertIn("Ideas/Notes about Skin Barrier research.md", members)
        self.assertIn("Attachments/Skin Barrier.png", members)      # exact file-name match
        nav = [g for g in res["groups"] if g.tier == co.TIER_NAV and not g.private]
        nav_members = {m for g in nav for m in g.members}
        self.assertIn("Loose/lonely.md", nav_members)
        self.assertIn("Attachments/unreferenced.pdf", nav_members)
        self.assertNotIn("Knowledge/Records/Record-1.md", nav_members)

    def test_each_orphan_has_a_hub_and_projection_has_zero_orphans(self):
        res = self.analyse(include_private=True, safe=True)
        p = res["summary"]["projected"]
        self.assertEqual(p["orphans_remaining"], 0)
        self.assertEqual(p["attachment_orphans_remaining"], 0)
        self.assertEqual(p["generated_hubs_unreachable"], 0)
        self.assertEqual(p["components"], 1)                       # everything reachable from the hubs
        self.assertEqual(p["nodes_outside_largest_component"], 0)

    def test_private_not_in_public_hubs_and_not_written_by_default(self):
        res = self.analyse(include_private=False)
        for f in res["write_files"]:
            self.assertFalse(f.private)
            self.assertNotIn("Personal/", f.content)
            self.assertNotIn("_private", f.content)
        s = res["summary"]
        self.assertGreater(s["files"]["private_skipped"], 0)
        self.assertGreater(s["projected"]["orphans_remaining_private"], 0)   # honest: not hidden

    def test_private_hub_contains_no_note_content(self):
        res = self.analyse(include_private=True, safe=True)
        privs = [f for f in res["write_files"] if f.private]
        self.assertTrue(privs)
        for f in privs:
            self.assertNotIn(PRIVATE_SECRET, f.content)
            self.assertIn("private: true", f.content)
            self.assertTrue(f.rel.startswith("Navigation/_private/"))

    def test_duplicate_basenames_are_path_qualified(self):
        res = self.analyse(include_private=True, safe=True)
        text = "\n".join(f.content for f in res["write_files"])
        self.assertIn("[[Personal/a/dup|dup]]", text)
        self.assertIn("[[Personal/b/dup|dup]]", text)
        self.assertNotIn("[[dup", text)
        self.assertIn("(Personal/weird%20%231%20%5Bx%5D.md)", text)    # markdown link for unsafe names

    def test_large_group_is_bucketed_with_cap(self):
        for i in range(120):
            write(self.vault, f"Knowledge/Records/R{i:03d}.md",
                  '---\nsource: "arXiv"\ntopics: ["뷰티스킨케어"]\n---\n')
        res = co.analyse(self.vault, "Navigation", ("Personal",), 50, False, False)
        buckets = [f for f in res["write_files"] if f.role == "bucket"]
        self.assertGreaterEqual(len(buckets), 3)
        self.assertEqual(res["summary"]["projected"]["orphans_remaining"] - res["summary"]["projected"]["orphans_remaining_private"], 0)
        again = co.analyse(self.vault, "Navigation", ("Personal",), 50, False, False)
        self.assertEqual({f.rel: f.content for f in buckets},
                         {f.rel: f.content for f in again["write_files"] if f.role == "bucket"})   # deterministic

    def test_disconnected_clusters_are_bridged_without_leaking_private(self):
        write(self.vault, "Islands/X1.md", "[[X2]]\n")
        write(self.vault, "Islands/X2.md", "[[X1]]\n")
        write(self.vault, "Personal/P1.md", "[[P2]]\n")
        write(self.vault, "Personal/P2.md", "[[P1]]\n")
        res = self.analyse(include_private=True, safe=True)
        s = res["summary"]
        self.assertGreaterEqual(s["cluster_bridges"], 2)
        self.assertEqual(s["projected"]["components"], 1)
        self.assertEqual(s["projected"]["nodes_outside_largest_component"], 0)
        for f in res["write_files"]:
            if not f.private:
                self.assertNotIn("Personal/", f.content)
        bridged = {m for g in res["groups"] if g.family == "cluster" for m in g.members}
        self.assertTrue(bridged & {"Islands/X1.md", "Islands/X2.md"})
        # honest labelling: bridge hubs say they claim no topical relation
        text = "\n".join(f.content for f in res["write_files"] if "Disconnected" in f.rel)
        self.assertIn("주제 관계를 주장하지 않습니다", text)

    def test_generic_title_target_is_not_used(self):
        write(self.vault, "Concepts/Generic Term.md", "# g\n[[Linked Note]]\n")
        for i in range(co.TITLE_MAX_GROUP + 5):
            write(self.vault, f"Bulk/Generic Term {i}.md", "x\n")
        res = self.analyse()
        title_members = {m for g in res["groups"] if g.tier == co.TIER_TITLE for m in g.members}
        self.assertFalse(any(m.startswith("Bulk/") for m in title_members))
        nav_members = {m for g in res["groups"] if g.tier == co.TIER_NAV for m in g.members}
        self.assertTrue(any(m.startswith("Bulk/") for m in nav_members))


class CliTests(VaultCase):
    def args(self, *extra):
        # 아래 CLI 테스트는 추정·탐색 링크까지 만드는 예전 동작(--keep-inferred)을 검사한다.
        return ["--vault", str(self.vault), "--backup-root", str(self.backup), "--keep-inferred", *extra]

    def test_default_writes_only_data_declared_direct_hubs(self):
        code, data, _ = run_cli("--vault", str(self.vault), "--backup-root", str(self.backup), "--apply")
        self.assertEqual(code, 0)
        written = [p.relative_to(self.vault).as_posix() for p in (self.vault / "Navigation").rglob("*.md")]
        self.assertTrue(written)
        for rel in written:
            text = (self.vault / rel).read_text(encoding="utf-8")
            self.assertNotIn("Inferred/", rel)
            self.assertNotIn("Folders/", rel)
            self.assertNotIn("inferred-", text.split("---", 2)[1] if text.startswith("---") else "")

    def test_dry_run_is_default_and_writes_nothing(self):
        before = snapshot_tree(self.vault)
        code, data, _ = run_cli(*self.args())
        self.assertEqual(code, 0)
        self.assertEqual(data["mode"], "dry-run")
        self.assertGreater(data["files"]["would_create"], 0)
        self.assertEqual(before, snapshot_tree(self.vault))
        self.assertFalse(self.backup.exists())

    def test_apply_is_additive_and_connects_everything_public(self):
        before = snapshot_tree(self.vault)
        code, data, _ = run_cli(*self.args("--apply"))
        self.assertEqual(code, 0)
        after = snapshot_tree(self.vault)
        for rel, digest in before.items():                     # nothing existing changed or vanished
            self.assertEqual(after.get(rel), digest, rel)
        new = set(after) - set(before)
        self.assertTrue(new and all(r.startswith("Navigation/") for r in new))
        self.assertFalse(any(r.startswith("Navigation/_private") for r in new))   # private not written
        self.assertFalse(any(r.endswith(".tmp-" + co.GENERATOR) for r in after))
        # verify pass: only private (not written) orphans remain, no public orphan
        code, vdata, _ = run_cli("--vault", str(self.vault), "--verify")
        self.assertEqual(vdata["orphans_remaining"], vdata["orphans_remaining_private"])
        self.assertGreater(vdata["generated_hubs"], 0)

    def test_idempotent_and_backup_of_changed_generated_files(self):
        run_cli(*self.args("--apply"))
        snap = snapshot_tree(self.vault)
        code, data, _ = run_cli(*self.args("--apply"))
        self.assertEqual(data["files"]["would_create"] + data["files"]["would_update"], 0)
        self.assertEqual(snap, snapshot_tree(self.vault))
        # tamper with one generated hub -> must be backed up, then restored
        hub = self.vault / "Navigation" / f"{co.ROOT_NAME}.md"
        hub.write_text(hub.read_text(encoding="utf-8") + "\nmanual edit\n", encoding="utf-8")
        edited = hub.read_bytes()
        code, data, _ = run_cli(*self.args("--apply"))
        self.assertEqual(data["applied"]["updated"], 1)
        backups = list(self.backup.rglob(f"{co.ROOT_NAME}.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), edited)
        self.assertEqual(snap, snapshot_tree(self.vault))

    def test_refuses_to_overwrite_non_generated_file(self):
        # a user file occupying a hub path must survive untouched
        target = self.vault / "Navigation" / f"{co.ROOT_NAME}.md"
        write(self.vault, f"Navigation/{co.ROOT_NAME}.md", "MY OWN NOTE\n")
        code, data, _ = run_cli(*self.args("--apply"))
        self.assertEqual(code, 2)
        self.assertEqual(target.read_text(encoding="utf-8"), "MY OWN NOTE\n")
        self.assertEqual(data["files"]["collisions_refused"], 1)

    def test_stale_generated_page_is_retired_not_deleted(self):
        run_cli(*self.args("--apply"))
        stale = self.vault / "Navigation" / "Folders" / "Folder · Old.md"
        write(self.vault, "Navigation/Folders/Folder · Old.md",
              f"---\ntitle: \"x\"\n{co.MARKER}\n---\nold\n")
        code, data, _ = run_cli(*self.args("--apply"))
        self.assertTrue(stale.exists())
        self.assertIn("retired", stale.read_text(encoding="utf-8"))
        code, vdata, _ = run_cli("--vault", str(self.vault), "--verify")
        self.assertEqual(vdata["orphans_remaining"], vdata["orphans_remaining_private"])

    def test_report_never_contains_private_names_or_content(self):
        report = self.tmp / "r.json"
        code, data, text = run_cli(*self.args("--report", str(report), "--include-private", "--git-exclude-private"))
        blob = text + report.read_text(encoding="utf-8")
        for needle in (PRIVATE_SECRET, "diary", "dup", "한글 노트", "weird"):
            self.assertNotIn(needle, blob)

    def test_tool_does_not_touch_obsidian_config(self):
        before = snapshot_tree(self.vault / ".obsidian")
        run_cli(*self.args("--apply"))
        self.assertEqual(before, snapshot_tree(self.vault / ".obsidian"))


@unittest.skipUnless(shutil.which("git"), "git not available")
class GitPrivateTests(VaultCase):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=self.tmp, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=self.tmp, check=True)

    def test_private_hubs_written_only_when_git_ignored(self):
        args = ["--vault", str(self.vault), "--backup-root", str(self.backup), "--apply", "--include-private", "--keep-inferred"]
        run_cli(*args)                                           # not ignored -> skipped
        self.assertFalse((self.vault / "Navigation" / "_private").exists())
        code, data, _ = run_cli(*args, "--git-exclude-private")
        self.assertEqual(code, 0)
        self.assertTrue((self.vault / "Navigation" / "_private").is_dir())
        status = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=self.tmp,
                                capture_output=True, text=True, encoding="utf-8").stdout
        self.assertNotIn("_private", status)                     # nothing private would be staged
        self.assertIn("Navigation/", status)                     # public hubs still visible to git
        code, vdata, _ = run_cli("--vault", str(self.vault), "--verify")
        self.assertEqual(vdata["orphans_remaining"], 0)
        self.assertEqual(vdata["orphans_remaining_attachments"], 0)
        self.assertEqual(vdata["links"]["components"], 1)
        self.assertEqual(vdata["links"]["nodes_outside_largest_component"], 0)
        # the local exclude entry is idempotent
        run_cli(*args, "--git-exclude-private")
        excl = (self.tmp / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertEqual(excl.count("/vault/Navigation/_private/"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
