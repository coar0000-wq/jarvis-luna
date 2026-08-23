#!/usr/bin/env python3
import base64
import sys

# 이미지 파일을 base64로 인코딩
image_path = r"C:\Users\Desktop\AppData\Roaming\Claude\local-agent-mode-sessions\ab2eb384-63dc-4ae8-905a-71460e9ab5d4\f0933c22-8c2d-42bf-80b4-5a7cd933feaf\local_062e88da-5cc1-4a51-a825-03661f67e32c\uploads\111.jpg"

try:
    with open(image_path, 'rb') as f:
        image_data = f.read()
        base64_str = base64.b64encode(image_data).decode('utf-8')

    # 결과 출력
    data_uri = f"data:image/jpeg;base64,{base64_str}"

    print("✅ Image encoded successfully!")
    print(f"Length: {len(base64_str)} characters")
    print(f"\nData URI (first 100 chars):")
    print(data_uri[:100] + "...")

    # 전체 data URI를 파일에 저장
    with open(r"C:\Users\Desktop\Claude\Projects\kms\jarvis-luna\image-base64.txt", 'w') as f:
        f.write(data_uri)

    print("\n✅ Full data URI saved to image-base64.txt")
    print(f"Ready to use in HTML!")

except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
