from __future__ import annotations

import re
import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from typing import Any, Mapping
from urllib.parse import urlparse

import requests


ABOUT_ACCOUNT_URL = 'https://i.instagram.com/api/v1/bloks/apps/com.instagram.interactions.about_this_account/'
ABOUT_ACCOUNT_BLOKS_VERSION = '8ca96ca267e30c02cf90888d91eeff09627f0e3fd2bd9df472278c9a6c022cbb'


def _instagram_cookies() -> dict[str, str]:
    cookies = {}
    sessionid = os.getenv('INSTAGRAM_SESSIONID') or os.getenv('IG_SESSIONID')
    if sessionid:
        cookies['sessionid'] = sessionid.strip()
    for name in ('csrftoken', 'ds_user_id', 'mid', 'ig_did'):
        value = os.getenv(f'INSTAGRAM_{name.upper()}') or os.getenv(f'IG_{name.upper()}')
        if value:
            cookies[name] = value.strip()
    return cookies


def _instagram_headers() -> dict[str, str]:
    return {
        'x-ig-app-id': '936619743392459',
        'User-Agent': 'Instagram 390.0.0.0.50 Android',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
    }


def _fetch_instagram_html_with_playwright(url: str, username: str) -> str:
    """Windows-only browser fallback; the existing Linux HTML parser remains authoritative."""
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36',
                    extra_http_headers={'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'},
                )
                page = context.new_page()
                response = page.goto(url, wait_until='networkidle', timeout=30000)
                status = response.status if response else None
                print(f'Playwright usado no Windows para @{username}; status HTML={status}')
                page.wait_for_timeout(3000)
                html_content = page.content()
                print(f'HTML Instagram recebido no Windows para @{username}: {len(html_content)} bytes')
                return html_content
            finally:
                browser.close()
    except Exception as exc:
        print(f'Playwright falhou no Windows para @{username}: {exc}')
        return ''


@dataclass
class IntegrationResult:
    ok: bool
    message: str
    data: dict[str, Any]


def normalize_instagram_bio(value: Any) -> str:
    """Deprecated compatibility helper; Bio values are now passed through unchanged."""
    return str(value or '')


def normalize_instagram_reference(source: str) -> dict[str, str]:
    value = str(source or '').strip()
    if not value:
        raise ValueError('Informe um @handle ou URL pública do Instagram.')
    if value.startswith('@'):
        username = value[1:]
    elif value.startswith(('http://', 'https://')):
        parsed = urlparse(value)
        if (parsed.hostname or '').lower().removeprefix('www.') != 'instagram.com':
            raise ValueError('Use uma URL pública do Instagram, por exemplo https://www.instagram.com/conta/.')
        username = next((part for part in parsed.path.split('/') if part and not part.startswith(('p', 'reel', 'tv'))), '')
    else:
        username = value
    username = username.strip().lstrip('@').split('/', 1)[0]
    if not re.fullmatch(r'[A-Za-z0-9._]{1,64}', username):
        raise ValueError('O @handle Instagram contém caracteres inválidos.')
    return {'username': username, 'handle': f'@{username}', 'url': f'https://www.instagram.com/{username}/'}


def _meta(document: str, name: str) -> str:
    patterns = (
        rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']*)',
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:name|property)=["\']{re.escape(name)}["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, document, flags=re.IGNORECASE)
        if match:
            return unescape(match.group(1)).strip()
    return ''


def _structured_metric(document: str, *keys: str) -> int | None:
    """Read numeric Instagram counters embedded in the public HTML payload."""
    document = unescape(document)
    for key in keys:
        patterns = (
            rf'\\?["\']{re.escape(key)}\\?["\']\s*:\s*\{{[^}}]{{0,240}}?\\?["\']count\\?["\']\s*:\s*(\d+)',
            rf'\\?["\']{re.escape(key)}\\?["\']\s*:\s*(\d+)',
        )
        for pattern in patterns:
            found = re.search(pattern, document, flags=re.IGNORECASE)
            if found:
                try:
                    return int(found.group(1))
                except ValueError:
                    continue
    return None


