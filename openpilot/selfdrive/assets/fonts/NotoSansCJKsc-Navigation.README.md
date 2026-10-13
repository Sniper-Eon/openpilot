# Navigation road-name font

This is the unmodified **Noto Sans CJK SC Regular 2.004** font distributed by
the Noto CJK project under the SIL Open Font License 1.1. The adjacent
`NotoSansCJKsc-Navigation.LICENSE` contains the license; copyright information
is also embedded in the original font metadata.

Source: https://github.com/notofonts/noto-cjk/blob/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf

SHA-256: `2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b`

The ordinary UI font is a small translation subset that cannot represent
arbitrary Chinese road names. The navigation overlay uses this complete
font. It rasterizes the characters currently needed by the overlay, retains
them across frames, and reloads the atlas only when a new character appears.
Distance digits are preloaded; the full font's 44,810 mapped characters are
never uploaded as one atlas. Simplified-Chinese settings also use this font
when it is present, but rasterize only the translation and navigation-settings
character set; this covers new settings glyphs absent from the old subset.
Other language fallback selections remain unchanged.
