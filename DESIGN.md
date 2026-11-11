---
name: Fareflare
description: Flight price alerts drawn as baggage tags on a paper desk, with one lavender studio field.
colors:
  lav: "#d2cbf6"
  lav-soft: "#ebe7fb"
  lav-poster: "#d0c5f6"
  lime: "#c6ff4d"
  lime-deep: "#b1ea34"
  violet: "#b58cff"
  violet-ink: "#6b3fd4"
  coral: "#ff7a66"
  paper: "#f3f2ee"
  paper-deep: "#e9e7e1"
  card: "#ffffff"
  ink: "#17141f"
  ink-hover: "#2c2839"
  ink-2: "#4a465c"
  ink-3: "#5f5a76"
  line: "#dddad2"
  line-strong: "#bdb9c9"
  night-2: "#262231"
  night-text: "#b9b4cc"
  code-text: "#f1effa"
  disabled-fill: "#e2dfd8"
  danger: "#b3261e"
  danger-deep: "#7c1a15"
  danger-wash: "#ffe3de"
  success: "#2f6b00"
typography:
  display:
    fontFamily: "'Mona Sans', system-ui, sans-serif"
    fontSize: "clamp(2rem, 5.2vw, 5rem)"
    fontWeight: 800
    lineHeight: 0.92
    letterSpacing: "-0.035em"
    fontVariation: "'wdth' 118"
  display-hero:
    fontFamily: "'Mona Sans', system-ui, sans-serif"
    fontSize: "clamp(2.75rem, 6.5vw, 7rem)"
    fontWeight: 800
    lineHeight: 0.92
    letterSpacing: "-0.035em"
    fontVariation: "'wdth' 118"
  display-turn:
    fontFamily: "'Mona Sans', system-ui, sans-serif"
    fontSize: "clamp(2rem, 5.2vw, 5rem)"
    fontWeight: 300
    lineHeight: 0.92
    letterSpacing: "-0.04em"
    fontVariation: "'wdth' 118"
  headline:
    fontFamily: "'Mona Sans', system-ui, sans-serif"
    fontSize: "clamp(2.1rem, 4.2vw, 3.4rem)"
    fontWeight: 780
    lineHeight: 1
    letterSpacing: "-0.04em"
    fontVariation: "'wdth' 112"
  tag-code:
    fontFamily: "'Mona Sans', system-ui, sans-serif"
    fontSize: "clamp(2.2rem, 5.4vw, 4.75rem)"
    fontWeight: 800
    lineHeight: 0.92
    letterSpacing: "-0.04em"
    fontVariation: "'wdth' 118"
  tag-price:
    fontFamily: "'Mona Sans', system-ui, sans-serif"
    fontSize: "clamp(2.1rem, 3.6vw, 3rem)"
    fontWeight: 800
    lineHeight: 1
    letterSpacing: "-0.045em"
    fontVariation: "'wdth' 108"
  title:
    fontFamily: "'Mona Sans', system-ui, sans-serif"
    fontSize: "1.3rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.025em"
  lede:
    fontFamily: "'Mona Sans', system-ui, sans-serif"
    fontSize: "1.15rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  body:
    fontFamily: "'Mona Sans', system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  body-reading:
    fontFamily: "'Mona Sans', system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.7
    letterSpacing: "normal"
  label:
    fontFamily: "'Mona Sans', system-ui, sans-serif"
    fontSize: "0.925rem"
    fontWeight: 620
    lineHeight: 1.5
    letterSpacing: "-0.005em"
  caption:
    fontFamily: "'Mona Sans', system-ui, sans-serif"
    fontSize: "0.8rem"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "normal"
  sticker:
    fontFamily: "'Mona Sans', system-ui, sans-serif"
    fontSize: "0.72rem"
    fontWeight: 800
    lineHeight: 1.35
    letterSpacing: "0.04em"
  mono:
    fontFamily: "ui-monospace, 'SF Mono', 'Cascadia Mono', Menlo, Consolas, monospace"
    fontSize: "0.85rem"
    fontWeight: 400
    lineHeight: 1.65
    letterSpacing: "normal"
