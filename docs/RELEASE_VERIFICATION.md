# Collector and integration verification

This record summarizes checks performed on November 5, 2026. It preserves useful
provider and integration evidence without publishing account credentials or
operator deployment inputs. See [website verification](WEBSITE_VERIFICATION.md)
for the latest frontend checks and [development status](DEVELOPMENT_STATUS.md) for
remaining work.

## Integration checks

The account/API release passed 47 production OAuth/MCP checks using the official
MCP SDK. These covered consent with PKCE, tool calls, refresh rotation, replay
rejection, revocation, and audience isolation. The API smoke covered invitation
signup, CSRF enforcement, key creation/revocation, repeated warm MCP calls, and
fresh scheduled collection. Disposable test accounts were deleted afterward.

Local tests exercised webhook signatures, ownership challenges, SSRF controls,
retries, and delivery ordering. This record does not establish successful receipt
of a production customer webhook or Telegram price alert.

ARM64 checks confirmed API password hashing, static assets, and browser worker
startup/cleanup with a read-only root filesystem and bounded temporary storage.
Actual release inputs and immutable image digests belong in private operator
records, not reusable setup examples.

## Scheduled price observations

For DEN–DFW on March 14, 2027:

| Observation time (UTC) | Observed eligible total | Evidence |
| --- | --- | --- |
| 08:11:23 | USD 314 Economy | Selected United itinerary recorded by scheduled AWS worker |
| 08:14:34 | USD 191 Economy Bundle | Route search selected Frontier F9 2550 |
| 08:44:36 | USD 191 Economy Bundle | New F9 2550 observation after the browser-startup retry update |

These are historical observations, not current offers. The final route check
validated flight identity, passenger count, fare eligibility, and the selected
booking link. A cached price was not counted as fresh collection.

Tests also exposed timeouts and a fast browser startup failure. The collector
allows one fresh-profile retry for a fast startup failure. Page failures back off
and remain visible; old prices are not marked as fresh.

## Limits of verification

Spot checks do not prove sustained capacity, availability, AWS free-tier
eligibility, or a fixed alert latency. A fare can appear and disappear between
checks. The service compares supported Google Flights results and cannot establish
a market-wide minimum. Broader coverage, cost measurements, alarm delivery, and a
production recovery drill remain necessary before unrestricted access.
