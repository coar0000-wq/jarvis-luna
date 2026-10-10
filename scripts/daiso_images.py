#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""다이소 상품 이미지 처리: 사람 얼굴 사진 제외 + 대표(메인) 이미지 선정 + 2048 정사각 변환.

규칙 (사용자 지시 2026-10-10)
  - 다이소 상품 이미지는 모두 올린다. 단, 사람 얼굴이 있는 사진은 올리지 않는다.
  - 대표(첫 번째) 이미지는 흰색/단색 배경에 제품만 보이는 깔끔한 컷을 우선한다 (shop.com 의 상품 대표컷처럼).
  - 규격: brand_kit.json 상품 이미지 2048 x 2048 정사각 JPEG.

얼굴 판독은 OpenCV YuNet (무료·로컬·결정적) 로 한다. 무료 Gemini 는 503/429 가 잦아 보조로만 쓴다.
판독 도구가 없거나 실패하면 그 이미지는 쓰지 않는다 (사람 얼굴이 섞이는 것보다 낫다).
"""
from __future__ import annotations

import io

_DETECTOR = None
FACE_SCORE = 0.80  # YuNet 신뢰도 임계값. 낮추면 로고·원형 장식을 얼굴로 오인한다.


def _model_path():
    from pathlib import Path  # noqa: PLC0415

    return str(Path(__file__).resolve().parents[1] / "assets" / "models" / "face_detection_yunet_2023mar.onnx")


def _gray(data, max_side=900):
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("cannot decode image")
    h, w = img.shape[:2]
    s = min(1.0, max_side / max(h, w))
    if s < 1.0:
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img, cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))


def count_faces(data):
    """사람 얼굴 수 (OpenCV YuNet 딥러닝 얼굴 검출, CPU). 로고·제품 그래픽은 얼굴로 세지 않는다."""
    import cv2  # noqa: PLC0415

    img, _ = _gray(data, 1000)
    h, w = img.shape[:2]
    det = cv2.FaceDetectorYN.create(_model_path(), "", (w, h), FACE_SCORE, 0.3, 5000)
    det.setInputSize((w, h))
    _, faces = det.detect(img)
    if faces is None:
        return 0
    # 너무 작은 검출(이미지 폭의 3% 미만)은 얼굴 사진으로 보지 않는다
    return int(sum(1 for f in faces if f[2] >= w * 0.03 and f[14] >= FACE_SCORE))


def cleanliness(data):
    """대표컷 점수(0~1, 높을수록 깔끔). 가장자리 색이 균일하고 채도 높은 장식(배지·스티커)이 적을수록 높다."""
    import cv2  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    img, _ = _gray(data, 600)
    h, w = img.shape[:2]
    b = max(4, int(min(h, w) * 0.06))
    border = np.concatenate([img[:b].reshape(-1, 3), img[-b:].reshape(-1, 3), img[:, :b].reshape(-1, 3), img[:, -b:].reshape(-1, 3)])
    spread = float(border.std(axis=0).mean())  # 0(단색) ~ 70+
    uniform = max(0.0, 1.0 - spread / 45.0)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    red = ((hsv[..., 0] < 8) | (hsv[..., 0] > 172)) & (hsv[..., 1] > 150) & (hsv[..., 2] > 120)
    badge_penalty = min(1.0, float(red.mean()) * 8)  # 빨간 'BEST/PICK' 배지류
    return max(0.0, uniform - 0.5 * badge_penalty)


def to_square_jpeg(data, size=2048):
    """2048x2048 정사각 JPEG. 원본을 자르지 않고 같은 사진을 흐리게 깔아 채운다. 배경이 거의 흰색이면 흰 바탕을 쓴다."""
    from PIL import Image, ImageFilter  # noqa: PLC0415

    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size
    corners = [im.getpixel(p) for p in ((2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3))]
    light = all(min(c) > 235 for c in corners)
    if light:
        bg = Image.new("RGB", (size, size), (255, 255, 255))
    else:
        s = size / min(w, h)
        bg = im.resize((max(size, int(w * s) + 1), max(size, int(h * s) + 1)))
        left, top = (bg.width - size) // 2, (bg.height - size) // 2
        bg = bg.crop((left, top, left + size, top + size)).filter(ImageFilter.GaussianBlur(45))
    fit = int(size * 0.96)
    f = min(fit / w, fit / h)
    fg = im.resize((max(1, int(w * f)), max(1, int(h * f))), Image.LANCZOS)
    bg.paste(fg, ((size - fg.width) // 2, (size - fg.height) // 2))
    out = io.BytesIO()
    bg.save(out, format="JPEG", quality=92, optimize=True)
    return out.getvalue()


def select_images(blobs):
    """blobs: [(url, bytes)] 원본 순서. 얼굴 사진 제외, 대표컷을 맨 앞으로. 반환: (kept[(url, bytes)], dropped[{url, reason}])"""
    kept, dropped = [], []
    for url, data in blobs:
        try:
            n = count_faces(data)
        except Exception as exc:  # noqa: BLE001
            dropped.append({"url": url, "reason": f"face_check_failed:{type(exc).__name__}"})
            continue
        if n > 0:
            dropped.append({"url": url, "reason": f"face_detected:{n}"})
            continue
        try:
            score = cleanliness(data)
        except Exception:  # noqa: BLE001
            score = 0.0
        kept.append((url, data, score))
    if not kept:
        return [], dropped
    best = max(range(len(kept)), key=lambda i: (kept[i][2], -i))
    ordered = [kept[best]] + [k for i, k in enumerate(kept) if i != best]
    return [(u, d) for u, d, _ in ordered], dropped