rounded:
  pill: "999px"
  block: "1.75rem"
  block-narrow: "1.4rem"
  card: "1.25rem"
  inner: "1rem"
  control: "0.875rem"
  check: "0.4rem"
spacing:
  gutter-narrow: "16px"
  gutter: "24px"
  sheet-inset: "0.75rem"
  stack: "0.75rem"
  list: "1rem"
  form: "1.25rem"
  panel: "clamp(1.25rem, 2.4vw, 2rem)"
  tile: "clamp(1.25rem, 2.2vw, 2rem)"
  bento-gap: "clamp(0.75rem, 1.4vw, 1.25rem)"
  section: "clamp(4.5rem, 10vw, 9rem)"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.card}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0.7rem 1.3rem"
    height: "46px"
  button-primary-hover:
    backgroundColor: "{colors.ink-hover}"
    textColor: "{colors.card}"
  button-primary-disabled:
    backgroundColor: "{colors.disabled-fill}"
    textColor: "{colors.ink-3}"
  button-flight:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.card}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0.45rem 0.45rem 0.45rem 1.35rem"
    height: "46px"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0.7rem 1.3rem"
    height: "46px"
  button-outline-hover:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.card}"
  button-quiet:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0.7rem 1.3rem"
    height: "46px"
  button-quiet-hover:
    backgroundColor: "{colors.paper-deep}"
    textColor: "{colors.ink}"
  button-light:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0.7rem 1.3rem"
    height: "46px"
  button-light-hover:
    backgroundColor: "{colors.lime}"
    textColor: "{colors.ink}"
  button-danger:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.card}"
    rounded: "{rounded.pill}"
    padding: "0.7rem 1.3rem"
    height: "46px"
  input:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0.75rem 1rem"
    height: "48px"
  link-field:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0.4rem"
  sticker:
    backgroundColor: "{colors.paper-deep}"
    textColor: "{colors.ink}"
    typography: "{typography.caption}"
    rounded: "{rounded.pill}"
    padding: "0.3rem 0.7rem"
  sticker-active:
    backgroundColor: "{colors.lime}"
    textColor: "{colors.ink}"
  sticker-attention:
    backgroundColor: "{colors.violet}"
    textColor: "{colors.ink}"
  sticker-failed:
    backgroundColor: "{colors.coral}"
    textColor: "{colors.ink}"
  panel:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.block}"
    padding: "{spacing.panel}"
  flight-tag:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.block}"
  flight-tag-paused:
    backgroundColor: "{colors.paper-deep}"
    textColor: "{colors.ink-2}"
  nav-item:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0 1.1rem"
    height: "48px"
  nav-item-current:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.card}"
  segment:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0 1.35rem"
    height: "46px"
  segment-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.card}"
  tile-lime:
    backgroundColor: "{colors.lime}"
    textColor: "{colors.ink}"
    rounded: "{rounded.block}"
    padding: "{spacing.tile}"
  tile-ink:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.card}"
    rounded: "{rounded.block}"
    padding: "{spacing.tile}"
  tile-lav:
    backgroundColor: "{colors.lav}"
    textColor: "{colors.ink}"
    rounded: "{rounded.block}"
    padding: "{spacing.tile}"
---

# Design System: Fareflare

## Overview

**Creative North Star: "The Baggage Tag"**

Every watched flight is a baggage tag laid flat on a paper desk: a strip with a giant airport code on its body, a perforated stub that carries the price, and a sticker pressed on for its state. The page around it is cut blocks of paper, ink, lavender and lime with the paper ground showing between them, never one continuous sheet. Pictures are matte folded-paper objects photographed in a lavender studio; the lavender panels in the interface are that same studio backdrop, so a picture and the panel behind it meet without an edge.

