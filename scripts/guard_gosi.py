"""
guard_gosi.py - 화장품 고시 보호 가드
- 루트 수집기 3종이 화장품 고시를 덮었는지 검사
- 덮였으면 직전 정상 커밋에서 복구, 복구 못하면 exit 1로 중단
- 시작 시점 상태 기록용으로도 사용

data/daiso_real/daiso_gosi.json = MoCRA 신고용 화장품 고시 (14건+ 유지해야 함)
data/civil_service_gosi.json = 공무원 시험 공고 (gosi_collector 전용)
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
    """화장품 고시가 망가졌는지 검사"""
    data = load_json_safe(COSMETIC_GOSI)
    if data is None:
        print(f"⚠️ 화장품 고시 없음: {COSMETIC_GOSI}")
        return False, "missing"
    
    # 구조 검사 - daiso_real은 items 또는 dict 형태
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
    
    # 14건 미만이면 덮인 것으로 간주
    if count < 5:  # 14건이어야 하는데 1건이면 덮인 것
        print(f"❌ 화장품 고시 손상 감지: {count}건 (기대 14건+)")
        return False, f"damaged_count_{count}"
    
    print(f"✅ 화장품 고시 정상: {count}건")
    return True, f"ok_{count}"

def restore_from_last_good():
    """직전 정상 커밋에서 복구"""
    try:
        # git log에서 daiso_gosi.json이 정상이던 커밋 찾기
        result = subprocess.run(
            ["git", "log", "--oneline", "--follow", "--", str(COSMETIC_GOSI)],
            capture_output=True, text=True, cwd=ROOT
        )
        commits = result.stdout.strip().split("\n")[:10]
        
        for commit_line in commits:
            if not commit_line.strip():
                continue
            commit_hash = commit_line.split()[0]
            # 해당 커밋에서 파일 내용 가져오기
            show_result = subprocess.run(
                ["git", "show", f"{commit_hash}:{COSMETIC_GOSI.relative_to(ROOT)}"],
                capture_output=True, text=True, cwd=ROOT
            )
            if show_result.returncode == 0 and show_result.stdout:
                try:
                    data = json.loads(show_result.stdout)
                    # 정상인지 검사
                    if isinstance(data, dict):
                        items = data.get("items", data)
                        count = len(items) if isinstance(items, (dict, list)) else 0
                        if count >= 5:
                            # 복구
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
        # 시작 시점 상태 기록
        is_ok, status = check_cosmetic_gosi()
        log = {
            "checked_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "cosmetic_gosi_path": str(COSMETIC_GOSI.relative_to(ROOT)),
            "status": status,
            "is_ok": is_ok
        }
        try:
            GUARD_LOG.parent.mkdir(parents=True, exist_ok=True)
            GUARD_LOG.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"📝 시작 상태 기록: {GUARD_LOG}")
        except Exception as e:
            print(f"⚠️ 로그 기록 실패: {e}")
        return
    
    # --restore 모드: 덮였으면 복구, 못 하면 중단
    is_ok, status = check_cosmetic_gosi()
    if is_ok:
        print("✅ 화장품 고시 보호: 정상 - 커밋 진행")
        return
    
    print(f"🚨 화장품 고시 보호: 손상 감지 ({status}) - 복구 시도")
    if restore_from_last_good():
        print("✅ 복구 성공 - 커밋 진행")
        return
    else:
        print("❌ 복구 실패 - 워크플로 중단 (망가진 채로 올리지 않음)")
        sys.exit(1)

if __name__ == "__main__":
    main()
