---
name: arabic-rtl-ui
description: >
  Conventions for building Arabic and right-to-left (RTL) user interfaces —
  used in EG-BANK (Arabic cheque extractor) and FinTracker (Arabic/English
  localization). Use whenever a task involves Arabic text, RTL layout,
  bilingual Arabic/English UI, localization to Arabic, Arabic numerals/dates,
  or fixing layout bugs in an RTL app. Trigger on: "Arabic", "RTL",
  "عربي", "localize", "bidi", "right-to-left".
---

# Arabic / RTL UI Conventions

RTL mistakes cost multiple fix rounds because they only surface visually.
Apply these rules up front instead of patching after review.

## Layout

1. **Set direction at the root**: `<html dir="rtl" lang="ar">` for
   Arabic-only apps; for bilingual apps toggle `dir` + `lang` together on
   `<html>` when the language switches — never on inner wrappers only.
2. **Use CSS logical properties everywhere**: `margin-inline-start`,
   `padding-inline-end`, `inset-inline-start`, `text-align: start`,
   `border-start-start-radius`. Never `left`/`right` physical properties in
   new code — they are the root cause of most RTL layout bugs. Flex/grid
   with `flex-direction: row` already mirrors correctly under `dir="rtl"`.
3. **Mirror direction-carrying icons only**: arrows, back/forward, undo,
   list indents flip; clocks, checkmarks, logos, media-playback triangles do
   NOT flip. Use `transform: scaleX(-1)` gated on `[dir="rtl"]`.
4. **React Native / Expo (FinTracker)**: use `I18nManager.isRTL`, start/end
   style props, and remember an RTL toggle needs an app reload — provide the
   one-tap reload flow rather than a broken half-flipped UI.

## Text and bidi

5. **Isolate mixed-direction inline content.** Latin fragments inside Arabic
   sentences (emails, file names, codes like `AR-101`, amounts) must be
   wrapped: HTML `<bdi>` / `<span dir="ltr">`, or Unicode isolates
   (U+2066..U+2069) in plain strings. Unisolated LTR runs reorder
   punctuation and look corrupted.
6. **Numbers**: default to Western Arabic digits (0-9) for financial and
   engineering data — that matches Egyptian banking documents and keeps
   values copy-pasteable. Use Eastern Arabic digits (٠١٢٣) only if the user
   asks. Either way, format via `Intl.NumberFormat('ar-EG', ...)`, never by
   string surgery.
7. **Dates**: display via `Intl.DateTimeFormat('ar-EG')`; store and export
   ISO `YYYY-MM-DD`. Never store localized date strings.
8. **Fonts**: system Arabic fonts are fine (Segoe UI, SF, Noto Naskh
   fallback). If a custom font is embedded (offline tools), verify it
   includes Arabic glyphs — a Latin-only font silently falls back and breaks
   the visual style. Line-height needs ~1.6 for Arabic diacritics.

## Language and content

9. **UI copy in Arabic apps is Arabic-first** — labels, buttons, errors, and
   empty states, not just headings. Keep technical identifiers (file names,
   regex, IDs) in Latin. In bilingual apps, every string goes through the
   localization table; no hardcoded literals in components.
10. **Exports stay machine-friendly**: CSV/Excel headers may be bilingual,
    but data cells keep canonical forms (ISO dates, Western digits, original
    document text as OCR'd).

## Verification checklist

- [ ] Whole-page flip test: no element still hugging the wrong side
- [ ] Mixed Arabic+Latin string renders with correct punctuation order
- [ ] Numbers/dates formatted via `Intl`, stored canonical
- [ ] Direction-carrying icons mirrored; symmetric icons untouched
- [ ] Bilingual apps: switching language flips `dir`, `lang`, and reloads
      cleanly (RN) with no mixed-direction leftovers
