"""Stage operator-supplied billing proof without trusting it or exposing secrets.

This bootstrap only parses the secret JSON. The shared adapter independently
validates API-key/org binding, billing safety, balance, and proof freshness.
Missing, malformed, or unwritable proof is a non-failing local-fallback marker.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def reject_constant(_value):
    raise ValueError("non-standard JSON constant")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def main():
    target = None
    try:
        runner_temp = os.environ.get("RUNNER_TEMP", "")
        declared = os.environ.get("TYPESAFE_BILLING_PROOF_PATH", "")
        if not runner_temp or not declared:
            raise ValueError("missing runner-temp path")
        temp_root = Path(runner_temp)
        candidate = Path(declared)
        if not temp_root.is_absolute() or not candidate.is_absolute():
            raise ValueError("absolute runner-temp path required")
        if candidate.name != "typesafe-billing-proof.json" or candidate.parent.resolve() != temp_root.resolve():
            raise ValueError("proof path must be the declared runner-temp file")
        target = candidate
        # Remove stale proof before parsing. Never retain a previous valid file.
        target.unlink(missing_ok=True)
        raw = os.environ.get("TYPESAFE_BILLING_PROOF_JSON", "")
        proof = json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_object)
        if not isinstance(proof, dict) or not proof:
            raise ValueError("proof must be a nonempty JSON object")
        encoded = json.dumps(proof, ensure_ascii=False, allow_nan=False) + "\n"
        # Exclusive creation avoids following a stale symlink; no extra proof files.
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
        # All main-publish consumers restore the latest successful OR failed
        # run's budget receipt before any inference. Missing evidence fails closed.
        if os.environ.get("GITHUB_ACTIONS") == "true":
            restore = subprocess.run([sys.executable, str(Path(__file__).with_name("restore_typesafe_receipt.py"))],
                                     capture_output=True, text=True, timeout=180)
            if restore.returncode != 0:
                raise ValueError("allowance receipt not verified")
        print("TypeSafe proof staged; adapter validation remains required.")
    except Exception:
        if target is not None:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        # No exception text, paths, JSON, API keys, or identity values in logs.
        print("TypeSafe proof unavailable; safe local fallback.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
