# Fareflare artwork

Everything pictured on the site belongs to one small paper world: a white paper
plane, a baggage tag, and a handful of folded-paper objects on a flat lavender
backdrop. The pictures are illustrations. None of them shows a real flight,
airline, airport or fare, and the tag in the pictures is always blank: prices and
route codes on the site are live text, never part of an image.

The raster artwork was generated with Higgsfield on November 10 and 11, 2026
(`gpt_image_2_6` for stills, `kling4_0` image-to-video for the two scroll
sequences), then trimmed, resized and encoded for delivery. Original generation
files stay outside the repository.

## Where each prompt is recorded

Every generated raster carries its own prompt:

- WebP files have a sidecar beside them, `<file>.webp.json`, with the prompt and
  the date. `web/angular.json` ignores `**/*.webp.json`, so sidecars are in the
  repository and never in the build.
- `social.jpg` carries its prompt in a JPEG comment and `fareflare-mark.png`
  carries a note on its origin in a PNG text chunk.

The prompts below are the ones worth reading in one place. The sidecars are the
complete record.

## The mark

| Asset | Path | Use |
| --- | --- | --- |
| Wing-shaped F mark | `web/public/assets/fareflare-mark.png` (256 × 256) | Navigation, sign-in, footer, structured data |
| Favicon | `web/public/favicon.svg` | Browser tab |

The mark is the wing-shaped F drawn for the project on November 5, 2026. It was
not regenerated: the same shape was recoloured in code to a lime mark
(`#c6ff4d`) on an ink disc (`#17141f`). The product name always sits beside it
as live text. Its original prompt, kept for the record:

> Create a clean graphic-design brand icon on a solid warm off-white #f7f4ed
> background, like a flat printed logo on paper. A compact abstract letter F formed
> by two swept aircraft wing shapes, one color: dark burnt orange #b94724. Sharp
> vector-like geometry. Flat ink on paper, perfectly uniform colors. Center the
> symbol, equal empty margins. Only the small symbol on plain off-white. No effects,
> lighting, shadows, glow, black, texture, gradients, words, presentation mockup,
> or dimensionality.

## Large artwork

| Asset | Path | Size | Use |
| --- | --- | --- | --- |
| Paper plane, cut out | `web/public/assets/art/paper-plane.webp` | 720 × 582, 31 KiB | Hero, workspace sidebar, page-not-found and load-error pages |
| Phone body with a blank screen | `web/public/assets/art/phone.webp` | 760 × 1743, 35 KiB | Hero |
| Suitcase with a blank tag | `web/public/assets/art/suitcase.webp` | 1200 × 1607, 33 KiB | Sign-in, sign-up and recovery |
| Three tag slots | `web/public/assets/art/tag-slots.webp` | 1168 × 880, 10 KiB | Flights page, before the first flight |
| Flock of paper planes | `web/public/assets/social.jpg` | 1200 × 630, 30 KiB | Social preview (`og:image`) |

The backdrop asked for in every prompt was lavender `#DAD4F7`. Encoded, the
frames settle at `#d2cbf6`, and that measured value is the site's `--ff-lav`, so
a picture and the panel behind it meet without a seam. The suitcase picture came
out a little deeper, so its backdrop was snapped to one colour, `#d0c5f6`, and
the sign-in panel uses exactly that.

### The phone in the hero

The phone is a picture of a body only. Its screen is blank, and the alert shown
on it is live HTML laid over the picture, so the price, the route and the bars
are real text. To make the two agree, the flat HTML box is given the picture's
own perspective. The numbers in `.phone-screen`
(`web/src/app/public/hero.component.scss`) are measured from the render:

- The body fills the trimmed picture, 894 × 2050 before resizing.
- The four screen corners, as fractions of that width: top left (0.0224, 0.1223),
  top right (0.8826, 0.0278), bottom right (0.8826, 2.2688), bottom left
  (0.0224, 2.1693).
- Solved for a box turned 24° about its vertical axis: `left: -3.682%`,
  `top: 3.425%`, `width: 93.966%`, `height: 93.309%`, and
  `perspective(4.2257 × phone width) rotateZ(0.132deg) rotateY(-24deg)
  rotateX(-0.316deg)`. The corners land within one pixel.

Everything on the screen is sized in `--r`, a fixed fraction of the phone's
width, so the screen scales with the body. A replacement render needs its
corners measured and these numbers solved again.

