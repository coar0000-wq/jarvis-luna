#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🧠 JARVIS Obsidian 그래프뷰 자동 동기화
주기적으로 Obsidian 그래프 데이터를 수집하고 동기화합니다.
"""

import json
import os
from pathlib import Path
from datetime import datetime

# 📁 디렉토리 설정
SCRIPT_DIR = Path(__file__).parent.parent
OBSIDIAN_VAULT = Path.home() / "Second brain"  # Obsidian 볼트 경로
GRAPH_DATA_DIR = SCRIPT_DIR / "data"
GRAPH_DATA_DIR.mkdir(exist_ok=True)

class ObsidianGraphSync:
    def __init__(self, vault_path):
        self.vault_path = vault_path
        self.graph_data = {
            "nodes": [],
            "links": [],
            "timestamp": datetime.now().isoformat()
        }

    def collect_graph_data(self):
        """Obsidian 폴더에서 노드 및 링크 수집"""
        if not self.vault_path.exists():
            print(f"⚠️ Obsidian 볼트를 찾을 수 없음: {self.vault_path}")
            return

        # 📝 마크다운 파일 수집
        md_files = list(self.vault_path.glob("**/*.md"))
        print(f"📊 {len(md_files)}개 파일 발견")

        nodes_set = set()
        links_set = set()

        for md_file in md_files:
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 🔗 노드 추가 (파일명)
                node_name = md_file.stem
                nodes_set.add(node_name)

                # 🔗 링크 추출 (형식: [[link]] 또는[text](link.md))
                import re

                # WikiLink 형식: [[target]]
                wikilinks = re.findall(r'\[\[([^\]]+)\]\]', content)
                for link in wikilinks:
                    target = link.split('|')[0].strip()  # alias 처리
                    nodes_set.add(target)
                    links_set.add((node_name, target))

                # Markdown 링크 형식: [text](file.md)
                mdlinks = re.findall(r'\[([^\]]+)\]\(([^)]+\.md)\)', content)
                for text, link in mdlinks:
                    target = Path(link).stem
                    nodes_set.add(target)
                    links_set.add((node_name, target))

            except Exception as e:
                print(f"⚠️ 파일 처리 오류 {md_file}: {e}")

        # 🧠 그래프 데이터 구성
        self.graph_data["nodes"] = [
            {"id": node, "label": node, "type": "note"}
            for node in sorted(nodes_set)
        ]

        self.graph_data["links"] = [
            {"source": source, "target": target}
            for source, target in sorted(links_set)
        ]

        self.graph_data["stats"] = {
            "nodes_count": len(nodes_set),
            "links_count": len(links_set),
            "last_updated": datetime.now().isoformat()
        }

        print(f"✅ 노드: {len(nodes_set)}, 링크: {len(links_set)}")

    def save_graph_data(self):
        """그래프 데이터를 JSON으로 저장"""
        output_file = GRAPH_DATA_DIR / "obsidian_graph.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.graph_data, f, ensure_ascii=False, indent=2)
        print(f"💾 그래프 데이터 저장: {output_file}")

    def sync(self):
        """Obsidian 동기화 실행"""
        print(f"🧠 [JARVIS] Obsidian 동기화 시작 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.collect_graph_data()
        self.save_graph_data()
        print(f"🧠 [JARVIS] Obsidian 동기화 완료!")

def main():
    # 🧠 Obsidian 동기화 실행
    syncer = ObsidianGraphSync(OBSIDIAN_VAULT)
    syncer.sync()

    # 📊 지수 생성 (선택사항)
    generate_graph_index()

def generate_graph_index():
    """그래프 인덱스 생성 (향후 검색 최적화용)"""
    graph_file = GRAPH_DATA_DIR / "obsidian_graph.json"

    if not graph_file.exists():
        return

    with open(graph_file, 'r', encoding='utf-8') as f:
        graph_data = json.load(f)

    # 📊 노드별 연결도 계산
    node_connections = {}
    for link in graph_data.get("links", []):
        source = link["source"]
        target = link["target"]

        if source not in node_connections:
            node_connections[source] = []
        if target not in node_connections:
            node_connections[target] = []

        node_connections[source].append(target)

    # 💾 인덱스 저장
    index_file = GRAPH_DATA_DIR / "graph_index.json"
    with open(index_file, 'w', encoding='utf-8') as f:
        json.dump(node_connections, f, ensure_ascii=False, indent=2)

    print(f"📇 그래프 인덱스 생성 완료")

if __name__ == "__main__":
    main()
