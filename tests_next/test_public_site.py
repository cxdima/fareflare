"""Public discovery must work before JavaScript without exposing private routes."""
import json
import re
import xml.etree.ElementTree as ET
from html import unescape

import pytest
from fastapi.testclient import TestClient

from fareflare.portal import create_portal
from fareflare.product_config import ProductConfig
from fareflare.service import MonitoringService
from fareflare.site_content import content_document, public_pages, render_document


@pytest.fixture
def public_site(store, clock, tmp_path):
    (tmp_path / "index.html").write_text('''<!doctype html><html lang="en"><head>
        <meta charset="utf-8"><title>Build placeholder</title><meta name="description" content="placeholder">
        <link rel="canonical" href="https://wrong.example/"><link rel="stylesheet" href="/styles-ABC12345.css">
        </head><body><app-root></app-root><script src="/main-ABC12345.js" type="module"></script></body></html>''')
    for name in ("main-ABC12345.js", "chunk-ABC12345.js", "styles-ABC12345.css", "favicon.svg"):
        (tmp_path / name).write_text("/* fixture */")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "fareflare-mark.png").write_bytes(b"image")
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "font-ABC12345.woff2").write_bytes(b"font")
    (tmp_path / ".env").write_text("DO_NOT_SERVE=private")
    (tmp_path / "main-ABC12345.js.map").write_text("private sources")
    (tmp_path / "secret.json").write_text('{"secret":"private"}')
    outside = tmp_path.parent / "private-ABC12345.js"
    outside.write_text("private")
    (tmp_path / "symlink-ABC12345.js").symlink_to(outside)
    config = ProductConfig(public_url="https://preview.example.com", search_enabled=True)
    service = MonitoringService(store, lambda: clock[0])
    app = create_portal(service, config, static_dir=tmp_path)
    with TestClient(app, base_url=config.public_url) as client:
        yield client, config


def json_ld(html):
    return json.loads(re.search(r'<script type="application/ld\+json" nonce="[^"]+">(.*?)</script>', html, re.S)[1])


def test_public_pages_have_crawlable_content_and_matching_metadata(public_site):
    client, config = public_site
    document = client.get("/site-content.json").json()
    assert len(document["pages"]) == 9
    for page in document["pages"]:
        for section in page["sections"]:
            assert all(isinstance(section[key], list) for key in ("paragraphs", "bullets", "links"))
        response = client.get(page["path"])
        assert response.status_code == 200
        assert "<h1>" + page["headline"] + "</h1>" in unescape(response.text)
        assert page["intro"] in unescape(response.text)
        assert '<link rel="canonical" href="' + config.public_url + page["path"] + '">' in response.text
        assert '<meta property="og:url" content="' + config.public_url + page["path"] + '">' in response.text
        assert '<meta name="robots" content="index, follow">' in response.text
        assert "wrong.example" not in response.text and "Build placeholder" not in response.text
        assert response.text.count("<title>") == 1
        assert response.text.count('name="description"') == 1
        assert 'style="' not in response.text and 'onclick=' not in response.text
        data = json_ld(response.text)
        assert data["@context"] == "https://schema.org"
        assert not any("aggregateRating" in entity or "review" in entity for entity in data["@graph"])
        if page["kind"] == "guide":
            article = next(entity for entity in data["@graph"] if entity["@type"] == "BlogPosting")
            assert article["headline"] == page["headline"]
            assert article["datePublished"] == page["published"]
            assert 'By Fareflare' in response.text
            assert response.text.count("<p>") >= 8


def test_nonce_is_random_per_document_and_shared_with_angular_and_jsonld(public_site):
    client, _ = public_site
    first, second = client.get("/"), client.get("/")
    first_nonce = re.search(r'ngCspNonce="([^"]+)"', first.text)[1]
    second_nonce = re.search(r'ngCspNonce="([^"]+)"', second.text)[1]
    assert first_nonce != second_nonce and len(first_nonce) >= 32
    policy = first.headers["content-security-policy"]
    assert "'nonce-" + first_nonce + "'" in policy
    assert 'nonce="' + first_nonce + '"' in first.text
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy
    assert "style-src-attr 'none'" in policy and "object-src 'none'" in policy
    assert first.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/app", "/login", "/register", "/recover",
                                   "/?invite=do-not-echo-token", "/?authorize=do-not-echo-token"])
def test_private_pages_and_auth_queries_are_not_indexable(public_site, path):
    client, _ = public_site
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert '<meta name="robots" content="noindex, nofollow">' in response.text
    assert "application/ld+json" not in response.text
    assert "do-not-echo-token" not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/missing", "/guides/not-a-guide", "/app/missing", "/app/settings", "/authorize", "/.env", "/secret.json",
                                   "/main-ABC12345.js.map", "/symlink-ABC12345.js", "/assets/../../.env"])
def test_unknown_routes_and_nonpublic_files_return_real_404(public_site, path):
    client, _ = public_site
    response = client.get(path)
    assert response.status_code == 404
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert "DO_NOT_SERVE" not in response.text and "private sources" not in response.text


def test_sitemap_and_feed_only_list_real_public_pages(public_site):
    client, config = public_site
    site_map = client.get("/sitemap.xml")
    assert "application/xml" in site_map.headers["content-type"]
    root = ET.fromstring(site_map.text)
    locations = [node.text for node in root.findall("{*}url/{*}loc")]
    assert set(locations) == {config.public_url + page.path for page in public_pages(config)}
    assert not any("/app" in url or "invite=" in url for url in locations)
    assert "Sitemap: " + config.public_url + "/sitemap.xml" in client.get("/robots.txt").text
    rss = client.get("/feed.xml")
    assert "application/rss+xml" in rss.headers["content-type"]
    items = ET.fromstring(rss.text).findall("channel/item")
    assert len(items) == 3
    assert all(item.findtext("link").startswith(config.public_url + "/guides/") for item in items)


def test_static_cache_matches_asset_names_and_does_not_capture_api(public_site):
    client, _ = public_site
    for path in ("/main-ABC12345.js", "/chunk-ABC12345.js", "/styles-ABC12345.css", "/media/font-ABC12345.woff2"):
        response = client.get(path)
        assert response.status_code == 200 and "immutable" in response.headers["cache-control"]
    assert client.get("/assets/fareflare-mark.png").headers["cache-control"] == "public, max-age=3600"
    assert client.get("/favicon.svg").status_code == 200
    assert client.get("/v1/account").status_code == 401
    assert client.get("/v1/config").json()["product_name"] == "Fareflare"
    assert client.head("/about").status_code == 200 and not client.head("/about").content
    assert client.get("/docs").status_code == 200


def test_content_tracks_config_and_never_executes_brand_text():
    config = ProductConfig(public_url="https://preview.example.com", product_name="</script><img src=x onerror=alert(1)>",
                           min_interval_seconds=300, monitor_limit=4, registration_mode="open")
    doc = content_document(config)
    text = str(doc)
    assert "minimum requested interval of 5 minutes" in text
    assert "4 monitors" in text and "free and open" in text
    assert "Route searches are not enabled" in text
    shell = "<html><head></head><body><app-root></app-root></body></html>"
    result = render_document(shell, public_pages(config)[0], config, "safe-nonce")
    assert "</script><img" not in result
    assert r"\u003c/script\u003e" in result
    assert json_ld(result)["@graph"][0]["name"] == config.product_name
