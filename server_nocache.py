#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import http.server
import socketserver
import os

class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # 강력한 캐시 무효화 헤더 추가
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def do_GET(self):
        # 현재 디렉토리 설정
        os.chdir(os.path.dirname(os.path.abspath(__file__)))
        super().do_GET()

if __name__ == '__main__':
    PORT = 8000
    Handler = NoCacheHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"🚀 JARVIS LUNA 웹서버 시작 (캐시 비활성화)")
        print(f"http://localhost:{PORT} 에서 접속하세요!")
        print(f"(종료하려면 Ctrl+C를 누르세요)")
        httpd.serve_forever()
