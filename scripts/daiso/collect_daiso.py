#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
JARVIS LUNA - Daiso 실제 상품 수집기
=====================================

목적
----
다이소몰 뷰티관(C245) 상품을 실제 웹 표면에서 수집한다.

핵심 원칙
---------
1. 실제 측정값만 저장한다.
2. 가격을 추정하지 않는다.
3. 상품 상세 페이지가 정상 HTML을 주지 않는 경우 공식 상품 검색 표면을
   보조 경로로 사용한다.
4. 이전에 실패한 상품은 다음 실행에서 자동 재시도한다.
5. 기존 정상 상품 데이터는 수집 실패 때문에 지우지 않는다.
6. 가격 출처를 반드시 기록한다.
7. unresolved / blocked / parse_failed를 구분하여 기록한다.
8. robots.txt의 Crawl-delay 30초를 기본값으로 유지한다.

이번 개선의 핵심
----------------
기존 문제:
    상품 상세 URL 요청
        ↓
    HTTP 200
        ↓
    HTML은 "다이소몰" 기본 페이지
        ↓
    og:title = 다이소몰
        ↓
    상품 가격 없음
        ↓
    "가격 없음"

개선:
    상세 페이지
        ↓
    정상 상품 HTML 파싱
        ↓ 실패
    공식 SearchGoods 검색 표면
        ↓
    pdNo 기준 상품 탐색
        ↓
    가격 후보 추출
        ↓
    실제 가격 확인
        ↓
    products.json 저장

환경변수
--------
DAISO_MAX_ITEMS
    이번 실행에서 확인할 최대 상품 수

DAISO_DELAY
    상품 요청 사이 대기 시간(초)

DAISO_TIMEOUT
    요청 timeout

DAISO_RETRY_FAILED
    이전 parse_failed 상품 재시도 여부

DAISO_RETRY_UNAVAILABLE
    이전 구매 불가 상품 재시도 여부

DAISO_SEARCH_FALLBACK
    상세 페이지 가격 추출 실패 시 SearchGoods fallback 여부