> Single isolated object on a fully transparent background: one modern smartphone
> with a matte near-black (#17141F) body, softly rounded corners and a thin even
> black bezel, floating upright. It is seen in an isometric three-quarter view:
> turned about 22 degrees around its vertical axis so the screen faces slightly
> toward the viewer's left, and tipped back very slightly, so the front face and
> the whole right side edge are visible. The right side edge shows real
> thickness: a rounded dark graphite metal frame with a soft highlight running
> along it and two small side buttons. […] The screen is switched off-white: one
> completely blank, perfectly uniform flat matte off-white surface (#F3F2EE) from
> bezel to bezel, like a sheet of uncoated paper set into the phone, with no
> notch, no camera hole, no icons, no interface, no reflections, no glare and no
> gradient. Soft diffuse studio light from the top left, gentle realistic shading
> in cool lavender-grey tones, fully matte finish, no gloss. Photoreal 3D product
> render, crisp edges. […] No ground shadow, no background, no hands, no text, no
> letters, no numbers, no logos.

The full prompt is in `phone.webp.json`. The render's screen was lifted to the
site's paper colour, keeping its soft shading.

Paper plane:

> Single isolated object on a fully transparent background: one crisp white paper
> airplane, classic dart fold, thick matte uncoated paper with visible fold
> creases, banking upward and flying toward the upper right, seen from a
> three-quarter rear-below view so the underside and one wing are visible. Soft
> diffuse studio light from the top left, gentle realistic shading in cool
> lavender-grey tones. Photoreal 3D render. No shadow on the ground, no
> background, no text.

Suitcase:

> Minimal high-end 3D studio render, portrait composition. A compact hard-shell
> cabin suitcase in smooth matte pastel lavender (slightly deeper than the
> background) with fine horizontal ribs, standing upright on a seamless floor,
> seen from a three-quarter front view. Tied to its top handle with a thin black
> elastic cord hangs a tall blank white paper luggage tag with clipped top corners
> and a row of tiny perforation holes near its bottom; a round fluorescent
> lime-green (#C6FF4D) sticker sits on the tag. A single crisp white paper
> airplane rests leaning against the base of the suitcase. Seamless pastel
> lavender studio backdrop, colour #DAD4F7, floor and wall blending with no
> visible horizon. Soft diffuse top-left light, soft realistic contact shadows.
> The suitcase sits in the lower two thirds of the frame, the upper third is calm
> empty lavender. Clean, calm, design-studio product photography. No text, no
> letters, no numbers, no logos, no people.

## Scroll sequences

Two pictures on the front page move with the scroll. Each is a short generated
video between two generated keyframes, cut into still frames. The page draws
the frame that matches the scroll position onto a canvas; nothing plays on its
own.

| Sequence | Path | Wide set | Narrow set | Use |
| --- | --- | --- | --- | --- |
| A paper plane unfolds into a baggage tag | `web/public/assets/seq/plane-tag/` | `w1440/`: 108 frames, 1440 × 813, 630 KiB | `w800/`: 54 frames, 800 × 452, 130 KiB | "From a flight link to a price alert" |
| The camera flies into a flock of planes | `web/public/assets/seq/flock/` | `w1440/`: 61 frames, 1440 × 813, 978 KiB | `w800/`: 41 frames, 800 × 452, 303 KiB | Closing section |

Each folder also holds `poster.webp`, the still shown before the frames arrive
and whenever the reader asks for reduced motion. Frames are numbered from
`000.webp`. The narrow set is used on small screens. In each frame the backdrop
was flattened to one colour before encoding, which is most of why 108 frames
fit in 630 KiB.

Both videos: Higgsfield `kling4_0`, image-to-video, 1080p, five seconds. The
video and keyframe prompts are in each folder's `poster.webp.json`. The plane
and tag video prompt:

> One continuous locked-off studio shot, no cuts, no camera movement. A white
> paper airplane glides gently in mid-air, slows down and turns to face the
> camera, then smoothly unfolds itself: its wings open flat one fold at a time,
> in clean precise origami motion, the creases relaxing until the sheet becomes a
> flat upright white paper luggage tag. As it flattens, a black elastic cord loop
> appears at its top, a lime green round sticker pops onto its upper right corner
> and a small barcode prints onto the bottom stub. The tag settles and hangs
> perfectly still in the centre. The flat pastel lavender background and soft
> lighting never change. Slow, calm, elegant, physically believable paper motion.
> No text, no people, no hands, no extra objects.

The flock video prompt:

> One continuous smooth camera move, no cuts. A flock of white folded paper planes
> glides to the right across a soft lavender studio backdrop. The camera slowly
> pushes in and travels alongside the single lime green paper plane until it
> fills the frame, while the white paper planes drift behind it and fall softly
> out of focus. Matte paper texture, soft even studio light, gentle shallow depth
> of field. The backdrop colour stays the same flat lavender for the whole shot.
> No text, no logos, no people.

The social preview is a crop of the flock sequence's opening keyframe.

## Paper objects

Nine small objects, all 280 × 280 WebP with a transparent background, 9 to
16 KiB each, in `web/public/assets/art/`. They are decorative and carry an empty
text alternative: the heading beside each one says what it stands for.

| File | Object | Use |
| --- | --- | --- |
| `stopwatch.webp` | Stopwatch with a lime quarter of its dial | Front page: check interval |
| `shield.webp` | Shield with a lime check mark | Front page: no Google account connection |
| `terminal.webp` | Ink card with a lime prompt | Front page: open source |
| `bubble.webp` | Speech bubble with a plane leaving it | Front page: alerts. Flights page: the invitation to connect Telegram |
| `search.webp` | Magnifying glass around a lime plane | Front page: price history |
| `plug.webp` | Plug meeting a paper socket | Front page: API and MCP |
| `bell.webp` | Bell with a lime sticker | Alerts page, before the first alert |
| `link.webp` | Two chain links, one lime | Webhooks page, before the first receiver |
| `key.webp` | Key with a lime tag | API keys, before the first key |

One prompt frame was used for all nine, with only the object changed, so they
share a material and a light:

> Single isolated papercraft object on a fully transparent background: [object].
> Everything is hand-folded and cut from thick matte uncoated paper with visible
> fold creases and clean cut edges, the same material as a crisp folded paper
> airplane. Soft diffuse studio light from the top left, gentle realistic shading
> in cool lavender-grey tones, three-quarter view, centred with a generous empty
> margin on every side so nothing touches the image edges. Photoreal 3D render,
> fully matte: no gloss, no plastic, no ceramic. No ground shadow, no background,
> no text, no letters, no numbers.

Each object's own sentence is in its sidecar.

## Adding or replacing artwork

1. Keep to the world: matte paper, top-left light, lavender `#DAD4F7` backdrop
   or a transparent one, ink `#17141F` and lime `#C6FF4D` as the only accents.
   No text, numbers or logos inside a picture.
2. Encode to WebP at the size the page uses and give the `<img>` its `width` and
   `height`.
3. Record the prompt beside the file as `<file>.webp.json`.
4. Assets are served from the site's own origin. The server only serves known
   image, font, style and script suffixes, so a new kind of file needs a look at
   the static whitelist first.

## README artwork

The README's header and section banners are five more Higgsfield images
(`gpt_image_2_6`, 21:9) in the same paper world, with titles set in HTML rather than
in the pictures. Their prompts are in `docs/readme/src/art/PROMPTS.md`, and
`node docs/readme/render.mjs` redraws every README figure from `docs/readme/src`.

## Airline identification

The dashboard bundles 70px airline identification images from Google's public
Flights asset collection. Files are served locally; opening a flight list does
not send a request to a third-party logo service.

Source pattern: `https://www.gstatic.com/flights/airline_logos/70px/{IATA}.png`.
Retrieved November 5, 2026: United (UA), American (AA), Delta (DL), Frontier (F9),
Southwest (WN), JetBlue (B6), Alaska (AS), and Spirit (NK). Files live in
`web/public/assets/airlines/` without altering the artwork. Carrier names and
flight numbers remain visible; unknown or unavailable artwork falls back to text.

These are third-party airline marks used to identify carriers, not Fareflare
artwork. Their ownership is not covered by this repository's MIT license and their
appearance does not imply endorsement or affiliation.

## Typography

Mona Sans is self-hosted as a variable font through
`@fontsource-variable/mona-sans` under the SIL Open Font License 1.1. One file
covers text and display: headlines use its wider, heavier end in capitals, with
a light italic for the turn. The build includes the font's full copyright and
license notice in the served `3rdpartylicenses.txt`
(`web/scripts/font-license.mjs`). See the package's `LICENSE` and
[Fontsource's provenance](https://fontsource.org/fonts/mona-sans/about).

## Interface vectors

`web/public/assets/arrow-out.svg` and `web/public/assets/control-chevron.svg`
are project-authored strokes in the interface's ink colour, covered by the
repository's MIT license. The arrow sits in the round end of the main buttons;
the chevron marks select fields and disclosures. Other interface icons come from
Bootstrap Icons under the MIT license, whose notice is also in
`3rdpartylicenses.txt`.

## Retired artwork

The four editorial photographs used before November 2026 (`window-seat.jpg`,
`coastal-approach.webp`, `above-the-clouds.jpg`, `coastal-runway.jpg`) and
`flight-watermark.svg` were removed with the redesign. Anything that checks a
deployment by fetching an image should ask for `/assets/social.jpg` or
`/assets/art/paper-plane.webp`.
