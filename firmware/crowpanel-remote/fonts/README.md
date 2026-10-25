# CrowPanel metadata fonts

The title, artist and album labels keep LVGL's built-in Montserrat fonts as
their primary font. Matching Montserrat supplements provide precomposed
European Latin characters, including `é`, `í`, `â`, `Ł` and `œ`, at 28, 20 and
18 pixels. This changes rendering only: metadata and artwork lookup text retain
their original UTF-8 bytes.

The supplemental fonts contain U+00A0–U+017F (Latin-1 Supplement and Latin
Extended-A), plus supported European punctuation from U+2010–U+2027,
U+2030, U+2039–U+203A, U+20AC and U+2122. The generated cmaps contain 244
characters per size. They do not provide full Unicode coverage or combining
mark shaping; missing glyphs outside this set remain visible in the serial
diagnostic. Nextion's separate ASCII rendering is unaffected.

LVGL 8 draws fallback glyphs on the primary font's baseline. The wrappers in
`src/metadata_fonts.cpp` copy the built-in descriptor and expand its ascent and
descent to fit the supplement, without modifying shared LVGL fonts. Line
heights are 37 pixels for the title, 26 for the artist and 24 for the album.
The title and album boxes accommodate two lines. All UI icons and other
controls continue using their built-in fonts.

## Source and license

- Source: Montserrat Medium, version 7.200, from the project's pinned
  [LVGL 8.3.11 source](https://github.com/lvgl/lvgl/blob/v8.3.11/scripts/built_in_font/Montserrat-Medium.ttf).
- Exact source URL:
  `https://raw.githubusercontent.com/lvgl/lvgl/v8.3.11/scripts/built_in_font/Montserrat-Medium.ttf`
- Vendored file: `Montserrat-Medium.ttf`, 243,180 bytes.
- SHA-256:
  `421f26b23e2be6b98373d32acd3cb2897b154d4bf0a77d26534ce476e4cbed53`
- Copyright 2011 The Montserrat Project Authors
  (`https://github.com/JulietaUla/Montserrat`).
- License: SIL Open Font License 1.1; the complete upstream
  [version 7.200 license](https://github.com/JulietaUla/Montserrat/blob/v7.200/OFL.txt)
  is retained in `OFL.txt` and covers the generated subsets.

## Reproduction

Firmware builds use the checked-in C assets; Node.js is only needed to
regenerate them. `tooling/package-lock.json` locks the build-only
`lv_font_conv` tool to 1.5.3, with npm package integrity
`sha512-0xJQThBOw2iptFccSXrKDIUTQAwr/2zhKjCI1lATIRgZo8uvYRTmenKafW9yTw6G0y5AyW00tqGpUtYuTuBIbQ==`.
Install it outside the checkout with lifecycle scripts disabled. From the
repository root:

```sh
font_tools=$(mktemp -d)
cp firmware/crowpanel-remote/fonts/tooling/package*.json "$font_tools/"
npm ci --prefix "$font_tools" --ignore-scripts --no-fund
python3 firmware/crowpanel-remote/fonts/generate.py \
  --converter "$font_tools/node_modules/.bin/lv_font_conv"
```

The generator verifies the source hash and converter version, uses 4bpp
uncompressed glyphs (matching the firmware configuration), and writes stable
paths into the generated headers. It emits explicit sparse membership for the
Latin cmap to avoid LVGL 8.3.11's dense-cmap end-boundary quirk: unsupported
U+0180 must not resolve to the following cmap's first glyph. This adds 448 bytes
per font. The three bitmap arrays total about 81 KB;
font descriptors and kerning tables add to the final flash footprint. No font
file needs to be placed on the SD card and there is no runtime computer helper.

At initial generation on 2026-10-24, `npm audit --json` reported zero
vulnerabilities for the locked tooling, and the official GitHub advisory API
query below returned an empty list. Recheck when changing the build tool:

```sh
npm audit --prefix "$font_tools" --json
gh api '/advisories?ecosystem=npm&affects=lv_font_conv%401.5.3'
```

## Verification

The portable host tests decode the actual generated cmap/bitmap tables and
check every glyph's bounds, the user examples, and the production wrappers:

```sh
python3 -m pytest tests/test_crowpanel_metadata_fonts.py -q
```

For an additional check with LVGL's real font decoder, point this script at the
pinned dependency source installed by PlatformIO. It compiles only LVGL's font
decoder, the base fonts, the shipped supplements and the production wrappers,
then queries glyphs/bitmaps and checks baseline bounds and unchanged ASCII/icon
bitmaps. It does not connect to hardware:

```sh
python3 firmware/crowpanel-remote/fonts/check_lvgl.py \
  --lvgl firmware/crowpanel-remote/.pio/libdeps/crowpanel_esp32s3_7in/lvgl
```
