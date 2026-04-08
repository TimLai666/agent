# Cinematic PPTX Reference

This reference is loaded **only** when output medium is `pptx`. It governs how cinematic grammar translates into PptxGenJS slide construction.

---

## Medium Mapping: Film → Slide

| Web concept | Slide equivalent |
|---|---|
| Full-bleed hero section | Cover slide: dominant shape panel + oversized type |
| Section reveal / entrance | Slide-level composition hierarchy (not animation) |
| Motion / parallax | Static composition tension: diagonal crop, asymmetric weight |
| Navigation bar | Sidebar strip or top rule line — consistent across all slides |
| Page rhythm (spectacle → info → rest) | Slide sequence rhythm (cover → argument → data → verdict) |
| Atmospheric layer | Background texture via semi-transparent shape overlay |

---

## Slide Anatomy Rules

Every content slide must have exactly **three visual layers**:

1. **Structure layer** — background color, panel shapes, rule lines
2. **Content layer** — text, formulas, tables (all-shape, never addTable)
3. **Accent layer** — verdict boxes, pull-quote bars, chapter marks

A slide that is only layer 2 is not cinematic. A slide that is only layer 1+3 is incomplete.

---

## Composition Families for Slides

Choose one per deck. Do not mix families.

| Family | Description | Best for |
|---|---|---|
| **Editorial split** | Left panel (30–40%) + right content column, gold/ink rule divider | Academic, research, analytical |
| **Monumental type** | Oversized heading (60pt+) dominates, data in subordinate zone | Thesis-driven, keynote |
| **Archive wall** | Tight grid of data blocks, dark frame, specimen card feel | Data-heavy, taxonomy |
| **Corridor** | Full-width dark band top + bottom, content in lit centre | Cinematic, dramatic |
| **Cover poster** | Left half solid dark + right half white/cream, editorial title | Journal, dispatch, report |

---

## Color Discipline

- Extract exactly **4 tokens** from the chosen film palette before writing any code: background, primary, accent, muted.
- Never use more than 4 colors per deck. Gold rule lines and shape borders count toward the 4.
- Dark backgrounds belong on the cover slide and verdict/summary slides. Content slides use the light background.
- Accent color is reserved for: Reject H₀ decisions, key results, chapter markers. Do not use it decoratively.

---

## Typography Rules

| Role | Font | Size | Notes |
|---|---|---|---|
| Deck title (cover) | Georgia / Garamond bold | 34–48pt | Never centered unless corridor family |
| Section heading | Georgia bold | 13–16pt | Left-aligned |
| Chapter tag | Courier New bold | 7–9pt, charSpacing 3+ | ALL CAPS |
| Formula / code | Courier New | 10–13pt | The monospace IS the cinematic signal |
| Body / explanation | Calibri | 10–11pt | Italic for footnotes/captions |
| Footer | Courier New | 7–8pt | Slide number right-aligned |

Never use Arial or sans-serif for headings in a cinematic deck. Serif + monospace is the editorial pairing.

---

## Table Rules

**Never use `addTable()`** — it produces unpredictable rendering across platforms. Always build tables as shape+text loops:

```javascript
// Pattern: all-shape table
const rows = [...];
const colX = [x0, x1, x2, ...];
const colW = [w0, w1, w2, ...];
rows.forEach((row, ri) => {
  const y = startY + ri * rowH;
  const bg = ri === 0 ? HEADER_COLOR : (ri % 2 === 0 ? ALT_COLOR : BASE_COLOR);
  colX.forEach((cx, ci) => {
    s.addShape(pres.shapes.RECTANGLE, { x: cx, y, w: colW[ci], h: rowH, fill: { color: bg }, line: { color: BORDER_COLOR } });
    s.addText(row[ci], { x: cx + 0.05, y: y + 0.05, w: colW[ci] - 0.1, h: rowH - 0.1, fontSize: 10, fontFace: "Courier New", color: ri === 0 ? WHITE : BODY_COLOR, bold: ri === 0, margin: 0 });
  });
});
```

---

## Verdict Box Pattern

Use for hypothesis decisions, key results, and final conclusions:

```javascript
function verdict(s, text, accentColor, x, y, w = 3.5, h = 0.5) {
  // Semi-transparent fill
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: accentColor, transparency: 88 }, line: { color: accentColor, transparency: 50 } });
  // Left accent bar
  s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.06, h, fill: { color: accentColor }, line: { color: accentColor } });
  // Text
  s.addText(text, { x: x + 0.12, y: y + 0.06, w: w - 0.18, h: h - 0.12,
    fontSize: 11, color: accentColor, fontFace: "Georgia", bold: true, italic: true,
    valign: "middle", margin: 0, wrap: true });
}
```

---

## Slide Sequence Rhythm

A cinematic deck follows scene rhythm, not topic-dump order:

```
Cover (spectacle)
  → Problem/data slides (information, 2-column split)
  → Derivation slides (step progression, numbered rows)
  → Verdict slides (decision, dark accent)
  → Summary (echo of cover energy)
```

Do not default to: Title → Bullet 1 → Bullet 2 → Thank you.

---

## pptx Phase 4 Checklist

Before declaring the deck complete, verify:

- [ ] All tables built as shape+text loops (zero `addTable()` calls)
- [ ] No header+overlay pattern (causes double-render) — shapes only
- [ ] Shadow objects use `makeShadow()` factory function (prevents EMU corruption)
- [ ] Cover slide has ≥ 3 visual elements beyond plain text
- [ ] Each content slide has structure + content + accent layers
- [ ] Verdict boxes present on every hypothesis-decision slide
- [ ] Footer with slide counter on all non-cover slides
- [ ] Color stays within 4-token palette
- [ ] QA: convert to PDF → pdftoppm → visually inspect all slides

---

## PptxGenJS Quick-Reference Pitfalls

- **Never `"#RRGGBB"`** — use bare hex `"RRGGBB"` or file corrupts
- **Never 8-char hex in shadow** — use `opacity` property separately
- **`breakLine: true`** required between array text items
- **`margin: 0`** on text boxes when aligning with shape edges
- **`makeShadow()` factory** — never reuse shadow object across calls
- **`ROUNDED_RECTANGLE` + accent border** — use `RECTANGLE` instead
- **Sidebar rotated text** — LibreOffice may mis-render; PowerPoint renders correctly

