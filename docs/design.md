---
name: Warm Editorial Finance
colors:
  surface: '#fcf8fb'
  surface-dim: '#dcd9dc'
  surface-bright: '#fcf8fb'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f6f3f5'
  surface-container: '#f0edef'
  surface-container-high: '#eae7ea'
  surface-container-highest: '#e4e2e4'
  on-surface: '#1b1b1d'
  on-surface-variant: '#404945'
  inverse-surface: '#303032'
  inverse-on-surface: '#f3f0f2'
  outline: '#717975'
  outline-variant: '#c0c8c4'
  surface-tint: '#396759'
  primary: '#154539'
  on-primary: '#ffffff'
  primary-container: '#2f5d50'
  on-primary-container: '#a3d4c3'
  inverse-primary: '#a0d1c0'
  secondary: '#296a4a'
  on-secondary: '#ffffff'
  secondary-container: '#abeec6'
  on-secondary-container: '#2e6e4e'
  tertiary: '#741f11'
  on-tertiary: '#ffffff'
  tertiary-container: '#933625'
  on-tertiary-container: '#ffb8aa'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#bceddc'
  primary-fixed-dim: '#a0d1c0'
  on-primary-fixed: '#002019'
  on-primary-fixed-variant: '#204f42'
  secondary-fixed: '#aef1c9'
  secondary-fixed-dim: '#93d5ae'
  on-secondary-fixed: '#002112'
  on-secondary-fixed-variant: '#095134'
  tertiary-fixed: '#ffdad3'
  tertiary-fixed-dim: '#ffb4a5'
  on-tertiary-fixed: '#3f0400'
  on-tertiary-fixed-variant: '#802919'
  background: '#fcf8fb'
  on-background: '#1b1b1d'
  surface-variant: '#e4e2e4'
typography:
  display-editorial:
    fontFamily: Newsreader
    fontSize: 30px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Newsreader
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 34px
    letterSpacing: -0.015em
  headline-md:
    fontFamily: Be Vietnam Pro
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Be Vietnam Pro
    fontSize: 17px
    fontWeight: '600'
    lineHeight: 24px
    letterSpacing: -0.01em
  body-reading:
    fontFamily: Be Vietnam Pro
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 28px
    letterSpacing: -0.01em
  body-reading-strong:
    fontFamily: Be Vietnam Pro
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.01em
  body-compact:
    fontFamily: Be Vietnam Pro
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 22px
    letterSpacing: -0.005em
  label-regular:
    fontFamily: Be Vietnam Pro
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
    letterSpacing: 0em
  label-micro:
    fontFamily: Be Vietnam Pro
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.02em
  citation-ref:
    fontFamily: Be Vietnam Pro
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.04em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 0.75rem
  margin: 1rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.875rem
  space-lg: 1.25rem
  space-xl: 2rem
---

## Brand & Style

This design system is tailored for an editorial mobile reading experience centered around understanding financial assets rather than chasing speculative returns ("수익률이 아닌 이해를 돕습니다"). It trades hyperactive trading interfaces, ticker red/blue flashes, and flashing charts for the pacing and typography of an essay collection or a tactile Sunday newsletter.

The design philosophy combines **Literary Minimalism** with **Warm Tactile Surfaces**:
- **Tone:** Calm, composed, patient, and conversational (`해요체`). It treats readers as curious thinkers rather than day-traders.
- **Form Factor:** Optimized mobile viewport (centered 375px–430px canvas), offering expansive typographic breathing room.
- **Visual Discipline:** Elimination of harsh drop shadows, high-chroma alert badges, and neon ticker metrics. Depth is established via subtle surface shifts and quiet hairline strokes.

## Colors

The palette reproduces the tactile quality of archival paper and muted ink. It replaces conventional volatile Korean stock colors with grounded, nature-derived tones that lower cognitive strain.

### Core Roles
- **Canvas Base (`#faf9f6`):** Warm unbleached paper surface.
- **Card Surface (`#ffffff`):** Pure sheet placed atop the warm canvas.
- **Primary Ink (`#1d1d1f`):** Dense charcoal black for effortless long-form reading.
- **Secondary Ink (`#6b6b70`):** Muted stone gray for captions, footnotes, and metadata.
- **Hairline Border (`#e6e4df`):** Warm 1px structure tone preventing stark contrast cuts.
- **Accent Forest Green (`#2f5d50`):** Primary branding, active tab indicators, and focal editorial headers.

### Semantic Status
- **Positive / Sound Health:** Ink `#2f6f4f` on soft mist background `#eef6f2`.
- **Caution / Risk Note:** Ink `#a2412f` on soft parchment rose `#fcf2ef`.
- **Calendar Marker (Holiday/Weekend):** Accent brick red `#d1352b`.

### Dark Mode Adjustments
When triggered, preserve warm undertones over pitch-black OLED contrasts:
- Canvas: `#141414`
- Card: `#1d1d1d`
- Text: `#ececec`
- Accent: `#8cc7b3`
- Border: `#2a2a2a`
- Positive: Ink `#7bc49f` on `#1b2921`
- Concern: Ink `#e88d7d` on `#2d1c1a`

## Typography

Typographic scale and rhythm drive the reading comfort of this system. While web fallback font stacks target native Korean font rendering (`Pretendard, -apple-system, Apple SD Gothic Neo, sans-serif`), layout tokens mandate an open line-height of `1.75` (`28px` leading on `16px` text) to eliminate scanning exhaustion.

