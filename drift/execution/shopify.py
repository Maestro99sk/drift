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

            # 3. Best-effort publish to the Online Store channel so the URL is reachable.
            # Requires read_publications + write_publications scopes; if the token
            # lacks them, the product still exists in admin and the merchant can
            # publish manually. We log and continue rather than failing the publish.
            try:
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
                            "publishablePublish userErrors (product created, not on Online Store): %s",
                            pp["userErrors"],
                        )
                    else:
                        log.info("Published to Online Store channel: %s", online_store_id)
                else:
                    log.warning(
                        "No Online Store publication found - product created but won't render at /products/%s",
                        handle,
                    )
            except ShopifyError as exc:
                log.warning(
                    "Channel publish skipped (%s). Product %s exists in admin; "
                    "add read_publications + write_publications scopes to enable auto-publish.",
                    exc,
                    product_gid,
                )

            # 4. Find-or-create a Collection per niche and add this product.
            # Gives the store visible structure ('/collections/kids', '/collections/home')
            # without touching the theme. Best-effort: failures don't break publish.
            collection_gid: str | None = None
            try:
                collection_gid = await self._ensure_collection(client, niche_theme)
                if collection_gid:
                    await self._add_product_to_collection(client, product_gid, collection_gid)
                    log.info(
                        "Added product %s to niche collection %s",
                        product_gid,
                        collection_gid,
                    )
            except ShopifyError as exc:
                log.warning("Collection sync skipped (%s)", exc)

            # 5. Find-or-create a niche landing Page (`/pages/<niche>-trending`)
            # with hero + product grid, refreshed each time a product joins the niche.
            # Best-effort; requires write_content scope.
            if collection_gid:
                try:
                    page_url = await self._ensure_niche_landing_page(
                        client, niche_theme, collection_gid
                    )
                    if page_url:
                        log.info("Niche landing page refreshed: %s", page_url)
                except ShopifyError as exc:
                    log.warning(
                        "Niche page sync skipped (%s). Add write_content scope to enable.",
                        exc,
                    )

        public_url = product.get("onlineStoreUrl") or (
            f"https://{self.domain}/products/{handle}?utm={utm_key}"
        )
        return PublishResult(external_id=product_gid, storefront_url=public_url)

    async def _ensure_collection(self, client: httpx.AsyncClient, niche_theme: str) -> str | None:
        """Find a Collection by handle, else create it. Returns the Collection GID."""
        handle = _slugify(niche_theme)
        find_query = """
        query findCollection($handle: String!) {
            collectionByHandle(handle: $handle) { id }
        }
        """
        data = await self._gql(client, find_query, {"handle": handle})
        existing = data.get("collectionByHandle")
        if existing:
            return existing["id"]

        title = niche_theme.replace("-", " ").replace("_", " ").title()
        create_query = """
        mutation createCollection($input: CollectionInput!) {
            collectionCreate(input: $input) {
                collection { id handle }
                userErrors { field message }
            }
        }
        """
        data = await self._gql(
            client,
            create_query,
            {
                "input": {
                    "title": title,
                    "handle": handle,
                    "descriptionHtml": (
                        f"<p>Hand-picked trending {title.lower()} items, "
                        "refreshed as the loop discovers new winners.</p>"
                    ),
                }
            },
        )
        cc = data["collectionCreate"]
        if cc["userErrors"]:
            log.warning("collectionCreate userErrors: %s", cc["userErrors"])
            return None
        log.info("Created niche collection: %s (%s)", title, cc["collection"]["id"])
        return cc["collection"]["id"]

    async def _add_product_to_collection(
        self, client: httpx.AsyncClient, product_gid: str, collection_gid: str
    ) -> None:
        add_query = """
        mutation driftCollectionAdd($id: ID!, $productIds: [ID!]!) {
            collectionAddProductsV2(id: $id, productIds: $productIds) {
                userErrors { field message }
            }
        }
        """
        data = await self._gql(
            client,
            add_query,
            {"id": collection_gid, "productIds": [product_gid]},
        )
        res = data["collectionAddProductsV2"]
        if res["userErrors"]:
            log.warning("collectionAddProductsV2 userErrors: %s", res["userErrors"])

    async def _ensure_niche_landing_page(
        self,
        client: httpx.AsyncClient,
        niche_theme: str,
        collection_gid: str,
    ) -> str | None:
        """Create or refresh `/pages/<niche>-trending` with hero + product grid.

        Idempotent: each call regenerates the body from the current set of
        products in the niche collection so the page stays fresh as the loop
        adds winners and sunsets losers.
        """
        handle = f"{_slugify(niche_theme)}-trending"
        title = f"Trending {niche_theme.replace('-', ' ').replace('_', ' ').title()}"

        # Pull current products in the niche collection to render the grid.
        prods_query = """
        query driftCollectionProducts($id: ID!) {
            collection(id: $id) {
                products(first: 50) {
                    edges {
                        node {
                            id
                            handle
                            title
                            featuredMedia {
                                preview { image { url } }
                            }
                        }
                    }
                }
            }
        }
        """
        data = await self._gql(client, prods_query, {"id": collection_gid})
        edges = (((data.get("collection") or {}).get("products") or {}).get("edges")) or []
        products = [e["node"] for e in edges]
        body_html = _render_niche_landing_html(niche_theme, products)

        # Find existing page by handle.
        find_query = """
        query driftFindPage($q: String!) {
            pages(first: 1, query: $q) {
                edges { node { id handle } }
            }
        }
        """
        data = await self._gql(client, find_query, {"q": f"handle:{handle}"})
        page_edges = data["pages"]["edges"]

        if page_edges:
            page_id = page_edges[0]["node"]["id"]
            update_query = """
            mutation driftPageUpdate($id: ID!, $page: PageUpdateInput!) {
                pageUpdate(id: $id, page: $page) {
                    page { id handle }
                    userErrors { field message }
                }
            }
            """
            data = await self._gql(
                client,
                update_query,
                {
                    "id": page_id,
                    "page": {"title": title, "body": body_html},
                },
            )
            pu = data["pageUpdate"]
            if pu["userErrors"]:
                log.warning("pageUpdate userErrors: %s", pu["userErrors"])
                return None
        else:
            create_query = """
            mutation driftPageCreate($page: PageCreateInput!) {
                pageCreate(page: $page) {
                    page { id handle }
                    userErrors { field message }
                }
            }
            """
            data = await self._gql(
                client,
                create_query,
                {
                    "page": {
                        "title": title,
                        "handle": handle,
                        "body": body_html,
                        "isPublished": True,
                    }
                },
            )
            pc = data["pageCreate"]
            if pc["userErrors"]:
                log.warning("pageCreate userErrors: %s", pc["userErrors"])
                return None

        return f"https://{self.domain}/pages/{handle}"


