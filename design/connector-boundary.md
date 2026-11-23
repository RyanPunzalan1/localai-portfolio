# Connector boundary and Square verification (Phase 0.5)

Written for: the project owner, to review before Phase 1 starts.
Status: **Proposed. Nothing here is built.** No application code was changed. Rules: CLAUDE.md.
Overview: design/architecture.md. Pack rules: design/packs.md.

## 1. Decisions already made (owner, 2026-11-17)

| # | Decision | Consequence in this design |
|---|---|---|
| 1 | Packs stay network-free. All Square traffic goes through a core connector | Section 3 |
| 2 | Keep route approval for the MVP. Design so reads can be classified later | Section 6 (`access` class in the manifest, enforced as "approve all" for now) |
| 3 | HTTP client is `httpx` (new dependency, pinned in `requirements.txt`) | The endpoint allowlist is the boundary, not the library |
| 4 | Tokens live on a dedicated 0600 secrets volume | Section 5. File permissions are not encryption at rest, and the docs say so |
| 5 | `business_id` in the data model and in storage paths from day one. No login, roles or multi-tenant UI | Section 4 |
| 6 | The uncommitted `app.py` edit is left alone | Phase 1 work must not touch `app.py` until that edit is resolved, or must keep to a few lines and say so |

## 2. What the Square docs say (checked 2026-11-17)

Source: official pages at developer.squareup.com, read by research agents on my behalf. I have not read
the pages myself. Several reference pages rendered only site navigation, so those items stay **UNCONFIRMED**.
This section replaces my earlier statement that no reporting API existed: **one does.**

### Confirmed

| Topic | Fact |
|---|---|
| OAuth flows | Two: code flow (needs `client_secret`) and **PKCE** ("must be used by any client that cannot safely store secrets ... native desktop applications"). The two cannot be mixed. PKCE refresh needs no secret |
| Token lifetimes | Authorization code 5 min, single use. Access token 30 days. **PKCE refresh tokens are single use and expire after 90 days**; each refresh returns a new one. Square suggests renewing every 7 days or less |
| Read scopes | `ORDERS_READ` (SearchOrders, BatchRetrieveOrders), `PAYMENTS_READ` (ListPayments, ListPaymentRefunds), `ITEMS_READ` (catalog reads), `INVENTORY_READ` (counts and changes), `MERCHANT_PROFILE_READ` (locations), `REPORTING_READ` (Reporting API) |
| Write endpoints to block | `BatchChangeInventory` is `POST /v2/inventory/changes/batch-create` (scope `INVENTORY_WRITE`). RefundPayment needs `PAYMENTS_WRITE`. CreateOrder and UpdateOrder need `ORDERS_WRITE`. Catalog upsert and delete need `ITEMS_WRITE` |
| Verbs do not mean read-only | Square does not say that "Search" or "Batch-retrieve" always means a safe verb. **Read-only is decided by the endpoint and its scope, never by GET versus POST** |
| Read endpoints | `POST /v2/orders/search`, `GET /v2/refunds`, `GET /v2/payments` (max 100 per page), `POST /v2/catalog/search` (`object_types` must be explicit), `GET /v2/catalog/list` (page size 100), `POST /v2/inventory/counts/batch-retrieve` and `POST /v2/inventory/changes/batch-retrieve` (limit 1 to 1000) |
| Pagination | Cursor in the response, passed back with the same request. A cursor lives **5 minutes**. The last page has no cursor. Results are eventually consistent (refunds can take seconds to appear) |
| Rate limits | `429 RATE_LIMITED`. Use exponential backoff with jitter. No numeric limits are published on the pages read |
| Versioning | `Square-Version: YYYY-MM-DD` header. Production `connect.squareup.com`, Sandbox `connect.squareupsandbox.com` |
| Sandbox | Sandbox tokens do not work in production. A test account can be authorized from the Developer Console. Sample order history is not promised, so data is seeded through the API |
| Reporting API | `https://connect.squareup.com/reporting`, `GET /v1/meta`, `GET/POST /v1/load` (examples use POST). Needs `REPORTING_READ`. Freshness about 15 minutes. Overview says it is **not recommended for high-frequency polling** |
| Reporting measures | `Orders.net_sales` ("Total sales after discounts and returns, excluding tax"), `discounts_amount`, `itemized_returns` ("Returns and refunds"), `tips_amount`, `sales_tax_amount`, `count`, `avg_net_sales`. Segment `closed_checks` ("Fully paid orders (recommended for sales reports)") |
| Reporting local days | Dimensions `Orders.local_date` and `local_reporting_timestamp` use the location's timezone. Do not mix UTC and local dimensions in one query. Pagination is `limit`/`offset` with a stable `order` |

