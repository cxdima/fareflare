# Fareflare design system

Fareflare helps travelers act on recorded flight price changes. The interface
should answer three questions quickly: which flight, what price, and when was it
checked? Connection settings should explain the next action without unrelated
product history.

## Visual language

| Role | Decision |
| --- | --- |
| Background | Muted sage `#e9ede8`; content `#f4f6f1`; sidebar `#e1e7df` |
| Text | Deep green `#243b3b`; secondary `#53645e` |
| Action | Burnt orange `#aa4428` for primary actions; teal `#315e60` for links/focus |
| State | Green `#16765f` for observed savings; amber for delayed collection |
| Borders | `#cbd4ca`, used to group information rather than decorate it |
| Type | Self-hosted Plus Jakarta Sans; upright text throughout |
| Icons | Bootstrap Icons, with labels for actions and hidden decorative icons |
| Shape | 8–9px controls, 12–16px panels, contained, unframed airline marks |

Public pages lead with what the tracker does and a clearly labeled example.
Flight rows align route details with their price, keep airline identity visible,
and show collection state once. A pending first check is not a failure. API and
MCP setup show the selected connection method, a complete endpoint, and a copy
action. Credentials remain distinct from ordinary configuration.

Keep the established sidebar and workspace layout. An underline and stronger type
identify the current navigation item; avoid a colored pill or repeated monitor
count. Group the account link and sign-out action in a compact panel, with GitHub
separate. Primary flight actions use an oversized plane silhouette as a subtly lighter,
clipped background texture behind a plain text label. Do not add a separate plane
icon or divider. Retain a defined edge, visible focus and pressed state. Keep movement brief and respect reduced-motion preferences.

Account settings use four short sections: Display, Notifications, Connections and
Security. Section changes preserve unsaved drafts. Show a format example before
saving and label sample message content explicitly.
Keep unsaved preview options distinct from persisted settings. Disable editing
during saves and preserve drafts when a request fails.

Use sentence-case headings and direct action labels. Avoid decorative overlines,
italic slogans, numbered sections without a real sequence, and repeated status
badges. Development and billing state belong in relevant account/access details,
not persistent page chrome. Never publish personal origin stories.

## Implementation

Angular standalone classes use OnPush, signals, and dependency injection.
Templates and SCSS live in separate files; Bootstrap provides form and layout
primitives. Theme custom buttons centrally and name classes by purpose. No inline
style attributes, remote font requests, or CDN scripts.

`ApiService` owns HTTP/CSRF, `SessionFacade` owns account state, and
`WorkspaceFacade` owns refreshes. Dashboard-scoped `PreferencesFacade` owns account
display/message settings; `RegionalFormat` formats observations and fares through
cached native `Intl` formatters. Airport calendar dates never shift with the
account time zone. See the [preference contract](docs/ACCOUNT_PREFERENCES.md).

`MonitorPresenter` uses the GoF Strategy pattern
for selected itineraries and route searches, both returning one display contract.
Airline identity is a separate reusable component with a text fallback. Its mark
uses a 28px box, 20px contained artwork and 8px spacing to the carrier name.

Flight rows lead with route, date, latest price and freshness. Filters and monitor
management use native disclosures; active filters remain evident when closed.
Keep the first fare visible in the initial mobile viewport. History leads with the
latest reading and chart, followed by comparisons and full recorded readings.

Native select fields share themed chevrons, focus and states. Supporting browsers
also theme the native picker; other browsers retain their platform picker. Do not
replace native keyboard semantics to obtain a visual effect. The existing history
range buttons remain date controls; there is no editable travel-date calendar.

The Python public-content registry supplies crawlable HTML, article content, and
metadata. Structured data must match visible facts. Private pages and credentials
stay out of search indexing.

## Review

Review desktop and narrow mobile renders, keyboard focus, long names, missing
logos, pending/error/empty states, and actual account flows. Test against the
Python portal so CSP, sessions, and server metadata are included. Automated axe
checks complement visual review. All example fares must be labeled; never imply
market-wide coverage or guaranteed detection of every price change.

See [design research](docs/DESIGN_RESEARCH.md) and
[asset provenance](docs/BRAND_ASSETS.md).
