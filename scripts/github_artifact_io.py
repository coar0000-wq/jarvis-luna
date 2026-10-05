"""Bounded GitHub artifact reads. Never log tokens or signed download URLs.

The caller owns authorization of run/repository/commit lineage and artifact
content. TLS GitHub metadata plus digest-bound bytes, not payload flags, vouch
for the transport. This module never writes source data or calls providers.
"""
from __future__ import annotations
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

REPOSITORY = 'coar0000-wq/jarvis-luna'
API_ORIGIN = 'https://api.github.com'
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 4 * 1024 * 1024


class ArtifactReadBlocked(ValueError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _api_url(url, *, artifact=False):
    parsed = urllib.parse.urlsplit(url)
    prefix = '/repos/' + REPOSITORY + '/actions/'
    if (parsed.scheme != 'https' or parsed.netloc != 'api.github.com'
            or parsed.username or parsed.password or parsed.fragment
            or not parsed.path.startswith(prefix)):
        raise ArtifactReadBlocked('github_repository_scope_required')
    if artifact and (parsed.query or not re.fullmatch(re.escape(prefix) + r'artifacts/[1-9][0-9]*/zip', parsed.path)):
        raise ArtifactReadBlocked('exact_artifact_download_endpoint_required')
    return parsed


def _storage_url(url):
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ''
    allowed = any(host.endswith(suffix) for suffix in (
        '.blob.core.windows.net', '.s3.amazonaws.com', '.actions.githubusercontent.com',
        '.githubusercontent.com'))
    if (parsed.scheme != 'https' or not allowed or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.fragment):
        raise ArtifactReadBlocked('untrusted_artifact_redirect')


def _headers():
    headers = {'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28',
               'User-Agent': 'JARVIS-source-safety/1'}
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    return headers


def _bounded(response, cap):
    if response.status != 200:
        raise ArtifactReadBlocked('github_read_not_successful')
    declared = response.headers.get('Content-Length')
    if declared:
        try:
            if not 0 <= int(declared) <= cap:
                raise ArtifactReadBlocked('github_read_size_limit')
        except ValueError:
            raise ArtifactReadBlocked('github_read_invalid_length') from None
    data = response.read(cap + 1)
    if len(data) > cap:
        raise ArtifactReadBlocked('github_read_size_limit')
    return data


def fetch_github_json(url):
    _api_url(url)
    opener = urllib.request.build_opener(_NoRedirect())
    try:
        with opener.open(urllib.request.Request(url, headers=_headers()), timeout=30) as response:
            data = _bounded(response, MAX_JSON_BYTES)
        return json.loads(data)
    except (urllib.error.URLError, OSError, ValueError):
        raise ArtifactReadBlocked('github_metadata_unavailable') from None


def fetch_artifact_bytes(url):
    _api_url(url, artifact=True)
    opener = urllib.request.build_opener(_NoRedirect())
    request = urllib.request.Request(url, headers=_headers())
    try:
        try:
            with opener.open(request, timeout=30) as response:
                return _bounded(response, MAX_ARCHIVE_BYTES)
        except urllib.error.HTTPError as error:
            if error.code not in (301, 302, 303, 307, 308):
                raise ArtifactReadBlocked('github_artifact_unavailable') from None
            location = error.headers.get('Location')
            error.close()
            if not location:
                raise ArtifactReadBlocked('github_artifact_redirect_missing')
        _storage_url(location)
        # A new request has NO GitHub Authorization, API version or cookie header.
        # A second redirect is denied rather than forwarding a signed URL/token.
        storage_request = urllib.request.Request(location, headers={'User-Agent': 'JARVIS-source-safety/1'})
        with opener.open(storage_request, timeout=45) as response:
            return _bounded(response, MAX_ARCHIVE_BYTES)
    except (urllib.error.URLError, OSError, ValueError):
        raise ArtifactReadBlocked('github_artifact_transport_blocked') from None
