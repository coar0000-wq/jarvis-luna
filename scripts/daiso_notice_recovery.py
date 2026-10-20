"""Free deterministic notice recovery. OCR is evidence, never verified label data."""
import hashlib
import time


def rendered_notice(pd_no, max_scroll=60):
    from playwright.sync_api import sync_playwright
    from daiso.collect_gosi_alt import PAGE, UA, parse_alt
    images, reached_bottom = [], False
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(locale="ko-KR", user_agent=UA)
            page.goto(PAGE.format(pd_no), timeout=60000, wait_until="domcontentloaded")
            button = page.locator('button:has-text("상품설명 더보기")')
            try:
                button.first.wait_for(state="visible", timeout=15000)
            except Exception:
                pass
            if button.count():
                button.first.click(timeout=8000)
            last, stable = -1, 0
            for _ in range(min(80, max(1, max_scroll))):
                page.mouse.wheel(0, 1600)
                page.wait_for_timeout(900)
                # Only expanded product detail, never recommendation/banner images.
                rows = page.locator('div.editor-content img').evaluate_all(
                    "els=>els.map(e=>({url:e.currentSrc||e.src,alt:e.getAttribute('alt')||''}))")
                for row in rows:
                    if '/description/' in row['url'] and row['url'] not in [r['url'] for r in images]:
                        images.append(row)
                    elif row['alt']:
                        for old in images:
                            if old['url'] == row['url']:
                                old['alt'] = row['alt']
                height, bottom = page.evaluate('()=>{const e=document.scrollingElement;return [e.scrollHeight,e.scrollTop+e.clientHeight]}')
                stable = stable + 1 if height == last else 0
                last = height
                if bottom >= height - 80 and stable >= 2:
                    reached_bottom = True
                    break
        finally:
            browser.close()
    text = '\n\n'.join(row['alt'] for row in images)
    return {'fields': parse_alt(text), 'images': images, 'reached_bottom': reached_bottom,
            'alt_sha256': hashlib.sha256(text.encode()).hexdigest()}


def ocr_notice(images, max_images=3, budget_sec=90):
    """Bottom notice first; bounded two-attempt local OCR, raw evidence only."""
    from daiso.localize_detail_images import ensure_ocr_ready, download, _tess
    from daiso.collect_gosi_alt import parse_alt
    ensure_ocr_ready()
    end = time.monotonic() + min(120, max(1, budget_sec))
    out = []
    for row in list(reversed(images))[:min(6, max(0, max_images))]:
        if time.monotonic() >= end:
            break
        try:
            data = download(row['url'])
            text = _tess(['-l', 'kor+eng', '--psm', '6'], data, 30, deadline=end).decode('utf-8', 'replace')
            out.append({'url': row['url'], 'image_sha256': hashlib.sha256(data).hexdigest(),
                        'text': text, 'candidate_fields': parse_alt(text), 'review_required': True})
        except Exception as exc:
            out.append({'url': row['url'], 'error': type(exc).__name__, 'review_required': True})
    return out
