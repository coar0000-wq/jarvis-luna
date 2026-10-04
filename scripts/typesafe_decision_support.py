#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Advisory-only Jev wrapper. Shared free-only ledger contract: typesafe_shared.py."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("TYPESAFE_MODEL", "jev-latest").strip() or "jev-latest"
TIMEOUT = float(os.environ.get("TYPESAFE_TIMEOUT_SEC", "20"))
MAX_INPUT_CHARS = int(os.environ.get("TYPESAFE_MAX_INPUT_CHARS", "12000"))

try:
    from .typesafe_shared import evaluate_typed, ledger
except ImportError:
    from typesafe_shared import evaluate_typed, ledger
BLOCKER_TEAMS = {
    "ontology": "sourcing",
    "copy": "listing",
    "gosi": "sourcing",
    "us_label": "legal",
    "price": "pricing",
    "legal": "legal",
    "legal_full": "legal",
}
TEAM_ORDER = ("legal", "pricing", "sourcing", "listing", "market", "design", "knowledge")


def _truth(name: str) -> bool:
    return os.environ.get(name, "").strip() == "1"


def _uniq(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def local_advisory(context: dict[str, Any]) -> dict[str, Any]:
    """비용 없이 현재 정본을 TypeSafe 질문 형태로 정리한다."""
    blocked = [str(x) for x in context.get("blocked_by") or []]
    public_blocked = [str(x) for x in context.get("public_blocked_by") or []]
    hard_legal = bool((context.get("legal") or {}).get("hard_block"))
    score = float(context.get("shopify_score") or 0)
    grade = str(context.get("grade") or "")

    if hard_legal or "legal" in blocked:
        grade_decision = "hold"
    elif grade == "S" and score >= 82:
        grade_decision = "keep_s"
    else:
        grade_decision = "review"

    if hard_legal:
        legal_decision = "block"
    elif any(x in public_blocked for x in ("legal", "legal_full", "gosi", "us_label")):
        legal_decision = "review"
    else:
        legal_decision = "clear"

    risk_points = len(set(blocked))
    if hard_legal:
        risk_points += 3
    if "legal_full" in public_blocked:
        risk_points += 1
    if score and score < 90:
        risk_points += 1
    if risk_points <= 0:
        risk_level = "low"
    elif risk_points == 1:
        risk_level = "medium"
    elif risk_points <= 3:
        risk_level = "high"
    else:
        risk_level = "critical"

    routes = [BLOCKER_TEAMS.get(x, "") for x in public_blocked]
    if grade_decision == "review":
        routes.append("market")
    if not routes:
        routes.append("listing")
    routes = _uniq(routes)
    routes.sort(key=lambda team: TEAM_ORDER.index(team) if team in TEAM_ORDER else 99)

    # 모델 라우팅은 정본 게이트를 대신하지 않는다. 필수 자료·승인·외부 계정이
    # 문제면 더 큰 모델을 불러도 해결되지 않으므로 사람/외부 대기로 보낸다.
    mandatory = {"gosi", "us_label", "legal", "legal_full", "price", "ontology"}
    if hard_legal or mandatory.intersection(blocked + public_blocked):
        model_route = "human"
    elif blocked or risk_level in {"high", "critical"}:
        model_route = "gemini"
    else:
        model_route = "local"

    findings = []
    if blocked:
        findings.append("draft blockers: " + ", ".join(blocked))
    if public_blocked:
        findings.append("public blockers: " + ", ".join(public_blocked))
    if hard_legal:
        findings.append("legal hard block")
    if not findings:
        findings.append("현재 정본 기준 추가 blocker 없음")

    return {
        "framework": "typesafe_system_one_compatible",
        "enabled": _truth("TYPESAFE_ENABLED"),
        "mode": "local_advisory",
        "source": "deterministic_local",
        "paid_api_called": False,
        "enforced": False,
        "grade_advisory": grade_decision,
        "legal_gate_advisory": legal_decision,
        "risk_level": risk_level,
        "risk_points": risk_points,
        "team_routes": routes,
        "model_route": model_route,
        "model_route_confidence": None,
        "findings": findings,
        "confidence": None,
        "usage": None,
    }


def _payload(context: dict[str, Any]) -> dict[str, Any]:
    state = {
        "canonical_product_id": context.get("canonical_product_id"),
        "pd_no": context.get("pd_no"),
        "name": context.get("name"),
        "grade": context.get("grade"),
        "shopify_score": context.get("shopify_score"),
        "blocked_by": context.get("blocked_by") or [],
        "public_blocked_by": context.get("public_blocked_by") or [],
        "gosi_ok": bool((context.get("gosi") or {}).get("gosi_ok")),
        "us_label_ok": bool((context.get("us_label") or {}).get("us_label_ok")),
        "price": context.get("price") or {},
        "legal": context.get("legal") or {},
        "legal_full_complete": bool(context.get("legal_full_complete")),
    }
    return {
        "state": state,
        "model": MODEL,
        "questions": {
            "grade_advisory": {
                "type": "choice",
                "instructions": "현재 S등급 후보를 유지, 재검토, 보류 중 하나로 판단하라.",
                "criteria": {
                    "keep_s": "수요 점수와 운영 근거가 충분하고 치명적 blocker가 없음",
                    "review": "근거 또는 준비 항목이 부족해 사람이 재검토해야 함",
                    "hold": "법률 또는 판매 차단 사유로 진행을 보류해야 함",
                },
            },
            "legal_gate_advisory": {
                "type": "choice",
                "instructions": "미국 판매 법률 게이트 보조 판정을 내려라.",
                "criteria": {
                    "clear": "현재 자동 근거에서 추가 법률 blocker가 보이지 않음",
                    "review": "라벨, 고시, MoCRA 또는 근거를 사람이 확인해야 함",
                    "block": "명시적 법률 하드블록이 있어 진행하면 안 됨",
                },
            },
            "risk_level": {
                "type": "score",
                "instructions": "이 상품의 운영 및 규제 위험도를 평가하라.",
                "criteria": ["low", "medium", "high", "critical"],
            },
            "team_route": {
                "type": "choice",
                "instructions": "다음 조치를 맡을 주 담당팀 하나를 고르라.",
                "criteria": {
                    "legal": "법률, 라벨, 고시, MoCRA 문제",
                    "pricing": "가격, 마진, 배송원가 문제",
                    "sourcing": "상품 정체, CP, 원본 자료 또는 공급 문제",
                    "listing": "상품 카피, Shopify 초안 또는 등록 문제",
                    "market": "수요, 등급 또는 시장 근거 재검토",
                    "design": "브랜드와 디자인 자산 문제",
                    "knowledge": "특정 실행팀보다 지식 정리가 우선",
                },
            },
            "model_route": {
                "type": "choice",
                "instructions": "다음 판단 단계를 local, gemini, human 중 하나로 고르라. 필수 자료나 승인이 없으면 human이다.",
                "criteria": {
                    "local": "결정적 정본 필드와 규칙만으로 충분히 판단 가능",
                    "gemini": "필수 자료는 있으나 열린 진단 또는 복합 설명이 필요",
                    "human": "법률 원본, 라벨, 가격, 외부 계정 또는 명시 승인이 필요",
                },
            },
        },
    }


class CreditStop(RuntimeError):
    """크레딧이 끝났거나 한도에 걸렸다. 더 부르지 않는다."""


def _request(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    """한 번만 호출한다. 유료 요청의 자동 재시도는 중복 과금 위험이 있다."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw.decode("utf-8")) > MAX_INPUT_CHARS:
        raise RuntimeError(f"TypeSafe 입력이 제한을 넘었습니다: {len(raw)} bytes")
    request = urllib.request.Request(
        ENDPOINT,
        data=raw,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read().decode("utf-8"))
            rid = (response.headers.get("x-request-id") or response.headers.get("request-id")
                   or body.get("id") or "")
            body["_http"] = {"status": response.status, "request_id": str(rid)[:80]}
            return body
    except Exception:
        # Shared dispatcher persists every HTTP/transport/protocol failure; no retry.
        raise

def _choice(answers: dict[str, Any], key: str, default: str) -> tuple[str, float | None]:
    row = answers.get(key) or {}
    return str(row.get("choice") or default), row.get("confidence")


def evaluate(context: dict[str, Any]) -> dict[str, Any]:
    """Preserve local/canonical/legal/human gates; Jev remains advisory only."""
    fallback = local_advisory(context)
    payload = _payload(context)
    payload['question_version'] = os.environ.get('TYPESAFE_QUESTION_VERSION', 'jarvis-listing-v1')
    payload['model_policy_version'] = os.environ.get('TYPESAFE_MODEL_POLICY_VERSION', 'jarvis-jev-alias-v1')
    result = evaluate_typed(payload, request_fn=_request)
    if result['source'] not in ('typesafe', 'typesafe_cache'):
        fallback['mode'] = result['mode']
        fallback['findings'].append('TypeSafe local fallback: ' + result['mode'])
        return fallback
    answers = result['answers']
    risk = answers['risk_level']['score']
    confidences = [row['confidence'] for row in answers.values()]
    return {
        **fallback, **{k: v for k, v in result.items() if k != 'answers'},
        'grade_advisory': answers['grade_advisory']['choice'],
        'legal_gate_advisory': answers['legal_gate_advisory']['choice'],
        'risk_level': ('low', 'medium', 'high', 'critical')[round(risk)],
        'risk_score': risk,
        'team_routes': _uniq([answers['team_route']['choice']] + fallback['team_routes']),
        'model_route': answers['model_route']['choice'],
        'model_route_confidence': answers['model_route']['confidence'],
        'confidence': round(sum(confidences) / len(confidences), 4),
    }
