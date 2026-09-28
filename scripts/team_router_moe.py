#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MoE 팀 배정기 (2026-09-28).

왜
  기존 MoE 는 키워드 규칙으로 만든 3분류(ai-image / ai-research / commerce)를
  따라 하는 모델이었고, 가중치를 읽는 곳이 하나도 없었다. 사업에 쓰이지 않았다.

  이 모델은 "이 자료·영상은 어느 팀 일인가" 를 배운다. 정답은 출처가 확실한
  것만 쓴다. 키워드 규칙이 붙인 팀은 정답으로 쓰지 않는다(자기 복제가 된다).

    기관 수집기가 받은 글        -> institutions
    로보틱스 수집기가 받은 글    -> robotics
    arXiv 수집분                -> knowledge
    미국 뷰티 수집분            -> market
    다이소 실측 상품명           -> sourcing
    디자인 레퍼런스 피드         -> design
    FDA·연방관보 원문            -> legal
    사람이 팀을 지정한 채널·영상 -> 지정한 팀
    자막을 검토해 채택한 인사이트 -> 검토자가 정한 팀

쓰는 곳
  scripts/team_routing.py  키워드로 팀을 못 정한 영상의 배정
  scripts/build_youtube_review_queue.py  주간 자막 검토 대상의 팀 배정

안전장치
  검증 세트(주소 해시 1/5)에서 정밀도 0.80 이상, 예측 5건 이상인 팀만
  '믿을 수 있는 팀' 으로 표시한다. 그 팀으로, 확률 0.60 이상일 때만 쓴다.
  다수 클래스 찍기보다 매크로 F1 이 0.10 이상 높지 않으면 승격하지 않는다.

  python scripts/team_router_moe.py --train     # 학습·평가·(조건부) 승격
  python scripts/team_router_moe.py --predict "Amazon FBA fee changes 2026"
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODEL = DATA / "knowledge" / "team_router_moe.npz"
REPORT = DATA / "knowledge" / "team_router_report.json"
TOKEN_RE = re.compile(r"[\w가-힣]{2,}", re.UNICODE)
MIN_DF, MIN_CLASS, STEPS, LR, EXPERTS, TEMP = 2, 15, 300, 5.0, 3, 0.9
TRUST_PRECISION, TRUST_MIN_PRED, USE_MIN_PROB, MIN_GAIN = 0.80, 5, 0.60, 0.10
SOURCE_TEAM = {"institutions": "institutions", "robotics": "robotics", "arxiv": "knowledge",
               "us_beauty": "market", "organic_skincare": "market"}
TEAMS = ("sourcing", "institutions", "market", "listing", "pricing", "legal", "robotics",
         "design", "channels", "knowledge", "graph")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def forced_teams(raw) -> list[str]:
    if not raw:
        return []
    parts = raw.split(",") if isinstance(raw, str) else list(raw)
    return [t.strip() for t in parts if str(t).strip() in TEAMS]


