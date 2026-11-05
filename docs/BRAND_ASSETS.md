# Fareflare artwork

These project assets were generated with the built-in image generation tool on
November 5, 2026, then resized/encoded for delivery. They are illustrations, not
documentation of an actual flight or airline. The logo is accompanied by live
text in the interface so the product name remains accessible and sharp.

| Asset | Saved path | Use |
| --- | --- | --- |
| Wing-shaped F mark | `web/public/assets/fareflare-mark.png` | Navigation and favicon |
| Window-seat editorial image | `web/public/assets/window-seat.jpg` | Landing page and social preview |

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
