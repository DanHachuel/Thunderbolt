import json
from unittest.mock import Mock, patch

from app.social_networks_ui import _metric, _persist_instagram_posts, _profile_bio
from integrations import instagram_public


HTML = '''
<meta property="og:title" content="Creator (@creator)">
<meta property="og:description" content="123 followers, 456 following and 2 posts">
<meta property="og:image" content="https://img.example/avatar.jpg">
<script type="application/json">
{"edge_followed_by":{"count":123},"edge_follow":{"count":456},"edge_owner_to_timeline_media":{"count":2,"edges":[{"node":{"id":"post-1","shortcode":"ABC","display_url":"https://img.example/post.jpg","edge_media_to_caption":{"edges":[{"node":{"text":"Legenda"}}]}}}]}}
</script>
'''

BRUNO_HTML = '''
<meta property="og:title" content="Bruno Francisco - IA | Marketing (@brun0gpt)">
<meta property="og:description" content="227K seguidores, seguindo 241, 2,277 posts — Veja as fotos e vídeos de Bruno Francisco - IA | Marketing (@brun0gpt)">
<script type="application/json">
{"username":"brun0gpt","full_name":"Bruno Francisco - IA | Marketing","biography":"🤖 Marketing e Vendas com Inteligência Artificial\\n🧑🏻‍💻 Tá cansado de usar IA no modo amador?\\n👉🏻 Acabou de chegar no lugar pra mudar isso\\n👇🏻 Segue aí\\nbrunogpt.com.br/simbiose-criativa","edge_followed_by":{"count":227000},"edge_follow":{"count":241},"edge_owner_to_timeline_media":{"count":2277}}
</script>
'''

SEO_ONLY_HTML = '''
<meta property="og:title" content="Bruno Francisco - IA | Marketing (@brun0gpt)">
<meta property="og:description" content="227K seguidores, seguindo 241, 2,277 posts — Veja as fotos e vídeos de Bruno Francisco - IA | Marketing (@brun0gpt)">
'''

REGEX_BIO_HTML = '''<script>var data = {"biography":"🤖 Marketing e Vendas com Inteligência Artificial\\n🧑🏻‍💻 Tá cansado de usar IA no modo amador?"};</script>'''

POST_NODES = ','.join(
    '{"node":{"id":"post-{0}","shortcode":"CODE{0}","display_url":"https://img.example/post-{0}.jpg","edge_media_to_caption":{"edges":[{"node":{"text":"Legenda {0}"}}]}}}'.replace('{0}', str(index))
    for index in range(1, 11)
)
POSTS_HTML = f'<script type="application/json">{{"edge_owner_to_timeline_media":{{"edges":[{POST_NODES}]}}}}</script>'


def test_persist_posts_writes_instagram_posts_json():
    posts = [{"id": "post-1", "shortcode": "CODE1", "image_url": "https://img.example/post-1.jpg", "url": "https://www.instagram.com/p/CODE1/"}]
    with patch("app.social_networks_ui.read_json", return_value={}) as read_json, patch("app.social_networks_ui.write_json") as write_json:
        _persist_instagram_posts({"id": "instagram_brun0gpt", "username": "brun0gpt"}, posts)
    read_json.assert_called_once_with("instagram_posts.json", {})
    write_json.assert_called_once()
    assert write_json.call_args.args[0] == "instagram_posts.json"
    assert write_json.call_args.args[1]["instagram_brun0gpt"][0]["shortcode"] == "CODE1"


def test_fetch_posts_with_ytdlp_maps_metadata():
    stdout = "\n".join(json.dumps({
        "id": "ABC123",
        "webpage_url": "https://www.instagram.com/p/ABC123/",
        "thumbnail": "https://img.example/abc.jpg",
        "description": "Legenda yt-dlp",
        "timestamp": 1700000000,
    }) for _ in range(2))
    completed = Mock(returncode=0, stdout=stdout, stderr="")
    with patch("subprocess.run", return_value=completed) as run:
        posts = instagram_public._fetch_posts_with_ytdlp("simoes.vi", limit=10)
    assert len(posts) == 2
    assert posts[0]["id"] == "ABC123"
    assert posts[0]["image_url"] == "https://img.example/abc.jpg"
    assert posts[0]["caption"] == "Legenda yt-dlp"
    assert run.call_args.args[0][:5] == ["yt-dlp", "--dump-json", "--no-download", "--flat-playlist", "--playlist-end"]