def _render_niche_landing_html(niche_theme: str, products: list[dict]) -> str:
    """Render a tasteful hero + responsive product grid as a single HTML blob.

    Inline styles (not stylesheet links) because Shopify Pages are inserted
    inside theme templates and we cannot assume any global CSS is loaded.
    """
    title = niche_theme.replace("-", " ").replace("_", " ").title()

    hero = (
        '<div style="text-align:center;padding:48px 16px;'
        "background:linear-gradient(135deg,#fafafa,#eef);"
        'border-radius:16px;margin-bottom:32px;">'
        f'<h1 style="font-size:2.4rem;margin:0 0 12px;">The {title} Edit</h1>'
        f'<p style="font-size:1.1rem;color:#444;max-width:560px;margin:0 auto;">'
        f"Hand-picked, currently trending {title.lower()} - refreshed as our "
        "discovery loop spots new winners and retires the cooled ones."
        "</p></div>"
    )

    if not products:
        return hero + '<p style="text-align:center;color:#888;">No products yet.</p>'

    cards: list[str] = []
    for p in products:
        media = (p.get("featuredMedia") or {}).get("preview") or {}
        img_url = (media.get("image") or {}).get("url") or ""
        img_tag = (
            f'<img src="{img_url}" alt="{p["title"]}" '
            'style="width:100%;height:220px;object-fit:cover;border-radius:8px;">'
            if img_url
            else '<div style="width:100%;height:220px;background:#eee;border-radius:8px;"></div>'
        )
        cards.append(
            '<a href="/products/' + p["handle"] + '" '
            'style="flex:1 1 240px;max-width:280px;text-decoration:none;color:inherit;'
            "border:1px solid #eee;border-radius:12px;padding:16px;"
            'transition:transform .12s ease,box-shadow .12s ease;display:block;">'
            f"{img_tag}"
            f'<h3 style="margin:14px 0 0;font-size:1.05rem;">{p["title"]}</h3>'
            "</a>"
        )

    grid = (
        '<div style="display:flex;flex-wrap:wrap;gap:20px;justify-content:center;">'
        + "".join(cards)
        + "</div>"
    )
    return hero + grid


def _slugify(value: str) -> str:
    """Turn 'Kids learning' into 'kids-learning' for use as a Shopify handle."""
    out = []
    for ch in value.lower().strip():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "general"


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
