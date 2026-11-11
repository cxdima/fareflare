---
version: 1
slug: "web-src-app-public-landing-component-html"
primary_target: "web/src/app/public/landing.component.html"
related_targets: ["web/src/app/dashboard/dashboard.component.html","web/src/app/auth/auth.component.html","web/src/styles.scss"]
---

# Fareflare web: whole-site redesign

Scope: every surface in `web/src/app` (landing, reading pages, status, sign-in,
dashboard). Mode by surface: landing = Persuade; guides, legal, docs = Read;
status and the dashboard = Operate; sign-in = Operate with one Persuade panel.

Audience and job: a traveler with one flight in mind who wants to stop
re-checking its price. Action: paste a Google Flights link. Proof on hand: the
product's own alert, its recorded price history, and its open source. No
testimonials, numbers or logos exist; none are invented.

Constraints: strict CSP (no `style` attributes anywhere, same-origin assets,
no remote fonts), script-free HTML for crawlers must still read well, the
Playwright suite and axe checks stay green, Angular standalone + OnPush + SCSS.

## How the direction was reached

No interview: the owner asked for work without check-ins, so this is inferred
from the brief and its two reference images. Build path this session: code-led
(not stored). The owner's references pin the materials: an oversized grotesk
headline with one italic line, a soft lavender field, a phone in the hero, a
light bento dashboard with bright chips and hatched bars, scroll-scrubbed image
sequences, generated 3D graphics.

Grounded list, by resonance: 1 split-flap departures board, 2 boarding pass,
3 fare graph and ticker, 4 baggage routing tag, 5 seat-back moving map,
6 airport wayfinding, 7 safety card. The roll assigned 4. The pinned materials
stay; the tag supplies topology, controls, state vocabulary and ritual.

Challenger verdicts, all declined (each needs a dark or surreal ground the
brief rules out), with what was kept:
- Raise from the nixie counter: a price is a set of fixed digit places; when it
  changes, each place rolls on its own.
- Raise from the sticker album: unused capacity is shown as ghost slots that
  say what belongs there; a new flight presses into its slot.
- Raise from the torn billboard: the perforation is real; the stub is a
  separate piece and actions happen on it.
- Raise from the cloud quarry: the page is cut blocks with deep gaps, never a
  continuous sheet.

## Direction contract

THESIS: Every watched flight is a baggage tag: a strip with a giant airport
code, a perforated stub that carries the price, and a sticker for its state.
Refuses the category page (sky gradient, stock plane photo, search box) and the
dashboard default (grey sidebar plus equal white cards).

OWN-WORLD: Paper ground #F3F2EE, ink #17141F, one lavender field #DAD4F7 that
owns whole regions, lime #C6FF4D for a recorded drop, violet #B58CFF for a
rise, ink-on-colour only. Mona Sans throughout: wide heavy capitals for
display with one light italic line, normal width for interface. Shapes: 28px
blocks, full pills, clipped tag corners, punched notches, dotted perforations,
hatched bars for "no record", solid bars for recorded prices. Graphics are
matte paper objects in a lavender studio.

STORY: The visitor sees their own move (paste a link), watches a paper plane
unfold into a tagged price as they scroll, tries the two alert rules, learns it
needs no Google account and checks every 15 minutes, then starts.

FIRST VIEWPORT: Paper page with a pill nav. Left, three lines of wide capitals,
"KNOW WHEN YOUR / FLIGHT PRICE / DROPS" (last line light italic), bleeding
down into a lavender block that holds the lede, the link field and the black
pill button. Right, a phone standing over the block edge showing the example
alert, a paper plane crossing behind it on a drawn flight path.

SIGNATURE INTERACTION: a pinned canvas plays an image sequence as the page
scrolls (plane to tag); the three steps change beside it and the example fare
prints onto the finished tag. Motion grammar: things arrive by unfolding or
pressing down, never by fading up; capitals rise line by line from a mask;
blocks stack over each other.

FORM: baggage routing tag, position 4 of 7; seed key 94e63aae.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Open

- Production deploy is not part of this work; it waits for the owner.