def test_windows_profile_api_uses_chrome_headers_and_logs_response():
    response = Mock(status_code=200, text='{"data":{"user":{"username":"simoes.vi","biography":"Bio","edge_follow":{"count":2},"edge_followed_by":{"count":3},"edge_owner_to_timeline_media":{"count":1,"edges":[]}}}}')
    response.json.return_value = json.loads(response.text)
    with patch.object(instagram_public.platform, "system", return_value="Windows"), \
         patch.object(instagram_public.requests, "get", return_value=response) as request, \
         patch.object(instagram_public, "print") as output:
        user = instagram_public._fetch_web_profile_user("simoes.vi")
    assert user["username"] == "simoes.vi"
    headers = request.call_args.kwargs["headers"]
    assert "Chrome/131.0" in headers["User-Agent"]
    assert headers["Accept-Encoding"] == "gzip, deflate, br"
    assert headers["Accept-Language"] == "pt-BR,pt;q=0.9,en;q=0.8"
    logged = "\n".join(str(call.args[0]) for call in output.call_args_list)
    assert "URL chamada" in logged
    assert "status=200" in logged
    assert "tamanho=" in logged
    assert "simoes.vi" in logged


def test_windows_public_posts_do_not_use_instaloader_and_use_profile_api():
    api_user = {
        "username": "simoes.vi",
        "biography": "Bio",
        "edge_follow": {"count": 2},
        "edge_followed_by": {"count": 3},
        "edge_owner_to_timeline_media": {"count": 1, "edges": [{"node": {"id": "1", "shortcode": "ABC123", "display_url": "https://img.example/abc.jpg"}}]},
    }
    with patch.object(instagram_public.platform, "system", return_value="Windows"), \
         patch.object(instagram_public, "_fetch_web_profile_user", return_value=api_user) as profile:
        result = instagram_public.fetch_public_instagram_posts("https://www.instagram.com/simoes.vi/", limit=10)
    assert result.ok is True
    assert result.data["posts"][0]["shortcode"] == "ABC123"
    profile.assert_called_once_with("simoes.vi")
    assert not hasattr(instagram_public, "_fetch_posts_with_instaloader")


def test_windows_fetches_ten_posts_for_brun0gpt_and_simoes_vi():
    with patch.object(instagram_public.platform, "system", return_value="Windows"), \
         patch.object(instagram_public, "_fetch_web_profile_user", return_value=None), \
         patch.object(instagram_public, "_fetch_instagram_html_with_playwright", return_value=POSTS_HTML) as playwright:
        for username in ("brun0gpt", "simoes.vi"):
            result = instagram_public.fetch_public_instagram_posts(f"https://www.instagram.com/{username}/", limit=10)
            assert result.ok is True
            assert result.message == "Posts públicos encontrados."
            assert len(result.data["posts"]) == 10
        assert playwright.call_count == 2


def test_frontend_uses_bio_directly_and_ignores_stale_seo_bio_raw():
    real_bio = "🤖 Marketing e Vendas com Inteligência Artificial\n🧑🏻‍💻 Tá cansado de usar IA no modo amador?"
    assert _profile_bio({"bio": real_bio, "biography": "", "bio_raw": "227K seguidores, seguindo 241"}) == real_bio


def test_regex_bio_is_used_when_profile_node_is_not_found():
    assert instagram_public._extract_bio_from_html(REGEX_BIO_HTML) == "🤖 Marketing e Vendas com Inteligência Artificial\n🧑🏻‍💻 Tá cansado de usar IA no modo amador?"


def test_seo_summary_is_used_as_bio_fallback_when_structured_bio_is_missing():
    user = instagram_public._extract_profile_user_from_html(SEO_ONLY_HTML, "brun0gpt")
    data = instagram_public._profile_data_from_api(user, instagram_public.normalize_instagram_reference("https://www.instagram.com/brun0gpt"))

    assert data["bio"] == "227K seguidores, seguindo 241, 2,277 posts — Veja as fotos e vídeos de Bruno Francisco - IA | Marketing (@brun0gpt)"
    assert data["subscriber_count"] == 227000
    assert data["following_count"] == 241