The website is loud in scale and quiet in means: three lines of wide heavy capitals with one light italic line, one lavender field, one ink pill with a lime disc. The workspace is the same materials at working size: white sheets on the paper ground, an ink pill for the page you are on, and the tag as the one large object. Density is low; a screen holds a few big things with deep gaps, and small type is reserved for facts about a recording (when it was checked, what it is compared with).

What this system refuses, as built: the sky-gradient travel page with a stock plane and a search box, and the dashboard of a grey sidebar plus equal white cards. Nothing fades up; things arrive by unfolding from a clip or pressing down onto the desk.

**Key Characteristics:**
- Paper ground, ink type, one lavender field that owns whole regions, lime and violet only as fills behind ink.
- One typeface, Mona Sans variable, moved along its width and weight axes instead of pairing families.
- Tag anatomy everywhere a flight appears: clipped corner, punched notches, dotted perforation, stub, sticker.
- Solid ink bars are recorded prices; hatched bars are "no record"; the lowest recorded bar is lime with an ink outline.
- Outlines are rare. A surface is told from its neighbour by a different paper, not by a border.
- State is a word on a sticker, a bar's shape, or a sentence, never colour alone.

## Colors

A warm off-white paper, a violet-black ink, one lavender measured from the artwork, and two sticker colours that never carry text of their own.

