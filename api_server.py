#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 JARVIS 실시간 API 서버
포트: 5000
엔드포인트: http://localhost:5000/api/tasks
"""

from flask import Flask, jsonify, send_file
from flask_cors import CORS
import json
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

DATA_FILE = './data/tasks.json'

def load_tasks():
    """JSON 파일에서 작업 데이터 로드"""
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"tasks": [], "lastUpdate": str(datetime.now())}

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    """실시간 작업 데이터 반환"""
    data = load_tasks()
    return jsonify(data), 200

@app.route('/api/tasks/<int:task_id>', methods=['GET'])
def get_task(task_id):
    """특정 작업 정보 반환"""
    data = load_tasks()
    task = next((t for t in data['tasks'] if t['id'] == task_id), None)
    if task:
        return jsonify(task), 200
    return jsonify({"error": "Task not found"}), 404

@app.route('/api/tasks/<int:task_id>/progress/<int:progress>', methods=['PUT'])
def update_task_progress(task_id, progress):
    """작업 진행도 업데이트"""
    data = load_tasks()
    task = next((t for t in data['tasks'] if t['id'] == task_id), None)

    if task:
        task['progress'] = min(100, max(0, progress))  # 0-100 범위
        task['updated'] = datetime.now().isoformat() + 'Z'
        data['lastUpdate'] = datetime.now().isoformat() + 'Z'

        # JSON 파일에 저장
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return jsonify(task), 200

    return jsonify({"error": "Task not found"}), 404

@app.route('/health', methods=['GET'])
def health():
    """헬스 체크"""
    return jsonify({"status": "✅ JARVIS API Server is running"}), 200

if __name__ == '__main__':
    print("=" * 60)
    print("🤖 JARVIS 실시간 API 서버 시작")
    print("=" * 60)
    print("📍 API 서버: http://localhost:5000")
    print("📊 엔드포인트:")
    print("   GET  /api/tasks         - 모든 작업 조회")
    print("   GET  /api/tasks/<id>    - 특정 작업 조회")
    print("   PUT  /api/tasks/<id>/progress/<progress> - 진행도 업데이트")
    print("   GET  /health           - 헬스 체크")
    print("=" * 60)
    print()

    app.run(host='localhost', port=5000, debug=True)
