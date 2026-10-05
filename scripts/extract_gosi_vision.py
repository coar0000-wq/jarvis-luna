#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""고시 이미지를 Gemini 비전으로 읽어 gosi.json 을 채운다.

용량과 전성분은 다이소 API 어디에도 텍스트로 없다. 상세 이미지 안에
인쇄되어 있다. 그 이미지를 모델이 읽어 표를 그대로 옮긴다.

지어내는 것과 읽는 것은 다르다. 여기서 하는 일은 읽기다. 다만 오독은
있을 수 있으므로 다음을 지킨다.
  - 표에 없는 항목은 빈 문자열로 둔다. 모델에게도 그렇게 지시한다.
  - 결과마다 source 와 verified 를 남긴다. verified 는 사람이 켠다.
  - 원본 이미지 경로를 함께 남겨 언제든 대조할 수 있게 한다.
  - 사람이 이미 채운 값은 덮어쓰지 않는다.
  - 상세 이미지가 여러 장이면 필수 4항목이 찰 때까지 순서대로 읽는다.
"""
from __future__ import annotations

import base64
import sys
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.gosi_observation_history import validate_document, attempt, observe_field, mark_stale, publish_observation, sha, receipt, utcnow, ProviderStop, classify_stop, assert_not_stopped, persist_stop

class DeadlineStop(RuntimeError):
    pass

DEADLINE = None

def call_timeout():
    if DEADLINE is None:
        return TIMEOUT
    remaining = DEADLINE - time.monotonic()
    if remaining <= 0:
        raise DeadlineStop('vision deadline exhausted')
    return min(TIMEOUT, remaining)

GOSI = ROOT / "data" / "gosi.json"
API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT = 120
DELAY = 3.0
# 워크플로 전체 한도가 60분인데 비전 한 단계가 39분을 먹은 적이 있다.
# 예산을 넘으면 남은 건 다음 회차로 넘긴다. 미룰 뿐 빠뜨리지 않는다.
BUDGET_SEC = float(os.environ.get("VISION_BUDGET_SEC") or 720)
FIELDS = (
    "volume", "ingredients", "maker", "origin", "warnings",
    "expiry", "functional",
)
NEED = ("ingredients", "volume", "maker", "origin")

PROMPT = """이 이미지는 한국 화장품의 '상품정보 제공고시' 표이거나 그 일부가 담긴 상세 이미지입니다.
표(또는 이미지)에 적힌 내용을 그대로 옮겨 JSON 으로만 답하세요.

{
  "volume": "내용물의 용량 또는 중량",
  "ingredients": "화장품법에 따라 기재해야 하는 모든 성분 전체",
  "maker": "화장품제조업자 및 책임판매업자",
  "origin": "제조국",
  "warnings": "사용할 때의 주의사항",
  "expiry": "사용기한 또는 개봉 후 사용기간",
  "functional": "기능성 화장품 여부"
}

규칙
- 표에 그 항목이 없거나 읽을 수 없으면 빈 문자열 "" 로 두세요.
- 요약하거나 정리하지 마세요. 특히 전성분은 하나도 빠뜨리지 말고
  쉼표까지 원문 그대로 옮기세요.
- 추측해서 채우지 마세요. 보이는 글자만 옮기세요.
- 마케팅 문구만 있고 고시 표가 없으면 모든 값을 "" 로 두세요.
- JSON 외에 다른 말을 붙이지 마세요.
{target}"""

# 한 이미지에 여러 상품의 고시 표가 연이어 들어 있는 경우가 있다.
#
# 2026-09-16 셀더마데일리 마스크 1042619 의 상세 이미지에는
# 바로 위에 품번 1042615(히알루) 표가 같이 있었다. 둘은 전성분이
# 다르다. 품번을 안 짚어주면 옆 상품 표를 옮겨 적을 수 있다.
# 그것은 미국 라벨과 법률 검토의 원천 자료가 틀리는 일이라 그냥 둘 수 없다.
TARGET_HINT = """
- 이 이미지에 품번(상품번호)가 다른 표가 여럿 개 있을 수 있습니다.
  반드시 품번이 {pd_no} 인 표만 옮기세요.
