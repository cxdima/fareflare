# Fareflare artwork

These project assets were generated with the built-in image generation tool on
November 5, 2026, then resized/encoded for delivery. They are illustrations, not
documentation of an actual flight or airline. The logo is accompanied by live
text in the interface so the product name remains accessible and sharp.

| Asset | Saved path | Use |
| --- | --- | --- |
| Wing-shaped F mark | `web/public/assets/fareflare-mark.png` | Navigation and favicon |
| Window-seat editorial image | `web/public/assets/window-seat.jpg` | Sign-in page and social preview |
| Coastal approach editorial image | `web/public/assets/coastal-approach.webp` | Landing page |
| Above-the-clouds editorial image | `web/public/assets/above-the-clouds.jpg` | First-run panel of the flights page |
| Coastal runway editorial image | `web/public/assets/coastal-runway.jpg` | Sign-in page |

The final logo has a transparent background. It was refined from the original
flat mark using a background-extraction edit, then resized to 192px. Original
generation files remain outside the repository; the website uses optimized assets.

## Final logo prompt

> Create a clean graphic-design brand icon on a solid warm off-white #f7f4ed
> background, like a flat printed logo on paper. A compact abstract letter F formed
> by two swept aircraft wing shapes, one color: dark burnt orange #b94724. Sharp
> vector-like geometry. Flat ink on paper, perfectly uniform colors. Center the
> symbol, equal empty margins. Only the small symbol on plain off-white. No effects,
> lighting, shadows, glow, black, texture, gradients, words, presentation mockup,
> or dimensionality.

## Transparent logo edit

> Remove the off-white background and preserve the two orange swept wing shapes.
> Keep crisp solid edges, the original arrangement, and a transparent background.
> No glow, shadow, outline, texture, text, or additional elements.

## Window image prompt

> Use case: photorealistic-natural. Asset: editorial travel image for the Fareflare
> flight price tracker landing page, 3:2 landscape. A quiet close view out of an
> airliner window at dawn, the ivory window surround framing a distant pale-blue
> mountain range and scattered clouds, small portion of the wing visible crossing
> the lower view. Warm morning sunlight grazes the window frame; subdued slate
> blue sky and soft cream tones, natural realistic film grain, refined independent
> travel-magazine photography. Off-center composition, intimate and calm,
> believable geometry, understated rather than spectacular. No people, no airline
> branding, no logos, no words, no interface, no graphic overlays, no oversaturated
> sunset.

## Coastal image prompt

Generated with the built-in image tool on November 5, 2026. The original is
1536 × 1024; the deployed WebP is 1280 × 853 and approximately 115 KiB. It
depicts an imagined coastline, not a destination associated with the example
fare. The image has an explicit aspect ratio to reserve its layout space.

> Use case: photorealistic-natural. Asset type: editorial travel photograph for
> the Fareflare flight price tracker website, landscape 3:2, 1536 by 1024.
> Create a quiet, believable aerial view of a rugged Mediterranean-style
> coastline seen from an arriving aircraft: deep slate blue open water in the
> foreground, a narrow headland with soft limestone cliffs and small pale
> buildings set well back, muted green hills receding into a naturally hazy
> horizon. No aircraft or window frame in the image. Natural late-afternoon
> directional light, subtle warm stone against cool water. Premium independent
> travel-magazine photography, restrained color, real fine water and terrain
> texture, a slightly imperfect candid composition, soft atmospheric depth.
> The coast runs diagonally across the frame with generous clean blue water
> around it; readable at small sizes. Beautiful but ordinary enough to feel
> real. No famous landmarks, no impossible cliffs, no dramatic oversaturated
> sunset, no invented text, no people in foreground, no logos, no graphics,
> no gradient overlays, no border, no watermark.

## First-run and sign-in image prompts

Generated on November 9, 2026 with Higgsfield (`gpt_image_2_6`), then resized to
1024 × 688 and encoded as JPEG (126 KiB and 146 KiB). Like the images above they
are illustrations of imagined places, chosen to sit in the same quiet,
early-light world as the window-seat image. The window-seat image now accompanies
sign-up and recovery.

> Photorealistic editorial travel photograph, 3:2 landscape. View from an airliner
> cabin window seat looking along the aircraft wing, high above a calm sea of low
> broken clouds shortly after sunrise. Soft warm light on the wing's upper
> surface, muted sage and slate tones below, pale peach horizon. Restrained
> natural color, fine film grain, independent travel-magazine photography,
> off-center composition, calm and ordinary enough to feel real. No people, no
> text, no logos, no airline livery or markings, no window frame, no watermark.

> Photorealistic editorial travel photograph, 3:2 landscape. A small regional
> airport seen from the air at early morning: a single pale runway crossing a
> muted sage-green coastal plain, soft low mist in the hollows, a calm slate-teal
> sea beyond, warm peach light on the horizon. Restrained natural color, fine
> film grain, independent travel-magazine photography, off-center composition,
> quiet and believable. No aircraft in the foreground, no people, no text, no
> logos, no watermark.

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

Plus Jakarta Sans is self-hosted through `@fontsource-variable/plus-jakarta-sans`
under the SIL Open Font License. The build includes its full copyright/license
notice in the served `3rdpartylicenses.txt`. See the package's `LICENSE` and
[Fontsource's provenance](https://fontsource.org/fonts/plus-jakarta-sans/about).

## Interface vectors

`web/public/assets/flight-watermark.svg` uses Bootstrap Icons' `airplane-fill`
shape under the MIT license. It is served locally as a decorative CSS mask inside
flight buttons, with no text alternative because the button already has a label.
The build includes the Bootstrap Icons copyright and license in
`3rdpartylicenses.txt`. Source: [Bootstrap Icons airplane-fill](https://icons.getbootstrap.com/icons/airplane-fill/).

`web/public/assets/control-chevron.svg` is a project-authored, three-point
chevron used by native select fields and disclosures. It shares the interface's
teal color and is covered by the repository's MIT license.
