"""
guard_gosi.py v4 - 최종 수정본 (missing이면 중단 안함)

- 이전 v2 문제: daiso_real/daiso_gosi.json이 없으면 missing으로 exit 1 -> 워크플로 실패
- v4 수정:
  1. check_cosmetic_gosi()가 count도 반환 (is_ok, status, count)
  2. --restore 모드에서 missing이면 복구 시도, 실패해도 경고만 하고 exit 0 (inci_converter가 새로 만들게)
  3. damaged_count(1건으로 덮인 경우)에만 exit 1로 차단
"""
import json
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
COSMETIC_GOSI = ROOT / "data" / "daiso_real" / "daiso_gosi.json"
CIVIL_GOSI = ROOT / "data" / "civil_service_gosi.json"
GUARD_LOG = ROOT / "data" / "guard_gosi_log.json"

def load_json_safe(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except:
        return None

def check_cosmetic_gosi():
    data = load_json_safe(COSMETIC_GOSI)
    if data is None:
        print(f"⚠️ 화장품 고시 없음: {COSMETIC_GOSI}")
        return False, "missing", 0
    
    if isinstance(data, dict):
        items = data.get("items", data)
        if isinstance(items, dict):
            count = len(items)
        elif isinstance(items, list):
            count = len(items)
        else:
            count = 0
    elif isinstance(data, list):
        count = len(data)
    else:
        count = 0
    
    if count < 5:
        print(f"❌ 화장품 고시 손상 감지: {count}건 (기대 14건+)")
        return False, f"damaged_count_{count}", count
    
    print(f"✅ 화장품 고시 정상: {count}건")
    return True, f"ok_{count}", count

def restore_from_last_good():
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--follow", "--", str(COSMETIC_GOSI)],
            capture_output=True, text=True, cwd=ROOT
        )
        commits = result.stdout.strip().split("\n")[:15]
        
        for commit_line in commits:
            if not commit_line.strip():
                continue
            commit_hash = commit_line.split()[0]
            show_result = subprocess.run(
                ["git", "show", f"{commit_hash}:{COSMETIC_GOSI.relative_to(ROOT)}"],
                capture_output=True, text=True, cwd=ROOT
            )
            if show_result.returncode == 0 and show_result.stdout:
                try:
                    data = json.loads(show_result.stdout)
                    if isinstance(data, dict):
                        items = data.get("items", data)
                        count = len(items) if isinstance(items, (dict, list)) else 0
                        if count >= 5:
                            COSMETIC_GOSI.parent.mkdir(parents=True, exist_ok=True)
                            COSMETIC_GOSI.write_text(show_result.stdout, encoding="utf-8")
                            print(f"✅ 화장품 고시 복구 완료: {commit_hash}에서 {count}건 복원")
                            return True
                except:
                    continue
        
        print("❌ 복구할 정상 커밋을 찾지 못함")
        return False
    except Exception as e:
        print(f"❌ 복구 실패: {e}")
        return False

def main():
    is_restore = "--restore" in sys.argv
    
    if not is_restore:
        is_ok, status, count = check_cosmetic_gosi()
        log = {
            "checked_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "cosmetic_gosi_path": str(COSMETIC_GOSI.relative_to(ROOT)),
            "status": status,
            "count": count,
            "is_ok": is_ok
        }
        try:
            GUARD_LOG.parent.mkdir(parents=True, exist_ok=True)
            GUARD_LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"📝 시작 상태 기록: {GUARD_LOG} - {status} ({count}건)")
        except Exception as e:
            print(f"⚠️ 로그 기록 실패: {e}")
        return
    
    is_ok, status, count = check_cosmetic_gosi()
    if is_ok:
        print(f"✅ 화장품 고시 보호: 정상 {count}건 - 커밋 진행")
        return
    
    print(f"🚨 화장품 고시 상태: {status} ({count}건)")
    
    if status == "missing":
        print("⚠️ 화장품 고시 파일 없음 - 복구 시도")
        if restore_from_last_good():
            print("✅ 복구 성공 - 커밋 진행")
            return
        else:
            print("⚠️ 복구할 커밋 없음 - inci_converter가 새로 생성할 것으로 예상, 경고만 하고 진행")
            print("::warning::화장품 고시 파일이 없어서 새로 생성됩니다. gosi-vision이 14건을 채울 예정")
            return
    
    print(f"🚨 화장품 고시 손상 감지: {count}건 - 복구 시도")
    if restore_from_last_good():
        print("✅ 복구 성공 - 커밋 진행")
        return
    else:
        print("❌ 복구 실패 - 망가진 채로 올리지 않음")
        sys.exit(1)

if __name__ == "__main__":
    main()