### Primary
- **Studio Lavender** (`lav`, #d2cbf6): the one field colour. It owns whole regions: the hero block, the pinned "how it works" block, the closing block, the first-flight invitation, the open FAQ item, the reading-page contents card, the 4px focus halo on fields, and the small discs behind glyphs in empty states. It is the measured backdrop of the encoded scroll-sequence frames, which is why the sequence can sit on a panel with no visible picture edge.
- **Poster Lavender** (`lav-poster`, #d0c5f6): the sign-in poster only. It is the exact backdrop of the suitcase picture, a different measurement from the sequence frames.
- **Lavender Wash** (`lav-soft`, #ebe7fb): informational notes inside a white sheet and the hover row in the themed select picker.

### Secondary
- **Signal Lime** (`lime`, #c6ff4d): a recorded drop and anything live or chosen: the "watching" sticker, the lowest bar, the disc in the flight button, the current step, the open-source card in the sidebar, the lead bento tile, the current item in the phone dock, text selection.
- **Lime, pressed** (`lime-deep`, #b1ea34): the lowest bar inside small charts, where it sits beside ink bars and needs more weight, and the pressed state of the white button.

### Tertiary
- **Rise Violet** (`violet`, #b58cff): a rise, or something that needs a look: stale and degraded stickers, the degraded status dot and hour bars.
- **Violet Ink** (`violet-ink`, #6b3fd4): the only violet that may be text or a line: inline code, list markers on reading pages, the text caret, link hover, the dotted target line and its label in charts.
- **Coral** (`coral`, #ff7a66): failure as a fill: the dead-letter sticker, the major-outage dot and hour bars.

### Neutral
- **Paper** (`paper`, #f3f2ee): the page ground everywhere, and the colour of every punched hole and notch.
- **Paper, shaded** (`paper-deep`, #e9e7e1): neutral stickers, hover on quiet controls, a paused tag's stock, skeleton lines.
- **Sheet White** (`card`, #ffffff): panels, tags, fields, the sidebar sheet.
- **Ink** (`ink`, #17141f): all primary text, the primary button, the current navigation pill, the developer block, the footer, the status history block. Hover on an ink button is `ink-hover` (#2c2839).
- **Ink, second** (`ink-2`, #4a465c) and **Ink, third** (`ink-3`, #5f5a76): supporting text; the third is the floor for placeholders, helper text and disabled labels.
- **Line** (`line`, #dddad2) and **Line, strong** (`line-strong`, #bdb9c9): the strong one draws field borders and every dotted perforation; the light one is table rules.
- **Night surfaces**: on ink blocks, the raised panel is `night-2` (#262231), supporting text is `night-text` (#b9b4cc), code is `code-text` (#f1effa), and focus outlines turn lime.
- **Functional**: `danger` (#b3261e) with `danger-deep` (#7c1a15) text on `danger-wash` (#ffe3de); `success` (#2f6b00) as text for a saved confirmation or a recorded decrease in the history table; `disabled-fill` (#e2dfd8) for a disabled button.

### Named Rules
**The Ink-on-Colour Rule.** Lime, violet, coral and lavender are fills. Text on them is ink; they are never text on paper. The one text violet is `violet-ink`.

**The One Field Rule.** Lavender owns a whole block or nothing. It is not a tint for cards, not a border, not a gradient stop.

**The Measured Backdrop Rule.** A panel behind a picture takes the picture's measured backdrop colour, not the colour the prompt asked for. That is why `lav` and `lav-poster` differ from the brief's lavender and from each other.

## Typography

**Display Font:** Mona Sans variable, widths 112 to 125, weight 800, capitals (with system-ui, sans-serif)
**Body Font:** Mona Sans variable, normal width (with system-ui, sans-serif)
**Label/Mono Font:** the platform monospace stack, for code, endpoints and keys only

**Character:** One family doing two jobs by moving along its axes: wide, heavy and tight for the things you read from across the room, normal width for everything you operate. The single light italic line is where a heading turns. The font is self-hosted from the package; there are no remote font requests.

### Hierarchy
- **Display** (800, width 118, `clamp(2rem, 5.2vw, 5rem)`, line-height 0.92, tracking -0.035em, word-spacing 0.1em, uppercase): section and page titles on the website, the sign-in poster, the status page title. The hero runs larger (`clamp(2.75rem, 6.5vw, 7rem)`), the footer wordmark is set to the container width at width 125.
- **Display turn** (300 italic, tracking -0.04em, word-spacing 0.12em): one line or phrase inside a display heading, usually on its own line.
- **Headline** (780, width 112, `clamp(2.1rem, 4.2vw, 3.4rem)`, line-height 1, tracking -0.04em, sentence case): workspace page titles, sign-in titles, the first-flight invitation. Reading-page titles use the same voice at 750.
- **Tag code** (800, width 118, `clamp(2.2rem, 5.4vw, 4.75rem)`, line-height 0.92) and **Tag price** (800, width 108, `clamp(2.1rem, 3.6vw, 3rem)`, tracking -0.045em): the two big readings on a tag.
- **Title** (700, 1.2 to 1.3rem, tracking -0.025em): panel and section headings inside the workspace; bento and FAQ titles run 680 to 720 at fluid sizes.
- **Lede** (400, 1.05 to 1.25rem, line-height 1.5, `ink-2` on paper or ink on lavender): the one quiet sentence under a display heading, capped near 34rem.
- **Body** (400, 1rem, line-height 1.5; reading pages 1.0625rem at 1.7, column 44 to 46rem): interface and article text.
- **Label** (600 to 650, 0.84 to 0.95rem): buttons, navigation, form labels, segment switches.
- **Caption** (550 to 650, 0.72 to 0.82rem, `ink-2`): timestamps, table headers, chart axes, price context.
- **Sticker** (800, 0.72rem, tracking 0.04em, uppercase): the state sticker on a tag, and the print on the sequence tag.

### Named Rules
**The Capitals Stay Outside Rule.** Wide capital display type belongs to the website, the sign-in poster and the status title. Inside the workspace the only wide heavy capitals are the airport codes on a tag; page titles there are sentence case at width 112.

**The One Turn Rule.** A display heading has at most one light italic phrase.

**The Plain Zero Rule.** Never set `font-variant-numeric: tabular-nums` on Mona Sans: it switches to a slashed zero. Prices keep their place by weight and tracking, and the build uses no numeric font features anywhere.

**The Printed-Only Capitals Rule.** Small tracked capitals appear only where something is printed or stuck on a tag (the sticker, the tag print). They are never set above a heading as a label.

## Layout

The website is a column of cut blocks inside a container `min(1360px, 100% - 48px)` (16px gutters under 768px). Blocks are separated by `clamp(4.5rem, 10vw, 9rem)` of bare paper. Headings may bleed across a block edge: the hero title's last line sits half in the lavender field (the field starts 52% of the title size up the line). Unequal grids are the norm: a 12-column bento with 5/4/3 and 5/7 rows, two-column blocks at 0.95fr/1.05fr or 0.8fr/1.2fr, a sticky heading beside a list. Reading pages hold a 44 to 46rem column with a sticky lavender contents card beside it.

The workspace is a 17.5rem white sidebar sheet inset 0.75rem from the window, and a body capped at 70rem with fluid side padding `clamp(1rem, 3.2vw, 3rem)`. Stacked sheets sit 0.75 to 1.25rem apart; forms stack at 1.25rem. Sign-in is a 5fr/7fr split: a sticky lavender poster inset 0.75rem, and a 27rem form column.

Two pinned sequences run the front page: the "how" block holds for 380vh and the closing block for 250vh, each pinned 4.75rem from the top, while a canvas draws the frame that matches the scroll position.

Responsive behavior, as built: under 992px two-column blocks stack, the sidebar becomes a floating ink dock fixed at the bottom (five items, lime for the current one), and the sign-in poster drops below the form as one short band. Under 768px the hero phone moves below the field, the link pill splits into a field and a full-width button, and a tag's stub hangs below its body with the perforation running across. Under 576px page headings stack, tables become rows of cards, and block radius drops to 1.4rem. Hit targets are 44 to 48px throughout.

## Elevation & Depth

Flat by tonal layering. White sheets sit on paper with no outline and no shadow; depth comes from a different stock (white on paper, lavender on paper, ink on paper) and from holes that show the ground through a sheet. Shadows are reserved for the few things that are physically above the desk.

### Shadow Vocabulary
- **Resting tag** (`0 1px 2px rgb(23 20 31 / 5%), 0 14px 32px -18px rgb(23 20 31 / 22%)`): tags that sit on a coloured field or on the phone screen, and the current step card in the pinned sequence.
- **Lifted sheet** (`0 2px 4px rgb(23 20 31 / 6%), 0 28px 48px -24px rgb(23 20 31 / 34%)`): dialogs and the themed select picker.
- **Pressed sticker** (`0 1px 0 rgb(23 20 31 / 16%), 0 8px 14px -9px rgb(23 20 31 / 45%)`): the state sticker on a tag, with a 2 to 3 degree tilt.
- **Button hover** (`0 12px 22px -14px rgb(23 20 31 / 70%)`): the ink button only, on hover.
- **Dock** (`0 18px 36px -14px rgb(23 20 31 / 60%)`): the floating navigation dock on narrow screens.
- **Paper object** (`drop-shadow(0 18px 18px rgb(23 20 31 / 18%))`, cut to the object's outline): transparent artwork on a tile; the phone uses a close contact shadow plus a long soft one.
- **Inset rule** (`inset 0 0 0 1.5px` in ink or `line-strong`): the drawn edge of a hollow thing: step numbers, the switch frame, the pending sticker, the empty slot.
- **Focus** (`outline: 3px solid` ink, offset 3px; lime on ink blocks) and **field focus** (ink border plus `0 0 0 4px` lavender).

### Named Rules
**The Desk Rule.** If it lies on the desk it has no shadow. Only something held above it (a dialog, a picker, a tag on a coloured field, a sticker, a paper object) casts one.

## Shapes

Three radii and a pill: blocks and sheets at 1.75rem (1.4rem on narrow screens), cards inside a block at 1.25rem, controls at 0.875rem, and everything you press that is not a field is a full pill. Discs carry glyphs, step numbers and the arrow.

The tag supplies the rest of the form language. A **clipped corner** is a `clip-path` polygon that cuts one top corner (1.75rem on a flight tag, 2rem on the status banner, 3.25rem on the example tag, up to 5.5rem on the developer block). A **punched notch** is a paper-coloured circle, 1.4rem across, centred on each end of a perforation so the ground shows through. A **perforation** is a dotted line, 2px on a tag stub and 1.5px everywhere else; every divider in the system is this dotted line, never a solid rule. A **hatch** is a 135 degree ink stripe (1.25px line on a 6px pitch) that means "cut but not filled": no record, a free slot, a pending price. An unused slot is drawn with a dashed 1.5px outline and a hatched disc.

Borders are 1.5px and reserved for controls: fields, the outline button, the link pill.

## Components

### Buttons
Pills that move, with colour that snaps.
- **Shape:** full pill (999px), 46px minimum height, 1.5px border, weight 620 at 0.925rem; small variant 40px.
- **Primary:** ink fill, white text, padding 0.7rem 1.3rem. Hover is `ink-hover` plus the button-hover shadow; pressed scales to 0.97 in 80ms.
- **Flight action:** the primary button with a 2.25rem lime disc at its trailing end holding a right arrow. On hover the disc rotates -45 degrees and grows to 1.06, like a plane leaving. Padding 0.45rem with 1.35rem at the leading side.
- **Outline:** transparent with an ink border; hover inverts to ink with white text, at once.
- **Quiet:** paper fill on a white sheet (white fill on paper), no border; hover is `paper-deep`. Quiet danger is red text that gains a `danger-wash` fill.
- **Light:** white on ink blocks; hover turns lime.
- **Text link button:** underlined ink, hover `violet-ink`, 0.4rem radius, 44px tall when it stands alone.
- **Joined to a field:** a button in an input group takes the control radius on its outer corners and does not scale when pressed.
- **Motion:** transitions cover `box-shadow` and `transform` only, 240ms on the standard ease. See the Snap Rule.

### Stickers
The state of a thing, in a word, on a coloured dot of paper.
- **Style:** pill, 0.3rem 0.7rem, 0.76rem at 650, ink text, a 0.45rem dot before the word.
- **State:** lime for active and sent; violet for stale and degraded; coral for dead letter; shaded paper for paused, suppressed, disabled, cancelled, expired; pending is hollow (inset 1.5px outline, hollow dot).
- **On a tag:** capitals at 800, tracking 0.04em, no dot, tilted -3 degrees with the pressed-sticker shadow. "At its low" is a lime pill tilted -2 degrees.

### Cards / Containers
- **Panel:** white sheet, 1.75rem radius, padding `clamp(1.25rem, 2.4vw, 2rem)`, no border, no shadow.
- **Bento tile:** 1.75rem radius, 19rem minimum height, content at the bottom, one paper object at the top right. Each tile is a different stock: lime, white, ink, lavender.
- **Ink block:** the developer block and status history; white text, `night-text` for support, lime focus rings, dotted rules in white at 16 to 28% alpha.
- **Dialog:** white sheet with the lifted shadow over a 56% ink scrim; a sticky heading with a perforation under it.
- **Drawer:** an action inside a row (change email, set up two-step sign-in, quiet hours) opens below it in place: the row grows from nothing to its own height in 460ms, and closed content is inert and hidden once the close has finished. Prefer a drawer to a dialog unless the task needs protected focus.
- **Security row:** a 2.75rem paper disc with a glyph (lime when the thing is on, pale red for deletion), the name and its state as a sticker, one sentence of consequence, and one action at the right.
- **Chat preview:** the Telegram message preview is a chat on the lavender field: a white header with the mark and "Fareflare bot", a paper body, and the message as a white bubble with one flat corner; inline buttons are white tiles below it. Empty, it shows a bubble of three grey lines.
- **Empty state:** a hollow slot (inset 1.5px `line-strong` outline) with a strip of hatch along its top edge, a paper object or a glyph on a lavender disc, a title and one sentence.

### Inputs / Fields
- **Style:** white, 1.5px `line-strong` border, 0.875rem radius, 48px tall; hover border `ink-3`; read-only on paper.
- **Focus:** ink border plus a 4px lavender halo. Invalid: danger border, pale red halo on focus, message at 0.83rem weight 550 below.
- **Checkbox:** 1.3rem, ink when checked, with a small pop as it is ticked.
- **Switch:** for a setting that is on or off. A 3.1 by 1.8rem pill: off is paper with an `ink-3` outline and grey disc; on is ink with a lime disc. The disc is a background gradient that slides in 320ms, so it moves the same way in every browser. Switches sit at the right end of a row, label and help on the left, rows divided by perforations.
- **Code field:** a 6-digit authenticator code is set large (1.45 to 1.6rem, weight 700) and widely spaced, centred, with `autocomplete="one-time-code"` and a numeric keypad.
- **Select:** a project chevron; where the browser supports it the native picker is themed (ink outline, 1rem radius, lime for the chosen option, lavender wash on hover). Native keyboard behavior is kept.
- **Link pill:** on the hero, one 1.5px ink pill holds the URL field and the flight action; under 768px it splits into a bordered field and a full-width button.

### Navigation
- **Website header:** sticky, paper at 86% with a 14px blur; pill links 44px tall with a `paper-deep` hover; "Sign in" is an outlined pill that inverts to ink at once.
- **Workspace sidebar:** white sheet; items are 48px pills at weight 600; hover is paper with the glyph tilting -12 degrees; the current page is an ink pill with a lime glyph.
- **Dock (under 992px):** a floating ink bar, 1.75rem radius, five items with short labels; the current one is lime with ink text.
- **Segment switch:** a pill track holding pill options; the chosen one is ink with white text. Used for the two alert rules, history ranges, settings sections and connection methods.
- **Settings menu:** when the page column is at least 60rem wide, the settings sections become a sticky vertical list of the same pills beside the content; narrower, they stay a row (two by two under 380px).
- **Workspace column:** the top bar, page and footer share one centred column, `clamp(88rem, 60vw, 104rem)` wide, so edges align at every width and spare space is split evenly. The page is a size container named `page`; components lay out by the room they get there (for example flights two to a row from 96rem), which keeps every zoom level right.
- **Footer:** an ink block with rounded top corners that ends in the wordmark set as wide as the container.

### Flight tag (signature)
A watched flight. White stock, 1.75rem radius, the top-left corner clipped at 1.75rem. Body: airline mark and name, state sticker, the route in tag-code capitals with an arrow, date, detail pills on paper, the rule in a sentence, actions. Stub: a fixed column `clamp(15rem, 30%, 19rem)` past a 2px dotted perforation with a paper notch at each end, holding the recent-record strip, a caption, the price in tag-price type, its context, and when it was checked. A paused flight is the same tag on shaded paper with second-ink readings. A loading tag shows the tag's shape in pill-shaped lines. Tags arrive by pressing down (28px rise, 0.97 scale, -0.6 degree turn, 620ms, staggered 70ms). The website's example tags follow the same anatomy with the clip on the top-right corner.

### Price bars (signature)
The record of a price. Solid ink bars are recorded prices; the lowest is lime-deep with an ink outline; a missing record is a hatched bar; the baseline is dotted. Bars grow from the baseline (520ms, staggered). Capacity uses the same grammar: ink slots for watched flights, hatched slots for free ones. The status page's hour bars add height: degraded is striped and shorter, a major outage shorter still, no record is a hollow dashed bar. The full history chart is a 2.5px ink line with a lime, ink-outlined dot at the low.

### Phone alert (signature)
The hero phone is a rendered body (`art/phone.webp`, aspect 894/2050) with live HTML laid over its blank screen in the picture's own perspective: one box positioned by percentages measured from the render and transformed with `perspective()` and a -24 degree Y rotation. Everything on the screen is sized from the phone's width through one unit, `--r` (the phone width divided by 17.5): type, gaps, radii, the tag's clip. The example alert on it is real text, a small flight tag, and is always labeled as an example.

### Scroll sequence (signature)
A 1912/1080 stage holding a still poster and a canvas. When motion is allowed the canvas draws the frame for the current scroll position (1440-wide set, 800-wide on small screens); otherwise the poster stays. The stage is oversized inside its lavender block and its edges are feathered with a mask so no picture edge is seen. Text that appears on the paper tag (route, price, sticker word) is live type printed on with a left-to-right clip wipe, never part of the image.

### Motion
One ease for arrivals and hovers, `cubic-bezier(0.16, 1, 0.3, 1)`; one for the print wipe, `cubic-bezier(0.3, 0, 0.2, 1)`. Hovers run 220 to 420ms, presses 80ms, arrivals 520ms to 1.2s. Capitals rise line by line from a mask; fields and dialogs unfold from a clip; tags, tiles and sheets press down with a slight scale and turn; glyphs and discs rotate. Scroll-linked effects use CSS scroll and view timelines behind `@supports`. All of it sits inside `prefers-reduced-motion: no-preference`, and a global reduce rule collapses any remaining duration.
Open and close are motion too: a disclosure grows to its height and shrinks back (440ms, where the browser can animate `::details-content`), a dismissed dialog slides down and away in 240ms, workspace pages and settings panels rise 0.75rem into place, a switch's disc slides and a checkbox pops. All of it is movement, never a fade on text, so contrast holds at every frame.

## Do's and Don'ts

### Do:
- **Do** draw every flight, example or real, as a tag: clipped corner, 2px dotted perforation, paper notches, price on the stub, state on a sticker.
- **Do** separate surfaces by stock (white, paper, lavender, ink, lime) and leave paper showing between blocks; use a 1.5px dotted line when a divider is needed.
- **Do** keep text on lime, violet, coral and lavender in ink, and pair every state colour with a word or a shape.
- **Do** snap colour when a control swaps ink and paper (outline button, current navigation item, segment switch, "Sign in"): transition only `transform` and `box-shadow`. A fade passes through unreadable greys and fails contrast checks mid-transition.
- **Do** size anything laid over artwork from the artwork: percentages measured from the render, one unit derived from its width, live text for every word and number.
- **Do** match a panel to the measured backdrop of the picture it holds, and record that value.
- **Do** use hatch for "no record" or "not yet filled" and solid ink for a recorded price, in every chart and meter.
- **Do** bring things in by unfolding, pressing down or rising from a mask, inside `prefers-reduced-motion: no-preference`.
- **Do** style through classes and custom properties only. The content security policy forbids inline `style` attributes, remote fonts and any asset from another origin.
- **Do** give every generated raster a `<file>.webp.json` sidecar with its prompt and date, in the matte-paper, top-left-light, lavender-studio world.

### Don't:
- **Don't** set `font-variant-numeric: tabular-nums` (or any numeric font feature) on Mona Sans; it changes the zero to a slashed one.
- **Don't** use lime, violet or coral as text or line colour on paper; `violet-ink` is the only violet for text.
- **Don't** outline or shadow a sheet that lies on the paper ground.
- **Don't** fade elements up or cross-fade an ink-to-paper colour swap.
- **Don't** bake text, prices, route codes or logos into a picture.
- **Don't** set wide capital display headings inside the workspace, or more than one italic turn in a heading.
- **Don't** use solid hairline rules, gradients as surface fills, or lavender as a small tint.
- **Don't** replace native controls (select, details, dialog) to get a look; theme them and keep their keyboard behavior.
- **Don't** present an example fare without the word "example", or a recorded price without when it was recorded.
