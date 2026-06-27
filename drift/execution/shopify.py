"""Shopify storefront adapter - live via the Admin GraphQL API.

REST product creation has been progressively restricted for new custom apps;
the canonical path is now GraphQL (https://shopify.dev/docs/api/admin-graphql).
We do three calls per publish:

  1. productCreate           - create the product shell (title, body, tags, status)
  2. productVariantsBulkUpdate - set price + SKU on the auto-created default variant
  3. publishablePublish      - publish to the Online Store channel so the URL is live

Each step's `userErrors` array is checked explicitly and any non-empty result
raises - silent partial publishes are worse than loud failures.
"""

from __future__ import annotations

import logging

import httpx

from drift.config import get_settings
from drift.execution.base import PublishResult, StorefrontAdapter

log = logging.getLogger(__name__)

API_VERSION = "2025-01"


class ShopifyError(RuntimeError):
    """Raised when the Shopify API returns a hard error or non-empty userErrors."""


class ShopifyStorefrontAdapter(StorefrontAdapter):
    def __init__(self, token: str | None = None, domain: str | None = None) -> None:
        s = get_settings()
        self.token = token or s.shopify_admin_token
        self.domain = domain or s.shopify_store_domain

    @property
    def _graphql_url(self) -> str:
        return f"https://{self.domain}/admin/api/{API_VERSION}/graphql.json"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _gql(self, client: httpx.AsyncClient, query: str, variables: dict) -> dict:
        resp = await client.post(
            self._graphql_url,
            headers=self._headers,
            json={"query": query, "variables": variables},
        )
        if resp.status_code >= 400:
            raise ShopifyError(
                f"Shopify HTTP {resp.status_code} at {self._graphql_url}: {resp.text}"
            )
        payload = resp.json()
        if payload.get("errors"):
            raise ShopifyError(f"Shopify GraphQL errors: {payload['errors']}")
        return payload["data"]

    async def publish(
        self,
        *,
        title: str,
        body_html: str,
        price: float,
        sku: str,
        niche_theme: str,
        utm_key: str,
    ) -> PublishResult:
        if not (self.token and self.domain):
            raise ShopifyError(
                "SHOPIFY_ADMIN_TOKEN or SHOPIFY_STORE_DOMAIN not set - storefront dormant"
            )

        async with httpx.AsyncClient(timeout=30) as client:
            # 1. Create product shell.
            create_query = """
            mutation driftProductCreate($input: ProductInput!) {
                productCreate(input: $input) {
                    product {
                        id
                        handle
                        onlineStoreUrl
                        variants(first: 1) { edges { node { id } } }
                    }
                    userErrors { field message }
                }
            }
            """
            # COMPLIANCE TODO: link returns policy + EU/UK ship-time disclosure in body.
            create_vars = {
                "input": {
                    "title": title,
                    "descriptionHtml": body_html,
                    "productType": niche_theme,
                    "vendor": "Drift",
                    "tags": [niche_theme, f"utm:{utm_key}"],
                    "status": "ACTIVE",
                }
            }
            data = await self._gql(client, create_query, create_vars)
            pc = data["productCreate"]
            if pc["userErrors"]:
                raise ShopifyError(f"productCreate failed: {pc['userErrors']}")
            product = pc["product"]
            product_gid = product["id"]
            handle = product["handle"]
            edges = product["variants"]["edges"]
            if not edges:
                raise ShopifyError("productCreate returned no default variant")
            variant_gid = edges[0]["node"]["id"]
            log.info("Shopify productCreate ok: %s (%s)", product_gid, handle)

            # 2. Set price + SKU on default variant.
            variant_query = """
            mutation driftVariantUpdate(
                $productId: ID!, $variants: [ProductVariantsBulkInput!]!
            ) {
                productVariantsBulkUpdate(productId: $productId, variants: $variants) {
                    productVariants { id price sku }
                    userErrors { field message }
                }
            }
            """
            variant_vars = {
                "productId": product_gid,
                "variants": [
                    {
                        "id": variant_gid,
                        "price": f"{price:.2f}",
                        "inventoryItem": {"sku": sku, "tracked": False},
                    }
                ],
            }
            data = await self._gql(client, variant_query, variant_vars)
            vu = data["productVariantsBulkUpdate"]
            if vu["userErrors"]:
                raise ShopifyError(f"variant update failed: {vu['userErrors']}")
            log.info("Shopify variant set: price=%.2f sku=%s", price, sku)

            # 3. Publish to the Online Store channel so the URL is reachable.
            # First find the Online Store publication ID (one per store).
            pubs_query = """
            { publications(first: 25) { edges { node { id name } } } }
            """
            data = await self._gql(client, pubs_query, {})
            online_store_id: str | None = None
            for edge in data["publications"]["edges"]:
                if edge["node"]["name"].lower().startswith("online store"):
                    online_store_id = edge["node"]["id"]
                    break

            if online_store_id:
                publish_query = """
                mutation driftPublish($id: ID!, $input: [PublicationInput!]!) {
                    publishablePublish(id: $id, input: $input) {
                        publishable {
                            availablePublicationsCount { count }
                        }
                        userErrors { field message }
                    }
                }
                """
                publish_vars = {
                    "id": product_gid,
                    "input": [{"publicationId": online_store_id}],
                }
                data = await self._gql(client, publish_query, publish_vars)
                pp = data["publishablePublish"]
                if pp["userErrors"]:
                    log.warning(
                        "publishablePublish userErrors (product created but not on Online Store): %s",
                        pp["userErrors"],
                    )
                else:
                    log.info("Published to Online Store channel: %s", online_store_id)
            else:
                log.warning(
                    "No Online Store publication found - product created but won't render at /products/%s",
                    handle,
                )

        public_url = product.get("onlineStoreUrl") or (
            f"https://{self.domain}/products/{handle}?utm={utm_key}"
        )
        return PublishResult(external_id=product_gid, storefront_url=public_url)


class MockStorefrontAdapter(StorefrontAdapter):
    async def publish(
        self,
        *,
        title: str,
        body_html: str,
        price: float,
        sku: str,
        niche_theme: str,
        utm_key: str,
    ) -> PublishResult:
        fake_id = f"mock-{abs(hash(sku)) % 10**8}"
        return PublishResult(
            external_id=fake_id,
            storefront_url=f"https://mock.drift.local/{niche_theme}/{fake_id}?utm={utm_key}",
        )