def labeled_items() -> list[dict]:
    """(key, text, teams) 목록. 팀 정답은 출처가 확실한 것만."""
    items: list[dict] = []

    def add(key: str, text: str, teams: list[str], origin: str):
        text = " ".join(str(text or "").split())[:600]
        teams = [t for t in dict.fromkeys(teams) if t in TEAMS]
        if key and text and teams:
            items.append({"key": key, "text": text, "teams": teams, "origin": origin})

    for line in (DATA / "knowledge" / "training_corpus.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        team = SOURCE_TEAM.get(r.get("source"))
        if team:
            add(r.get("url") or r.get("title"), r.get("text") or r.get("title"), [team], f"corpus:{r.get('source')}")

    prods = load(DATA / "daiso_real" / "products.json", {})
    for p in (prods.get("products") if isinstance(prods, dict) else prods) or []:
        add(f"daiso:{p.get('pd_no')}", f"{p.get('name', '')} {p.get('site_category', '')}", ["sourcing"], "daiso")

    for r in ((load(DATA / "design_team.json", {}).get("references") or {}).get("items") or []):
        add(r.get("url"), f"{r.get('title', '')} {r.get('summary', '')}", ["design"], "design_refs")

    for r in (load(DATA / "team_feeds.json", {}).get("teams") or {}).get("legal", []):
        if r.get("pool") == "fda":
            add(r.get("url") or r.get("title"), f"{r.get('title', '')} {r.get('summary', '')}", ["legal"], "fda")

    yc = load(DATA / "youtube_channels.json", {})
    for ch in yc.get("items") or []:
        hint = forced_teams(ch.get("team_hint"))
        if not hint:  # 사람이 팀을 안 정한 채널은 정답으로 쓰지 않는다
            continue
        for v in ch.get("videos") or []:
            add(v.get("url") or v.get("video_id"), v.get("title"), hint, "youtube_channel")

    for v in load(DATA / "youtube_manual.json", {}).get("videos") or []:
        if v.get("team_source") == "사람 지정" and v.get("ai_training_allowed") is not False:
            add(v.get("url"), f"{v.get('title', '')} {v.get('description', '')[:300]}", v.get("teams") or [], "youtube_manual")

    for f in (DATA / "manual" / "shopify_youtube_insights.json", DATA / "manual" / "team_youtube_insights.json"):
        for ins in load(f, {}).get("insights") or []:
            add(f"insight:{ins.get('id')}", f"{ins.get('tactic', '')} {ins.get('action', '')} {ins.get('applicability', '')}",
                ins.get("teams") or [], "insight")

    # 같은 key 가 여러 번 나오면 팀을 합친다
    merged: dict[str, dict] = {}
    for it in items:
        m = merged.setdefault(it["key"], {**it, "teams": []})
        m["teams"] = list(dict.fromkeys(m["teams"] + it["teams"]))
    return list(merged.values())


_TUNE = None


def _tune():
    global _TUNE
    if _TUNE is None:
        spec = importlib.util.spec_from_file_location("tune_moe", ROOT / "tune_real_knowledge_moe.py")
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(ROOT))
        spec.loader.exec_module(mod)
        _TUNE = mod
    return _TUNE


def vectorize(texts: list[str], vocab: list[str], idf):
    import numpy as np
    index = {w: i for i, w in enumerate(vocab)}
    X = np.zeros((len(texts), len(vocab)), dtype=np.float32)
    for r, t in enumerate(texts):
        for w in TOKEN_RE.findall(t.lower()):
            j = index.get(w)
            if j is not None:
                X[r, j] += 1.0
    X = np.log1p(X) * idf[None, :]
    X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-9)
    return X