### Unconfirmed, and why each matters

| Open item | Why it matters |
|---|---|
| Is the Reporting API GA or beta? Is it in Sandbox? | We cannot build the MVP on it if Sandbox does not serve it |
| Is there a **gross sales** measure? Service charges? | You required gross and net to be kept apart |
| Money-field definitions on the Order object (`total_money`, `total_discount_money`, `net_amounts`, and others) | Needed to compute sales ourselves. The Order reference page did not render |
| How a CANCELED order, a partial refund, and a refund made on a later day appear in totals | Decides which day a refund is subtracted from (section 7) |
| Square's own help-centre definitions of gross and net sales | The metric definitions must match what the owner sees in Square |
| Max `limit` and location count for SearchOrders. Any Reporting row cap | Sync paging |
| Whether `Retry-After` is sent on 429 | Backoff design (we do not rely on it) |
| Whether Square accepts a localhost redirect URI for the OAuth callback. Revoke auth for PKCE: the page's example uses `Authorization: Client <secret>`, which a PKCE app does not have | OAuth design and the "disconnect and revoke" requirement |
| Whether the Location `timezone` field is returned by ListLocations (an example shows an IANA name) | Business timezone |

## 3. The connector boundary

```
Hermes ──▶ Coordinator ──▶ biz pack (no network, no files, no secrets)
                              │  typed calls only
                              ▼
                        BizGateway  (core: checks manifest + business_id)
                              │ reads only
                              ▼
                       SQLite store  data/<business_id>/business.db
                              ▲ writes only from sync
                              │
                       square_sync  ──▶  square_client (core, the ONLY code that opens a socket)
                                           │ endpoint allowlist, GET/POST-read only, httpx
                                           ▼
                                     Square (production or sandbox)
```

Rules:

1. **Only `square_client` makes network calls.** It is the single place that imports `httpx`. A test fails if
   any other project module imports `httpx` or any other HTTP library.
2. **Allowlist of (method, path) pairs**, written out in code. Anything else raises before a request is made.
   The initial list is the read endpoints in section 2. The write endpoints listed there are in a test that
   asserts each one is refused. Unknown paths are refused by default, so a new Square endpoint is never
   reachable by accident.
3. **Scope check at connect time.** After OAuth the connector reads the granted scopes. If any scope outside
   the read list is present, it refuses to store the token and tells the user. This is a second, independent
   read-only control, separate from the allowlist.
4. **Packs never see the client, the token or raw responses.** The `biz` pack asks the gateway for fixed,
   validated queries on the local store. It has no `network`, and it does not read `docs/` either.
5. **The model never writes SQL.** The gateway exposes named functions with typed arguments (dates are
   `YYYY-MM-DD` strings checked against a real calendar, a maximum range, and a location id from a known list).
   Queries inside the gateway are parameterized.
6. **Sync is separate from answering.** A question never triggers a live Square call. Answers come from the
   store, and the answer says when the store was last synced. A "Sync now" button (and later a slow schedule)
   updates it. This keeps Square load low and means a Square outage only stales the data.
7. **Failure isolation.** Any connector error is caught, logged as an event with no response body, and shown as
   "Square could not be reached; showing data from `<time>`". LocalAI never retries in a tight loop.