def _structured_metric_from_json(document: str, *keys: str) -> int | None:
    wanted = {key.casefold() for key in keys}
    for parsed in _embedded_json_documents(document):
        for node in _walk_json(parsed):
            if not isinstance(node, dict):
                continue
            for key, value in node.items():
                if str(key).casefold() not in wanted:
                    continue
                if isinstance(value, dict):
                    value = value.get('count') or value.get('value')
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
    return None


def _extract_posts_from_html(document: str, limit: int = 10) -> list[dict[str, Any]]:
    posts: list[dict[str, Any]] = []
    seen: set[str] = set()
    wanted_limit = max(1, int(limit))

    def add_node(node: Any) -> bool:
        if not isinstance(node, dict):
            return False
        post = _post_from_node(node)
        if not post or post['id'] in seen:
            return False
        seen.add(post['id'])
        posts.append(post)
        return len(posts) >= wanted_limit

    for payload in _embedded_json_documents(document):
        for node in _walk_json(payload):
            if not isinstance(node, dict):
                continue
            media = node.get('edge_owner_to_timeline_media')
            if isinstance(media, Mapping):
                edges = media.get('edges') or media.get('items') or []
                for edge in edges:
                    candidate = edge.get('node') if isinstance(edge, dict) else edge
                    if add_node(candidate):
                        return posts
            if add_node(node):
                return posts
    return posts


def _metric_text_value(value: Any) -> int | None:
    if isinstance(value, Mapping):
        value = value.get('count') or value.get('value')
    text = str(value or '').strip().casefold().replace(' ', '')
    if not text:
        return None
    multiplier = 1
    if text.endswith(('k', 'mil')):
        multiplier = 1000
        text = text[:-1] if text.endswith('k') else text[:-3]
    elif text.endswith(('m', 'mi', 'milhões')):
        multiplier = 1_000_000
        text = text[:-1] if text.endswith('m') else text[:-2] if text.endswith('mi') else text[:-7]
    digits = re.sub(r'[^0-9]', '', text)
    if not digits:
        return None
    return int(digits) * multiplier


def _extract_bio_from_html(document: str) -> str:
    """Extract only the JSON biography value; never use an SEO description as Bio."""
    patterns = (
        r'"biography"\s*:\s*"((?:\\.|[^"\\])*)"',
        r"'biography'\s*:\s*'((?:\\.|[^'\\])*)'",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, document, flags=re.IGNORECASE | re.DOTALL):
            raw_value = match.group(1)
            try:
                decoded = json.loads(f'"{raw_value}"')
            except (TypeError, ValueError, json.JSONDecodeError):
                decoded = bytes(raw_value, 'utf-8').decode('unicode_escape')
            if str(decoded or '').strip():
                return str(decoded).strip()
    return ''


def _embedded_profile_user(document: str, username: str) -> Mapping[str, Any]:
    wanted = str(username or '').strip().lstrip('@').casefold()
    for payload in _embedded_json_documents(document):
        for node in _walk_json(payload):
            if not isinstance(node, Mapping):
                continue
            node_username = str(node.get('username') or node.get('handle') or '').strip().lstrip('@').casefold()
            has_profile_fields = any(key in node for key in ('biography', 'bio', 'edge_followed_by', 'edge_follow', 'followers', 'following'))
            if node_username == wanted and has_profile_fields:
                return node
    return {}


