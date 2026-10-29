# Automatic check operations (pilot-13 v2)

Every operation takes the delivered file and an assertion dict (`op` plus settings) and returns `(status,
evidence)`. Status is `pass`, `fail` or `person`; `person` means the code could not decide and a person answers that
row. Rules for every operation:

- Nothing passes on a failed read. An absence on an image passes only when OCR read every wording line at 80% or more.
- A near miss that could be a misreading goes to a person, never to a fail. A letter-case-only difference goes to a
  person unless the check is about case ("reads exactly"); spelling checks ignore case.
- Optional checks ("If X appears", "Any X") pass when X is surely absent; a supplied file not found goes to a person
  (it may be present but redrawn), never to a pass, unless the operation says otherwise.
- Colour tolerance (2026-10-22 policy): within 5 per RGB channel; 8 on JPEG and video frames; text ink on images is
  read from letter cores and gets 3 more. A colour 30 or more off every allowed one fails; in between goes to a person.

Assets named in settings are found through `_asset_dirs` (the task's supplied folders); `_artifacts` is the run's task
folder (other deliverables, e.g. `deliverables/producer-card-r002.pdf`).

## Text (objective_ops.py, round 1)

| op | settings | meaning |
|---|---|---|
| v2_text_present | expected [text or {regex} or [alternatives]], forbidden, any_case, case_matters, line_has + optional, if_any, whole_line | wording present |
| v2_text_absent | texts, patterns {name: regex}, allow, found_is ('person') | wording absent |
| v2_prices | mode none / only (allowed) / range (min, max) | prices |
| v2_pdf_text_style | texts / patterns / all_text (+except, except_patterns), optional; family+weight / size / caps / colors | PDF type style of named text |
| v2_largest_text | text, except, page | named text is the largest |
| v2_relation | rel larger/smaller/above/below, a, b [..], optional | size or position |
| v2_text_inside | texts, whole_line | text read in full inside the frame |
| v2_line_count | text, max_lines, optional | lines a text runs over |
| v2_order | texts | reading order |
| v2_weekdays | year | weekday beside a date is right |
| v2_palette_only / v2_colours_present / v2_main_ground / v2_area_share | hexes / hex / max_pct or compare_hexes | PDF and SVG colours |
| v2_contains_asset / v2_lacks_asset | assets, shape, inside, max_scale, optional | supplied file found or not |
| v2_image_ppi | asset, min_ppi | placed photo resolution (PDF) |
| v2_line_lengths | texts, max_chars | PDF line lengths |
| v2_all_of / v2_any_of | checks [..] | combine |

## Layout, PDF style, pictures (objective_ops_r2.py, round 2)

| op | settings | meaning |
|---|---|---|
| v2_paired | anchor [names or {regex}], whole_line, rivals, label/label_rivals, kind (regex of the field), value, where section/above/below/column/above_or_same/beside, optional, empty_ok | the value that belongs to a name |
| v2_followed_by | a, b | b comes directly after a |
| v2_text_on_ground | texts / patterns / all_text (+except); grounds [hex or 'photo'] + colors, or ground_must; foot_ok; optional | PDF type colour on a ground |
| v2_position | a, b locators ({colour}, {asset}, {image: largest}, {text}, {pattern}), rel above_or_left/below/above, optional_b | positions |
| v2_mark | colour, min_mm or solid | PDF mark drawn in one colour |
| v2_page_size | width_mm, height_mm, tol, no_bleed | PDF page size |
| v2_no_blank_page, v2_bare_below (names, min_mm) | | PDF pages |
| v2_tracking | a {texts/patterns}, b {...}, pair below, optional | PDF letter spacing |
| v2_description | trigger, required, forbidden, scope_map, scope_line | descriptions that must match |
| v2_names_full, v2_spelled | names | names given in full / spelled right |
| v2_directly_above | texts, pattern, optional | line directly above a name |
| v2_stacked | top, bottom, stack, optional | two-part wordmark stacked or not |
| v2_inside_all | texts, patterns, optional | nothing cut off at an edge |
| v2_style_lines | texts / whole_lines / patterns / font_family; family, weight, size, max_size, caps, except_digits, optional | PDF type style |
| v2_size_vs, v2_size_pairs | a vs b list / names + kind | size comparisons |
| v2_figures, v2_initial_ratio, v2_sections, v2_placed_opacity | | PDF figure style, initials, sections, opacity |
| v2_pictured, v2_names_by_photo, v2_same_photo, v2_no_added_detail | photos {file: name}, when, then / photo, names, expected / asset, min_ncc | which supplied photo is shown |
| v2_mark_with_text, v2_asset_finish, v2_shows_deliverable, v2_ground_mark | | wordmarks, placed marks, posters in a deck |
| v2_svg_size, v2_svg_no_cutline, v2_main_ink, v2_svg_glyph_ratio, v2_built_from, v2_no_halftone | | SVG artwork |
| v2_from_capture, v2_largest_last_frame | | video |

## Colour on images, PDF shapes and text roles (objective_ops_r3.py, round 3)

Raster settings common to all: `photos` (supplied photo files to leave out where found; textured regions are left out
anyway), `sitter_ground` (also leave out the flat ground a cut-out subject was set on), `tol`.

| op | settings | meaning |
|---|---|---|
| v2_palette_raster | hexes | every flat designed colour is a palette colour (videos: every held frame) |
| v2_colour_present_raster | hexes | the colour appears outside photographs |
| v2_area_share_raster | hexes, max_pct | share of the area outside photographs |
| v2_ground_raster | hexes, main, panels_only | grounds and panels (flat areas of 1% or more) are allowed colours; main: largest is hexes[0] |
| v2_colour_role_raster | hexes, allowed ['thin', 'small', 'type', 'area'], thin_px, small_px | where a colour may appear |
| v2_text_colour_raster | texts / patterns / all_text / roles (+except), largest_only; colors with optional grounds, or ground_must; optional | ink of text lines on images (videos: held frames) |
| v2_mark_colour_raster | asset or text; colors, or pairs [[ink, ground]]; grounds | colour of a mark |
| v2_no_overlay | photo or photos (PDF: no setting) | no scrim, gradient or tint over a photo (images: pass when tones unchanged, fail on an even scrim, else person) |
| v2_chroma_kept | photo(s) | photo stays in colour |
| v2_two_colour | pair [hex, hex] | photo reproduced in two colours |
| v2_tone_between | photo, hexes [a, b] | sitter's ground between two tones |
| v2_legible_at | text, width | OCR reads every word at that width (pass or person) |
| v2_no_gold | allow | no gold or metallic colour |
| v2_pdf_shapes | hexes + only_rules (full_width, count) / thickness (full_width); or grounds; or rules_not | PDF drawn shapes |
| v2_pdf_rule_by_text | text, hexes, where below/above | a full-width rule directly by a text |
| v2_pdf_rules_match | hexes, deliverable | rules at the same heights as another file |
| v2_colour_only_in_mark | hexes, max_mm | colour used for the mark only (PDF and images) |
| v2_solid_pdf | | no transparency or shading in a PDF |
| v2_role_lines | role (body, heading, main, secondary, fine, caption, label); max_chars / family+weight (+except_digits) / size / leading / smaller_than / larger_than; optional | text roles (see below) |
| v2_role_colour_pdf | roles / patterns / texts; colors; grounds | PDF type colour by role |

Text roles (`_roles`): running text = lines with lowercase letters not repeated 3+ times with only figures changed;
body size = the size with the most characters among running lines of 4+ words; body = running lines at that size;
heading = 1.3 x body or more (main = the largest size; secondary = other headings); fine = under 0.85 x body, split
into caption (sentence case) and label (capitals). On images sizes are letter heights; style checks are PDF only.

## Task-family extensions (round 3)

Written with the round-3 handlers and loaded by `objective_ops_r3.py`; every operation's docstring states its settings,
its limits and when it answers pass, fail or person. An op name may be defined once only (the loader refuses a repeat).

| module | ops | covers |
|---|---:|---|
| ops_r3_photo_a.py | 28 | PHOTO-04, 06, 08, 10: type and rule colour on images, leaf marks, photographs against their supplied files (`v2_vs_source`), PDF grounds, roles and overlays, `v2_agree` (answers only when a narrow and a broad reading of a definition agree) |
| ops_r3_photo_b.py | 39 | PHOTO-19, 20, 24, 26, 28 (names end `_pb`): ink of type by ground, colour roles, tile-by-tile photo comparison (`v2_photo_compare_pb`), placed PDF photos, role styles, leftover backdrop, the cut-out sitter's ground, copy taken only from the supplied text |
| ops_r3_layout.py | 77 | LAYOUT-15, LAYOUT-12, VECTOR-04, MOTION-11: typeface from glyph advance widths, PDF reading in drawing order, cut files and proofs, capture frames behind thumbnails, end cards |
| ops_r3_fonts.py | 4 | typefaces, italics, horizontal scaling and letter spacing read from images (calibrated margins; a line not found never passes) |

## Round 4 (2026-10-29)

Loaded by `objective_ops_r4.py`; names end with the module's suffix. Every op's docstring states its settings, limits and
pass, fail and person bands.

| module | ops | covers |
|---|---:|---|
| ops_r4_vector.py | 14 | VECTOR-04: cut path offset and corner radius, cut lines in the art, arch angle, mark part colours, opacity and shadows, proof against the SVG (`_r4v`) |
| ops_r4_type.py | 7 | lining figures, dollar-sign size and alignment, opening-capital ratio, plate numerals, rules under names and prices, door-line spacing (`_r4t`) |
| ops_r4_photo.py | 8 | palette with whole photographs left out, shadows, clipped whites, border casts, grain, mark counters and lettering, knit texture (`_r4p`) |
| ops_r4_video.py | 9 | moving mascot, repeated shots, captures used, music matched to the supplied track, enlargement, scrim and recolour, stacked titles (`_r4m`) |


## Round 5 (2026-10-29)

Loaded by `objective_ops_r5.py`; names end with the module's suffix. `ops_r5_code.py` settles close calls in code (same
rules as rounds 1 to 4). The `ops_r5_vlm*.py` modules answer objective look, count and read checks with a vision model
(Gemini 3.8 Flash through OpenRouter, pinned to Google Vertex, temperature 0, low reasoning): each question is asked twice
with seeds 11 and 23 and a check passes or fails only when every answer agrees; the model never sees the expected answer
(it copies, counts or lists, and code compares); every answer is saved with its question and the SHA-256 of each file and
replayed (`vlm_answers/` beside the rules; `VLM_OFFLINE=1` replays without any API call; a missing answer goes to a person).
The API key is read from `OPENROUTER_API_KEY` or `~/.config/pilot13/openrouter.env` and is never stored in the repo.

| module | ops | covers |
|---|---:|---|
| ops_r5_code.py | 7 | Linen keyline only round the photo, ground colour absent, opening-capital ratio with dotted letters, small labels, named label colours, lining figures beside photo detail, fine print size (`_r5c`) |
| ops_r5_vlm.py | 5 | shared vision ops: yes/no, copy text, count, list, copy every text once per file (`_r5v`) |
| ops_r5_vlm_a.py | 3 | PHOTO-08/10 line checks on the shared transcription: joined wording, lines traced to the supplied files, a value stated once (`_r5va`) |
| ops_r5_vlm_b.py | 2 | PHOTO-04/06/20/24/28: transcription read with patterns, and listed items sorted by allowed and breach patterns (`_r5vb`) |
| ops_r5_vlm_c.py | 5 | LAYOUT-12, MOTION-11, VECTOR-04: questions over film frames or every PDF page, joined or partial text, named acts (`_r5vc`) |
