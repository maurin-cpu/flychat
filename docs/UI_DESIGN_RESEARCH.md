# Premium Dark-Theme UI Design Research

Actionable design findings from 8 best-in-class dark-theme applications, compiled for the Gleitcast redesign.

---

## 1. Linear.app

**Source**: [Linear UI Redesign](https://linear.app/now/how-we-redesigned-the-linear-ui) | [Linear Brand Colors](https://mobbin.com/colors/brand/linear) | [Linear Style](https://linear.style/) | [Linear Custom Themes](https://linear.app/changelog/2020-12-04-themes)

### Color System
- **Background (primary)**: Deep neutral, approximately `#0A0A0B` to `#111113` (near-black with very slight blue undertone)
- **Surface/Card elevated**: `#1B1B1F` to `#1E1E22` (subtle lift via lightness, not shadow)
- **Brand accent**: Indigo/violet (`#5E6AD2`) -- their signature color conveying "calm authority"
- **Supporting neutrals**: Woodsmoke (deep charcoal, ~`#16161A`), Oslo Gray (mid-neutral, ~`#878A94`), Black Haze (near-white, ~`#F2F2F2`)
- **Text primary**: `#EDEDEF` (not pure white, slightly muted)
- **Text secondary**: `#7E7E86` to `#8B8B93`

### Border Treatments
- Extremely subtle: `1px solid rgba(255, 255, 255, 0.06)` to `rgba(255, 255, 255, 0.08)`
- Borders are barely visible -- separation comes from background lightness differences
- No visible borders on many elements; relies on spacing and background contrast

### Shadow Styles
- Minimal to zero box-shadows in the main interface
- Elevation conveyed through lighter surface colors (Material-style overlay approach)
- Occasional very subtle glow on focus states: `0 0 0 2px rgba(94, 106, 210, 0.4)` (accent ring)

### Key Design Principles
- **Monochrome-first**: 2025 redesign stripped almost all color; black/white/gray dominates, accent color used extremely sparingly
- **LCH color space** for theme generation (perceptually uniform, unlike HSL)
- Few core colors (bg, text, accent) generate all derived shades programmatically
- **Typography**: System font stack (Inter-like), tight letter-spacing, medium weight (~500) for labels
- **Spacing**: 8px grid system, generous padding (16-24px in cards), 4px micro-spacing for inline elements

### Actionable Takeaways for Gleitcast
- Use near-black bg with very slight cool undertone (not pure `#000`)
- Derive border/surface colors from white at extremely low opacity (5-8%)
- Limit accent to one hue; use it only for interactive/active states
- Elevation = lighter background, NOT shadow

---

## 2. Vercel Dashboard (Geist Design System)

**Source**: [Geist Colors](https://vercel.com/geist/colors) | [Geist Theme Switcher](https://vercel.com/geist/theme-switcher) | [Vercel Design Breakdown](https://seedflip.co/blog/vercel-design-system) | [Veist Theme](https://github.com/guilhermerodz/veist-theme)

### Color System
- **Background (primary)**: Pure black `#000000` -- Vercel is one of the few apps that actually uses true black
- **Surface/Card**: `#111111` (gray-900 equivalent)
- **Elevated surface**: `#171717` (gray-850)
- **Gray scale (dark mode)**:
  - gray-100: `#F7F7F7` (light mode text area)
  - gray-200: `#E5E5E5`
  - gray-400: `#A3A3A3`
  - gray-500: `#737373`
  - gray-600: `#525252`
  - gray-700: `#404040`
  - gray-800: `#262626`
  - gray-900: `#171717`
  - gray-1000: `#0A0A0A`
- **Accent**: Blue `#0070F3` (Vercel blue), success green `#0070F3`, error red `#EE0000`
- **Text primary**: `#EDEDED`
- **Text secondary**: `#888888`

### Border Treatments
- `1px solid #333333` (gray-700 area) -- visible but restrained
- In dark mode, borders are the primary elevation mechanism (not shadows)
- Occasional `rgba(255, 255, 255, 0.1)` for softer contexts

### Shadow Styles
- Almost no shadows in dark mode
- Light mode uses subtle shadows; dark mode replaces them entirely with borders
- Focus rings: `0 0 0 1px #333, 0 0 0 4px rgba(0, 112, 243, 0.3)`

### Typography
- **Geist Sans**: Custom geometric sans-serif, negative letter-spacing by default
- **Geist Mono**: For code/data
- Size scale: 12px (caption) / 14px (body) / 16px (large body) / 20-64px (headings)
- Font weight: 400 normal, 500 medium for labels, 600 semi-bold for emphasis

### Key Design Principles
- **"Aggressive reduction"**: Fewer design decisions than almost any competitor
- Pure black + pure white as absolute anchors
- Borders over shadows in dark mode
- **Spacing**: 4px base unit, consistent 16px / 24px / 32px rhythm

### Actionable Takeaways for Gleitcast
- Consider a true `#000` background if going for maximum contrast/OLED efficiency
- Use a well-defined gray scale with consistent steps
- Replace shadows with border treatments in dark mode
- Geist-style tight letter-spacing gives a "designed" feel for free

---

## 3. Raycast (Glassmorphism Approach)

**Source**: [Dark Glassmorphism 2026](https://medium.com/@developer_89726/dark-glassmorphism-the-aesthetic-that-will-define-ui-in-2026-93aa4153088f) | [Glassmorphism Best Practices](https://uxpilot.ai/blogs/glassmorphism-ui) | [CSS Glassmorphism Guide](https://csstopsites.com/glassmorphism-dark-backgrounds) | [Glass UI Generator](https://ui.glass/generator)

### Core CSS Recipe (Dark Glassmorphism)
```css
/* Card / Panel on dark background */
.glass-panel {
  background: rgba(255, 255, 255, 0.05);        /* 5% white */
  backdrop-filter: blur(12px) saturate(180%);
  -webkit-backdrop-filter: blur(12px) saturate(180%);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

/* Darker variant for overlays on maps */
.glass-overlay {
  background: rgba(17, 25, 40, 0.75);           /* deep blue-black at 75% */
  backdrop-filter: blur(16px) saturate(150%);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
}

/* Subtle inner glow for depth */
.glass-panel::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(
    135deg,
    rgba(255, 255, 255, 0.06) 0%,
    transparent 50%
  );
  pointer-events: none;
}
```

### Key Parameters
| Property | Light Glass | Dark Glass | Map Overlay Glass |
|----------|-------------|------------|-------------------|
| Background opacity | 0.15-0.25 | 0.05-0.10 | 0.65-0.80 |
| Blur | 8-12px | 10-16px | 12-20px |
| Border opacity | 0.15-0.25 | 0.06-0.12 | 0.08-0.15 |
| Border radius | 12-16px | 12-16px | 12-20px |
| Box shadow | subtle | minimal | 0 8px 32px rgba(0,0,0,0.3) |

### Color Choices
- Background tint: `rgba(17, 25, 40, 0.75)` (Raycast-style blue-black) or `rgba(255, 255, 255, 0.05)` (neutral)
- The `saturate(150-180%)` filter is critical -- it keeps colors behind the glass vibrant
- Adding a slight gradient overlay (white at 4-6% from top-left) simulates light reflection

### Performance Considerations
- `backdrop-filter` is GPU-intensive; limit to 3-5 glass panels per view
- Provide fallback: `background: rgba(17, 25, 40, 0.92)` for browsers without backdrop-filter
- Avoid glass on frequently re-rendering elements

### Actionable Takeaways for Gleitcast
- Use glassmorphism for map overlay panels (sidebar, spot info cards)
- The `rgba(17, 25, 40, 0.75)` with `blur(16px)` is ideal for weather data panels on maps
- Always add `saturate()` alongside blur to prevent washed-out appearance
- Keep glass to key panels only (max 3-5 per view) for performance

---

## 4. Arc Browser

**Source**: [Arc CSS Properties](https://ginger.wtf/posts/creating-a-theme-using-arc/) | [Arc Theme Styling](https://www.devslovecoffee.com/blog/using-arc-theme-to-style-website) | [Arc-Dark Palette](https://www.color-hex.com/color-palette/36646)

### Color System
- **Dark palette**: `#404552` (sidebar), `#383C4A` (background), `#4B5162` (elevated), `#5294E2` (accent blue), `#7C818C` (secondary text)
- **CSS Custom Properties exposed**:
  - `--arc-palette-background`: Main surface
  - `--arc-palette-backgroundExtra`: Elevated surface
  - `--arc-palette-foregroundPrimary`: Main text
  - `--arc-palette-foregroundSecondary`: Secondary text
  - `--arc-palette-foregroundTertiary`: Muted text
  - `--arc-palette-hover`: Hover state
  - `--arc-palette-focus`: Focus ring
  - `--arc-palette-cutoutColor`: Inset/recessed areas
  - `--arc-palette-title`: Heading color
  - `--arc-palette-subtitle`: Subheading color
  - `--arc-palette-maxContrastColor`: Highest contrast (near white)
  - `--arc-palette-minContrastColor`: Lowest contrast (near bg)

### Color on Dark Backgrounds
- Arc uses **space-specific color theming**: each browser Space gets its own accent color
- Colors are desaturated slightly on dark backgrounds to avoid visual harshness
- The sidebar uses a slightly lighter background than the content area to create hierarchy
- Accent colors work at **medium saturation** (not neon-bright); the blue `#5294E2` is a good reference

### Typography and Spacing
- System font stack following platform conventions
- Compact spacing in the sidebar (28-32px row height)
- Content area uses standard web spacing

### Actionable Takeaways for Gleitcast
- Use a semantic variable system (background, foregroundPrimary/Secondary/Tertiary, accent, hover, focus)
- Desaturate accent colors ~15-20% for dark backgrounds to avoid eye strain
- Different background levels (bg -> bgExtra -> cutout) create depth without borders

---

## 5. Stripe Dashboard (Data Visualization)

**Source**: [Stripe Accessible Color Systems](https://stripe.com/blog/accessible-color-systems) | [Stripe Appearance API](https://docs.stripe.com/elements/appearance-api) | [Stripe Dark Mode](https://docs.stripe.com/connect/embedded-appearance-support-dark-mode) | [Stripe Dashboard Design](https://mattstromawn.com/projects/stripe-dashboard/)

### Dark Mode Color Tokens
- **colorBackground**: `#14171D` (deep blue-black, NOT neutral gray)
- **colorText**: `#C9CED8` (soft blue-gray, not pure white)
- **colorPrimary**: `#0085FF` (vivid blue)
- **colorDanger**: Red (estimated `#DF1B41`)
- **colorSuccess**: Green (estimated `#30B065`)
- **colorWarning**: Yellow (estimated `#D97706`)
- **Surface elevated**: estimated `#1A1F29`

### Data Visualization Colors
Stripe's color system for charts is built on three principles:
1. **Predictable accessibility**: Every color pair passes WCAG contrast
2. **Clear vibrant hues**: Users can distinguish adjacent colors instantly
3. **Consistent visual weight**: No single color dominates visually

They use **CIELAB/LCH perceptually uniform color space** to ensure:
- Equal lightness across all chart colors
- Maximally distinct hues at the same luminance level
- Colors that work on both light and dark backgrounds

### Recommended Chart Palette (Dark Background)
For data viz on dark backgrounds, follow Stripe's approach:
- Use 5-7 distinct hues at the same perceptual lightness (~L*55-65 in CIELAB)
- Reduce saturation ~20% compared to light-mode charts
- Test all colors against the specific background for WCAG AA (4.5:1 for text, 3:1 for UI)

### Border and Shadow
- Borders: `1px solid rgba(255, 255, 255, 0.08)` between data rows
- Card shadows: Minimal; uses border + slight background lift
- Focus: `0 0 0 3px rgba(0, 133, 255, 0.4)` (brand blue ring)
- Table row hover: `rgba(255, 255, 255, 0.03)` background

### Design Token Architecture
- All components use tokens, not hardcoded colors
- Extensible theming architecture supports "darker mode" overlays
- Color tokens include a full semantic layer: `color.bg.primary`, `color.bg.secondary`, `color.text.primary`, etc.

### Actionable Takeaways for Gleitcast
- Use blue-black (`#14171D`) not neutral gray for dashboard backgrounds (feels more premium)
- For thermal/wind data viz, use perceptually uniform color scales (LCH space)
- Muted text color (`#C9CED8`) is more pleasant than bright white
- Build a semantic token system from the start

---

## 6. Apple Weather App

**Source**: [Apple Glassmorphism 2025](https://www.everydayux.net/glassmorphism-apple-liquid-glass-interface-design/) | [Glassmorphism NNG](https://www.nngroup.com/articles/glassmorphism/) | [Apple Weather Features](https://ios.gadgethacks.com/how-to/your-iphones-weather-app-has-crazy-number-customization-options-you-probably-didnt-know-about-0384907/)

### Background and Visual System
- **Animated gradient backgrounds** that change with weather conditions and time of day
- Night/dark: Deep blue-to-black gradients (`#0B1628` -> `#000000`)
- Clear day: Blue-to-cyan gradients
- Overcast: Gray-blue muted gradients
- Background is NEVER static; it communicates weather state visually

### Glassmorphism Panels (iOS Liquid Glass)
```css
/* Apple Weather-style card */
.weather-card {
  background: rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(20px) saturate(180%);
  border-radius: 16px;
  border: 0.5px solid rgba(255, 255, 255, 0.18);
  /* Apple uses thinner borders (0.5px via retina) */
}
```

### Map Overlay Design
- **Precipitation overlay**: Semi-transparent color wash (blue/green/yellow/red) at ~40-60% opacity
- **Temperature overlay**: Gradient color scale from blue (cold) through green/yellow to red (hot)
- **Wind overlay**: Animated particles flowing in wind direction
- Map controls use frosted glass panels positioned in corners
- Data panels slide up from bottom as translucent sheets

### Key Specifications
- **Border radius**: 14-16px (consistent across all cards)
- **Border**: `0.5px` (Retina hairline) at `rgba(255, 255, 255, 0.15-0.20)`
- **Blur**: 20-25px (stronger than typical web glass)
- **Card spacing**: 8-12px between cards in a scrollable list
- **Inner padding**: 16px
- **Typography**: SF Pro (system), 13pt body, 11pt caption, 34pt display temperature

### Liquid Glass (iOS 26 / 2025)
- Physically accurate light refraction simulation
- Dynamically adapts tint, opacity, contrast based on background content
- Semi-transparent overlay of 10-30% opacity (auto-adjusted for legibility)

### Actionable Takeaways for Gleitcast
- Use weather-condition-aware background gradients (even subtle ones behind the map)
- Frosted glass panels on map should use ~12-20% white bg with 16-20px blur
- Hairline borders (0.5-1px) at very low opacity look premium on retina
- Bottom sheet pattern is ideal for mobile spot detail views
- Animated weather backgrounds are a strong differentiator for weather apps

---

## 7. Windy.com (Weather Map Overlays)

**Source**: [Windy Color Codes](https://community.windy.com/topic/3811/color-codes) | [Windy Overlay Descriptions](https://community.windy.com/topic/3361/description-of-weather-overlays) | [Windy Custom Colors](https://community.windy.com/topic/10336/customize-the-color-scales-of-windy-layers) | [Windy Background Map](https://community.windy.com/topic/25075/background-map-change)

### Map and UI Background
- **Dark map style**: Approximately `#323232` (RGB 50,50,50) for base map
- **UI panel backgrounds**: Dark translucent, ~`rgba(30, 30, 36, 0.85)`
- **Widget backgrounds**: Three modes: Dark, Bright, Transparent
- Map tiles themselves can be dark (Windy map), satellite, or hybrid

### Wind Color Scale (Default)
| Wind Speed | Color | Hex (approx) |
|-----------|-------|---------------|
| 0-3 m/s (calm) | White | `#FFFFFF` |
| 4-5 m/s (light) | Light Blue | `#96C8FA` |
| 6-8 m/s (moderate) | Green | `#64C864` |
| 9-12 m/s (fresh) | Orange | `#FFA000` |
| 14-17 m/s (strong) | Red | `#FF3232` |
| 18+ m/s (gale) | Purple | `#C832C8` |

### Overlay Design Principles
- **Opacity balance**: Overlays at 40-70% opacity to show both data and terrain
- **Color saturation**: High saturation for weather data (needs to read over varied terrain)
- **Transparency tradeoff**: High-opacity overlays obscure map detail; too-low opacity makes data unreadable
- RGBA format for all overlay colors: `rgba(R, G, B, opacity)`
- Color scales are **continuous gradients** interpolated between threshold values

### UI Panel Design
- Compact slide-out panels from left/right edge
- Timeline/playback bar pinned to bottom with translucent background
- Spot detail: Popup panels with semi-transparent dark background
- Control icons: Simple white/light gray on dark translucent bg

### Data Presentation on Maps
- **Legend bar**: Horizontal gradient strip showing color-to-value mapping
- **Particle animation**: Wind direction shown as flowing white particles (like smoke)
- **Isobars/contours**: Thin lines (1-2px) at low opacity over color overlay
- **Spot markers**: Circular badges with wind speed number, colored by wind scale

### Actionable Takeaways for Gleitcast
- Wind color scale: white(calm) -> blue(light) -> green(moderate) -> orange(fresh) -> red(strong) -> purple(gale)
- Map overlays at 40-60% opacity with map dark tiles underneath
- Use particle animations for wind if performance allows
- Spot markers with colored badges (wind-speed-based) are instantly readable
- Translucent dark panels (`rgba(30,30,36,0.85)`) on map edges

---

## 8. XCTrack / XContest (Paragliding-Specific)

**Source**: [XCTrack Widgets Manual](https://www.fly-air3.com/en/support/air3-xctrack-manual/xctrack-manual/xctrack-widgets-manual/xctrack-pro-widgets-xcontest/) | [XCTrack Preferences](https://www.fly-air3.com/en/support/air3-xctrack-manual/xctrack-manual/preferences3/) | [XCTrack.org](https://xctrack.org/) | [Flybubble Weather](https://flybubble.com/blog/flybubble-weather)

### Theme System
- **Three base themes**: Light, Dark, XContest (custom)
- **Dark (Black)**: Pure black background for OLED efficiency on flight instruments
- **Map theme can differ from widget theme**: e.g., black widgets + white map for best readability
- **High Contrast mode**: Available for both light and dark, increases border/text contrast

### Thermal Overlay Visualization
- **Source data**: thermal.kk7.ch (crowdsourced from real flights, no model data)
- **Color encoding**: Strength of lift displayed through color variation (dark/light theme) or circle size (eInk theme)
- **Color scale**: Typically green(weak) -> yellow(moderate) -> orange(strong) -> red(very strong)
- Overlay opacity adjustable by user

### Paragliding Data Presentation Patterns
- **Widget grid**: Modular, configurable data cells arranged in grid layout
- **Large single-value displays**: Altitude, vario, speed shown as big numbers (40-60pt equivalent)
- **Color-coded vario**: Green (positive/lift), red (negative/sink), sized by magnitude
- **Compass rose**: Wind direction with colored sectors showing safe/dangerous angles
- **Airspace overlay**: Semi-transparent colored zones on map with altitude labels

### Flybubble Weather (Paragliding Weather Reference)
- **Wind suitability colors**: Light blue -> dark green (soarable), light green (upper limit for PG), yellow/red (blown out)
- **Map markers**: Site icons colored by flyability
- **Data panels**: Compact forecast tables with color-coded cells

### Actionable Takeaways for Gleitcast
- Modular widget grid is the standard for flight instrument apps
- Large numbers for key metrics (climb rate, wind speed)
- Thermal data: green-yellow-orange-red scale is universal in PG
- Wind suitability: blue/green = good, yellow = marginal, red = dangerous
- Separate map theme from UI theme option is a power-user feature
- Airspace overlays: colored zones at ~30% opacity with text labels

---

## Cross-Cutting Synthesis: Design System for Gleitcast

### Recommended Background Colors
```css
:root {
  /* Primary surfaces */
  --bg-base:      #0A0A0F;      /* Near-black with slight blue (Linear/Stripe influenced) */
  --bg-surface:   #111118;      /* Cards, panels */
  --bg-elevated:  #1A1A24;      /* Elevated cards, modals */
  --bg-hover:     #222230;      /* Hover states */

  /* Map overlay panels */
  --bg-glass:     rgba(17, 20, 30, 0.78);  /* Glassmorphism panels on map */
  --bg-glass-light: rgba(255, 255, 255, 0.06); /* Subtle glass on dark bg */
}
```

### Recommended Border System
```css
:root {
  --border-subtle:   1px solid rgba(255, 255, 255, 0.06);  /* Default */
  --border-default:  1px solid rgba(255, 255, 255, 0.10);  /* Cards */
  --border-strong:   1px solid rgba(255, 255, 255, 0.15);  /* Active/focused */
  --border-accent:   1px solid rgba(94, 106, 210, 0.5);    /* Focus ring base */
}
```

### Recommended Shadow System
```css
:root {
  /* Shadows minimal in dark mode; use for floating elements only */
  --shadow-sm:    0 2px 8px rgba(0, 0, 0, 0.3);
  --shadow-md:    0 4px 16px rgba(0, 0, 0, 0.4);
  --shadow-lg:    0 8px 32px rgba(0, 0, 0, 0.5);
  --shadow-glow:  0 0 0 3px rgba(94, 106, 210, 0.3);  /* Focus/accent glow */

  /* Glass shadow */
  --shadow-glass: 0 8px 32px rgba(0, 0, 0, 0.25),
                  inset 0 1px 0 rgba(255, 255, 255, 0.05);
}
```

### Recommended Text Colors
```css
:root {
  --text-primary:    #EDEDED;   /* Main text, NOT pure white */
  --text-secondary:  #8B8B96;   /* Descriptions, labels */
  --text-tertiary:   #5C5C6A;   /* Disabled, hints */
  --text-accent:     #7B8AFF;   /* Links, interactive text */
}
```

### Recommended Typography
```css
:root {
  --font-sans:  'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  --font-mono:  'JetBrains Mono', 'Fira Code', 'SF Mono', monospace;

  --text-xs:    0.75rem;    /* 12px - captions, badges */
  --text-sm:    0.875rem;   /* 14px - body small, table cells */
  --text-base:  1rem;       /* 16px - body */
  --text-lg:    1.25rem;    /* 20px - section headers */
  --text-xl:    1.5rem;     /* 24px - page titles */
  --text-2xl:   2rem;       /* 32px - hero/temperature display */

  --font-normal:    400;
  --font-medium:    500;    /* Labels, nav items (use this not regular on dark bg) */
  --font-semibold:  600;    /* Headings, emphasis */

  --tracking-tight: -0.02em;  /* Headings (Linear/Vercel style) */
  --tracking-normal: 0;       /* Body text */

  /* Dark mode: slightly heavier weight, more line-height */
  --leading-tight:  1.3;
  --leading-normal: 1.6;     /* Body text on dark bg */
  --leading-relaxed: 1.8;    /* Long-form content */
}
```

### Recommended Spacing
```css
:root {
  --space-1:  4px;
  --space-2:  8px;
  --space-3:  12px;
  --space-4:  16px;
  --space-5:  20px;
  --space-6:  24px;
  --space-8:  32px;
  --space-10: 40px;
  --space-12: 48px;

  --radius-sm:  6px;
  --radius-md:  10px;
  --radius-lg:  14px;   /* Cards, panels */
  --radius-xl:  20px;   /* Modals, map overlays */
}
```

### Glassmorphism Recipe for Map Panels
```css
.map-panel {
  background: rgba(17, 20, 30, 0.78);
  backdrop-filter: blur(16px) saturate(160%);
  -webkit-backdrop-filter: blur(16px) saturate(160%);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.25);
  padding: 16px;
  color: #EDEDED;
}

/* Fallback for no backdrop-filter support */
@supports not (backdrop-filter: blur(1px)) {
  .map-panel {
    background: rgba(17, 20, 30, 0.94);
  }
}
```

### Weather Data Color Scales
```css
:root {
  /* Wind speed (Windy.com-inspired) */
  --wind-calm:     #A8D8EA;   /* 0-2 m/s */
  --wind-light:    #57A0D2;   /* 2-4 m/s */
  --wind-moderate: #4CAF50;   /* 4-7 m/s */
  --wind-fresh:    #FF9800;   /* 7-10 m/s */
  --wind-strong:   #F44336;   /* 10-15 m/s */
  --wind-gale:     #9C27B0;   /* 15+ m/s */

  /* Thermal / climb rate (PG standard) */
  --thermal-none:    #5C5C6A; /* 0 m/s */
  --thermal-weak:    #66BB6A; /* 0-1 m/s */
  --thermal-mod:     #FFCA28; /* 1-2 m/s */
  --thermal-good:    #FFA726; /* 2-3 m/s */
  --thermal-strong:  #EF5350; /* 3+ m/s */

  /* Flyability (Flybubble-inspired) */
  --fly-excellent:   #4CAF50; /* All green */
  --fly-good:        #66BB6A; /* Light green */
  --fly-marginal:    #FFB74D; /* Yellow-orange */
  --fly-unflyable:   #EF5350; /* Red */
}
```

### Map Overlay Opacity Guidelines
| Overlay Type | Recommended Opacity | Notes |
|-------------|-------------------|-------|
| Wind color wash | 0.40 - 0.55 | Must see terrain underneath |
| Thermal heatmap | 0.35 - 0.50 | Circles/blobs, not full coverage |
| Precipitation | 0.45 - 0.60 | Can be more opaque; rain is primary info |
| Airspace zones | 0.20 - 0.35 | Must not obscure other data |
| Cloud cover | 0.30 - 0.45 | Subtle wash effect |
| Spot markers | 1.0 (opaque) | Badge with number, colored border |

### Elevation Strategy (Dark Mode)
Instead of shadows (which disappear on dark backgrounds), use the Material Design approach:
```
Level 0 (base):     --bg-base      #0A0A0F    (+0% white overlay)
Level 1 (card):     --bg-surface   #111118    (+5% white overlay)
Level 2 (raised):   --bg-elevated  #1A1A24    (+8% white overlay)
Level 3 (modal):    --bg-modal     #222230    (+11% white overlay)
Level 4 (popover):  --bg-popover   #2A2A3A    (+14% white overlay)
```

Each level is achieved by compositing `rgba(255, 255, 255, X%)` over the base `#121212`:
- dp 0: 0%
- dp 1: 5%
- dp 2: 7%
- dp 3: 8%
- dp 4: 9%
- dp 6: 11%
- dp 8: 12%
- dp 12: 14%
- dp 16: 15%
- dp 24: 16%
