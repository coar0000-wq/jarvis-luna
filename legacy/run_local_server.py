#!/usr/bin/env python3
"""
로컬 웹 서버 실행 - http://localhost:8000
"""
import http.server
import socketserver
import os
import webbrowser
import time

os.chdir(r"C:\Users\Desktop\Claude\Projects\kms")

PORT = 8000
Handler = http.server.SimpleHTTPRequestHandler

try:
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print("=" * 70)
        print(f"🌐 웹 서버 시작됨!")
        print("=" * 70)
        print(f"\n📍 주소: http://localhost:{PORT}")
        print(f"📁 폴더: {os.getcwd()}")
        print(f"\n✅ 브라우저에서 http://localhost:{PORT} 로 이동하세요")
        print(f"\n💡 파일 저장 후 브라우저 새로고침 (F5)하면 즉시 반영됩니다!")
        print(f"\n⚠️ 서버를 종료하려면 Ctrl+C를 누르세요\n")
        print("=" * 70)

        # 자동 브라우저 열기
        time.sleep(1)
        try:
            webbrowser.open(f'http://localhost:{PORT}')
        except:
            pass

        httpd.serve_forever()

except KeyboardInterrupt:
    print("\n\n🛑 서버 종료됨")
except Exception as e:
    print(f"❌ 에러: {e}")
