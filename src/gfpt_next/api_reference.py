"""Dependency-free HTML API reference shared by the API and customer portal."""
from html import escape
from pathlib import Path


def render_api_reference(schema: dict, product_name: str = "Fareflare", *,
                         static_dir: Path | None = None, public_url: str | None = None) -> str:
    name = escape(product_name)
    routes = "".join(
        "<tr><td><code>" + escape(method.upper()) + "</code></td><td><code>" +
        escape(path) + "</code></td><td>" + escape(operation.get("summary", "")) + "</td></tr>"
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
        if method in {"get", "put", "post", "delete", "patch", "head", "options", "trace"}
    )
    styles = "".join(
        '<link rel="stylesheet" href="/' + escape(path.name, quote=True) + '">'
        for path in sorted(static_dir.glob("styles-*.css"))
    ) if static_dir else ""
    navigation = (
        "<nav class='site-nav' aria-label='Main navigation'><a href='/developers'>Developers</a>"
        "<a href='/guides'>Guides</a><a href='/app'>Dashboard</a></nav>"
    ) if public_url else ""
    credentials = (
        "Create a revocable API key in the dashboard and send it as "
    ) if public_url else "Send your configured service credential as "
    integration = (
        " Connect an MCP client to <code>" + escape(public_url) +
        "/mcp</code> using OAuth or a bearer API key."
    ) if public_url else ""
    dashboard = "<p><a href='/app'>Open the dashboard</a></p>" if public_url else ""
    footer = (
        "<footer class='public-footer'><div class='public-container'><nav class='footer-links' "
        "aria-label='Footer'><a href='/privacy'>Privacy</a><a href='/terms'>Terms</a></nav></div></footer>"
    ) if public_url else ""
    home = "/" if public_url else "/docs"
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        "<meta name='robots' content='noindex, follow'><title>" + name + " API reference</title>" + styles +
        "</head><body><a class='skip-link' href='#main-content'>Skip to content</a><header class='site-header'>"
        "<div class='public-container site-header-inner'><a class='brand' href='" + home + "'>" + name +
        "</a>" + navigation + "</div></header><main id='main-content' class='public-container public-article'>"
        "<h1>" + name + " API reference</h1><p>" + credentials +
        "<code>Authorization: Bearer YOUR_KEY</code>. Creating monitors and webhooks also requires a unique "
        "<code>Idempotency-Key</code> header (8–128 characters); reuse it when retrying the same request.</p>"
        "<p>Prices use integer minor units: USD 123.45 is <code>12345</code>. Lists are paginated "
        "using <code>limit</code> and <code>cursor</code>. Honor <code>Retry-After</code> on HTTP 429.</p>"
        "<p><a href='/openapi.json'>Download the OpenAPI schema</a> for request fields and response types." +
        integration + "</p><div class='table-responsive'><table class='table table-striped align-middle'>"
        "<caption>Available endpoints</caption><thead><tr><th scope='col'>Method</th><th scope='col'>Path</th>"
        "<th scope='col'>Purpose</th></tr></thead><tbody>" + routes + "</tbody></table></div>" +
        dashboard + "</main>" + footer + "</body></html>"
    )
