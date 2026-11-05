# Fareflare design research

Research checked November 5, 2026. The goal is a recognizable, useful product with
consistent implementation, rather than a collection of fashionable effects.

## What people recommend

Directly reviewed Reddit discussions consistently favor **specific references,
explicit design decisions, and visual iteration** over a longer list of banned
styles. One [Claude Code/Codex discussion](https://www.reddit.com/r/ClaudeCode/comments/1wu9e5a/how_do_you_get_claude_code_codex_to_actually/)
describes defining the grid, spacing, typography, and component behavior before
coding. A [Codex workflow discussion](https://www.reddit.com/r/codex/comments/1wkhzv3/i_found_the_best_way_to_build_insane_uis_with/)
recommends refining a visual reference before implementation. Another
[design-consistency discussion](https://www.reddit.com/r/ClaudeAI/comments/1t24gan/few_months_of_frontenddesign_uiuxpromaxskill/)
argues for project-specific layout primitives and a persistent `DESIGN.md`.

These are practitioner anecdotes, not controlled evidence that one model is
better than another. The reviewed [Astra discussion](https://www.reddit.com/r/codex/comments/1w8zkv3/astras_design_capabilities/)
contains conflicting opinions; it does not establish a special setting that
guarantees better design.

A separate [Astra UI discussion](https://www.reddit.com/r/codex/comments/1wbu3zq/codex_with_astra_vs_ui_design/)
describes poor proportions and unnecessary explanatory text despite higher reasoning
settings. Replies recommend concrete visual references and bounded critique cycles.
On [Hacker News](https://news.ycombinator.com/item?id=49901973), practitioners describe
the familiar design process: choose a functional goal and motif, explore, then refine
one direction. These accounts support reviewing actual screens rather than assuming
a model setting or a different palette will fix the interface.

[OpenAI's frontend guidance](https://developers.openai.com/api/docs/guides/frontend-prompt)
emphasizes domain-appropriate interfaces, restrained operational screens,
established icon libraries, relevant visual assets, and desktop/mobile screenshot
verification. Its example is currently described as GPT-5.5 guidance, with broader
applicability; it is not an Astra-specific benchmark.
[Anthropic's design guidance](https://claude.com/marketplace/plugins/frontend-design)
also starts with purpose, audience, and a deliberate visual direction.
[Nielsen Norman Group](https://www.nngroup.com/articles/visual-hierarchy-ux-definition/)
explains how scale, contrast, and grouping establish a clear reading order.

## Decisions applied to Fareflare

- Separate the public travel/product story from the working dashboard. The
  dashboard prioritizes routes, prices, freshness, and actions; the landing page
  explains why the product exists and how to start.
- Use warm paper (`#f7f4ed`), dark ink (`#172e36`), and burnt orange (`#b94724`),
  with self-hosted DM Sans and Newsreader. Public headings use editorial serif
  typography; the application stays denser and functional. Dawn travel imagery
  supports the story without turning every section into an illustrated card.
- Use shared typography, color, spacing, control, and icon rules. Keep styles in
  external SCSS and class names in templates; avoid per-element style bindings.
- Use one established icon family, with text labels for ambiguous actions.
  A generated brand asset serves the identity; icons serve navigation and actions.
- Build meaningful content around the original family use case, supported flight
  links, and actual notification behavior. Do not invent testimonials, customer
  counts, savings statistics, or guaranteed market-wide lowest prices.
- Review rendered desktop and mobile pages, keyboard interactions, empty/error
  states, and real account workflows. Passing a build is not visual verification.

These choices are the team's synthesis of the research and the product brief,
not claims that any single article proves a particular aesthetic is best.

## Stack and delivery choices

The npm registry reported Angular core **22.2.4**, CLI **22.2.6**, Bootstrap
**5.3.8**, and Bootstrap Icons **1.13.2** during research.
[Bootstrap](https://getbootstrap.com/) currently advertises version 6 as an alpha;
Fareflare uses the stable 5.3 series. [Bootstrap Icons](https://icons.getbootstrap.com/)
provides one consistent, open-source symbol set.
[Fontsource](https://fontsource.org/docs/getting-started/introduction) supports
versioned, self-hosted fonts without runtime font-service requests.

[Angular's static rendering documentation](https://angular.dev/guide/ssr)
establishes that public HTML can be generated without adding a Node production
server. Fareflare serves public, indexable HTML alongside the Angular customer
application through its existing Python portal. Private account views remain
outside search indexing. The implementation keeps the existing same-origin
security boundary: no remote scripts or style attributes, external application
SCSS, and no relaxation to `unsafe-inline`. Where framework styles or structured
data need a nonce, the portal supplies a new nonce per response. See
[Angular's CSP guidance](https://angular.dev/best-practices/security).

Public content uses descriptive titles, canonical links, social metadata, a
sitemap, and structured data that matches visible content. Blog entries use
`BlogPosting` with real publication metadata; no fabricated ratings are added.
[Google's article documentation](https://developers.google.com/search/docs/appearance/structured-data/article)
and [JavaScript SEO guidance](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics)
inform these choices. Structured data helps machines understand pages; it does
not guarantee indexing, ranking, or rich results.