- 품번이 {pd_no} 인 표가 이 이미지에 없으면 모든 값을 "" 로 두세요.
  다른 품번의 표를 대신 옮기지 마세요."""


def http_json(url, payload=None):
    data = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=data, method='POST' if payload else 'GET', headers={'Content-Type': 'application/json'})
    try:
        raw = urllib.request.urlopen(req, timeout=call_timeout()).read()
        evidence = receipt(raw, url.split('?')[0], 'provider_response_only')
        result = json.loads(raw.decode('utf-8'))
        stop = classify_stop(json.dumps(result.get('error') or {}), 'gemini')
        if stop: raise stop
        result['_receipt'] = evidence
        return result
    except (ProviderStop, DeadlineStop):
        raise
    except Exception as exc:
        stop = classify_stop(exc, 'gemini')
        if stop: raise stop from exc
        raise RuntimeError(f'gemini request failed: {type(exc).__name__}') from exc


def pick_models(key: str) -> list[str]:
    """사용 가능한 비전 모델만 고른다.

    2026-09-12 실측: gemini-2.5-flash-lite 는 HTTP 404
    (no longer available). lite / discontinued 는 제외한다.
    """
    forced = os.environ.get("GEMINI_MODEL", "").strip()
    if forced:
        return [forced]

    fallback = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-001",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]
    try:
        d = http_json(f"{API_ROOT}/models?key={key}&pageSize=200")
    except (ProviderStop, DeadlineStop):
        raise
    except Exception as exc:
        print(f"모델 목록 조회 실패: {type(exc).__name__} → fallback 사용")
        return fallback

    usable = [
        m["name"].replace("models/", "")
        for m in d.get("models", [])
        if "generateContent" in (m.get("supportedGenerationMethods") or [])
    ]
    # 2026-09-16: 골라진 후보가 이렇게 나왔다.
    #   gemini-flash-latest, gemini-2.5-flash,
    #   gemini-2.5-flash-preview-tts, gemini-2.5-flash-image
    #
    # 뒤의 둘은 표를 읽는 모델이 아니다. tts 는 음성이고
    # -image 는 그림을 만드는 쪽이다. 둘 다 generateContent 를
    # 지원한다고 나오기 때문에 걸러지지 않았다.
    # 쓸데없는 호출로 할당량을 태우고 429 를 받았다.
    ban = ("lite", "discontinued", "vision-exp", "1.0",
           "tts", "-image", "embedding", "audio", "live", "learnlm")
    usable = [n for n in usable if not any(b in n.lower() for b in ban)]

    order, seen = [], set()
    for pat in (
        "2.0-flash", "flash-latest", "1.5-flash",
        "2.5-flash", "2.0-pro", "1.5-pro", "pro",
    ):
        for name in usable:
            low = name.lower()
            if pat in low and name not in seen:
                if "lite" in low:
                    continue
                order.append(name)
                seen.add(name)
    return (order[:4] or usable[:3] or fallback)


def mime_of(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".png":
        return "image/png"
    if suf in (".webp",):
        return "image/webp"
    return "image/jpeg"


# Groq is an optional provider, never a quota/auth stop bypass.
#
# 2026-09-19 사용자가 말했다. "다이소에는 고시표가 무조건 있는데
# 네가 못찾는건데 없다고 하니". 맞다. 그날 1072554 · 1053482 두 건은
# 고시가 없어서 가 아니라 Gemini 할당량 429 로 판독을 못 해서 비어 있었다.
# 사람이 직접 열어보면 둘 다 상세 이미지 맨 아래에 표가 있었다.
#
# Any auth/quota stop terminates this run and is persisted.
# Only ordinary non-circuit failures may use the optional provider.
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = [
    m.strip() for m in os.environ.get(
        "GROQ_VISION_MODELS",
        "meta-llama/llama-4-maverick-17b-128e-instruct,"
        "meta-llama/llama-4-scout-17b-16e-instruct").split(",") if m.strip()
]


def groq_key() -> str:
    for name in ("GROQ_API_KEY", "GROQ_API_KEY_LUNA"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


# Groq 은 base64 인라인 이미지를 4MB 까지만 받는다.
# 고시 조각은 860x3000 급이라 그대로 보내면 넘길 수 있다.
GROQ_MAX_B64 = 3_500_000


def shrink_for_groq(img: Path) -> bytes:
    raw = img.read_bytes()
    if len(base64.b64encode(raw)) <= GROQ_MAX_B64:
        return raw
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        return raw
    import io  # noqa: PLC0415

    with Image.open(img) as im:
        im = im.convert("RGB")
        for quality in (85, 70, 55):
            for scale in (1.0, 0.8, 0.6):
                buf = io.BytesIO()
                work = im if scale == 1.0 else im.resize(
                    (max(1, int(im.width * scale)), max(1, int(im.height * scale))))
                work.save(buf, format="JPEG", quality=quality, optimize=True)
                data = buf.getvalue()
                if len(base64.b64encode(data)) <= GROQ_MAX_B64:
                    return data
    return raw


def read_table_groq(key: str, img: Path, prompt: str) -> tuple[dict | None, str]:
    """Groq 비전 모델로 같은 표를 읽는다. 응답 형식은 Gemini 경로와 같다."""
    payload_bytes = shrink_for_groq(img)
    b64 = base64.b64encode(payload_bytes).decode()
    data_url = f"data:image/jpeg;base64,{b64}"
    last = ""
    for model in GROQ_MODELS:
        payload = {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
        }
        try:
            req = urllib.request.Request(
                GROQ_URL, data=json.dumps(payload).encode(), method="POST",
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {key}"})
            raw = urllib.request.urlopen(req, timeout=call_timeout()).read()
            evidence = receipt(raw, 'groq', 'provider_response_only')
            result = json.loads(raw.decode('utf-8'))
            stop = classify_stop(json.dumps(result.get('error') or {}), 'groq')
            if stop: raise stop
            txt = result['choices'][0]['message']['content']
        except (ProviderStop, DeadlineStop):
            raise
        except urllib.error.HTTPError as exc:
            stop = classify_stop(exc, 'groq')
            if stop: raise stop from exc
            detail = exc.read().decode("utf-8", "replace")[:120]
            last = f"groq {model} HTTP {exc.code}: {detail}"
            continue
        except Exception as exc:  # noqa: BLE001
            stop = classify_stop(exc, 'groq')
            if stop: raise stop from exc
            last = f'groq {model} {type(exc).__name__}'
            continue

        txt = re.sub(r"^```(?:json)?|```$", "", str(txt).strip(), flags=re.M).strip()
        try:
            parsed = json.loads(txt)
        except json.JSONDecodeError:
            last = f"groq {model} JSON 파싱 실패"
            continue
        if not isinstance(parsed, dict):
            last = f"groq {model} JSON 객체가 아님"
            continue
        parsed["_model"] = f"groq:{model}"
        parsed["_provenance"] = dict(evidence, model=f"groq:{model}", payload_image_sha256=sha(payload_bytes), payload_image_byte_count=len(payload_bytes))
        return parsed, ""
    return None, last or "groq 호출 실패"


def read_table(key: str, models: list[str], img: Path,
               pd_no: str = "") -> tuple[dict | None, str]:
    """이미지 한 장을 읽는다. Auth/quota stops propagate without retry.

    pd_no 를 주면 그 품번의 표만 옮기라고 모델에게 명시한다.
    """
    # str.format 을 쓰면 안 된다.
    #
    # PROMPT 안에 응답 예시 JSON 이 들어 있고 그 중괄호를 format 이
    # 치환 자리로 읽는다. 2026-09-16 에 품번 지정을 넣으면서 format 을
    # 썼다가 이렇게 터졌다.
    #   KeyError: '\n  "volume"'
    # 그 바람에 gosi-vision 이 통째로 죽었고, 새로 S등급이 된 1049285 의
    # 고시가 채워지지 않았다. 중괄호를 건드리지 않는 replace 로 바꾼다.
    hint = TARGET_HINT.replace("{pd_no}", pd_no) if pd_no else ""
    prompt = PROMPT.replace("{target}", hint)
    b64 = base64.b64encode(img.read_bytes()).decode()
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_of(img), "data": b64}},
            ]
        }],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    last = ""
    d = None
    used = ""
    for model in models:
        try:
            d = http_json(f'{API_ROOT}/models/{model}:generateContent?key={key}', payload)
            used = model
            break
        except (ProviderStop, DeadlineStop):
            raise
        except Exception as exc:
            stop = classify_stop(exc, 'gemini')
            if stop:
                raise stop from exc
            last = f'{model} {type(exc).__name__}'
    if d is None:
        # Gemini 가 다 막혔다. 그렇다고 "고시 없음"으로 넘기지 않는다.
        gk = groq_key()
        if gk:
            parsed, gerr = read_table_groq(gk, img, prompt)
            if parsed is not None:
                return parsed, ""
            # 대체 경로 사유를 앞에 둔다. Gemini 429 본문이 길어서
            # 뒤에 붙이면 화면에서 잘려 진짜 이유가 안 보였다.
            return None, f"{gerr} | gemini: {(last or '')[:60]}"
        return None, last or "호출 실패"
    try:
        txt = d["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return None, "응답에 텍스트가 없음"
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    try:
        parsed = json.loads(txt)
        if not isinstance(parsed, dict):
            return None, "JSON 객체가 아님"
        parsed["_model"] = used
        parsed["_provenance"] = dict(d.get("_receipt", {}), model=used, payload_image_sha256=sha(img.read_bytes()), payload_image_byte_count=img.stat().st_size)
        return parsed, ""
    except json.JSONDecodeError:
        return None, "JSON 파싱 실패"


def image_candidates(row: dict) -> list[Path]:
    """gosi_images → gosi_image 순으로 존재하는 파일만."""
    paths: list[Path] = []
    seen: set[str] = set()
    for key in ("gosi_images", "detail_image_paths"):
        for item in row.get(key) or []:
            s = str(item).strip()
            if not s or s in seen:
                continue
            seen.add(s)
            paths.append(ROOT / s)
    single = str(row.get("gosi_image") or "").strip()
    if single and single not in seen:
        paths.append(ROOT / single)
    return [p for p in paths if p.exists() and p.stat().st_size > 500]


# 세로로 긴 상세 이미지를 조각내는 기준
#
# 2026-09-16 VT 리들샷 300(1049276) 의 상세 이미지는 850 x 22,534 였다.
# 통째로 보내면 모델이 받을 크기로 줄이는데, 그러면 세로가 27배
# 압축되어 맨 아래 전성분 글자가 뭉개진다. 읽힌 것처럼 보이지만
# 실제로는 읽을 수 없는 픽셀을 보낸 것이다.
#
# 고시 표는 항상 상세 이미지 "맨 아래" 에 있다. 그래서 아래쪽부터
# 조각을 내서 보낸다. 조각 하나는 가로폭의 1.6배 높이로 잡아
# 글자가 무너지지 않는 비율을 유지한다.
TALL_RATIO = 2.5
SLICE_OVERLAP = 0.15
SLICES_PER_IMAGE = 3
MAX_CANDIDATES = 6
SLICE_DIR = ROOT / "data" / "daiso_real" / "gosi_slice"


def tall_slices(img: Path) -> list[Path]:
    """긴 이미지를 아래쪽부터 조각낸다. 짧으면 원본 그대로 돌려준다."""
    try:
        from PIL import Image
    except ImportError:
        print("  (Pillow 없음 - 원본 그대로 보낸다)")
        return [img]

    try:
        with Image.open(img) as im:
            w, h = im.size
            if h <= w * TALL_RATIO:
                return [img]

            step = max(int(w * 1.6), 900)
            back = int(step * SLICE_OVERLAP)
            SLICE_DIR.mkdir(parents=True, exist_ok=True)

            out: list[Path] = []
            bottom = h
            while bottom > 0 and len(out) < SLICES_PER_IMAGE:
                top = max(0, bottom - step)
                dest = SLICE_DIR / f"{img.stem}_b{len(out)}.jpg"
                im.crop((0, top, w, bottom)).convert("RGB").save(
                    dest, "JPEG", quality=88)
                out.append(dest)
                if top == 0:
                    break
                bottom = top + back
            print(f"  {img.name} {w}x{h} → 아래쪽 조각 {len(out)}장")
            return out
    except Exception as exc:                                   # noqa: BLE001
        print(f"  조각내기 실패({img.name}): {type(exc).__name__}: {exc}")
        return [img]


CANDIDATE_ORIGINS = {}

def ordered_candidates(imgs: list[Path]) -> list[Path]:
    """볼 순서를 정한다.

    고시 표는 마지막 상세 이미지의 맨 아래에 있다. 그러니
    마지막 이미지부터, 각 이미지 안에서는 아래 조각부터 본다.
    호출 수는 MAX_CANDIDATES 로 막는다. 예산을 지키기 위해서다.
    """
    out: list[Path] = []
    for img in reversed(imgs):
        for piece in tall_slices(img):
            CANDIDATE_ORIGINS[str(piece)] = img
            out.append(piece)
            if len(out) >= MAX_CANDIDATES:
                return out
    return out


def needs_fill(row: dict) -> bool:
    return not all(str(row.get(f) or "").strip() for f in NEED)


def apply_vision(row, got, img, pd_no):
    original = CANDIDATE_ORIGINS.get(str(img), img)
    original_raw = original.read_bytes()
    image_path = str(original.relative_to(ROOT))
    source = row.get('image_observations', {}).get(image_path, {})
    source_matches = source.get('sha256') == sha(original_raw)
    evidence = dict(got.get('_provenance') or {}, source_image=image_path,
                    source_image_sha256=sha(original_raw), source_image_byte_count=len(original_raw),
                    source_received_at=source.get('received_at') if source_matches else None,
                    capture_scope='single_image_or_crop_model_transcription',
                    intended_product_id=pd_no, product_identity_verified=False,
                    human_verified=False, image=str(img.relative_to(ROOT)))
    return [f for f in FIELDS if isinstance(got.get(f), str) and
            got[f].strip() not in {'', '-', '상세페이지 참조', '상세 페이지 참조'} and
            observe_field(row, f, got[f], evidence)]

def main() -> int:
    doc = json.loads(GOSI.read_text(encoding='utf-8-sig'))
    items = validate_document(doc)
    try:
        assert_not_stopped(doc, {'gemini', 'groq'})
    except ProviderStop as exc:
        print(str(exc))
        return 0
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    todo = {k: r for k, r in items.items() if needs_fill(r)}
    if not todo or (not key and not groq_key()):
        # No calls, no fresh collection clocks or new missing-fact claims.
        return 0
    global DEADLINE
    DEADLINE = time.monotonic() + BUDGET_SEC
    fails, deferred, stopped = [], [], False
    try:
        models = pick_models(key) if key else []
        for pd_no, row in todo.items():
            if stopped or time.monotonic() >= DEADLINE:
                deferred.append(pd_no)
                continue
            imgs = image_candidates(row)
            if not imgs:
                attempt(row, utcnow(), 'vision', 'unavailable', reason='local_image_not_available', capture_scope='local_inventory_only')
                continue
            for img in ordered_candidates(imgs):
                if not needs_fill(row):
                    break
                when = utcnow()
                try:
                    got, err = read_table(key, models, img, pd_no)
                except ProviderStop as exc:
                    persist_stop(doc, exc)
                    attempt(row, when, 'vision', 'stopped', reason=str(exc))
                    mark_stale(row)
                    stopped = True
                    deferred.append(pd_no)
                    break
                except DeadlineStop:
                    deferred.append(pd_no)
                    stopped = True
                    break
                attempt(row, when, 'vision', 'received' if got else 'failed', image=str(img.relative_to(ROOT)), reason=err, capture_scope='candidate_image_only')
                if got:
                    apply_vision(row, got, img, pd_no)
                else:
                    mark_stale(row)
                    fails.append({'pd_no': pd_no, 'reason': err})
                if time.monotonic() + DELAY >= DEADLINE:
                    break
                time.sleep(DELAY)
    except ProviderStop as exc:
        persist_stop(doc, exc)
        deferred.extend(todo)
        stopped = True
    except DeadlineStop:
        deferred.extend(todo)
        stopped = True
    doc['vision_failures'] = fails
    doc['vision_deferred'] = list(dict.fromkeys(deferred))
    doc['vision_status'] = 'circuit_stopped' if doc.get('provider_stops') else 'partial' if any(needs_fill(r) for r in items.values()) else 'fields_present_unverified'
    doc['vision_note'] = 'Model transcription of selected local images/crops only; no human or complete-page verification. Failures do not establish missing product facts.'
    publish_observation(ROOT, doc)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
