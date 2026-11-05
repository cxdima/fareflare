# Interface design decisions

The November 2026 revision responds to feedback about vague copy, inconsistent
button hierarchy, repetitive labels, poor flight alignment, and generic marketing
styling. The product uses Angular and Bootstrap, external SCSS, and local assets.

## Guidance applied

- [Anthropic frontend-design](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md): derive layout from the actual task; remove decorative labels and slogan fragments; use deliberate typography and review the rendered result.
- [Impeccable](https://impeccable.style/) and its [craft floor](https://github.com/pbakaus/impeccable/blob/main/.agents/skills/impeccable/reference/craft-floor.md): give task screens a clear hierarchy, make controls explain their action, inspect responsive states, and remove generic presentation habits. The guidance was read directly; an Impeccable binary was not installed or run.
- [Angular styling](https://angular.dev/guide/components/styling) and [security](https://angular.dev/best-practices/security): component styles, safe templates, and nonce-based CSP.
- [Bootstrap buttons](https://getbootstrap.com/docs/5.3/components/buttons/): reuse accessible button semantics while defining Fareflare colors and states centrally.
- [Google structured-data guidelines](https://developers.google.com/search/docs/appearance/structured-data/sd-policies): metadata describes visible content, without fabricated reviews or claims.

## Choices in Fareflare

Flight rows place route, airline, fare, and observation timing in a stable order.
Airline logos identify actual carriers and have a readable fallback. Awaiting a
first observation is distinguished from an overdue check. The developer view
prioritizes a connection method and complete copyable configuration rather than
equal panels competing for attention.

Public pages explain tracking with a labeled example and a real sequence of user
actions. Upright Plus Jakarta Sans replaces the serif/italic combination. Cool
surfaces, navy text, orange primary actions, and green price states are shared
across the site. No personal origin story, decorative overlines, or development
labels in the workspace header/footer.

These sources inform decisions, not guarantees of visual quality. Verification
includes screenshots, narrow screens, keyboard use, accessibility checks, and
behavioral browser tests against the actual Python portal.
