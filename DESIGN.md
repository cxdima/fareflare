# Fareflare design system

Fareflare is a practical flight-price notebook with a personal origin: a father
and son wanted to notice fares before a nightly email arrived. Public pages should
feel like an independent travel publication. The application should make prices,
observation times, and the next action easy to find.

## Visual rules

| Role | Decision |
| --- | --- |
| Background | Warm paper `#f7f4ed`; surfaces `#fffefa` |
| Text | Ink `#172e36`; secondary text `#5b686c` |
| Accent | Burnt orange `#b94724`; use for orientation, focus, and selected actions |
| Borders | `#d8d9d2`; group related content with spacing and rules |
| Type | Locally served DM Sans for controls/body; Newsreader for editorial headings |
| Icons | Bootstrap Icons; decorative icons are hidden from assistive technology |
| Spacing | Multiples of 4px; generous public sections, tighter application rows |
| Corners | 4–8px for controls/panels; no pill-shaped containers by default |
| Motion | Brief state feedback; respect reduced-motion preferences |

Use imagery where it explains the travel context. Do not add imagery to routine
account operations. Generated imagery is illustrative, never evidence of a real
fare or customer. Label all example prices. No fabricated reviews, live counters,
customer logos, or promises of detecting every market change.

## Implementation boundaries

- Angular standalone component classes use OnPush, signals, and dependency injection.
  Templates and SCSS live in separate files. Use semantic classes and Bootstrap
  layout/form primitives. Do not add `style` attributes or Angular style bindings.
- `ApiService` owns same-origin requests, CSRF, and error translation.
  `SessionFacade` owns account state; `WorkspaceFacade` owns dashboard refreshes.
  Components express user actions and rendering rather than duplicating transport.
- `MonitorPresenter` applies the GoF **Strategy** pattern to selected itineraries
  and route searches. Both return one presentation contract; the route strategy
  chooses the actual observed offer, while the selected strategy retains the
  selected itinerary. Templates do not branch on provider internals.
- The Python content registry supplies public article content and metadata to
  both initial crawlable HTML and Angular. Structured data must describe visible
  content. Account routes and credential-bearing URLs are not indexed.
- Component style elements use a fresh server-issued CSP nonce. Application code
  does not use inline CSS, `unsafe-inline`, remote fonts, or CDN scripts.

## Review a change

Check desktop and 375px mobile screenshots, keyboard focus, labels, errors, empty
states, long routes, and real account flows. Run the browser suite against the
Python portal so CSP and session behavior are exercised. Use axe as an automated
check alongside visual and keyboard review. Confirm that CSS classes describe
reusable states instead of encoding arbitrary one-off values.

See [research and sources](docs/DESIGN_RESEARCH.md) for the reasoning and
[asset provenance](docs/BRAND_ASSETS.md) for generated artwork.