def _extract_profile_user_from_html(document: str, username: str) -> dict[str, Any]:
    embedded_user = _embedded_profile_user(document, username)
    regex_biography = _extract_bio_from_html(document)
    seo_description = _meta(document, 'og:description')
    biography = str(embedded_user.get('biography') or embedded_user.get('bio') or regex_biography or '').strip()
    print(f'embedded_user for @{username}: {embedded_user}')
    print(f'biography extracted for @{username}: {biography!r}')
    description = biography or seo_description
    title = str(embedded_user.get('full_name') or embedded_user.get('name') or _meta(document, 'og:title') or username).split('(')[0].strip() or username
    avatar_url = str(embedded_user.get('profile_pic_url_hd') or embedded_user.get('profile_pic_url') or _meta(document, 'og:image')).strip()

    def metric(patterns: tuple[str, ...]) -> int | None:
        for pattern in patterns:
            found = re.search(pattern, seo_description, flags=re.IGNORECASE)
            if found:
                parsed = _metric_text_value(found.group(1) + (found.group(2) or ''))
                if parsed is not None:
                    return parsed
        return None

    followers = _metric_text_value(embedded_user.get('edge_followed_by')) or _metric_text_value(embedded_user.get('followers')) or metric((r'([\d.,]+)\s*(k|mil)?\s*(?:followers|seguidores)', r'(?:followers|seguidores)\s*([\d.,]+)\s*(k|mil)?')) or _structured_metric(document, 'edge_followed_by', 'followers', 'follower_count') or _structured_metric_from_json(document, 'edge_followed_by', 'followers', 'follower_count', 'followerCount')
    following = _metric_text_value(embedded_user.get('edge_follow')) or _metric_text_value(embedded_user.get('following')) or metric((r'([\d.,]+)\s*(k|mil)?\s*(?:following|seguindo)', r'(?:following|seguindo)\s*([\d.,]+)\s*(k|mil)?')) or _structured_metric(document, 'edge_follow', 'follows', 'following', 'following_count', 'followingCount') or _structured_metric_from_json(document, 'edge_follow', 'follows', 'following', 'following_count', 'followingCount')
    post_count = _metric_text_value(embedded_user.get('edge_owner_to_timeline_media')) or _metric_text_value(embedded_user.get('posts')) or metric((r'([\d.,]+)\s*(k|mil)?\s*(?:posts|publicações|publications)', r'(?:posts|publicações|publications)\s*([\d.,]+)\s*(k|mil)?')) or _structured_metric(document, 'edge_owner_to_timeline_media', 'posts', 'post_count')
    country = _country_value(embedded_user.get('country') or embedded_user.get('country_code')) or extract_public_instagram_country(embedded_user)
    if not country:
        for payload in _embedded_json_documents(document):
            country = extract_public_instagram_country(payload)
            if country:
                break
    posts = _extract_posts_from_html(document, 10)
    user: dict[str, Any] = {
        'username': username,
        'full_name': title.split('(')[0].strip() or username,
        'biography': description,
        'edge_followed_by': {'count': followers} if followers is not None else {},
        'edge_follow': {'count': following} if following is not None else {},
        'edge_owner_to_timeline_media': {'count': post_count, 'edges': [{'node': post} for post in posts]},
        'country': country,
        'profile_pic_url': avatar_url,
        '_html_posts': posts,
    }
    return user if any((description, followers, following, post_count, country, posts)) else {}


