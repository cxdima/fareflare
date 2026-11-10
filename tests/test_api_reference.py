"""The API reference must stay usable without a second UI runtime or remote assets."""

from fastapi.testclient import TestClient

from fareflare.api import create_app
from fareflare.api_reference import render_api_reference


def test_standalone_reference_keeps_schema_and_endpoints_without_swagger_or_redoc(service):
    with TestClient(create_app(service, {"alice": "a" * 40})) as client:
        response = client.get("/docs")
        assert response.status_code == 200
        assert "Fareflare API reference" in response.text
        assert "/v1/monitors" in response.text and "/v1/preferences" in response.text
        assert "/openapi.json" in response.text
        assert "<script" not in response.text and "https://" not in response.text
        assert "swagger" not in response.text.lower() and "redoc" not in response.text.lower()
        assert "/app" not in response.text
        assert client.get("/redoc").status_code == 404
        assert client.get("/docs/oauth2-redirect").status_code == 404
        schema = client.get("/openapi.json").json()
        assert "post" in schema["paths"]["/v1/monitors"]
        assert "/docs" not in schema["paths"]
        assert client.get("/v1/monitors").status_code == 401


def test_reference_escapes_schema_content_and_branding(tmp_path):
    (tmp_path / "styles-local.css").write_text("body {}")
    html = render_api_reference(
        {
            "paths": {
                "/example<unsafe>": {
                    "get": {"summary": '<script>alert("bad")</script>'},
                    "parameters": [{"name": "ignored"}],
                }
            }
        },
        "Fareflare <example>",
        static_dir=tmp_path,
        public_url="https://fareflare.example",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html and "/example&lt;unsafe&gt;" in html
    assert "Fareflare &lt;example&gt;" in html
    assert 'href="/styles-local.css"' in html
    assert "href='/app'" in html and "https://fareflare.example/mcp" in html
    assert "<td><code>PARAMETERS</code>" not in html
