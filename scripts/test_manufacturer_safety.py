"""Offline synthetic receipts only; no production approval is created."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import manufacturer_safety as ms


def synthetic_receipt(root, pd_no="1"):
    """Real temporary fixture files, explicitly fictional qualified review."""
    manual = Path(root) / "data/manual"
    manual.mkdir(parents=True, exist_ok=True)
    dossier = b"SYNTHETIC TEST ONLY: formula-specific safety dossier; not production evidence."
    adequacy = b"SYNTHETIC TEST ONLY: completed qualified adequacy assessment; not an approval."
    (manual / "synthetic-dossier.txt").write_bytes(dossier)
    (manual / "synthetic-adequacy.txt").write_bytes(adequacy)
    scope = {"scope_type": "exact_product_formula", "pd_nos": [pd_no], "formula_id": "SYNTHETIC-FORMULA-1"}
    sha = hashlib.sha256(dossier).hexdigest()
    return {"document_type": "qualified_safety_dossier", "scope": scope,
            "file": "data/manual/synthetic-dossier.txt", "sha256": sha,
            "manual_review": {"method": "manual", "disposition": "adequate", "reviewer_qualified": True,
                              "reviewed_by": "SYNTHETIC-REVIEWER-NOT-A-REAL-APPROVAL", "reviewed_at": "2026-01-01",
                              "document_sha256": sha, "scope": copy.deepcopy(scope),
                              "adequacy_type": "product_safety_substantiation",
                              "adequacy_file": "data/manual/synthetic-adequacy.txt",
                              "adequacy_sha256": hashlib.sha256(adequacy).hexdigest()}}


class ManufacturerSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.record = synthetic_receipt(self.root)
        self.public = self.root / "data/manual/mocra_business.json"
        self.public.write_text(json.dumps({"safety_substantiation": {"covered_pd_nos": ["1"]}}), encoding="utf-8")
        self.ledger = self.root / "data/manual/manufacturer_safety_evidence.private.json"

    def install(self, record=None):
        self.ledger.write_text(json.dumps({"schema_version": 1, "records": [record if record is not None else self.record]}), encoding="utf-8")

    def result(self, pd_no="1"):
        return ms.manufacturer_safety_record(pd_no, self.root)

    def test_scoped_real_files_and_manual_adequacy_receipt_pass_without_signed_report(self):
        self.install()
        out = self.result()
        self.assertTrue(out["covered"])
        self.assertIsNone(out["reason"])
        self.assertTrue(self.result(1)["covered"])
        self.assertFalse(self.result("2")["covered"])
        self.assertNotIn("SYNTHETIC-REVIEWER", json.dumps(out))
        self.assertNotIn("synthetic-dossier.txt", json.dumps(out))
        self.assertNotIn("SYNTHETIC-FORMULA", json.dumps(out))
        self.assertEqual(len(ms.public_view(out)["evidence_digest"]), 64)

    def test_declared_status_verified_owner_future_promise_never_pass(self):
        self.public.write_text(json.dumps({"safety_substantiation": {"covered_pd_nos": ["1"],
            "status": "검증완료", "verified_by": "사업주", "basis": "판매 발생 시 사업주가 실제 자료를 확보해 보관한다"}}), encoding="utf-8")
        self.assertFalse(self.result()["covered"])
        self.assertIn("scoped_evidence_missing", self.result()["reason"])

    def test_missing_hash_mismatch_and_review_file_changes_fail_closed(self):
        self.install()
        dossier = self.root / self.record["file"]
        dossier.write_bytes(b"changed")
        self.assertIn("file_hash_mismatch", self.result()["reason"])
        dossier.unlink()
        self.assertIn("file_missing", self.result()["reason"])
        self.record = synthetic_receipt(self.root)
        self.install()
        (self.root / self.record["manual_review"]["adequacy_file"]).unlink()
        self.assertIn("adequacy_file_missing", self.result()["reason"])

    def test_reject_inadequate_unspecific_marketing_future_review_and_bad_privacy_inputs(self):
        mutations = [lambda r: r.update(document_type="marketing_summary"),
            lambda r: r.update(document_type=[]), lambda r: r.update(scope={}),
            lambda r: r["scope"].update(pd_nos=["2"]), lambda r: r["scope"].update(pd_nos=[True]),
            lambda r: r["scope"].update(formula_id=""), lambda r: r.update(file="../PRIVATE-SECRET"),
            lambda r: r.update(file="https://SECRET.example/doc"), lambda r: r.update(sha256=False),
            lambda r: r.update(manual_review={}), lambda r: r["manual_review"].update(disposition="pending"),
            lambda r: r["manual_review"].update(reviewed_at="2999-01-01"),
            lambda r: r["manual_review"].update(reviewer_qualified="true"),
            lambda r: r["manual_review"]["scope"].update(formula_id="OTHER-FORMULA"),
            lambda r: r["manual_review"].update(adequacy_type="marketing_summary"),
            lambda r: r["manual_review"].update(adequacy_sha256="a"*64)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                record = copy.deepcopy(self.record)
                mutate(record)
                self.install(record)
                out = self.result()
                self.assertFalse(out["covered"])
                self.assertNotIn("SECRET", json.dumps(out))
                self.assertNotIn("OTHER-FORMULA", json.dumps(out))
        for bad_id in (None, True, False, [], {}, 1.0):
            self.assertFalse(self.result(bad_id)["covered"])

    def test_still_valid_receipt_and_file_changes_change_masked_digest(self):
        self.install()
        before = ms.public_view(self.result())
        self.record["manual_review"]["reviewed_at"] = "2026-02-01"
        self.install()
        after = ms.public_view(self.result())
        self.assertTrue(after["covered"])
        self.assertNotEqual(before, after)
        file = self.root / self.record["manual_review"]["adequacy_file"]
        file.write_bytes(b"SYNTHETIC TEST revised adequate review")
        self.record["manual_review"]["adequacy_sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
        self.install()
        self.assertTrue(self.result()["covered"])
        self.assertNotEqual(after, ms.public_view(self.result()))

    def test_corrupt_ledger_cannot_fall_back_to_profile(self):
        self.ledger.write_text("{broken", encoding="utf-8")
        self.assertFalse(self.result()["covered"])
        self.ledger.write_text('{"schema_version":true,"records":[]}', encoding="utf-8")
        self.assertFalse(self.result()["covered"])

if __name__ == "__main__":
    unittest.main()