8. **Disconnect** deletes the token file, calls revoke if the flow allows it (open item), and offers to delete
   the local store for that business. Disconnecting changes nothing in the Square account except the app's access.

Packs and manifest: `design/packs.md` permits only file access. The `biz` pack needs a new permission kind
(`data = ["sales", "products"]`, a list of named query groups). That is a **manifest schema change**
(`api_version` 2) and must be approved before it is built. Existing packs keep `api_version` 1.

## 4. Data model and `business_id`

- Paths: `data/<business_id>/business.db` and `secrets/<business_id>/square.json`. `business_id` is
  validated against `[a-z0-9-]{1,40}` and is never taken from model output. For now there is one id,
  `default`, set in configuration.
- Every table has `business_id` and every gateway query filters on it. Test: with two fabricated businesses in
  one database file, no function returns the other's rows.
- Money is **integer cents** plus a currency code. No floats anywhere in the calculation path.
- Timestamps are stored as UTC. Each location row stores its IANA timezone. A "day" is computed in the
  location's timezone, and the answer states that timezone.
- Tables (sketch): `locations`, `orders_raw` (the unmodified order payload, for audit), `order_lines`,
  `payments`, `refunds`, `catalog_items`, `inventory_counts`, `sync_runs` (start, end, status, row counts,
  `complete` flag), and `metric_definitions` (name, text, version).
- Documents and embeddings get the same `business_id` filter when RAG is revised in Phase 4. That work is out of
  scope here.

## 5. Credentials

- File `secrets/<business_id>/square.json`, mode 0600, on a separate Docker volume mounted only into the
  connector's process path. Never in `docs/`, `logs/`, `data/`, the image, or Git (`.gitignore` and the
  gitleaks hook are extended in Phase 1).
- **PKCE, so no client secret ships with the app.** Only the public `client_id` is configured.
- The single-use refresh token must be handled carefully: write the new token to a temp file, fsync, then
  atomically rename, and only then discard the old one. If the process dies between the Square response and the
  write, the old refresh token is already spent and the owner must reconnect. The connector detects this and shows
  "Reconnect Square" rather than looping.
- Refresh at least every 7 days while the app runs, and warn when the refresh token is within 14 days of its
  90-day expiry (a shop that is closed for a quarter will need to reconnect).
- Tokens are never in logs, prompts, tool results, exception messages, or the UI. A redaction test feeds a
  token through every error path and scans the log and the model context.
- Document plainly: **0600 permissions limit who can read the file; they are not encryption at rest.** Anyone with
  the Mac's disk and the user's login can read it. macOS Keychain is the later upgrade.

## 6. Approval classes (groundwork only)

Each tool in a manifest gets an `access` value: `read_routine`, `read_sensitive`, or `write`. For the MVP the
coordinator **treats all of them as needing route approval, exactly as today**, so behavior does not change.
The field exists so a later, tested change can relax `read_routine` only. Sales and inventory queries are
`read_routine` for the owner. Nothing in the MVP is `write` for Square: Square tools cannot be marked `write`
(the loader refuses it), because no Square write path exists.

## 7. Accuracy contract

Every financial answer is built by code as an **AnswerEnvelope**, and the model only explains it:

| Field | Example |
|---|---|
| metric | `net_sales` |
| definition | The text stored in `metric_definitions`, quoted from Square or from our documented formula, with its version |
| period | 2026-11-15 to 2026-11-15, as local dates |
| timezone | `America/Los_Angeles` |
| source | `Square Orders API (SearchOrders), calculated by LocalAI` or `Square Reporting API (Orders.net_sales)` |
| freshness | `cached`, with `synced_at` (never "live", since answers never call Square) |
| completeness | the last sync's `complete` flag and the number of rows used |
| caveats | for example "includes refunds made on later days" |
| value | integer cents plus currency |

Rules:

- Code renders the sentence with the number. Hermes may add explanation around it but the number is inserted by
  code. Output check: every number in the final reply must appear in the envelope, or the reply is replaced with
  the code-rendered text. An eval case tries to make the model change a figure.
