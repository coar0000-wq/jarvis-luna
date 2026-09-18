#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "data" / "daiso_real" / "daiso_gosi.json"


def load_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def restore_from_git():
    try:
        commits = subprocess.check_output(
            [
                "git",
                "log",
                "--pretty=format:%H",
                "--",
                "data/daiso_real/daiso_gosi.json",
            ],
            text=True,
        ).splitlines()

        for commit in commits:
            try:
                content = subprocess.check_output(
                    [
                        "git",
                        "show",
                        f"{commit}:data/daiso_real/daiso_gosi.json",
                    ],
                    text=True,
                )

                data = json.loads(content)

                TARGET.parent.mkdir(parents=True, exist_ok=True)

                with open(TARGET, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

                print(f"복구 성공 : {commit[:7]}")
                return True

            except Exception:
                continue

    except Exception:
        pass

    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()

    TARGET.parent.mkdir(parents=True, exist_ok=True)

    if not TARGET.exists():
        print(f"⚠️ 화장품 고시 없음: {TARGET}")

        if args.restore:
            print("🚨 복구 시도")

            if restore_from_git():
                return

            with open(TARGET, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=2)

            print("🆕 빈 고시 파일 생성")
            return

        sys.exit(1)

    data = load_json(TARGET)

    if data is None:
        print("🚨 JSON 손상")

        if args.restore and restore_from_git():
            return

        with open(TARGET, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)

        print("🆕 새 JSON 생성")
        return

    print(f"✅ GOSI 보호 통과 ({len(data)}개)")


if __name__ == "__main__":
    main()
