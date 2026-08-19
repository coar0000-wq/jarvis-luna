#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
비디오 분석 스크립트 - 강아지 포즈 스크롤 애니메이션 분석
"""
import cv2
import json
from pathlib import Path

# 비디오 파일 경로
video_path = r"C:\Users\Desktop\AppData\Roaming\Claude\local-agent-mode-sessions\ab2eb384-63dc-4ae8-905a-71460e9ab5d4\f0933c22-8c2d-42bf-80b4-5a7cd933feaf\local_062e88da-5cc1-4a51-a825-03661f67e32c\uploads\녹음 2026-08-16 133016.mp4"

print("=" * 80)
print("🎬 비디오 분석 시작")
print("=" * 80)

try:
    # 비디오 열기
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print("❌ 비디오 파일을 열 수 없습니다!")
        exit(1)

    # 비디오 정보 추출
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total_frames / fps if fps > 0 else 0

    print(f"\n📊 비디오 정보:")
    print(f"  • 해상도: {width}x{height}px")
    print(f"  • FPS: {fps:.2f}")
    print(f"  • 총 프레임: {total_frames}")
    print(f"  • 재생 시간: {duration:.2f}초")

    # 프레임 샘플 추출 (5개 프레임)
    print(f"\n📸 프레임 분석 중...")
    frames_to_extract = [0, total_frames//4, total_frames//2, 3*total_frames//4, total_frames-1]

    output_dir = Path("C:/Users/Desktop/Claude/Projects/kms/video_frames")
    output_dir.mkdir(exist_ok=True)

    for idx, frame_num in enumerate(frames_to_extract):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = cap.read()

        if ret:
            output_path = output_dir / f"frame_{idx:02d}_{frame_num}.jpg"
            cv2.imwrite(str(output_path), frame)
            timestamp = frame_num / fps
            print(f"  ✅ 프레임 {idx+1}/5: {timestamp:.2f}초 저장 ({frame_num}/{total_frames})")

    # 비디오 내용 분석
    print(f"\n🔍 비디오 내용 분석:")
    print(f"  • 비디오에 강아지 이미지가 표시되는가?")
    print(f"  • 스크롤하면서 포즈가 변하는가?")
    print(f"  • 얼마나 많은 포즈 변화가 있는가?")

    # 결과 저장
    analysis_result = {
        "video_file": str(video_path),
        "resolution": f"{width}x{height}",
        "fps": fps,
        "total_frames": total_frames,
        "duration_seconds": duration,
        "frames_extracted": len(frames_to_extract),
        "frame_output_dir": str(output_dir),
        "observations": [
            "비디오 분석 완료",
            f"총 {total_frames}개 프레임 감지",
            f"재생 시간: {duration:.2f}초",
            "포즈 변화 관찰 필요 - 프레임 이미지 확인 필요"
        ]
    }

    output_json = Path("C:/Users/Desktop/Claude/Projects/kms/video_analysis.json")
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(analysis_result, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 분석 완료!")
    print(f"  • 프레임 저장 경로: {output_dir}")
    print(f"  • 분석 결과 저장: {output_json}")

    cap.release()

except ImportError:
    print("❌ OpenCV(cv2)가 설치되지 않았습니다.")
    print("설치 명령: pip install opencv-python")
    exit(1)

except Exception as e:
    print(f"❌ 오류 발생: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
