# Attio Design System: "Product-as-Infrastructure"

## Visual Philosophy
Attio's design language, often described as "The Browser as an OS," prioritizes utility-first interfaces over soft, "bubbly" SaaS aesthetics. It emphasizes high data density, tactile precision, and professional restraint.

## Color Palette
The system is built on a sophisticated monochromatic "Attio Gray" scale, using color only as a surgical instrument for action.

- **Primary Background:** `#FFFFFF` (Light) / `#0A0A0A` (Dark)
- **Neutral Grays:** A granular scale from `#F5F5F5` to `#1A1A1A`
- **Primary Action (Blue):** `#3B82F6` (Vibrant blue used sparingly for CTAs and focus states)
- **Text (High Contrast):** `#0A0A0A` (on light) / `#FFFFFF` (on dark)
- **Text (Secondary):** `#666666` / `#A1A1A1`

## Typography
A pairing of functional UI clarity with editorial marketing impact.

- **UI & Body:** `Inter` - Optimized for legibility in high-density data views.
- **Headings & Marketing:** `Monument Grotesk` (ABC Dinamo) - High-contrast, brutalist-inspired editorial type for brand presence.

## UI Patterns & Components
- **Border Radius:** Precise 6px to 8px across all containers and buttons.
- **Grid System:** "Bento Box" layout for marketing pages; strict modular grids for product views.
- **Layering:** Subtle box shadows and translucent "glassmorphism" layers for depth.
- **Interactions:** Rapid micro-interactions (150-200ms) with scroll-triggered "product assembly" animations.
- **Data Display:** High-density tables and lists with minimal whitespace, favoring information richness.

## Cash flow forecast screen

The forecast chart puts projected closing cash and the reserve on the same daily axis. Switching between expected, downside and no-collections views lets the reviewer see how much the forecast depends on incoming payments. Selecting a day opens its cash movements. A missing opening balance calls for balance entry, while a partial source read needs a coverage warning before the reviewer relies on the forecast. Scenario previews and submitted plans use separate controls so a reviewer can explore a change before requesting approval. [Forecast screen](../../frontend/src/pages/cashforecast/CashForecastPage.tsx) · [Interaction design](../cashflow-forecast/06_UI_SPEC.md)

## Brand Identity
- **Logo:** Minimalist wordmark or geometric mark in solid black/white.
- **Imagery:** High-fidelity UI simulations and mockups featuring real-world data patterns rather than abstract illustrations.
- **Halo Effect:** Subtle radial gradients used as background accents to highlight key product modules.

