#!/usr/bin/env python3
"""아티팩트 그래프 Mermaid 내보내기의 결정성·주입 방지 회귀 테스트."""
from __future__ import annotations

from pathlib import Path
import re
from unittest.mock import patch

from build_artifact_graph import render_mermaid

workflow = '.github/workflows/example.yml'
script = 'scripts/example.py'
input_artifact = 'data/input.json'
output_artifact = 'data/x\"] --> injected\n  fake --> outside.json'
graph = {
    'workflows': {workflow: {'effective': [script]}},
    'scripts': {script: {'reads': [input_artifact], 'writes': [output_artifact]}},
    'violations': [{'workflow': workflow, 'stale_artifact': output_artifact,
                    'producer_not_run': script, 'upstream_updated': [input_artifact]}],
}
with patch.object(Path, 'write_text', side_effect=AssertionError('unexpected write')):
    diagram = render_mermaid(graph)
    assert render_mermaid(graph) == diagram
assert diagram.startswith('flowchart LR\n')
assert ' ==> ' in diagram  # 실제 워크플로 → 스크립트
assert ' --> ' in diagram  # 실제 읽기/쓰기 의존성
assert diagram.count('-.->|stale|') == 1
assert 'classDef stale' in diagram
assert 'x#34;#93; --#62; injected' in diagram
assert 'x"] --> injected' not in diagram
assert '\n  fake --> outside.json' not in diagram
# 입력 문자열의 줄바꿈이나 닫는 구분자가 새 노드/간선을 만들 수 없다.
assert len(re.findall(r'^  n_artifact_[0-9a-f]{16}\[', diagram, re.M)) == 2
assert len(re.findall(r'^  n_script_[0-9a-f]{16}\[', diagram, re.M)) == 1
assert len(re.findall(r'^  n_workflow_[0-9a-f]{16}\[', diagram, re.M)) == 1
print('ARTIFACT_GRAPH_MERMAID_OK')