- Gross sales, net sales, refunds, discounts, tax, tips and service charges are separate named metrics. A question
  that does not say which one gets a short clarification, defaulting to net sales **only if the answer states it**.
- If the period is not fully covered by a completed sync, the answer says which dates are missing.
- Missing data returns "no data for that period", never zero.
- **Refund attribution is an owner decision** (section 9, Q3), because the docs do not say how Square assigns a
  later-day refund. Whichever policy is chosen goes into the metric definition and the caveat.

## 8. Choosing the data source (decided by a Phase 1a spike)

| Option | For | Against |
|---|---|---|
| A. Reporting API `Orders.net_sales` | Square's own definition, location-local days, least code | Beta status, Sandbox support and a gross sales measure are unconfirmed; 15-minute delay; row and rate limits unknown |
| B. Compute from Orders, Payments and Refunds | Full control, works in Sandbox, every number traceable to orders, gross and net both possible | We own the definitions, and Order money fields are unconfirmed; more code; must be reconciled to what Square shows |
| C. Both: B for answers, A as a cross-check | Strongest accuracy evidence | Most work. Only worth it if A works in Sandbox |

My leaning: **B, with a reconciliation test against A where available**, because it satisfies "explain the
calculation" and "cite source records". It is a leaning, not a decision. The store in section 4 holds raw order
data, so switching to A, or adding it, does not change the schema.

The spike (Phase 1a, no LLM, no app changes) answers: does Sandbox serve the Reporting API, do Order money
fields reproduce Square's net sales for seeded orders with discounts, tips, tax and a partial refund, and how
do canceled and later-day refunds behave. Its output is a short findings note and fabricated fixtures.

## 9. Questions for the owner

1. Approve the `api_version` 2 manifest change (a `data` permission and an `access` class) in section 3 and 6?
2. Approve the data-source leaning in section 8 (B, cross-check against A if possible), pending the spike?
3. Refund attribution: subtract a refund on the **day the refund happened** (matches a cash view) or on the **day
   of the original sale** (matches a "what did that day earn" view)? I recommend the refund date, labelled, but
   Square's own behavior must be checked first.
4. The app has no place for `business_id` configuration. OK to read it from an environment variable with default
   `default`?
5. Egress: the container can reach the whole internet today. Real domain-level egress filtering needs a proxy
   sidecar. Is it acceptable to rely on the in-code allowlist for the Sandbox MVP and make the proxy a Phase 5
   item? I recommend yes, written in the threat model as a known gap.

## 10. Tests the design requires (before the code that satisfies them)

Non-interference: every write endpoint in the table is refused; an unknown path is refused; a token with a write
scope is rejected at connect; no module other than `square_client` imports an HTTP library; a mocked transport
records every request and the suite asserts only allowlisted calls were made.
Accuracy (fabricated fixtures): a day with discounts, tax, tips; a partial refund; a refund on a later day; a
canceled order; an empty day; a day across a UTC boundary and a DST change; pagination across several pages with a
cursor; a 429 followed by success; an expired cursor; a sync that stops halfway (answer says incomplete).
Secrets: redaction through every error path; file mode 0600; atomic refresh with a simulated crash.
Isolation: two `business_id` values in one test database never leak.
Model behavior: Hermes routes revenue questions to the `biz` pack and document questions to notes; asked to
change a number, the reply still shows the code's number.

## 11. What changes elsewhere (not done yet)

`requirements.txt` (httpx, pinned, said out loud), the Dockerfile and compose (two volumes, an env var), the
telemetry test that asserts no HTTP client, `.gitignore`, threat-model rewrite for outbound traffic and
credentials, a new rule file `design/code-rules/rule-connector-egress.md`, and a roadmap entry. Each is its own
small step with its own test.

## 12. Gate before Phase 1

Phase 1 starts only after you review this note and answer section 9. The first code step is the Phase 1a spike
(read-only, standalone, fabricated data), not the connector.