def test_bruno_profile_prefers_real_bio_and_normalizes_top_metrics():
    user = instagram_public._extract_profile_user_from_html(BRUNO_HTML, "brun0gpt")
    data = instagram_public._profile_data_from_api(user, instagram_public.normalize_instagram_reference("https://www.instagram.com/brun0gpt"))

    assert data["bio"] == "🤖 Marketing e Vendas com Inteligência Artificial\n🧑🏻‍💻 Tá cansado de usar IA no modo amador?\n👉🏻 Acabou de chegar no lugar pra mudar isso\n👇🏻 Segue aí\nbrunogpt.com.br/simbiose-criativa"
    assert data["subscriber_count"] == 227000
    assert data["following_count"] == 241
    assert data["post_count"] == 2277
    assert _metric(data["subscriber_count"]) == "227.000"
    assert _metric(data["following_count"]) == "241"


def test_windows_profile_tries_requests_then_uses_playwright_html_parser():
    with patch.object(instagram_public.platform, "system", return_value="Windows"), \
         patch.object(instagram_public.requests, "get", side_effect=instagram_public.requests.RequestException("HTML instead of JSON")), \
         patch.object(instagram_public.shutil, "which", return_value=None), \
         patch.object(instagram_public, "_fetch_instagram_html_with_playwright", return_value=HTML) as playwright:
        result = instagram_public._fetch_web_profile_user("creator")

    assert result["biography"] == "123 followers, 456 following and 2 posts"
    assert result["edge_followed_by"]["count"] == 123
    assert result["edge_follow"]["count"] == 456
    assert result["edge_owner_to_timeline_media"]["edges"][0]["node"]["shortcode"] == "ABC"
    playwright.assert_called_once_with("https://www.instagram.com/creator/", "creator")


def test_windows_posts_use_the_same_html_parser_after_profile_fallback():
    with patch.object(instagram_public.platform, "system", return_value="Windows"), \
         patch.object(instagram_public, "_fetch_web_profile_user", return_value={}), \
         patch.object(instagram_public, "_fetch_instagram_html_with_playwright", return_value=HTML) as playwright:
        result = instagram_public.fetch_public_instagram_posts("@creator", limit=10)

    assert result.ok is True
    assert result.data["posts"][0]["id"] == "post-1"
    assert result.data["posts"][0]["caption"] == "Legenda"
    playwright.assert_called_once_with("https://www.instagram.com/creator/", "creator")


def test_playwright_failure_returns_empty_html_without_generic_data_fallback():
    with patch.dict("sys.modules", {"playwright": None}):
        # The public helper must keep the original empty-result contract on errors.
        with patch.object(instagram_public, "print") as output:
            result = instagram_public._fetch_instagram_html_with_playwright("https://www.instagram.com/creator/", "creator")
    assert result == ""
    output.assert_called_once()


def test_bio_preserves_metric_words_and_real_text():
    value = "606 seguidores, seguindo 3,432, 278 posts — Veja as fotos"
    assert instagram_public.normalize_instagram_bio(value) == value


def test_linux_html_path_remains_requests_based():
    response = Mock(status_code=200, text='<meta property="og:title" content="Creator"><meta property="og:description" content="Bio real">')
    # 1.0.56 — `_fetch_web_profile_user` tem fallback via `curl` em subprocess
    # (integrations/instagram_public.py): sem mock, um runner CI com rede faz
    # o curl real bater no Instagram e devolve o perfil VERDADEIRO antes do
    # `requests.get` mockado — o teste ficava dependente da rede (flaky).
    with patch.object(instagram_public.platform, "system", return_value="Linux"), \
         patch.object(instagram_public, "_fetch_web_profile_user", return_value=None), \
         patch.object(instagram_public.requests, "get", return_value=response) as request:
        result = instagram_public.fetch_public_instagram_profile("@creator")
    assert result.ok is True
    assert result.data["bio"] == "Bio real"
    request.assert_called()