- **Editorial Headings:** Latin titles and prominent section openings pair with an elegant serif voice (`Newsreader`), while Korean script falls gracefully to balanced medium/semi-bold humanist sans-serifs.
- **Copy Voice:** Prose must be articulated in respectful, conversational Korean (`해요체` — e.g., "~공시를 살펴보았어요", "~한 이유를 함께 짚어볼게요").
- **Paragraph Cadence:** Article paragraphs must not exceed 4–5 continuous lines without a divider, visual citation anchor, or pull quote block.

## Layout & Spacing

Layout geometry is structured for single-hand mobile readability within a 375px baseline viewport, clamped to a centered max-width of 480px on wider screens:

- **Outer Margins:** Fixed `16px` (`margin: 1rem`) screen margins create consistent reading boundaries.
- **Content Blocks:** Standardized vertical separation of `space-xl` (`32px`) between editorial chapters.
- **Safe Zones:** Top header offset leaves room for status bars, while bottom padding respects the fixed `56px` navigation bar plus a `34px` platform home indicator buffer.

## Elevation & Depth

Visual hierarchy relies entirely on **low-contrast outlines** and **tonal contrast** rather than cast drop shadows.

- **Elevation 0 (Background):** Base tone `#faf9f6`.
- **Elevation 1 (Card Content):** Pure white surface `#ffffff` encased in a crisp 1px border `#e6e4df`. No ambient drop shadows are applied (`box-shadow: none`).
- **Elevation 2 (Floating Search & Tooltips):** Background `#ffffff` with a delicate, whisper-light anchor shadow: `0 4px 16px rgba(29, 29, 31, 0.04)`, framed with a 1px border `#e6e4df`.
- **Elevation 3 (Modal Bottom Sheets):** `#ffffff` surfaced with a warm dim backdrop overlay: `rgba(29, 29, 31, 0.24)`.

## Shapes

The form language communicates softness and accessibility through intentional curvature:
- **Card Enclosures:** Standardized to `14px` border-radius, pairing organically with handheld screen edges.
- **Search & Input Bars:** Pill or gentle `12px` rounding to suggest relaxed user entry.
- **Citations & Status Badges:** `4px` to `6px` radius, keeping compact metadata structured without feeling aggressive.
- **Pill Tags / Micro Chips:** Complete full-radius pill silhouettes (`9999px`) for touchable, interactive criteria.

## Components

### 1. Cards
- **Styling:** White surface `#ffffff`, 1px solid `#e6e4df`, corner radius `14px`, interior padding `20px`.
- **Behavior:** Never stacked tightly; spaced vertically by `14px`. Clean division using soft hairline horizontal separators `#f2efe9` when dividing internal sub-metrics.

### 2. Fixed Bottom Tab Bar
- **Structure:** Height `56px` + device safe-area inset bottom. Positioned sticky at the base, frosted warm white background (`background: rgba(250, 249, 246, 0.92)`, `backdrop-filter: blur(12px)`), top hairline border `1px solid #e6e4df`.
- **Tabs (2 items only):**
  - **내 종목 (My Stocks):** Focused portfolio and watch narratives.
  - **캘린더 (Calendar):** Filing and earnings milestones.
- **States:** Inactive tab uses `#6b6b70` with `12px` label; active tab uses `#2f5d50` with an emphasized `600` font weight and a micro indicator dot.

### 3. Sticky Search Bar & Suggestions
- **Styling:** Inset `16px` horizontally; height `44px`; background `#ffffff`; border `1px solid #e6e4df`; radius `10px`. 
- **Autocomplete Flyout:** Drops immediately beneath with matching 1px hairline perimeter, grouping matches with clear code markers (e.g., `005930 삼성전자`) and gentle explanatory tags (e.g., "반도체 / 배당").

### 4. Editorial Reading View & Inline Citations
- **Article Container:** Uncluttered vertical stack with comfortable letter line-height (`28px`).
- **Citation Badges (`[F1]`, `[D1]`):**
  - Styled as superscript inline pills: background `#eef6f2`, text `#2f5d50`, font size `11px`, font-weight `600`, radius `4px`, padding `1px 5px`.
  - Tapping reveals an anchored tooltip with an explanation of the official filing source (`DART 전자공시`, `FactSet`), rendered in 13px neutral ink with a soft border.

### 5. Calendar Monthly Grid
- **Grid Layout:** 7-column uniform layout; cell height `56px`.
- **Date Indicators:** Weekdays styled in `#1d1d1f`; Sundays and recognized Korean public holidays highlighted in `#d1352b`.
- **Filing Chips:** Compact horizontal capsules (`height: 16px`, font size `10px`) nestled beneath date numbers:
  - Regulatory disclosure: `#eef6f2` bg with `#2f5d50` text.
  - Caution/Audit alert: `#fcf2ef` bg with `#a2412f` text.

### 6. Buttons & Interactive Chips
- **Primary Action Button:** Solid `#2f5d50` background, pure white text `#ffffff`, radius `12px`, height `48px`, font size `15px` semi-bold.
- **Secondary / Filter Chip:** Background `#ffffff`, border `1px solid #e6e4df`, text `#1d1d1f`, radius `9999px`, height `32px`, padding `0 14px`. Active chip switches to `#2f5d50` text and `#eef6f2` background with `#2f5d50` outline.