def _fetch_web_profile_user(username: str) -> dict[str, Any] | None:
    headers = _instagram_headers()
    if platform.system() == 'Windows':
        headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
        })
    # The www host is the current public web endpoint. The legacy i host is
    # retained as a fallback because Instagram rate-limits the two hosts
    # independently and their availability can vary by region.
    endpoints = (
        f'https://www.instagram.com/api/v1/users/web_profile_info/?username={username}',
        f'https://i.instagram.com/api/v1/users/web_profile_info/?username={username}',
    )
    def profile_quality(user: Mapping[str, Any]) -> int:
        return sum(bool(user.get(key)) for key in ('biography', 'edge_follow', 'edge_followed_by', 'edge_owner_to_timeline_media', 'username'))

    def merge_profile(base: dict[str, Any] | None, candidate: Mapping[str, Any]) -> dict[str, Any]:
        merged = dict(base or {})
        for key, value in candidate.items():
            if value not in (None, '', [], {}):
                if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value
        return merged

    def profile_is_complete(user: Mapping[str, Any]) -> bool:
        if profile_quality(user) < 4:
            return False
        if platform.system() != 'Windows':
            return True
        has_bio = bool(str(user.get('biography') or user.get('bio') or '').strip())
        has_following = any(user.get(key) not in (None, '', {}, []) for key in ('edge_follow', 'follows', 'following', 'following_count', 'followingCount'))
        return has_bio and has_following

    best_user: dict[str, Any] | None = None
    for endpoint in endpoints:
        try:
            if platform.system() == 'Windows':
                print(f'Instagram API Windows: URL chamada: {endpoint}')
            response = requests.get(endpoint, headers=headers, timeout=15)
            if platform.system() == 'Windows':
                response_text = str(getattr(response, 'text', '') or '')
                print(f'Instagram API Windows: status={response.status_code}; tamanho={len(response_text)}; início={response_text[:500]!r}')
            if response.status_code >= 400:
                if platform.system() == 'Windows':
                    print(f'Instagram API Windows: HTTP {response.status_code}; a tentar o próximo endpoint/fallback.')
                continue
            payload = response.json()
        except (requests.RequestException, ValueError, AttributeError) as exc:
            if platform.system() == 'Windows':
                print(f'Instagram API Windows: erro ao consultar/parsing {endpoint}: {exc}')
            continue
        user = ((payload.get('data') or {}).get('user') if isinstance(payload, dict) else None)
        if isinstance(user, dict):
            best_user = merge_profile(best_user, user)
            if profile_is_complete(best_user):
                return best_user

    curl = shutil.which('curl')
    if curl:
        for endpoint in endpoints:
            try:
                completed = subprocess.run(
                    [curl, '-L', '--max-time', '20', '-sS', '-A', headers['User-Agent'], '-H', f"x-ig-app-id: {headers['x-ig-app-id']}", '-H', 'Accept', 'application/json, text/plain, */*', endpoint],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    timeout=25,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                payload = json.loads(completed.stdout) if completed.returncode == 0 and completed.stdout else None
                user = ((payload.get('data') or {}).get('user') if isinstance(payload, dict) else None)
                if isinstance(user, dict):
                    best_user = merge_profile(best_user, user)
                    if profile_quality(best_user) >= 4:
                        return best_user
            except (OSError, subprocess.SubprocessError, ValueError):
                continue
    if platform.system() == 'Windows':
        html_content = _fetch_instagram_html_with_playwright(f'https://www.instagram.com/{username}/', username)
        if html_content:
            html_user = _extract_profile_user_from_html(html_content, username)
            if html_user:
                print(f'Perfil Instagram extraído do HTML no Windows para @{username}')
                return html_user
    return best_user


def _country_from_bloks(value: Any) -> str:
    if isinstance(value, Mapping):
        data_key = str(value.get('key') or '').casefold()
        if data_key in PUBLIC_COUNTRY_KEYS:
            serialized = value.get('initial_lispy') or value.get('value')
            if isinstance(serialized, str) and 'bk.action.array.Make' in serialized:
                country = _country_value(serialized.rsplit('bk.action.array.Make,', 1)[-1].split(')', 1)[0].replace('\\"', '"').replace('"', '').strip())
            else:
                country = _country_value(serialized)
            if country:
                return country
        for key, candidate in value.items():
            if str(key).casefold() in PUBLIC_COUNTRY_KEYS:
                if isinstance(candidate, str) and 'bk.action.array.Make' in candidate:
                    country = _country_value(candidate.rsplit('bk.action.array.Make,', 1)[-1].split(')', 1)[0].replace('\\"', '"').replace('"', '').strip())
                else:
                    country = _country_value(candidate)
                if country:
                    return country
            country = _country_from_bloks(candidate)
            if country:
                return country
    elif isinstance(value, list):
        for candidate in value:
            country = _country_from_bloks(candidate)
            if country:
                return country
    elif isinstance(value, str) and 'about_this_account_country' in value:
        marker = 'bk.action.array.Make,'
        if marker in value:
            country = value.rsplit(marker, 1)[-1].split(')', 1)[0].replace('\\"', '"').replace('"', '').strip()
            return _country_value(country)
    return ''


def _fetch_instagram_about_country(user_id: Any) -> str:
    cookies = _instagram_cookies()
    if not cookies or not str(user_id or '').strip():
        return ''
    payload = {
        'referer_type': 'ProfileUsername',
        'target_user_id': str(user_id),
        'bk_client_context': json.dumps({'bloks_version': ABOUT_ACCOUNT_BLOKS_VERSION, 'style_id': 'instagram'}, separators=(',', ':')),
        'bloks_versioning_id': ABOUT_ACCOUNT_BLOKS_VERSION,
    }
    try:
        response = requests.post(ABOUT_ACCOUNT_URL, data=payload, headers=_instagram_headers(), cookies=cookies, timeout=20)
        if response.status_code >= 400:
            return ''
        return _country_from_bloks(response.json())
    except (requests.RequestException, ValueError, TypeError):
        return ''


def _profile_data_from_api(user: Mapping[str, Any], reference: Mapping[str, str]) -> dict[str, Any]:
    followers = _profile_metric(user, 'edge_followed_by', 'followers', 'follower_count', 'followerCount')
    following = _profile_metric(user, 'edge_follow', 'follows', 'following', 'following_count', 'followingCount')
    followers = followers if followers is not None else _structured_metric_from_json(json.dumps(user), 'edge_followed_by', 'followers', 'follower_count', 'followerCount')
    following = following if following is not None else _structured_metric_from_json(json.dumps(user), 'edge_follow', 'follows', 'following', 'following_count', 'followingCount')
    media = ((user.get('edge_owner_to_timeline_media') or {}).get('count') if isinstance(user.get('edge_owner_to_timeline_media'), dict) else None)
    biography = str(user.get('biography') or '').strip()
    country = extract_public_instagram_country(user) or _fetch_instagram_about_country(user.get('id') or user.get('pk'))
    return {
        'id': f"instagram_{reference['username']}",
        **reference,
        'name': str(user.get('full_name') or user.get('username') or reference['username']).strip(),
        'bio': biography,
        'bio_raw': biography,
        'country': country,
        'avatar_url': str(user.get('profile_pic_url_hd') or user.get('profile_pic_url') or '').strip(),
        'subscriber_count': followers,
        'following_count': following,
        'post_count': media,
        'is_private': bool(user.get('is_private')),
        'public_lookup': True,
        'metrics_source': 'instagram_web_profile_info',
        'last_public_lookup_at': datetime.now(timezone.utc).isoformat(),
        '_api_posts': (((user.get('edge_owner_to_timeline_media') or {}).get('edges') or []) if isinstance(user.get('edge_owner_to_timeline_media'), dict) else []),
    }


def normalize_instagram_metric(value: Any) -> int | None:
    """Normalize an Instagram counter without turning an unknown value into zero."""
    if isinstance(value, Mapping):
        value = value.get('count') or value.get('value')
    if value in (None, ''):
        return None
    digits = re.sub(r'[^0-9]', '', str(value))
    return int(digits) if digits else None


PUBLIC_COUNTRY_KEYS = {
    'about_this_account_country', 'account_based_in', 'account_country', 'country_name',
    'country_of_origin', 'country_of_registration', 'location_country', 'transparency_country',
}
PUBLIC_TRANSPARENCY_KEYS = {'about', 'about_account', 'account_transparency', 'transparency', 'account_info'}


def _country_value(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ('name', 'label', 'display_name', 'country', 'country_name', 'code'):
            candidate = str(value.get(key) or '').strip()
            if candidate and not candidate.isdigit() and len(candidate) <= 80:
                return candidate
        return ''
    candidate = str(value or '').strip()
    return candidate if candidate and not candidate.isdigit() and len(candidate) <= 80 else ''


def extract_public_instagram_country(value: Any) -> str:
    """Read only the account-country field exposed by Instagram transparency data."""
    if isinstance(value, Mapping):
        for key, candidate in value.items():
            if str(key).casefold() in PUBLIC_COUNTRY_KEYS:
                country = _country_value(candidate)
                if country:
                    return country
        for key, candidate in value.items():
            if str(key).casefold() in PUBLIC_TRANSPARENCY_KEYS:
                country = extract_public_instagram_country(candidate)
                if country:
                    return country
    elif isinstance(value, list):
        for candidate in value:
            country = extract_public_instagram_country(candidate)
            if country:
                return country
    return ''


def _profile_metric(user: Mapping[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = normalize_instagram_metric(user.get(key))
        if value is not None:
            return value
    return None


def fetch_public_instagram_profile(source: str) -> IntegrationResult:
    try:
        reference = normalize_instagram_reference(source)
    except ValueError as exc:
        return IntegrationResult(False, str(exc), {})
    api_user = _fetch_web_profile_user(reference['username'])
    if api_user:
        return IntegrationResult(True, 'Perfil Instagram encontrado publicamente.', _profile_data_from_api(api_user, reference))
    if platform.system() == 'Windows':
        return IntegrationResult(False, 'Não foi possível encontrar o perfil público estruturado do Instagram.', reference)
    try:
        response = requests.get(reference['url'], headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8'}, timeout=12)
    except requests.RequestException as exc:
        return IntegrationResult(False, f'Não foi possível consultar o perfil público do Instagram: {exc}', reference)
    if response.status_code >= 400:
        return IntegrationResult(False, f'O Instagram devolveu HTTP {response.status_code}. Confirme o @handle ou use o cadastro manual.', reference | {'status_code': response.status_code})
    title = _meta(response.text, 'og:title') or reference['username']
    description = _meta(response.text, 'og:description')
    avatar_url = _meta(response.text, 'og:image')
    def metric(patterns: tuple[str, ...]) -> int | None:
        for pattern in patterns:
            found = re.search(pattern, description, flags=re.IGNORECASE)
            if not found:
                continue
            try:
                return int(re.sub(r'[^0-9]', '', found.group(1)))
            except ValueError:
                continue
        return None

    followers = metric((r'([\d,.]+)\s*(?:mil\s+)?(?:followers|seguidores)',)) or _structured_metric(response.text, 'edge_followed_by', 'followers', 'follower_count') or _structured_metric_from_json(response.text, 'edge_followed_by', 'followers', 'follower_count', 'followerCount')
    following = metric((r'([\d,.]+)\s*(?:mil\s+)?(?:following|seguindo)',)) or _structured_metric(response.text, 'edge_follow', 'follows', 'following', 'following_count', 'followingCount') or _structured_metric_from_json(response.text, 'edge_follow', 'follows', 'following', 'following_count', 'followingCount')
    posts = metric((r'([\d,.]+)\s*(?:mil\s+)?(?:posts|publicações|publications)',)) or _structured_metric(response.text, 'edge_owner_to_timeline_media', 'posts', 'post_count')
    embedded_country = ''
    for document in _embedded_json_documents(response.text):
        embedded_country = extract_public_instagram_country(document)
        if embedded_country:
            break
    data = {'id': f"instagram_{reference['username']}", **reference, 'name': title.split('(')[0].strip() or reference['username'], 'bio': description, 'bio_raw': description, 'country': embedded_country, 'avatar_url': avatar_url, 'subscriber_count': followers, 'following_count': following, 'post_count': posts, 'public_lookup': True, 'metrics_source': 'instagram_public_page', 'last_public_lookup_at': datetime.now(timezone.utc).isoformat()}
    return IntegrationResult(True, 'Perfil Instagram encontrado publicamente.', data)


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _embedded_json_documents(document: str) -> list[Any]:
    decoder = json.JSONDecoder()
    documents: list[Any] = []
    for script in re.findall(r'<script[^>]*>(.*?)</script>', document, flags=re.IGNORECASE | re.DOTALL):
        candidate = script.strip()
        if not candidate:
            continue
        for start in [0] + [match.start() for match in re.finditer(r'[\[{]', candidate)][:20]:
            try:
                parsed, _ = decoder.raw_decode(candidate[start:])
            except (json.JSONDecodeError, TypeError):
                continue
            documents.append(parsed)
            break
    return documents


def _post_from_node(node: dict[str, Any]) -> dict[str, Any] | None:
    shortcode = str(node.get('shortcode') or node.get('code') or '').strip()
    media_id = str(node.get('id') or '').strip()
    image_url = str(node.get('display_url') or node.get('thumbnail_src') or node.get('image') or '').strip()
    if not shortcode and not media_id:
        return None
    if not image_url and not node.get('is_video'):
        return None
    caption_value = node.get('caption') or node.get('title') or ''
    if isinstance(caption_value, dict):
        caption_value = caption_value.get('text') or ''
    edges = node.get('edge_media_to_caption')
    if isinstance(edges, dict):
        edge_list = edges.get('edges') or []
        if edge_list and isinstance(edge_list[0], dict):
            caption_value = ((edge_list[0].get('node') or {}).get('text') or caption_value)
    url = str(node.get('permalink') or node.get('url') or '').strip()
    if not url and shortcode:
        url = f'https://www.instagram.com/p/{shortcode}/'
    return {
        'id': media_id or shortcode,
        'shortcode': shortcode,
        'url': url,
        'image_url': image_url,
        'caption': str(caption_value or '').strip(),
        'published_at': node.get('taken_at_timestamp') or node.get('taken_at') or '',
        'is_video': bool(node.get('is_video') or node.get('video_url')),
    }



def _fetch_posts_with_ytdlp(username: str, limit: int = 10) -> list[dict[str, Any]]:
    """Fetch public Instagram post metadata with the installed yt-dlp CLI."""
    import subprocess

    url = f'https://www.instagram.com/{username}/'
    cmd = [
        'yt-dlp', '--dump-json', '--no-download', '--flat-playlist',
        '--playlist-end', str(max(1, int(limit))), url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode != 0:
            print(f'yt-dlp erro para @{username}: {result.stderr.strip()}')
            return []
        posts: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            post_id = str(data.get('id') or '').strip()
            post_url = str(data.get('webpage_url') or data.get('url') or '').strip()
            shortcode = post_id or (post_url.rstrip('/').split('/')[-1] if post_url else '')
            if not shortcode and not post_id:
                continue
            timestamp = data.get('timestamp') or data.get('release_timestamp') or ''
            thumbnail = str(data.get('thumbnail') or '').strip()
            posts.append({
                'id': post_id or shortcode,
                'shortcode': shortcode,
                'url': post_url or f'https://www.instagram.com/p/{shortcode}/',
                'image_url': thumbnail,
                'display_url': thumbnail,
                'caption': str(data.get('description') or data.get('title') or '').strip(),
                'published_at': timestamp,
                'timestamp': timestamp,
                'is_video': bool(data.get('vcodec') not in (None, 'none')),
            })
        posts = posts[:max(1, int(limit))]
        print(f'yt-dlp sucesso para @{username}: {len(posts)} posts')
        return posts
    except Exception as exc:
        print(f'yt-dlp exceção para @{username}: {exc}')
        return []


def fetch_public_instagram_posts(source: str, limit: int = 10) -> IntegrationResult:
    try:
        reference = normalize_instagram_reference(source)
    except ValueError as exc:
        return IntegrationResult(False, str(exc), {})
    if platform.system() == 'Windows':
        print(f'Posts Windows: a iniciar consulta pública API/HTML para @{reference["username"]}')
    api_user = _fetch_web_profile_user(reference['username'])
    if api_user:
        api_posts: list[dict[str, Any]] = []
        for edge in ((api_user.get('edge_owner_to_timeline_media') or {}).get('edges') or []):
            node = edge.get('node') if isinstance(edge, dict) else None
            if isinstance(node, dict):
                post = _post_from_node(node)
                if post:
                    api_posts.append(post)
        if api_posts:
            return IntegrationResult(True, 'Posts públicos encontrados.', reference | {'posts': api_posts[:max(1, int(limit))]})
        if api_user.get('is_private'):
            return IntegrationResult(False, 'Esta conta é privada. O Instagram não disponibiliza posts sem uma sessão autenticada.', reference | {'posts': [], 'is_private': True})
        if platform.system() == 'Windows':
            html_posts = api_user.get('_html_posts') or []
            print(f'Posts no user inicial para @{reference["username"]}: {len(html_posts)}')
            if html_posts:
                return IntegrationResult(True, 'Posts públicos encontrados.', reference | {'posts': html_posts[:max(1, int(limit))]})
    if platform.system() == 'Windows':
        html_content = _fetch_instagram_html_with_playwright(reference['url'], reference['username'])
        html_user = _extract_profile_user_from_html(html_content, reference['username']) if html_content else {}
        media = html_user.get('edge_owner_to_timeline_media') if isinstance(html_user, Mapping) else {}
        edges = media.get('edges') if isinstance(media, Mapping) else []
        print(f'JSON do perfil extraído no Windows para @{reference["username"]}: {bool(html_user)}; edges encontrados: {len(edges or [])}')
        posts: list[dict[str, Any]] = []
        for edge in edges or []:
            node = edge.get('node') if isinstance(edge, Mapping) else edge
            if isinstance(node, dict):
                post = _post_from_node(node)
                if post:
                    posts.append(post)
        if not posts:
            posts = _extract_posts_from_html(html_content, limit) if html_content else []
        posts = posts[:max(1, int(limit))]
        print(f'Posts extraídos no Windows para @{reference["username"]}: {len(posts)}')
        if not posts and html_content:
            try:
                os.makedirs('storage', exist_ok=True)
                with open('storage/debug_posts.html', 'w', encoding='utf-8', errors='replace') as debug_file:
                    debug_file.write(html_content)
                print(f'HTML de debug dos posts guardado em storage/debug_posts.html para @{reference["username"]}')
            except OSError as exc:
                print(f'Não foi possível guardar storage/debug_posts.html: {exc}')
        return IntegrationResult(bool(posts), 'Posts públicos encontrados.' if posts else 'Não foi possível encontrar posts públicos nesta página do Instagram.', reference | {'posts': posts})
    try:
        response = requests.get(reference['url'], headers={'User-Agent': 'Mozilla/5.0', 'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8'}, timeout=15)
    except requests.RequestException as exc:
        return IntegrationResult(False, f'Não foi possível consultar os posts públicos do Instagram: {exc}', reference)
    if response.status_code >= 400:
        return IntegrationResult(False, f'O Instagram devolveu HTTP {response.status_code} ao consultar os posts.', reference | {'status_code': response.status_code})
    posts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for document in _embedded_json_documents(response.text):
        for node in _walk_json(document):
            post = _post_from_node(node)
            if not post or post['id'] in seen:
                continue
            seen.add(post['id'])
            posts.append(post)
            if len(posts) >= max(1, int(limit)):
                break
        if len(posts) >= max(1, int(limit)):
            break
    return IntegrationResult(bool(posts), 'Posts públicos encontrados.' if posts else 'Não foi possível encontrar posts públicos nesta página do Instagram.', reference | {'posts': posts[:max(1, int(limit))]})


__all__ = ['IntegrationResult', 'extract_public_instagram_country', 'fetch_public_instagram_posts', 'fetch_public_instagram_profile', 'normalize_instagram_bio', 'normalize_instagram_metric', 'normalize_instagram_reference']
