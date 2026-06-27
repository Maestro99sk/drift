"""One-shot OAuth helper: exchanges a Shopify Client ID/Secret for a permanent
Admin API access token (shpat_...).

Why this exists: as of 2026, Shopify's managed-app dashboard no longer surfaces
Admin API access tokens directly. You define an OAuth app and then have to install
it on a store to mint a token. This script runs the install dance from the CLI.

Prereqs in .env:
    SHOPIFY_CLIENT_ID          - "Client ID" from dev.shopify.com app Settings
    SHOPIFY_CLIENT_SECRET      - "Secret" from the same page (shpss_...)
    SHOPIFY_STORE_DOMAIN       - e.g. drift-test.myshopify.com
    SHOPIFY_SCOPES             - default: write_products,read_products
    SHOPIFY_INSTALL_REDIRECT_URL - must EXACTLY match a Redirect URL allow-listed
                                   in the Shopify app config

Add `SHOPIFY_INSTALL_REDIRECT_URL` to the app's Redirect URLs list FIRST, otherwise
Shopify will refuse the install.
"""

from __future__ import annotations

import contextlib
import http.server
import logging
import secrets
import socketserver
import threading
import urllib.parse
import webbrowser
from typing import ClassVar

import httpx

from drift.config import get_settings

log = logging.getLogger(__name__)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    received: ClassVar[dict[str, str]] = {}
    expected_state: ClassVar[str] = ""

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        url = urllib.parse.urlparse(self.path)
        if not url.path.endswith("/callback"):
            self.send_response(404)
            self.end_headers()
            return
        params = dict(urllib.parse.parse_qsl(url.query))
        if params.get("state") != _CallbackHandler.expected_state:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"state mismatch - rejecting")
            return
        _CallbackHandler.received.update(params)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<h2>Drift: Shopify install complete.</h2>"
            b"<p>You can close this tab and return to the terminal.</p>"
        )


def _exchange_code_for_token(shop: str, code: str, client_id: str, client_secret: str) -> str:
    resp = httpx.post(
        f"https://{shop}/admin/oauth/access_token",
        json={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
        },
        timeout=20,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(f"unexpected response from Shopify: {resp.text}")
    return token


def run_install() -> str:
    """Run the OAuth install and return the permanent Admin API access token."""
    s = get_settings()
    missing = [
        name
        for name, val in {
            "SHOPIFY_CLIENT_ID": s.shopify_client_id,
            "SHOPIFY_CLIENT_SECRET": s.shopify_client_secret,
            "SHOPIFY_STORE_DOMAIN": s.shopify_store_domain,
        }.items()
        if not val
    ]
    if missing:
        raise SystemExit(f"missing required env: {', '.join(missing)}")

    state = secrets.token_urlsafe(24)
    _CallbackHandler.received = {}
    _CallbackHandler.expected_state = state

    install_url = (
        f"https://{s.shopify_store_domain}/admin/oauth/authorize?"
        + urllib.parse.urlencode(
            {
                "client_id": s.shopify_client_id,
                "scope": s.shopify_scopes,
                "redirect_uri": s.shopify_install_redirect_url,
                "state": state,
            }
        )
    )

    # Bind the callback listener before opening the browser so we never miss the hit.
    httpd = socketserver.TCPServer(
        (s.shopify_install_callback_host, s.shopify_install_callback_port),
        _CallbackHandler,
    )
    httpd.allow_reuse_address = True
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    print("\nOpen this URL in your browser and approve the install:\n")
    print(install_url + "\n")
    with contextlib.suppress(Exception):
        webbrowser.open(install_url)

    print(
        f"Waiting for OAuth callback on "
        f"{s.shopify_install_callback_host}:{s.shopify_install_callback_port}/callback ..."
    )
    try:
        while "code" not in _CallbackHandler.received:
            server_thread.join(0.5)
    finally:
        httpd.shutdown()

    if "error" in _CallbackHandler.received:
        raise SystemExit(f"Shopify returned error: {_CallbackHandler.received['error']}")

    code = _CallbackHandler.received["code"]
    shop = _CallbackHandler.received.get("shop", s.shopify_store_domain)
    token = _exchange_code_for_token(shop, code, s.shopify_client_id, s.shopify_client_secret)

    print("\n  Admin API access token (paste into SHOPIFY_ADMIN_TOKEN in .env):\n")
    print("  " + token + "\n")
    print(f"  Store domain (SHOPIFY_STORE_DOMAIN): {shop}\n")
    return token