def train_main() -> int:
    import numpy as np
    tune = _tune()
    items = labeled_items()
    counts: dict[str, int] = {}
    for it in items:
        for t in it["teams"]:
            counts[t] = counts.get(t, 0) + 1
    classes = sorted(t for t, c in counts.items() if c >= MIN_CLASS)
    skipped = {t: c for t, c in counts.items() if c < MIN_CLASS}
    items = [dict(it, teams=[t for t in it["teams"] if t in classes]) for it in items]
    items = [it for it in items if it["teams"]]
    val = np.array([int(hashlib.sha256(it["key"].encode()).hexdigest()[:8], 16) % 5 == 0 for it in items])

    # 다중 팀 항목은 팀마다 한 줄로 늘려 학습한다. 검증은 항목 단위로 한다.
    tr_idx = [i for i in range(len(items)) if not val[i]]
    tr_texts = [items[i]["text"] for i in tr_idx for _ in items[i]["teams"]]
    tr_labels = [classes.index(t) for i in tr_idx for t in items[i]["teams"]]
    df: dict[str, int] = {}
    for t in tr_texts:
        for w in set(TOKEN_RE.findall(t.lower())):
            df[w] = df.get(w, 0) + 1
    vocab = sorted(w for w, c in df.items() if c >= MIN_DF)
    idf = np.log(len(tr_texts) / (1.0 + np.array([df[w] for w in vocab], dtype=np.float32)))
    X_tr = vectorize(tr_texts, vocab, idf)
    Y_tr = np.eye(len(classes), dtype=np.float32)[tr_labels]
    params, loss_history = tune.train(X_tr, Y_tr, EXPERTS, STEPS, LR, 1e-4, TEMP)

    va_items = [items[i] for i in range(len(items)) if val[i]]
    X_va = vectorize([it["text"] for it in va_items], vocab, idf)
    logits, _ = tune.predict(X_va, params, TEMP)
    pred = logits.argmax(1)
    truth_sets = [{classes.index(t) for t in it["teams"]} for it in va_items]

    def metrics(p):
        per = {}
        f1s = []
        for c, name in enumerate(classes):
            predicted = [i for i in range(len(p)) if p[i] == c]
            actual = [i for i in range(len(p)) if c in truth_sets[i]]
            tp = sum(1 for i in predicted if c in truth_sets[i])
            prec = tp / len(predicted) if predicted else 0.0
            rec = sum(1 for i in actual if p[i] == c) / len(actual) if actual else 0.0
            f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
            per[name] = {"precision": round(prec, 3), "recall": round(rec, 3),
                         "predicted": len(predicted), "support": len(actual)}
        acc = sum(1 for i in range(len(p)) if p[i] in truth_sets[i]) / len(p) if len(p) else 0.0
        return {"accuracy": round(acc, 4), "macro_f1": round(float(np.mean(f1s)), 4), "per_team": per}

    model_m = metrics(pred)
    majority = int(np.argmax(Y_tr.sum(0)))
    base_m = metrics(np.full(len(va_items), majority))
    trusted = sorted(t for t, s in model_m["per_team"].items()
                     if s["precision"] >= TRUST_PRECISION and s["predicted"] >= TRUST_MIN_PRED)
    effective = model_m["macro_f1"] >= base_m["macro_f1"] + MIN_GAIN
    report = {
        "generated_at": now(),
        "generator": "scripts/team_router_moe.py",
        "task": "자료·영상 -> 담당 팀 (11팀 중 정답 표본이 충분한 팀)",
        "label_policy": "출처가 확실한 것만 정답으로 쓴다. 키워드 규칙이 붙인 팀은 쓰지 않는다.",
        "classes": classes,
        "skipped_small_classes": skipped,
        "items": len(items), "train_items": len(tr_idx), "validation_items": len(va_items),
        "label_origins": {o: sum(1 for it in items if it["origin"] == o) for o in sorted({it["origin"] for it in items})},
        "features": f"TF-IDF + L2 (min_df {MIN_DF}, 어휘 {len(vocab)})",
        "model": f"MoE experts {EXPERTS}, steps {STEPS}, lr {LR}, 클래스 균형",
        "validation": model_m,
        "baseline_majority": base_m,
        "effective": effective,
        "trusted_teams": trusted if effective else [],
        "use_rule": f"믿을 수 있는 팀(정밀도 ≥{TRUST_PRECISION}, 예측 ≥{TRUST_MIN_PRED}건)으로, 확률 ≥{USE_MIN_PROB} 일 때만 쓴다.",
        "promoted": False,
    }
    if effective:
        expert_w, expert_b, gate_w, gate_b = params
        MODEL.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(MODEL, expert_weights=expert_w, expert_bias=expert_b, gate_weights=gate_w,
                            gate_bias=gate_b, vocabulary=np.array(vocab), idf=idf, classes=np.array(classes),
                            trusted=np.array(trusted if trusted else [""]), temperature=np.array([TEMP]))
        report["promoted"] = True
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("classes", "items", "effective", "trusted_teams", "promoted")}
                     | {"val_acc": model_m["accuracy"], "val_macro_f1": model_m["macro_f1"],
                        "baseline_macro_f1": base_m["macro_f1"]}, ensure_ascii=False))
    return 0


_CACHE: dict | None = None


def predict(texts: list[str]) -> list[dict]:
    """[{team, prob, trusted, usable}] 모델이 없거나 numpy 가 없으면 빈 목록."""
    global _CACHE
    try:
        import numpy as np
    except ImportError:
        return []
    if _CACHE is None:
        if not MODEL.exists():
            _CACHE = {}
        else:
            m = np.load(MODEL, allow_pickle=False)
            _CACHE = {"params": (m["expert_weights"], m["expert_bias"], m["gate_weights"], m["gate_bias"]),
                      "vocab": [str(v) for v in m["vocabulary"]], "idf": m["idf"],
                      "classes": [str(c) for c in m["classes"]],
                      "trusted": {str(t) for t in m["trusted"] if str(t)},
                      "temp": float(m["temperature"].ravel()[0])}
    if not _CACHE or not texts:
        return []
    tune = _tune()
    X = vectorize(texts, _CACHE["vocab"], _CACHE["idf"])
    logits, _ = tune.predict(X, _CACHE["params"], _CACHE["temp"])
    probs = tune.softmax(logits)
    out = []
    for row in probs:
        c = int(row.argmax())
        team, prob = _CACHE["classes"][c], float(row[c])
        trusted = team in _CACHE["trusted"]
        out.append({"team": team, "prob": round(prob, 3), "trusted": trusted,
                    "usable": trusted and prob >= USE_MIN_PROB})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--predict", nargs="*")
    args = ap.parse_args()
    if args.train:
        return train_main()
    if args.predict:
        print(json.dumps(predict(args.predict), ensure_ascii=False))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
