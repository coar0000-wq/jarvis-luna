"""Offline image selection and safe access-stop diagnostics for official GOSI HTML.

Selecting actual image elements prevents video sources being treated as JPGs.
This module never fetches, changes access identity, or resets a provider stop.
"""
from __future__ import annotations

from html.parser import HTMLParser
from datetime import datetime
import re
from urllib.parse import urljoin, urlsplit, unquote
from urllib.error import HTTPError

IMAGE_MIMES = frozenset(('image/jpeg', 'image/png', 'image/webp', 'image/gif',
                        'image/bmp', 'image/tiff', 'image/avif'))
IMAGE_EXT = re.compile(r'\.(?:jpe?g|png|webp|gif|bmp|tiff?|avif)(?:/|$)', re.I)
VIDEO_EXT = re.compile(r'\.(?:mp4|webm|mov|m4v|avi|m3u8|mpd|svg)(?:/|$)', re.I)
SOURCE_HOSTS = frozenset(('www.daisomall.co.kr', 'cdn.daisomall.co.kr'))
DIAGNOSTIC_HOSTS = SOURCE_HOSTS | {'fapi.daisomall.co.kr'}


def image_url(value, base_url):
    """Resolve ordinary relative references; never strip CDN transforms/query."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if any(ord(c) < 32 for c in value) or '\\' in value:
        return None
    try:
        url = urljoin(base_url, value)
        p = urlsplit(url)
        if (p.scheme != 'https' or p.hostname not in SOURCE_HOSTS or
                p.username or p.password or p.port not in (None, 443) or
                VIDEO_EXT.search(unquote(p.path))):
            return None
    except ValueError:
        return None
    return url


def srcset_urls(value):
    """Read URL tokens without splitting commas embedded in a URL query."""
    rest = value or ''
    result = []
    while rest:
        rest = rest.lstrip(' \t\r\n\f,')
        if not rest:
            break
        match = re.match(r'\S+', rest)
        url = match.group()
        rest = rest[match.end():]
        if url.endswith(','):
            url, descriptor = url.rstrip(','), ''
        else:
            descriptor, _, rest = rest.partition(',')
            descriptor = descriptor.strip()
        if not descriptor:
            result.append((1.0, url))
        elif re.fullmatch(r'(?:[1-9][0-9]*w|(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)x)', descriptor):
            weight = float(descriptor[:-1])
            if weight > 0:
                result.append((weight, url))
    return result


class _Images(HTMLParser):
    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.urls = []
        self.pictures = []
        self.video_depth = 0

    def choose(self, attrs, *, source=False):
        for key in ('data-src', 'data-original', 'data-lazy-src'):
            url = image_url(attrs.get(key), self.base_url)
            if url:
                return url
        for key in ('data-srcset', 'srcset'):
            for _, value in sorted(srcset_urls(attrs.get(key)), reverse=True):
                url = image_url(value, self.base_url)
                if url and (not source or (attrs.get('type') or '').lower() in IMAGE_MIMES or IMAGE_EXT.search(urlsplit(url).path)):
                    return url
        return image_url(attrs.get('src'), self.base_url) if not source else None

    def handle_starttag(self, tag, pairs):
        attrs = dict(pairs)
        if tag == 'video':
            self.video_depth += 1
        elif tag == 'picture' and not self.video_depth:
            self.pictures.append({'sources': [], 'image_found': False})
        elif tag == 'source' and self.pictures and not self.video_depth:
            mime = (attrs.get('type') or '').lower()
            if mime and mime not in IMAGE_MIMES:
                return
            url = self.choose(attrs, source=True)
            if url:
                self.pictures[-1]['sources'].append(url)
        elif tag == 'img' and not self.video_depth:
            sources = self.pictures[-1]['sources'] if self.pictures else []
            url = sources[0] if sources else self.choose(attrs)
            if url:
                self.urls.append(url)
                if self.pictures:
                    self.pictures[-1]['image_found'] = True

    def handle_endtag(self, tag):
        if tag == 'video':
            self.video_depth = max(0, self.video_depth - 1)
        elif tag == 'picture' and self.pictures:
            picture = self.pictures.pop()
            if not picture['image_found'] and picture['sources']:
                self.urls.append(picture['sources'][0])


def image_candidates(raw_html, base_url):
    parser = _Images(base_url)
    parser.feed(raw_html)
    parser.close()
    # One candidate per image, de-duplicated. No fallback requests after denial.
    return list(dict.fromkeys(parser.urls))


def diagnostic_url(value):
    """Retain only known public Daiso routes; omit identity/query/fragment data."""
    try:
        p = urlsplit(str(value))
        host = p.hostname
    except ValueError:
        return '[redacted]'
    if host not in DIAGNOSTIC_HOSTS:
        return '[redacted]'
    path = p.path
    api = re.fullmatch(r'/pd/pdr/pdDtl/selPdDtl(?:Ntfc|Desc)', path)
    media = re.fullmatch(
        r'/file/PD/[0-9]{8}/[A-Za-z0-9_-]{1,140}\.(?:jpg|jpeg|png|webp|gif|bmp|tiff|avif|mp4)'
        r'(?:/dims(?:/(?:resize/[0-9]{1,5}(?:x[0-9]{1,5})?|quality/(?:100|[0-9]{1,2})|format/(?:webp|jpg|png)|strip/true))+'
        r'|/xcdr/preset/_mute_360p(?:/xcdr/preset/_mp42webm/options/video\.codec=vp9/\.webm/faststart/true)?)?',
        path, re.I)
    if not (api or media):
        path = '/[redacted]'
    return 'https://' + host + path


def denial_diagnostic(exc, url, method, stage, observed_at):
    """No response bodies, cookies, auth headers, session IDs, or IPs are stored."""
    code = exc.code if isinstance(exc, HTTPError) else None
    code = code if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599 else None
    headers = getattr(exc, 'headers', None)
    mime = str(headers.get('Content-Type', '')).split(';')[0].strip().lower() if headers else ''
    retry_after = str(headers.get('Retry-After', '')).strip() if headers else ''
    result = {'url': diagnostic_url(url), 'method': method, 'stage': stage,
              'observed_at': observed_at, 'http_status': code,
              'response_content_type': mime if mime in IMAGE_MIMES | {'application/json', 'text/html', 'text/plain'} else 'unknown',
              'response_body_saved': False, 'raw_headers_saved': False}
    if retry_after.isdigit() and len(retry_after) <= 6 and int(retry_after) <= 604800:
        result['retry_after_seconds'] = int(retry_after)
    return result


def valid_denial_diagnostic(value):
    """Bound the new persisted field without loosening other history rules."""
    if not isinstance(value, dict) or not isinstance(value.get('stage'), str) or value.get('stage') not in {'notice_api', 'description_api', 'detail_image'}:
        return False
    if set(value) == {'stage', 'diagnostic_unavailable'}:
        return value['diagnostic_unavailable'] is True
    keys = {'url', 'method', 'stage', 'observed_at', 'http_status',
            'response_content_type', 'response_body_saved', 'raw_headers_saved'}
    if not keys <= set(value) or set(value) - keys - {'retry_after_seconds'}:
        return False
    if not isinstance(value['url'], str) or value['url'] != diagnostic_url(value['url']):
        return False
    if not isinstance(value['method'], str) or value['method'] not in {'GET', 'POST'}:
        return False
    code = value['http_status']
    if code is not None and (type(code) is not int or not 100 <= code <= 599):
        return False
    if not isinstance(value['response_content_type'], str) or value['response_content_type'] not in IMAGE_MIMES | {'application/json', 'text/html', 'text/plain', 'unknown'}:
        return False
    if value['response_body_saved'] is not False or value['raw_headers_saved'] is not False:
        return False
    try:
        at = value['observed_at']
        if not isinstance(at, str) or len(at) > 64 or datetime.fromisoformat(at.replace('Z', '+00:00')).tzinfo is None:
            return False
    except ValueError:
        return False
    if 'retry_after_seconds' in value:
        seconds = value['retry_after_seconds']
        if type(seconds) is not int or not 0 <= seconds <= 604800:
            return False
    return True