"""

from __future__ import annotations

import html as html_lib
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

OUT_DIR = ROOT / "data" / "daiso_real"

PRODUCTS = OUT_DIR / "products.json"
STATE = OUT_DIR / "crawl_state.json"
QUEUE = OUT_DIR / "beauty_queue.json"
STATUS = OUT_DIR / "collection_status.json"

CATMAP = Path(__file__).with_name("category_map.json")


# ============================================================
# DAISO
# ============================================================

BASE = "https://www.daisomall.co.kr"

SITEMAP = BASE + "/sitemap.xml"

PRODUCT_PATH = "/pd/pdr/SCR_PDR_0001"

# 공식 상품 검색 표면
SEARCH_GOODS = BASE + "/ssn/search/SearchGoods"

# 보조 상품 요약 표면
GOODS_SUMMARY = BASE + "/ssn/search/GoodsMummResult"

# 온라인 재고 표면
ONLINE_STOCK = BASE + "/api/pdo/selOnlStck"

UA = (
    "JarvisLunaResearchBot/1.0 "
    "(+contact: coar0000@naver.com)"
)


# ============================================================
# ENV
# ============================================================

MAX_ITEMS = int(
    os.environ.get("DAISO_MAX_ITEMS", "110")
)

DELAY = float(
    os.environ.get("DAISO_DELAY", "30")
)

TIMEOUT = float(
    os.environ.get("DAISO_TIMEOUT", "20")
)

RETRY_FAILED = (
    os.environ.get(
        "DAISO_RETRY_FAILED",
        "1",
    )
    .strip()
    .lower()
    not in {"0", "false", "no"}
)

# 큐가 비었을 때 사이트맵 전체를 훑을지. 기본은 끈다.
# 사이트맵은 쇼핑몰 전체 19,739건이라 뷰티 적중률이 낮다.
# 2026-09-12 에 110건을 받아 105건을 버렸고 Crawl-delay 30 이라 52분이다.
# 받아 보고 버리는 문을 기본으로 열어 두지 않는다.
ALLOW_SITEMAP = (
    os.environ.get(
        "DAISO_ALLOW_SITEMAP",
        "0",
    )
    .strip()
    .lower()
    not in {"0", "false", "no", ""}
)

RETRY_UNAVAILABLE = (
    os.environ.get(
        "DAISO_RETRY_UNAVAILABLE",
        "1",
    )
    .strip()
    .lower()
    not in {"0", "false", "no"}
)

SEARCH_FALLBACK = (
    os.environ.get(
        "DAISO_SEARCH_FALLBACK",
        "1",
    )
    .strip()
    .lower()
    not in {"0", "false", "no"}
)


# ============================================================
# CURRENT TIME
# ============================================================


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# JSON HELPERS
# ============================================================


def load_json(path: Path, default):
    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
    ):
        return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            obj,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


# ============================================================
# HTTP
# ============================================================


def fetch(
    url: str,
    method: str = "GET",
    data: bytes | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, str, dict[str, str]]:

    headers = {
        "User-Agent": UA,
        "Accept": (
            "text/html,"
            "application/xhtml+xml,"
            "application/xml,"
            "application/json,"
            "*/*;q=0.8"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6",
        "Referer": BASE + "/",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    if extra_headers:
        headers.update(extra_headers)

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=TIMEOUT,
        ) as response:

            raw = response.read()

            charset = (
                response.headers.get_content_charset()
                or "utf-8"
            )

            text = raw.decode(
                charset,
                errors="replace",
            )

            response_headers = {
                str(k): str(v)
                for k, v in response.headers.items()
            }

            return (
                response.status,
                text,
                response_headers,
            )

    except urllib.error.HTTPError as exc:

        try:
            body = exc.read().decode(
                "utf-8",
                errors="replace",
            )
        except Exception:
            body = ""

        return (
            exc.code,
            body,
            {},
        )

    except Exception as exc:

        return (
            0,
            str(exc),
            {},
        )


# ============================================================
# TEXT HELPERS
# ============================================================


def unescape(value) -> str:
    return html_lib.unescape(
        str(value or "")
    ).strip()


def clean_text(value: str) -> str:

    value = unescape(value)

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value.strip()


def normalize_pd_no(value) -> str:

    value = str(
        value or ""
    ).strip()

    value = value.strip(
        "\"'"
    )

    return value


# ============================================================
# META
# ============================================================


META = re.compile(
    r'<meta[^>]+'
    r'(?:property|name)'
    r'=["\']([^"\']+)["\']'
    r'[^>]+content'
    r'=["\']([^"\']*)["\']',
    re.I,
)

META_REV = re.compile(
    r'<meta[^>]+'
    r'content'
    r'=["\']([^"\']*)["\']'
    r'[^>]+'
    r'(?:property|name)'
    r'=["\']([^"\']+)["\']',
    re.I,
)


def meta_tags(html: str) -> dict[str, str]:

    tags: dict[str, str] = {}

    for key, value in META.findall(html):
        tags.setdefault(
            key.lower().strip(),
            unescape(value),
        )

    for value, key in META_REV.findall(html):
        tags.setdefault(
            key.lower().strip(),
            unescape(value),
        )

    return tags


# ============================================================
# VISIBLE TEXT
# ============================================================


def visible_text(html: str) -> str:

    text = re.sub(
        r"<script\b[^>]*>.*?</script>",
        " ",
        html,
        flags=re.I | re.S,
    )

    text = re.sub(
        r"<style\b[^>]*>.*?</style>",
        " ",
        text,
        flags=re.I | re.S,
    )

    text = re.sub(
        r"<noscript\b[^>]*>.*?</noscript>",
        " ",
        text,
        flags=re.I | re.S,
    )

    text = re.sub(
        r"<svg\b[^>]*>.*?</svg>",
        " ",
        text,
        flags=re.I | re.S,
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    return clean_text(text)


# ============================================================
# JSON-LD
# ============================================================


def json_ld_objects(html: str) -> list:

    result = []

    blocks = re.findall(
        r'<script[^>]+'
        r'type=["\']application/ld\+json["\']'
        r'[^>]*>(.*?)</script>',
        html,
        flags=re.I | re.S,
    )

    for block in blocks:

        raw = html_lib.unescape(
            block
        ).strip()

        if not raw:
            continue

        candidates = [raw]

        # script 내부에 HTML entity / control char가 섞인 경우
        cleaned = re.sub(
            r"[\x00-\x08\x0b\x0c\x0e-\x1f]",
            " ",
            raw,
        )

        if cleaned != raw:
            candidates.append(cleaned)

        for candidate in candidates:

            try:
                obj = json.loads(candidate)
                result.append(obj)
                break
            except json.JSONDecodeError:
                continue

    return result


def iter_json_values(value):

    if isinstance(value, dict):

        for key, child in value.items():

            yield (
                str(key),
                child,
            )

            yield from iter_json_values(
                child
            )

    elif isinstance(value, list):

        for child in value:

            yield from iter_json_values(
                child
            )


# ============================================================
# NUMERIC PRICE
# ============================================================


def numeric_price(value) -> int | None:

    if value is None:
        return None

    if isinstance(
        value,
        bool,
    ):
        return None

    text = unescape(value)

    text = (
        text.replace("₩", "")
        .replace("￦", "")
        .replace("KRW", "")
        .replace("원", "")
        .strip()
    )

    # 5,000
    match = re.search(
        r"(?<!\d)"
        r"(\d{1,3}(?:,\d{3})+)"
        r"(?:\.\d+)?"
        r"(?!\d)",
        text,
    )

    if not match:

        # 5000
        match = re.search(
            r"(?<!\d)"
            r"(\d{2,6})"
            r"(?:\.\d+)?"
            r"(?!\d)",
            text,
        )

    if not match:
        return None

    try:
        price = int(
            match.group(1)
            .replace(",", "")
        )
    except ValueError:
        return None

    # 다이소 일반 상품 가격 범위를 고려한 방어선.
    # 1,000,000원 이상은 자동 채택하지 않는다.
    if price <= 0:
        return None

    if price > 1_000_000:
        return None

    return price


# ============================================================
# PRICE PATTERNS
# ============================================================


PRICE_WON_RE = re.compile(
    r"(?<!\d)"
    r"(\d{1,3}(?:,\d{3})+|\d{2,6})"
    r"\s*원"
    r"(?!\d)"
)

PRICE_LABEL_RE = re.compile(
    r"(?:"
    r"판매가|"
    r"판매가격|"
    r"판매 금액|"
    r"가격|"
    r"정가|"
    r"할인가|"
    r"할인판매가|"
    r"최저가|"
    r"상품가격|"
    r"상품 가격|"
    r"결제가|"
    r"결제금액|"
    r"salePrice|"
    r"sellingPrice|"
    r"sellPrice|"
    r"goodsPrice|"
    r"productPrice|"
    r"priceValue|"
    r"price"
    r")"
    r"\s*"
    r"(?:[:=]\s*)?"
    r"['\"]?"
    r"\s*"
    r"(\d{1,3}(?:,\d{3})+|\d{2,6})"
    r"(?:\.\d+)?"
    r"\s*(?:원|KRW)?",
    re.I,
)


# ============================================================
# PRICE CANDIDATE SCORING
# ============================================================


PRICE_KEYS = {
    "price",
    "saleprice",
    "sale_price",
    "sellingprice",
    "selling_price",
    "sellprice",
    "sell_price",
    "productprice",
    "product_price",
    "goodsprice",
    "goods_price",
    "pricevalue",
    "price_value",
    "amount",
    "saleamount",
    "sale_amount",
    "sellamount",
    "sell_amount",
    "discountprice",
    "discount_price",
    "finalprice",
    "final_price",
}


def normalize_key_name(
    value: str,
) -> str:

    value = (
        value or ""
    ).strip().lower()

    value = value.replace(
        "-",
        "_",
    )

    return value


def is_price_key(
    value: str,
) -> bool:

    key = normalize_key_name(
        value
    )

    if key in PRICE_KEYS:
        return True

    if key.endswith(
        "_price"
    ):
        return True

    if key.endswith(
        "price"
    ):
        return True

    return False


# ============================================================
# JSON PRICE SEARCH
# ============================================================


def extract_price_from_json(
    html: str,
) -> tuple[int | None, str | None]:

    best_price = None
    best_source = None

    for obj in json_ld_objects(html):

        for key_name, value in iter_json_values(obj):

            if not is_price_key(
                key_name
            ):
                continue

            price = numeric_price(
                value
            )

            if price is None:
                continue

            normalized = normalize_key_name(
                key_name
            )

            score = 0

            if normalized in {
                "saleprice",
                "sale_price",
                "sellingprice",
                "selling_price",
                "sellprice",
                "sell_price",
                "productprice",
                "product_price",
                "goodsprice",
                "goods_price",
            }:
                score += 5

            elif normalized in {
                "price",
                "pricevalue",
                "price_value",
            }:
                score += 4

            else:
                score += 2

            # 다이소 가격대 방어
            if 500 <= price <= 10_000:
                score += 2
            elif 100 <= price <= 50_000:
                score += 1

            candidate = (
                score,
                price,
                f"json:{key_name}",
            )

            if (
                best_price is None
                or candidate[0]
                > best_price[0]
            ):
                best_price = candidate

    if best_price:
        return (
            best_price[1],
            best_price[2],
        )

    return None, None


# ============================================================
# HTML ATTRIBUTE PRICE
# ============================================================


ATTRIBUTE_PATTERNS = [

    re.compile(
        r'<[^>]+'
        r'itemprop=["\']price["\']'
        r'[^>]+'
        r'content=["\']([^"\']+)["\']'
        r'[^>]*>',
        re.I,
    ),

    re.compile(
        r'<[^>]+'
        r'content=["\']([^"\']+)["\']'
        r'[^>]+'
        r'itemprop=["\']price["\']'
        r'[^>]*>',
        re.I,
    ),

    re.compile(
        r'<[^>]+'
        r'(?:'
        r'data-price|'
        r'data-sale-price|'
        r'data-selling-price|'
        r'data-sell-price|'
        r'data-product-price|'
        r'data-goods-price'
        r')'
        r'=["\']([^"\']+)["\']'
        r'[^>]*>',
        re.I,
    ),

    re.compile(
        r'<[^>]+'
        r'(?:'
        r'data-price|'
        r'data-sale-price|'
        r'data-selling-price|'
        r'data-sell-price|'
        r'data-product-price|'
        r'data-goods-price'
        r')'
        r'='
        r'([0-9,]+)'
        r'[^>]*>',
        re.I,
    ),

]


def extract_price_from_attributes(
    html: str,
) -> tuple[int | None, str | None]:

    for index, pattern in enumerate(
        ATTRIBUTE_PATTERNS,
        start=1,
    ):

        for raw in pattern.findall(
            html
        ):

            price = numeric_price(
                raw
            )

            if price is not None:

                return (
                    price,
                    f"attribute:{index}",
                )

    return None, None


# ============================================================
# META PRICE
# ============================================================


META_PRICE_KEYS = (
    "product:price:amount",
    "og:price:amount",
    "product:price",
    "price",
    "saleprice",
    "sale_price",
    "sellingprice",
    "selling_price",
    "sellprice",
    "pricevalue",
    "price_value",
)


def extract_price_from_meta(
    tags: dict[str, str],
) -> tuple[int | None, str | None]:

    for candidate in META_PRICE_KEYS:

        value = tags.get(
            candidate.lower()
        )

        price = numeric_price(
            value
        )

        if price is not None:

            return (
                price,
                f"meta:{candidate}",
            )

    return None, None


# ============================================================
# LABEL / BODY PRICE
# ============================================================


def extract_price_from_text(
    text: str,
    source_name: str,
) -> tuple[int | None, str | None]:

    if not text:
        return None, None

    # 먼저 "5,000원" 형태
    for match in PRICE_WON_RE.finditer(
        text
    ):

        price = numeric_price(
            match.group(1)
        )

        if price is not None:
            return (
                price,
                f"{source_name}:won",
            )

    # 다음으로 "판매가 5,000" 형태
    for match in PRICE_LABEL_RE.finditer(
        text
    ):

        price = numeric_price(
            match.group(1)
        )

        if price is not None:
            return (
                price,
                f"{source_name}:label",
            )

    return None, None


# ============================================================
# COMPLETE PRICE EXTRACTION
# ============================================================


def extract_price(
    html: str,
    tags: dict[str, str],
    title: str,
    desc: str,
) -> tuple[int | None, str | None]:

    # --------------------------------------------------------
    # 1. JSON-LD
    # --------------------------------------------------------

    price, source = extract_price_from_json(
        html
    )

    if price is not None:
        return price, source

    # --------------------------------------------------------
    # 2. meta
    # --------------------------------------------------------

    price, source = extract_price_from_meta(
        tags
    )

    if price is not None:
        return price, source

    # --------------------------------------------------------
    # 3. itemprop / data-* attributes
    # --------------------------------------------------------

    price, source = extract_price_from_attributes(
        html
    )

    if price is not None:
        return price, source

    # --------------------------------------------------------
    # 4. JavaScript / embedded state
    # --------------------------------------------------------

    scripts = " ".join(
        re.findall(
            r"<script\b[^>]*>(.*?)</script>",
            html,
            flags=re.I | re.S,
        )
    )

    price, source = extract_price_from_text(
        scripts,
        "script",
    )

    if price is not None:
        return price, source

    # --------------------------------------------------------
    # 5. title / description
    # --------------------------------------------------------

    price, source = extract_price_from_text(
        title,
        "title",
    )

    if price is not None:
        return price, source

    price, source = extract_price_from_text(
        desc,
        "description",
    )

    if price is not None:
        return price, source

    # --------------------------------------------------------
    # 6. visible body
    # --------------------------------------------------------

    body = visible_text(
        html
    )

    price, source = extract_price_from_text(
        body,
        "body",
    )

    if price is not None:
        return price, source

    return None, None


# ============================================================
# SEARCH API JSON NORMALIZATION
# ============================================================


def try_json(
    text: str,
):
    try:
        return json.loads(
            text
        )
    except Exception:
        return None


def collect_product_objects(
    value,
):

    if isinstance(
        value,
        dict,
    ):

        # 현재 object 자체도 상품 후보가 될 수 있다.
        yield value

        for child in value.values():
            yield from collect_product_objects(
                child
            )

    elif isinstance(
        value,
        list,
    ):

        for child in value:
            yield from collect_product_objects(
                child
            )


def value_for_keys(
    obj: dict,
    keys: set[str],
):

    for key_name, value in obj.items():

        normalized = (
            str(key_name)
            .replace("-", "_")
            .lower()
        )

        if normalized in keys:
            return value

    return None


PD_KEYS = {
    "pdno",
    "pd_no",
    "productno",
    "product_no",
    "goodsno",
    "goods_no",
    "itemno",
    "item_no",
    "onldpdno",
    "onld_pd_no",
}

NAME_KEYS = {
    "name",
    "productname",
    "product_name",
    "goodsname",
    "goods_name",
    "itemname",
    "item_name",
    "prdname",
    "prd_name",
}

PRICE_KEYS_SEARCH = {
    "price",
    "saleprice",
    "sale_price",
    "sellingprice",
    "selling_price",
    "sellprice",
    "sell_price",
    "goodsprice",
    "goods_price",
    "productprice",
    "product_price",
    "pricevalue",
    "price_value",
    "amount",
    "saleamount",
    "sale_amount",
    "finalprice",
    "final_price",
}

CATEGORY_KEYS = {
    "category",
    "categoryname",
    "category_name",
    "cate",
    "catename",
    "cate_name",
    "goods_category",
    "goodsCategory",
}


def find_matching_search_product(
    payload,
    pd_no: str,
):

    target = normalize_pd_no(
        pd_no
    )

    best = None

    for obj in collect_product_objects(
        payload
    ):

        if not isinstance(
            obj,
            dict,
        ):
            continue

        all_pd_values = []

        for key_name, value in obj.items():

            normalized = (
                str(key_name)
                .replace("-", "_")
                .lower()
            )

            if normalized in PD_KEYS:
                all_pd_values.append(
                    str(value).strip()
                )

        matched = any(
            str(value).strip()
            == target
            for value in all_pd_values
        )

        if not matched:
            continue

        name = value_for_keys(
            obj,
            NAME_KEYS,
        )

        price_raw = value_for_keys(
            obj,
            PRICE_KEYS_SEARCH,
        )

        category = value_for_keys(
            obj,
            CATEGORY_KEYS,
        )

        image = value_for_keys(
            obj,
            {
                "image",
                "imageurl",
                "image_url",
                "img",
                "imgurl",
                "img_url",
                "thumbnail",
                "thumbnailurl",
                "thumbnail_url",
            },
        )

        url = value_for_keys(
            obj,
            {
                "url",
                "producturl",
                "product_url",
                "goodsurl",
                "goods_url",
                "link",
            },
        )

        price = numeric_price(
            price_raw
        )

        # 혹시 price 값이 한 객체 안에서
        # 중첩 구조로 들어오면 다시 전체 object JSON을 검사.
        if price is None:

            serialized = json.dumps(
                obj,
                ensure_ascii=False,
            )

            price, source = extract_price_from_text(
                serialized,
                "search-json",
            )
        else:
            source = "search-json:key"

        score = 0

        if price is not None:
            score += 10

        if name:
            score += 5

        if category:
            score += 2

        if image:
            score += 1

        candidate = {
            "pd_no": target,
            "name": clean_text(
                str(name or "")
            ),
            "price_krw": price,
            "price_source": source,
            "site_category": clean_text(
                str(category or "")
            ),
            "image_url": str(
                image or ""
            ).strip()
            or None,
            "search_url": str(
                url or ""
            ).strip()
            or None,
            "_score": score,
            "_raw": obj,
        }

        if (
            best is None
            or candidate["_score"]
            > best["_score"]
        ):
            best = candidate

    return best


# ============================================================
# DAISO SEARCH FALLBACK
# ============================================================


def search_daiso_product(
    pd_no: str,
) -> tuple[dict | None, dict]:

    target = normalize_pd_no(
        pd_no
    )

    diagnostic = {
        "pd_no": target,
        "attempted": False,
        "endpoint": SEARCH_GOODS,
        "http_status": 0,
        "found": False,
        "price_found": False,
    }

    if not SEARCH_FALLBACK:
        diagnostic["skipped"] = True
        diagnostic["reason"] = (
            "DAISO_SEARCH_FALLBACK=0"
        )
        return None, diagnostic

    params = urllib.parse.urlencode(
        {
            "searchTerm": target,
        }
    )

    url = (
        SEARCH_GOODS
        + "?"
        + params
    )

    diagnostic["attempted"] = True

    status, body, _headers = fetch(
        url
    )

    diagnostic["http_status"] = status
    diagnostic["response_length"] = len(
        body
    )

    if status != 200:
        diagnostic["reason"] = (
            f"HTTP {status}"
        )
        return None, diagnostic

    payload = try_json(
        body
    )

    if payload is not None:

        candidate = find_matching_search_product(
            payload,
            target,
        )

        if candidate:

            diagnostic["found"] = True
            diagnostic["price_found"] = (
                candidate.get("price_krw")
                is not None
            )

            return candidate, diagnostic

    # --------------------------------------------------------
    # JSON이 아니거나 object 구조가 달라진 경우
    # HTML / text 안에서 pdNo + price를 찾는다.
    # --------------------------------------------------------

    target_pos = body.find(
        target
    )

    if target_pos >= 0:

        start = max(
            0,
            target_pos - 10000,
        )

        end = min(
            len(body),
            target_pos + 20000,
        )

        window = body[
            start:end
        ]

        price, price_source = extract_price_from_text(
            window,
            "search-window",
        )

        diagnostic["found"] = True
        diagnostic["price_found"] = (
            price is not None
        )

        if price is not None:

            title_match = re.search(
                r'"(?:name|productName|goodsName|itemName)"\s*:\s*"([^"]+)"',
                window,
                re.I,
            )

            name = (
                clean_text(
                    title_match.group(1)
                )
                if title_match
                else ""
            )

            return (
                {
                    "pd_no": target,
                    "name": name,
                    "price_krw": price,
                    "price_source": price_source,
                    "site_category": "",
                    "image_url": None,
                    "search_url": None,
                    "_score": 1,
                },
                diagnostic,
            )

    diagnostic["reason"] = (
        "상품 번호 매칭 실패"
    )

    return None, diagnostic


# ============================================================
# PRODUCT URL
# ============================================================


def product_url(
    pd_no: str,
) -> str:

    return (
        BASE
        + PRODUCT_PATH
        + "?"
        + urllib.parse.urlencode(
            {
                "pdNo": pd_no,
                "recmYn": "N",
            }
        )
    )


# ============================================================
# SOLD OUT
# ============================================================


SOLDOUT_RE = re.compile(
    r"(일시품절|품절|판매종료|"
    r"재고\s*없음|구매\s*불가|"
    r"판매하지\s*않습니다)",
    re.I,
)


def is_sold_out(
    title: str,
    desc: str,
    body: str,
) -> bool:

    text = (
        f"{title} "
        f"{desc} "
        f"{body}"
    )

    return bool(
        SOLDOUT_RE.search(
            text
        )
    )


# ============================================================
# REVIEW
# ============================================================


REVIEW_RE = re.compile(
    r"리뷰\s*"
    r"([0-9.]+)"
    r"\s*점"
    r"\s*"
    r"\("
    r"\s*"
    r"([0-9,]+)"
    r"\s*건"
    r"\s*\)"
)


def extract_review(
    title: str,
    desc: str,
) -> tuple[float | None, int | None]:

    match = (
        REVIEW_RE.search(desc)
        or REVIEW_RE.search(title)
    )

    if not match:
        return None, None

    try:
        rating = float(
            match.group(1)
        )

        review_count = int(
            match.group(2)
            .replace(",", "")
        )

        return (
            rating,
            review_count,
        )

    except ValueError:
        return None, None


# ============================================================
# PRODUCT TITLE
# ============================================================


def split_title(
    raw_title: str,
) -> tuple[str, str | None, str | None]:

    head = raw_title

    # 사이트 기본 suffix 제거
    head = re.sub(
        r"\s+-\s+다이소몰.*$",
        "",
        head,
        flags=re.I,
    )

    head = head.strip()

    parts = [
        clean_text(part)
        for part in head.split("|")
        if clean_text(part)
    ]

    if not parts:
        return "", None, None

    name = parts[0]

    brand = None
    category = None

    if len(parts) >= 3:
        brand = parts[1]
        category = parts[2]

    elif len(parts) == 2:
        category = parts[1]

    return (
        name,
        brand,
        category,
    )


# ============================================================
# FAILURE STATE
# ============================================================


LAST_FAIL: dict = {}


def set_failure(
    **kwargs,
) -> None:

    LAST_FAIL.clear()
    LAST_FAIL.update(
        kwargs
    )


# ============================================================
# PARSE PRODUCT DETAIL
# ============================================================


def parse_product(
    pd_no: str,
    url: str,
    html: str,
) -> dict | None:

    LAST_FAIL.clear()

    target = normalize_pd_no(
        pd_no
    )

    tags = meta_tags(
        html
    )

    og_title = clean_text(
        tags.get(
            "og:title",
            "",
        )
    )

    meta_title = clean_text(
        tags.get(
            "title",
            "",
        )
    )

    title = (
        og_title
        or meta_title
        or ""
    )

    desc = clean_text(
        tags.get(
            "og:description",
            "",
        )
        or tags.get(
            "description",
            "",
        )
    )

    body = visible_text(
        html
    )

    # --------------------------------------------------------
    # 기본 페이지 / 차단 페이지 여부
    # --------------------------------------------------------

    generic_site = (
        title.casefold()
        in {
            "",
            "다이소몰",
            "daisomall",
            "daiso mall",
        }
    )

    sold_out = is_sold_out(
        title,
        desc,
        body,
    )

    # --------------------------------------------------------
    # 상품명
    # --------------------------------------------------------

    if not title:

        set_failure(
            pd_no=target,
            reason="og:title 없음",
            og_title="",
            og_type=tags.get(
                "og:type",
                "",
            ),
            sold_out=sold_out,
            html_len=len(html),
        )

        return None

    name, brand, category = split_title(
        title
    )

    # 기본 "다이소몰" title일 경우
    # 상세 페이지 실패로 간주하고 search fallback으로 넘긴다.
    if generic_site:

        set_failure(
            pd_no=target,
            reason="상품 상세 HTML이 다이소몰 기본 페이지로 반환됨",
            unavailable=False,
            og_title=title[:160],
            og_type=tags.get(
                "og:type",
                "",
            ),
            sold_out=sold_out,
            html_len=len(html),
        )

        return None

    if not name:

        set_failure(
            pd_no=target,
            reason="상품명 없음",
            og_title=title[:160],
            og_type=tags.get(
                "og:type",
                "",
            ),
            sold_out=sold_out,
            html_len=len(html),
        )

        return None

    # --------------------------------------------------------
    # 가격
    # --------------------------------------------------------

    price, price_source = extract_price(
        html,
        tags,
        title,
        desc,
    )

    if price is None:

        set_failure(
            pd_no=target,
            reason="가격 없음",
            og_title=title[:160],
            og_type=tags.get(
                "og:type",
                "",
            ),
            price_source=None,
            sold_out=sold_out,
            html_len=len(html),
        )

        return None

    # --------------------------------------------------------
    # review
    # --------------------------------------------------------

    rating, review_count = extract_review(
        title,
        desc,
    )

    # --------------------------------------------------------
    # product
    # --------------------------------------------------------

    return {
        "pd_no": target,
        "name": name,
        "brand": brand,
        "site_category": category,
        "price_krw": price,
        "price_source": price_source,
        "sold_out": sold_out,
        "stock_note": (
            "품절 표시 있음"
            if sold_out
            else "판매 중"
        ),
        "stock_checked_at": now_iso(),
        "rating": rating,
        "review_count": review_count,
        "image_url": (
            tags.get(
                "og:image"
            )
            or None
        ),
        "url": url,
        "collected_at": now_iso(),
        "source": (
            "daisomall.co.kr "
            "상품 상세 페이지"
        ),
    }


# ============================================================
# SEARCH FALLBACK MERGE
# ============================================================


def merge_search_fallback(
    detailed: dict | None,
    fallback: dict | None,
) -> dict | None:

    if not fallback:
        return detailed

    if detailed is None:

        return {
            "pd_no": fallback.get(
                "pd_no"
            ),
            "name": fallback.get(
                "name"
            )
            or f"Daiso Product {fallback.get('pd_no')}",
            "brand": None,
            "site_category": fallback.get(
                "site_category"
            )
            or None,
            "price_krw": fallback.get(
                "price_krw"
            ),
            "price_source": fallback.get(
                "price_source"
            )
            or "search-goods",
            "sold_out": False,
            "stock_note": "판매 상태 확인 필요",
            "stock_checked_at": now_iso(),
            "rating": None,
            "review_count": None,
            "image_url": fallback.get(
                "image_url"
            ),
            "url": fallback.get(
                "search_url"
            )
            or product_url(
                fallback.get(
                    "pd_no"
                )
            ),
            "collected_at": now_iso(),
            "source": (
                "daisomall.co.kr "
                "SearchGoods 상품 검색 보조 표면"
            ),
        }

    result = dict(
        detailed
    )

    if not result.get(
        "price_krw"
    ):

        result[
            "price_krw"
        ] = fallback.get(
            "price_krw"
        )

        result[
            "price_source"
        ] = fallback.get(
            "price_source"
        )

    if not result.get(
        "name"
    ):

        result[
            "name"
        ] = fallback.get(
            "name"
        )

    if not result.get(
        "site_category"
    ):

        result[
            "site_category"
        ] = fallback.get(
            "site_category"
        )

    if not result.get(
        "image_url"
    ):

        result[
            "image_url"
        ] = fallback.get(
            "image_url"
        )

    return result


# ============================================================
# CATEGORY CONFIG
# ============================================================


DEFAULT_BUCKETS = {
    "구강용품": [
        "치약",
        "칫솔",
        "가글",
        "구강",
    ],
    "헤어케어": [
        "샴푸",
        "린스",
        "트리트먼트",
        "두피",
        "헤어",
        "hair",
        "shampoo",
        "conditioner",
    ],
    "바디케어": [
        "바디워시",
        "바디 샴푸",
        "바디샴푸",
        "바디로션",
        "핸드크림",
        "샤워젤",
        "body wash",
        "bodywash",
        "body lotion",
        "bodylotion",
        "hand cream",
    ],
    "맨즈케어": [
        "남성",
        "맨즈",
        "맨즈케어",
        "면도",
        "쉐이빙",
        "mens",
        "men's",
    ],
    "향수": [
        "향수",
        "퍼퓸",
        "오드퍼퓸",
        "오드뚜왈렛",
        "perfume",
        "parfum",
    ],
    "클렌징": [
        "클렌징",
        "클렌저",
        "클렌징폼",
        "클렌징 폼",
        "리무버",
        "cleanser",
        "cleansing",
    ],
    "마스크팩": [
        "마스크팩",
        "시트팩",
        "마스크 시트",
        "mask pack",
        "sheet mask",
    ],
    "메이크업": [
        "쿠션",
        "파운데이션",
        "컨실러",
        "블러셔",
        "블러쉬",
        "아이섀도",
        "아이섀도우",
        "마스카라",
        "아이라이너",
        "립스틱",
        "틴트",
        "립밤",
        "메이크업",
        "makeup",
        "foundation",
        "cushion",
        "blush",
    ],
    "뷰티소품": [
        "퍼프",
        "브러시",
        "브러쉬",
        "스펀지",
        "스폰지",
        "화장솜",
        "면봉",
        "뷰티툴",
        "뷰티소품",
        "beauty tool",
    ],
    "스킨케어": [
        "토너",
        "스킨",
        "에센스",
        "세럼",
        "세럼",
        "앰플",
        "크림",
        "로션",
        "모이스처",
        "수분",
        "보습",
        "진정",
        "미백",
        "잡티",
        "탄력",
        "주름",
        "스킨케어",
        "skincare",
        "toner",
        "serum",
        "ampoule",
        "essence",
        "cream",
        "lotion",
    ],
}


EXCLUDED_KEYWORDS = [
    "선케어",
    "선크림",
    "선스틱",
    "선쿠션",
    "sunscreen",
    "네일",
    "매니큐어",
    "페디큐어",
    "nail",
]


def load_category_map() -> dict:

    payload = load_json(
        CATMAP,
        {},
    )

    if not isinstance(
        payload,
        dict,
    ):
        return {}

    return payload


def is_excluded(
    item: dict,
) -> str:

    hay = (
        f"{item.get('site_category') or ''} "
        f"{item.get('name') or ''}"
    ).lower()

    for keyword in EXCLUDED_KEYWORDS:

        if keyword.lower() in hay:
            return keyword

    return ""


def classify_bucket(
    item: dict,
    category_map: dict,
) -> str | None:

    category = (
        item.get(
            "site_category"
        )
        or ""
    )

    name = (
        item.get(
            "name"
        )
        or ""
    )

    hay = (
        f"{category} "
        f"{name}"
    ).lower()

    # 먼저 사용자 정의 category_map
    if isinstance(
        category_map,
        dict,
    ):

        for bucket, spec in category_map.items():

            if str(
                bucket
            ).startswith("_"):
                continue

            if isinstance(
                spec,
                dict,
            ):

                keywords = spec.get(
                    "keywords",
                    [],
                )

            elif isinstance(
                spec,
                list,
            ):

                keywords = spec

            else:
                keywords = []

            if any(
                str(keyword).lower()
                in hay
                for keyword in keywords
            ):
                return str(
                    bucket
                )

    # 기본 규칙
    for bucket, keywords in DEFAULT_BUCKETS.items():

        if any(
            str(keyword).lower()
            in hay
            for keyword in keywords
        ):
            return bucket

    return None


# ============================================================
# SITEMAP
# ============================================================


def parse_xml_urls(
    text: str,
) -> list[str]:

    urls = []

    try:

        root = ET.fromstring(
            text
        )

        for element in root.iter():

            if element.tag.endswith(
                "loc"
            ):

                value = clean_text(
                    element.text
                    or ""
                )

                if value:
                    urls.append(
                        value
                    )

        return urls

    except Exception:

        # XML 파서 fallback
        return re.findall(
            r"<loc>\s*(.*?)\s*</loc>",
            text,
            flags=re.I | re.S,
        )


def product_urls_from_sitemap() -> list[str]:

    status, body, _headers = fetch(
        SITEMAP
    )

    if status != 200:

        return []

    urls = parse_xml_urls(
        body
    )

    return [
        url
        for url in urls
        if PRODUCT_PATH in url
        or "/pd/pdr/" in url
    ]


# ============================================================
# PDNO FROM URL
# ============================================================


def pd_no_from_url(
    url: str,
) -> str | None:

    parsed = urllib.parse.urlparse(
        url
    )

    query = urllib.parse.parse_qs(
        parsed.query
    )

    values = query.get(
        "pdNo"
    )

    if values:
        return normalize_pd_no(
            values[0]
        )

    match = re.search(
        r"[?&]pdNo=([^&]+)",
        url,
        flags=re.I,
    )

    if match:

        return normalize_pd_no(
            urllib.parse.unquote(
                match.group(1)
            )
        )

    return None


# ============================================================
# EXISTING PRODUCT INDEX
# ============================================================


def load_existing_products() -> list[dict]:

    payload = load_json(
        PRODUCTS,
        {},
    )

    if isinstance(
        payload,
        dict,
    ):

        values = payload.get(
            "products",
            [],
        )

        if isinstance(
            values,
            list,
        ):
            return values

    if isinstance(
        payload,
        list,
    ):
        return payload

    return []


def index_existing_products(
    products: list[dict],
) -> dict[str, dict]:

    index = {}

    for item in products:

        if not isinstance(
            item,
            dict,
        ):
            continue

        pd_no = normalize_pd_no(
            item.get(
                "pd_no"
            )
        )

        if pd_no:
            index[pd_no] = item

    return index


# ============================================================
# CRAWL STATE
# ============================================================


def load_state() -> dict:

    payload = load_json(
        STATE,
        {},
    )

    if not isinstance(
        payload,
        dict,
    ):
        return {}

    return payload


def save_state(
    state: dict,
) -> None:

    save_json(
        STATE,
        state,
    )


# ============================================================
# FAILURE RETRY SELECTION
# ============================================================


def previous_failed_ids(
    state: dict,
) -> list[str]:

    values = []

    failed = state.get(
        "failed",
        {},
    )

    if not isinstance(
        failed,
        dict,
    ):
        return []

    for pd_no, info in failed.items():

        if not isinstance(
            info,
            dict,
        ):
            continue

        reason = str(
            info.get(
                "reason",
                "",
            )
        )

        if (
            reason == "가격 없음"
            and RETRY_FAILED
        ):
            values.append(
                str(pd_no)
            )

        elif (
            "구매 불가"
            in reason
            and RETRY_UNAVAILABLE
        ):
            values.append(
                str(pd_no)
            )

    return values


# ============================================================
# BEAUTY QUEUE
# ============================================================


def load_queue_ids() -> list[str]:
    """뷰티 큐에 담긴 pdNo 를 순서대로 돌려준다.

    큐는 build_beauty_queue.py 가 뷰티관 안에서 고른 URL 목록이다.
    사이트맵은 쇼핑몰 전체(19,739건)라 뷰티 적중률이 낮은데
    큐는 뷰티관에서 골라 온 것이라 훨씬 높다.

    그런데 QUEUE 상수가 102줄에 정의만 돼 있고 어디서도 읽히지 않았다.
    큐를 만들어 둬도 수집기가 쓰지 않았다는 뜻이다. 그래서 이 함수를 넣는다.

    큐에는 URL 만 담는다. 이름과 가격은 collect_daiso.py 가 직접 받는다.
    LLM 이 옮긴 숫자를 실측값으로 쓰지 않는다. 큐 파일의 '신뢰' 칸과 같은 약속이다.
    """

    payload = load_json(
        QUEUE,
        {},
    )

    if not isinstance(
        payload,
        dict,
    ):
        return []

    out = []

    seen = set()

    for url in payload.get(
        "urls"
    ) or []:

        pd_no = pd_no_from_url(
            str(url)
        )

        if not pd_no or pd_no in seen:
            continue

        seen.add(
            pd_no
        )

        out.append(
            pd_no
        )

    return out


# ============================================================
# COLLECTION STATS
# ============================================================


def build_totals(
    products: list[dict],
) -> dict:

    by_bucket: dict[str, int] = {}

    price_values = []
    rated = 0

    for item in products:

        bucket = (
            item.get(
                "bucket"
            )
            or item.get(
                "site_category"
            )
            or "미분류"
        )

        by_bucket[bucket] = (
            by_bucket.get(
                bucket,
                0,
            )
            + 1
        )

        price = item.get(
            "price_krw"
        )

        if isinstance(
            price,
            (int, float),
        ) and price > 0:

            price_values.append(
                int(price)
            )

        if item.get(
            "rating"
        ) is not None:

            rated += 1

    avg_price = (
        round(
            sum(price_values)
            / len(price_values)
        )
        if price_values
        else None
    )

    return {
        "products": len(
            products
        ),
        "by_bucket": by_bucket,
        "avg_price_krw": avg_price,
        "price_krw_min": (
            min(price_values)
            if price_values
            else None
        ),
        "price_krw_max": (
            max(price_values)
            if price_values
            else None
        ),
        "with_rating": rated,
    }


# ============================================================
# TARGET BUCKETS
# ============================================================


BUCKET_TARGETS = {
    "구강용품": 3,
    "헤어케어": 18,
    "바디케어": 15,
    "맨즈케어": 5,
    "향수": 7,
    "클렌징": 30,
    "마스크팩": 45,
    "메이크업": 25,
    "뷰티소품": 2,
    "스킨케어": 150,
}


# ============================================================
# MAIN
# ============================================================


def main() -> int:

    started_at = now_iso()

    OUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    existing_products = load_existing_products()

    existing_index = index_existing_products(
        existing_products
    )

    state = load_state()

    category_map = load_category_map()

    sitemap_urls = product_urls_from_sitemap()

    known_ids: list[tuple[str, str]] = []

    seen_ids = set()

    for url in sitemap_urls:

        pd_no = pd_no_from_url(
            url
        )

        if not pd_no:
            continue

        if pd_no in seen_ids:
            continue

        seen_ids.add(
            pd_no
        )

        known_ids.append(
            (
                pd_no,
                url,
            )
        )

    # --------------------------------------------------------
    # 이미 판정이 끝난 상품은 다시 받지 않는다 (2026-09-13)
    #
    # 왜 넣었나. 2026-09-12 21:29 실행을 실측한 결과다.
    #
    #   요청 110건  성공 0건
    #   뷰티 아님으로 버린 것 105건
    #   실패 5건 (전부 구매 불가)
    #   걸린 시간 60분
    #
    # 다이소 사이트맵은 19,739건이고 쇼핑몰 전체다. 뷰티관만 있는 게 아니다.
    # 그런데 후보를 그 앞에서 110개 잘라 왔다. 뷰티일 확률이 낮다.
    #
    # 더 나쁜 것은 이것이다. 뷰티인지 아닌지는 상세 페이지를 받아 봐야 안다.
    # robots.txt 의 Crawl-delay 가 30초다. 그래서 뷰티가 아닌 105건에
    # 30초씩, 52분을 썼다. 받아서 버리려고 쓴 시간이다.
    #
    # crawl_state.json 에 visited 가 1,535건 쌓여 있었다.
    # 이미 한 번 받아 보고 판정한 것들이다. 그런데 후보를 고를 때
    # 그 목록을 보지 않았다. 그래서 같은 자리를 계속 받았다.
    #
    # 이제 본다. 아직 안 본 것부터 준다.
    # 기존 상품의 가격·재고 갱신은 이 경로가 아니라
    # scripts/daiso/recheck_stock.py 가 맡는다. 역할을 섞지 않는다.
    # --------------------------------------------------------

    visited_before = state.get(
        "visited"
    )

    if not isinstance(
        visited_before,
        list,
    ):
        visited_before = []

    visited_set = {
        normalize_pd_no(
            str(x)
        )
        for x in visited_before
    }

    fresh_items = []

    revisit_items = []

    for item in known_ids:

        if item[0] in visited_set:
            revisit_items.append(
                item
            )
        else:
            fresh_items.append(
                item
            )

    skipped_already_visited = len(
        revisit_items
    )

    # --------------------------------------------------------
    # 이전 가격 실패 상품 우선 재시도
    #
    # previous_failed_ids 는 '가격 없음' 과 '구매 불가' 만 돌려준다.
    # '기본 페이지로 반환됨' 은 안 돌려준다. 그건 다이소가 내린 상품이라
    # 몇 번을 더 받아도 같은 답이 온다.
    # --------------------------------------------------------

    failed_ids = previous_failed_ids(
        state
    )

    priority_items = []

    normal_items = []

    failed_id_set = set(
        failed_ids
    )

    for item in fresh_items:

        if item[0] in failed_id_set:
            priority_items.append(
                item
            )
        else:
            normal_items.append(
                item
            )

    # 재시도 대상은 이미 본 쪽에도 있을 수 있다. 그것만 되살린다.
    retry_seen = [
        item
        for item in revisit_items
        if item[0] in failed_id_set
    ]

    ordered_items = (
        retry_seen
        + priority_items
        + normal_items
    )

    # --------------------------------------------------------
    # 뷰티 큐가 차 있으면 그것부터 본다
    #
    # QUEUE 는 102줄에 정의만 돼 있고 아무 데서도 읽지 않았다.
    # build_beauty_queue.py 가 만들어 둬도 쓰이지 않았다는 뜻이다.
    # 큐는 뷰티관 안에서 고른 URL 이라 적중률이 사이트맵보다 훨씬 높다.
    # --------------------------------------------------------

    queue_ids = load_queue_ids()

    queue_size = len(
        queue_ids
    )

    queue_revisit: list[tuple[str, str]] = []

    if queue_ids:

        url_by_id = {
            pid: url
            for pid, url in known_ids
        }

        queued_items = []

        # 큐에 있는데 이미 본 것. 큐를 다 돌았을 때 다시 받을 대상이다.
        # 사이트맵 쪽 revisit_items 를 쓰면 안 된다. 거기에는 뷰티가
        # 아니라고 판정한 것들이 섞여 있어서 다시 받으면 또 버린다.
        queue_revisit = []

        for pid in queue_ids:

            item = (
                pid,
                url_by_id.get(
                    pid
                )
                or product_url(
                    pid
                ),
            )

            if pid in visited_set:
                queue_revisit.append(
                    item
                )
                continue

            queued_items.append(
                item
            )

        # 큐가 있으면 큐만 쓴다. 뒤에 사이트맵을 붙이지 않는다.
        #
        # 처음에는 큐 뒤에 사이트맵을 이어 붙였다. 큐가 3,572건이라
        # 한 회차 110건이면 사이트맵까지 갈 일이 없다고 봤다.
        # 그런데 큐가 줄면 그 순간 사이트맵이 새어 들어온다.
        # 그러면 다시 받아 보고 버리는 일이 생긴다.
        #
        # 받아 보고 버리는 것이 문제의 전부였다. 110건 중 105건,
        # Crawl-delay 30 으로 52분이다. 그 문을 열어 두지 않는다.
        #
        # queued_items 가 비어도 url_source 는 queue 로 둔다.
        # '큐가 비었다' 와 '큐를 다 봤다' 는 다른 상태다.
        # 전에 이 둘을 같이 다뤄서, 큐를 다 본 경우에 재방문을 못 하고
        # 사이트맵 안내문만 찍고 0건으로 끝났다. 시험 4번이 그걸 잡았다.
        ordered_items = queued_items
        url_source = "queue"

    else:
        url_source = "sitemap"

    # --------------------------------------------------------
    # 큐가 비었을 때 사이트맵으로 되돌아가지 않는다
    #
    # 사용자가 정확히 이것을 지적했다.
    #   "뷰티 아니라 버림 105건 << 수집 자체를 하면 안되는건데
    #    시간낭비잖아 이미지 카테고리 저것만 해달라고 했는데"
    #
    # 맞는 말이다. 뷰티관 밖 상품은 받을 이유가 없다.
    # 그런데 큐가 비면 예전처럼 사이트맵 19,739건을 앞에서부터 훑는다.
    # 그 순간 다시 뷰티 아닌 것을 받아 보고 버린다.
    #
    # 그래서 큐가 비면 사이트맵으로 안 간다. 아무것도 안 받고 멈춘다.
    # 조용히 0건을 내는 것이 아니라 왜 0건인지 적고 멈춘다.
    # 큐를 고치라는 신호다. 낭비하며 버티는 것보다 낫다.
    #
    # 정말 사이트맵이 필요하면 DAISO_ALLOW_SITEMAP=1 로 켠다.
    # 기본은 꺼져 있다.
    # --------------------------------------------------------

    if url_source == "sitemap" and not ALLOW_SITEMAP:

        print(
            "큐가 비어 있다. 사이트맵으로 되돌아가지 않는다.\n"
            "  사이트맵은 쇼핑몰 전체 19,739건이라 뷰티 적중률이 낮다.\n"
            "  2026-09-12 에 110건을 받아 105건을 버렸다. "
            "Crawl-delay 30 이라 52분이다.\n"
            "  scripts/daiso/build_beauty_queue.py 를 먼저 돌려 큐를 채운다.\n"
            "  그래도 사이트맵을 쓰려면 DAISO_ALLOW_SITEMAP=1 로 켠다."
        )

        ordered_items = []

    # --------------------------------------------------------
    # 안 본 것이 하나도 없으면 굶지 않는다
    #
    # 큐를 다 돌면 fresh 가 빈다. 그때 아무것도 안 하면
    # 수집기가 조용히 0건을 내놓는다. 고장과 구분이 안 된다.
    # 그래서 이미 본 것 중에서 다시 본다. 이것은 전부 뷰티관 상품이라
    # 받아 보고 버리는 낭비가 아니다. 가격과 재고를 새로 받는 것이다.
    # --------------------------------------------------------

    exhausted = (
        not ordered_items
        and url_source != "sitemap"
    )

    if exhausted:

        # 큐를 쓰는 중이면 큐 안에서만 다시 받는다.
        # 사이트맵 쪽 revisit_items 에는 뷰티가 아니라고 판정한 것이
        # 섞여 있다. 그것을 다시 받으면 또 버린다. 같은 낭비다.
        ordered_items = (
            queue_revisit
            if url_source.startswith("queue")
            else revisit_items
        )

        url_source = (
            url_source
            + "+재방문"
        )

        print(
            f"큐에 안 본 상품이 없다. "
            f"이미 본 것 {len(ordered_items)}건 중에서 다시 받는다."
        )

    # --------------------------------------------------------
    # MAX_ITEMS
    # --------------------------------------------------------

    candidates = ordered_items[
        :MAX_ITEMS
    ]

    print(
        f"후보 선정: 사이트맵 {len(known_ids)}건 중 "
        f"이미 판정한 {skipped_already_visited}건 제외, "
        f"큐 {queue_size}건, "
        f"이번에 받을 것 {len(candidates)}건 "
        f"(출처 {url_source})"
    )

    requested = len(
        candidates
    )

    ok_count = 0
    parse_failed = 0
    http_error = 0
    sold_out_count = 0

    skipped_not_beauty = 0
    skipped_bucket_full = 0

    skipped_excluded: dict[str, int] = {}

    parse_fail_reasons: dict[str, int] = {}

    parse_fail_samples: list[dict] = []

    fallback_used = 0
    fallback_price_fixed = 0

    fallback_diagnostics = []

    visited = 0

    # 현재 이미 있는 bucket count
    bucket_counts: dict[str, int] = {}

    for item in existing_products:

        if not isinstance(
            item,
            dict,
        ):
            continue

        bucket = item.get(
            "bucket"
        )

        if bucket:

            bucket_counts[
                bucket
            ] = (
                bucket_counts.get(
                    bucket,
                    0,
                )
                + 1
            )

    # --------------------------------------------------------
    # crawl
    # --------------------------------------------------------

    for index, (
        pd_no,
        url,
    ) in enumerate(
        candidates,
        start=1,
    ):

        visited += 1

        if index > 1:

            time.sleep(
                max(
                    0.0,
                    DELAY
                    + random.uniform(
                        0,
                        1.5,
                    ),
                )
            )

        print(
            f"[{index}/{requested}] "
            f"pdNo={pd_no}"
        )

        # ----------------------------------------------------
        # 1. 상세 페이지
        # ----------------------------------------------------

        status, html, headers = fetch(
            url
        )

        detailed = None

        if status == 200:

            detailed = parse_product(
                pd_no,
                url,
                html,
            )

            if detailed:

                bucket = classify_bucket(
                    detailed,
                    category_map,
                )

                excluded_reason = is_excluded(
                    detailed
                )

                if excluded_reason:

                    skipped_excluded[
                        excluded_reason
                    ] = (
                        skipped_excluded.get(
                            excluded_reason,
                            0,
                        )
                        + 1
                    )

                    print(
                        "  ↳ excluded:",
                        excluded_reason,
                    )

                    continue

                if not bucket:

                    skipped_not_beauty += 1

                    print(
                        "  ↳ not beauty"
                    )

                    continue

                # bucket을 꽉 채운 상태면 추가 저장하지 않는다.
                target = BUCKET_TARGETS.get(
                    bucket
                )

                if (
                    target is not None
                    and bucket_counts.get(
                        bucket,
                        0,
                    )
                    >= target
                    and pd_no
                    not in existing_index
                ):

                    skipped_bucket_full += 1

                    print(
                        "  ↳ bucket full:",
                        bucket,
                    )

                    continue

                detailed[
                    "bucket"
                ] = bucket

                detailed[
                    "detailed_http_status"
                ] = status

                existing_index[
                    pd_no
                ] = detailed

                bucket_counts[
                    bucket
                ] = (
                    bucket_counts.get(
                        bucket,
                        0,
                    )
                    + 1
                )

                ok_count += 1

                if detailed.get(
                    "sold_out"
                ):
                    sold_out_count += 1

                print(
                    "  ↳ OK",
                    detailed.get(
                        "price_krw"
                    ),
                    detailed.get(
                        "price_source"
                    ),
                )

                continue

        else:

            if status:
                http_error += 1

        # ----------------------------------------------------
        # 2. SearchGoods fallback
        # ----------------------------------------------------

        fallback = None
        fallback_diag = {
            "pd_no": pd_no,
            "detail_http_status": status,
            "detail_parse_failed": detailed
            is None,
        }

        if SEARCH_FALLBACK:

            # 검색 fallback은 요청 사이에도
            # robots delay 원칙을 따른다.
            time.sleep(
                max(
                    0.0,
                    DELAY,
                )
            )

            fallback, diag = search_daiso_product(
                pd_no
            )

            fallback_diag[
                "search"
            ] = diag

            fallback_diagnostics.append(
                fallback_diag
            )

        if fallback:

            fallback_used += 1

            fixed = merge_search_fallback(
                detailed,
                fallback,
            )

            # search 결과에 가격이 있어야 성공
            if (
                fixed
                and fixed.get(
                    "price_krw"
                )
                is not None
            ):

                bucket = classify_bucket(
                    fixed,
                    category_map,
                )

                excluded_reason = is_excluded(
                    fixed
                )

                if excluded_reason:

                    skipped_excluded[
                        excluded_reason
                    ] = (
                        skipped_excluded.get(
                            excluded_reason,
                            0,
                        )
                        + 1
                    )

                    print(
                        "  ↳ fallback excluded:",
                        excluded_reason,
                    )

                    continue

                if not bucket:

                    skipped_not_beauty += 1

                    print(
                        "  ↳ fallback not beauty"
                    )

                    continue

                fixed[
                    "bucket"
                ] = bucket

                fixed[
                    "fallback_used"
                ] = True

                fixed[
                    "detailed_http_status"
                ] = status

                # 기존 상세 페이지 parse가 실패한 경우
                # fallback source로 명시
                if (
                    not fixed.get(
                        "price_source"
                    )
                ):
                    fixed[
                        "price_source"
                    ] = (
                        "search-goods"
                    )

                existing_index[
                    pd_no
                ] = fixed

                bucket_counts[
                    bucket
                ] = (
                    bucket_counts.get(
                        bucket,
                        0,
                    )
                    + 1
                )

                ok_count += 1
                fallback_price_fixed += 1

                print(
                    "  ↳ FALLBACK OK",
                    fixed.get(
                        "name"
                    ),
                    fixed.get(
                        "price_krw"
                    ),
                    fixed.get(
                        "price_source"
                    ),
                )

                continue

        # ----------------------------------------------------
        # 3. 최종 실패
        # ----------------------------------------------------

        parse_failed += 1

        failure = dict(
            LAST_FAIL
        )

        reason = (
            failure.get(
                "reason"
            )
            or "가격 없음"
        )

        parse_fail_reasons[
            reason
        ] = (
            parse_fail_reasons.get(
                reason,
                0,
            )
            + 1
        )

        if len(
            parse_fail_samples
        ) < 20:

            parse_fail_samples.append(
                {
                    "pd_no": pd_no,
                    "reason": reason,
                    "og_title": failure.get(
                        "og_title"
                    ),
                    "sold_out": failure.get(
                        "sold_out"
                    ),
                    "fallback_attempted": bool(
                        fallback_diag
                    ),
                }
            )

        state.setdefault(
            "failed",
            {},
        )[
            pd_no
        ] = {
            "reason": reason,
            "updated_at": now_iso(),
            "detail_http_status": status,
            "detail_url": url,
            "diagnostic": failure,
            "fallback": fallback_diag,
        }

        print(
            "  ↳ FAILED:",
            reason,
        )

    # ========================================================
    # SAVE PRODUCTS
    # ========================================================

    final_products = list(
        existing_index.values()
    )

    # 중복 제거
    dedup: dict[str, dict] = {}

    for item in final_products:

        pd_no = normalize_pd_no(
            item.get(
                "pd_no"
            )
        )

        if pd_no:
            dedup[
                pd_no
            ] = item

    final_products = list(
        dedup.values()
    )

    # 안정적인 정렬
    final_products.sort(
        key=lambda item: (
            str(
                item.get(
                    "bucket"
                )
                or ""
            ),
            str(
                item.get(
                    "name"
                )
                or ""
            ),
            str(
                item.get(
                    "pd_no"
                )
                or ""
            ),
        )
    )

    save_json(
        PRODUCTS,
        {
            "updated_at": now_iso(),
            "source": "Daiso Korea",
            "count": len(
                final_products
            ),
            "products": final_products,
        },
    )

    # ========================================================
    # STATE
    # ========================================================

    # 이번에 받아 본 pd_no 를 visited 에 더한다 (2026-09-13)
    #
    # crawl_state.json 에 visited 목록이 1,535건 있었는데
    # 이 스크립트는 그것을 읽지도 쓰지도 않았다. visited 라는 이름의
    # 지역 변수는 그냥 이번 회차 건수를 세는 정수였다. 이름만 같았다.
    #
    # 그래서 판정 결과가 다음 회차로 넘어가지 않았다.
    # 어제 뷰티가 아니라고 버린 105건을 오늘 또 30초씩 받는다.
    # 이제 더해 둔다. 위 후보 선정이 이것을 보고 거른다.

    visited_after = list(
        visited_set
    )

    for pd_no, _url in candidates:
        if pd_no not in visited_set:
            visited_set.add(
                pd_no
            )
            visited_after.append(
                pd_no
            )

    state[
        "visited"
    ] = sorted(
        visited_after
    )

    state[
        "updated_at"
    ] = now_iso()

    state[
        "last_run"
    ] = {
        "started_at": started_at,
        "finished_at": now_iso(),
        "requested": requested,
        "visited": visited,
        "skipped_already_visited": skipped_already_visited,
        "visited_total": len(
            visited_after
        ),
        "queue_size": queue_size,
        "url_source": url_source,
        "ok": ok_count,
        "parse_failed": parse_failed,
        "http_error": http_error,
        "sold_out": sold_out_count,
        "fallback_used": fallback_used,
        "fallback_price_fixed": fallback_price_fixed,
        "parse_fail_reasons": parse_fail_reasons,
        "parse_fail_samples": parse_fail_samples,
        "fallback_diagnostics": fallback_diagnostics[
            :50
        ],
        "sitemap_urls_known": len(
            sitemap_urls
        ),
        "scope": (
            "다이소몰 뷰티관(C245) "
            "10개 카테고리 "
            "(선케어·네일 제외)"
        ),
        "delay_seconds": DELAY,
        "max_items": MAX_ITEMS,
        "search_fallback": SEARCH_FALLBACK,
        "user_agent": UA,
        "robots_note": (
            "robots.txt 기준 "
            "상품 경로 /pd/pdr/ "
            "Crawl-delay 30초"
        ),
        "bucket_targets": BUCKET_TARGETS,
        "status": "ok",
    }

    save_state(
        state
    )

    # ========================================================
    # TOTALS
    # ========================================================

    totals = build_totals(
        final_products
    )

    # ========================================================
    # COLLECTION STATUS
    # ========================================================

    by_bucket = totals.get(
        "by_bucket",
        {},
    )

    categories = {}

    for bucket, count in by_bucket.items():

        bucket_prices = []

        for item in final_products:

            current_bucket = (
                item.get(
                    "bucket"
                )
                or item.get(
                    "site_category"
                )
                or "미분류"
            )

            if current_bucket != bucket:
                continue

            price = item.get(
                "price_krw"
            )

            if isinstance(
                price,
                (int, float),
            ) and price > 0:

                bucket_prices.append(
                    int(price)
                )

        categories[
            bucket
        ] = {
            "count": count,
            "avg_price_krw": (
                round(
                    sum(bucket_prices)
                    / len(
                        bucket_prices
                    )
                )
                if bucket_prices
                else None
            ),
            "min_price_krw": (
                min(bucket_prices)
                if bucket_prices
                else None
            ),
            "max_price_krw": (
                max(bucket_prices)
                if bucket_prices
                else None
            ),
        }

    status_payload = load_json(
        STATUS,
        {},
    )

    if not isinstance(
        status_payload,
        dict,
    ):
        status_payload = {}

    status_payload[
        "last_run"
    ] = {
        "started_at": started_at,
        "requested": requested,
        "ok": ok_count,
        "parse_failed": parse_failed,
        "http_error": http_error,
        "sold_out": sold_out_count,
        "parse_fail_reasons": parse_fail_reasons,
        "parse_fail_samples": parse_fail_samples,
        "fallback_used": fallback_used,
        "fallback_price_fixed": fallback_price_fixed,
        "skipped_not_beauty": skipped_not_beauty,
        "skipped_bucket_full": skipped_bucket_full,
        "skipped_excluded": skipped_excluded,
        "pruned_existing": {},
        # 2026-09-13 이전에는 이 두 칸이 0 과 "sitemap" 로 박혀 있었다.
        # 실행이 무엇을 썼는지와 상관없이 늘 같은 값을 적었다.
        # 큐를 붙여도 보고가 그대로라 붙었는지 알 수 없었다. 실측으로 바꾼다.
        "queue_size": queue_size,
        "url_source": url_source,
        # 사이트맵에 있지만 이미 판정이 끝나 이번에 안 받은 것.
        # 이 값이 커지는 것이 정상이다. 같은 자리를 다시 안 판다는 뜻이다.
        "skipped_already_visited": skipped_already_visited,
        "scope": (
            "다이소몰 뷰티관(C245) "
            "10개 카테고리 "
            "(선케어·네일 제외)"
        ),
        "delay_seconds": DELAY,
        "max_items": MAX_ITEMS,
        "user_agent": UA,
        "robots_note": (
            "robots.txt: "
            "User-agent * → Allow /pd/pdr/, "
            "Crawl-delay 30"
        ),
        "finished_at": now_iso(),
        "bucket_targets": BUCKET_TARGETS,
        "buckets_short": {
            key: by_bucket.get(
                key,
                0,
            )
            for key in (
                "헤어케어",
                "바디케어",
                "클렌징",
                "마스크팩",
                "스킨케어",
            )
        },
        "status": "ok",
    }

    status_payload[
        "totals"
    ] = {
        "products": totals[
            "products"
        ],
        "bucket_targets": BUCKET_TARGETS,
        "by_bucket": by_bucket,
        "categories": categories,
        "avg_price_krw": totals[
            "avg_price_krw"
        ],
        "price_krw_min": totals[
            "price_krw_min"
        ],
        "price_krw_max": totals[
            "price_krw_max"
        ],
        "with_rating": totals[
            "with_rating"
        ],
    }

    # sitemap 정보
    status_payload[
        "sitemap_urls_known"
    ] = len(
        sitemap_urls
    )

    status_payload[
        "visited"
    ] = visited

    save_json(
        STATUS,
        status_payload,
    )

    # ========================================================
    # REPORT
    # ========================================================

    print()
    print("=" * 70)
    print("DAISO COLLECTION RESULT")
    print("=" * 70)
    print(
        f"products total       : {len(final_products)}"
    )
    print(
        f"requested            : {requested}"
    )
    print(
        f"ok                   : {ok_count}"
    )
    print(
        f"parse_failed         : {parse_failed}"
    )
    print(
        f"http_error           : {http_error}"
    )
    print(
        f"fallback_used        : {fallback_used}"
    )
    print(
        f"fallback_price_fixed : {fallback_price_fixed}"
    )
    print(
        f"price failures       : {parse_fail_reasons.get('가격 없음', 0)}"
    )
    print(
        f"sitemap urls         : {len(sitemap_urls)}"
    )
    print("=" * 70)

    if parse_fail_samples:

        print()
        print(
            "Remaining failures:"
        )

        for item in parse_fail_samples:
            print(
                f" - {item['pd_no']}: "
                f"{item['reason']}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
