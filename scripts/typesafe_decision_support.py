#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TypeSafe System One 방식의 상품 판단 보조 계층.

중요한 안전 규칙
- 기본 실행은 로컬 규칙 기반 advisory만 만든다. 네트워크 호출도 비용도 없다.
- 실제 TypeSafe 호출은 TYPESAFE_ENABLED=1 과 아래 둘 중 하나가 필요하다.
    TYPESAFE_FREE_CREDITS_ONLY=1   계정에 이미 있는 무료(프로모션) 크레딧만 쓴다
    TYPESAFE_ALLOW_PAID=1          유료 사용까지 명시적으로 승인했다
- 무료 모드는 한 번 실행에 쓸 수 있는 호출 수와 입력 토큰을 스스로 제한하고,
  크레딧이 떨어졌다는 응답(402·403·429)을 받으면 그 즉시 마지막까지 멈춘다.
  크레딧을 사거나 자동충전을 켜는 일은 어떤 경우에도 하지 않는다.
- 결과는 관찰용이다. 기존 점수·법률·listing gate 정본을 덮거나 차단하지 않는다.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("TYPESAFE_MODEL", "jev-latest").strip() or "jev-latest"
TIMEOUT = float(os.environ.get("TYPESAFE_TIMEOUT_SEC", "20"))
MAX_INPUT_CHARS = int(os.environ.get("TYPESAFE_MAX_INPUT_CHARS", "12000"))

# 한 번 실행의 상한. 무료 크레딧을 한 회차에 써 버리지 않기 위한 것이다.
# S등급 후보는 보통 10건이고 건당 600토큰 안팔이라 기본값이면 넣넘하다.
MAX_CALLS = int(os.environ.get("TYPESAFE_MAX_CALLS", "40"))
MAX_INPUT_TOKENS = int(os.environ.get("TYPESAFE_MAX_INPUT_TOKENS", "60000"))

# 크레딧 소진·권한·한도 응답. 이걸 받으면 재시도하지 않고 멈춘다.
STOP_STATUSES = (401, 402, 403, 429)

# 한 프로세스 안에서만 사는 장부다. 다음 실행은 다시 0에서 시작한다.
_LEDGER: dict[str, Any] = {
    "calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "stopped": "",
}


def ledger() -> dict[str, Any]:
    """이번 실행에서 실제로 쓴 양. 게이트가 이걸 산출물에 적는다."""
    cost = _LEDGER["input_tokens"] / 1_000_000 * 0.042
    return {
        **_LEDGER,
        "max_calls": MAX_CALLS,
        "max_input_tokens": MAX_INPUT_TOKENS,
        "input_token_price_per_mtok_usd": 0.042,
        "estimated_cost_usd": round(cost, 6),
        "purchased_credits": False,
    }

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
        },
    }


class CreditStop(RuntimeError):
    """크레딧이 끝났거나 한도에 걸렸다. 더 부르지 않는다."""


def _request(payload: dict[str, Any], api_key: str) -> dict[str, Any]:
    """한 번만 호출한다. 유료 요청의 자동 재시도는 중복 과금 위험이 있다."""
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 공급자 본문은 산출물에 남기지 않는다. 진단 내용에 민감 정보가
        # 섞일 가능성을 막고 상태 코드만 보존한다.
        if exc.code in STOP_STATUSES:
            _LEDGER["stopped"] = f"HTTP {exc.code}"
            raise CreditStop(f"HTTP {exc.code}") from exc
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(type(exc).__name__) from exc


def _choice(answers: dict[str, Any], key: str, default: str) -> tuple[str, float | None]:
    row = answers.get(key) or {}
    return str(row.get("choice") or default), row.get("confidence")


def evaluate(context: dict[str, Any]) -> dict[str, Any]:
    """기본은 무료 advisory, 이중 승인 때만 TypeSafe를 호출한다."""
    fallback = local_advisory(context)
    if not _truth("TYPESAFE_ENABLED"):
        fallback["mode"] = "disabled_local_advisory"
        return fallback

    free_only = _truth("TYPESAFE_FREE_CREDITS_ONLY")
    if not free_only and not _truth("TYPESAFE_ALLOW_PAID"):
        fallback["mode"] = "blocked_no_paid_approval"
        fallback["findings"].append("호출 승인 없음: 로컬 advisory만 사용")
        return fallback

    if _LEDGER["stopped"]:
        fallback["mode"] = "typesafe_stopped_local_fallback"
        fallback["findings"].append(f"TypeSafe 중단: {_LEDGER['stopped']}")
        return fallback

    if free_only and (_LEDGER["calls"] >= MAX_CALLS
                      or _LEDGER["input_tokens"] >= MAX_INPUT_TOKENS):
        _LEDGER["stopped"] = "free_budget_reached"
        fallback["mode"] = "typesafe_budget_local_fallback"
        fallback["findings"].append("무료 한도 도달: 남은 상품은 로컬 advisory")
        return fallback

    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not api_key:
        fallback["mode"] = "blocked_missing_api_key"
        fallback["findings"].append("TYPESAFE_API_KEY 없음: 로컬 advisory만 사용")
        return fallback

    try:
        response = _request(_payload(context), api_key)
        usage = response.get("usage") or {}
        _LEDGER["calls"] += 1
        _LEDGER["input_tokens"] += int(usage.get("input_tokens") or 0)
        _LEDGER["output_tokens"] += int(usage.get("output_tokens") or 0)
        answers = response.get("answers") or {}
        grade, grade_conf = _choice(answers, "grade_advisory", fallback["grade_advisory"])
        legal, legal_conf = _choice(answers, "legal_gate_advisory", fallback["legal_gate_advisory"])
        route, route_conf = _choice(answers, "team_route", fallback["team_routes"][0])
        risk = answers.get("risk_level") or {}
        score = risk.get("score")
        levels = ("low", "medium", "high", "critical")
        risk_level = levels[min(len(levels) - 1, max(0, round(float(score or 0))))]
        confidence_values = [x for x in (grade_conf, legal_conf, route_conf, risk.get("confidence"))
                             if isinstance(x, (int, float))]
        return {
            **fallback,
            "enabled": True,
            "mode": ("typesafe_observational_free_credits" if free_only
                     else "typesafe_observational"),
            "source": "typesafe",
            "paid_api_called": not free_only,
            "free_credits_only": free_only,
            "enforced": False,
            "grade_advisory": grade,
            "legal_gate_advisory": legal,
            "risk_level": risk_level,
            "risk_score": score,
            "team_routes": _uniq([route] + fallback["team_routes"]),
            "confidence": (round(sum(confidence_values) / len(confidence_values), 4)
                           if confidence_values else None),
            "usage": response.get("usage"),
            "model": response.get("model") or MODEL,
        }
    except CreditStop as exc:
        # 크레딧이 끝났거나 한도에 걸렸다. 다음 상품부터는 아예 안 부른다.
        fallback["mode"] = "typesafe_credit_stop_local_fallback"
        fallback["findings"].append(f"TypeSafe 중단: {exc}")
        return fallback
    except Exception as exc:  # 외부 보조 계층 실패가 정본 게이트를 깨면 안 된다.
        fallback["mode"] = "typesafe_error_local_fallback"
        fallback["paid_api_called"] = not free_only
        fallback["findings"].append(f"TypeSafe 실패: {type(exc).__name__}")
        return fallback
