# Website Redesign Design

## Status

Draft for user review. This document replaces the previous website design direction because the first implementation looked visually busy and did not achieve the clean Feishu-style order requested by the user.

Do not commit this spec until the user reviews and approves it.

## Problem Statement

The current redesigned home page has the right content but the wrong composition. It presents too many visual systems at once: a sticky custom header, oversized left-aligned hero, dark diagram panels, numbered feature rows, repeated delivery-flow images, stage tiles, contrast blocks, and a closing CTA. The result feels busy instead of clear.

The next design must be simpler, more centered, and more disciplined. It should reference the Feishu official website at `https://www.feishu.cn/` for page structure and interaction style: a clean top navigation, centered first-screen messaging, compact CTAs, generous white space, a single dominant product visual, and orderly section rhythm.

The new design must not copy Feishu's brand assets, color identity, copy, illustrations, product screenshots, or exact component styling.

## Audience And Goal

The page is a public website surface for project introduction, not the console. The primary audience is a visitor evaluating what AI DevFlow Engine is and why it matters.

The page must make one idea clear within the first viewport:

> AI DevFlow Engine turns requirement-to-delivery work into a traceable pipeline.

Success means the page feels calm, precise, and easy to scan. It should look like a deliberate product website, not a dashboard and not a README rendered as a web page.

## Design Register

Use the Impeccable `brand` register.

The repository does not currently include `PRODUCT.md` or `DESIGN.md`. This spec uses the user's approved direction, `README.zh.md`, the current route structure, the existing `assets/agent-delivery-flow.svg`, and direct inspection of Feishu's website structure as source context.

## Feishu Reference Extraction

Use these reference characteristics from Feishu:

- A full-width, white or near-white page surface.
- A compact, high-confidence top navigation with brand on the left, product links in the middle, and two or three actions on the right.
- A centered hero that uses short copy, not a dense explanatory paragraph.
- Primary and secondary CTAs placed close to the hero copy.
- One large product visual below the hero copy, visually treated as the proof of the product.
- Wide section spacing with few competing elements.
- Section headings that are short and centered.
- Product capability presentation that feels ordered and modular, not like a grid of generic marketing cards.

Do not use these Feishu details:

- Feishu brand gradients, mascots, icons, illustrations, or event banners.
- Large quantities of promotional links.
- Enterprise sales copy, pricing, customer cases, or fake social proof.
- Feishu's exact nav labels or button styling.

## Revised Page Shape

### Global Header

Use one website header for the home page. The app's existing console header should not appear on the home page.

Header content:

- Brand: `AI DevFlow Engine`
- Navigation links: `Overview`, `Flow`, `Control`, `Start`
- Secondary action: `Docs`
- Primary action: `Open Console`

Header behavior:

- Sticky at the top.
- White or near-white background.
- Height around 64px on desktop.
- Thin bottom border only after scroll or as a very subtle divider.
- No colored logo dot, decorative mark, or large brand block.
- On mobile, keep brand and `Open Console`; collapse or hide section links.

### Hero

The hero must be centered and quiet.

Hero content:

- Eyebrow: `Local-first AI delivery workflow`
- H1: `Make delivery work traceable.`
- Supporting copy: one sentence, maximum 110 English characters or equivalent length if localized later.
- Primary CTA: `Open Console`
- Secondary CTA: `View Flow`

Hero composition:

- Center align the copy.
- Keep the H1 to one or two lines.
- Use ample top and bottom spacing.
- Show a hint of the next section in the first viewport on common desktop and mobile sizes.
- Do not use a left-right hero split.
- Do not place the hero text in a card.
- Do not use oversized decorative typography.

### Product Visual

Use `assets/agent-delivery-flow.svg` as the only main visual asset.

Placement:

- Put the delivery flow image directly below the hero CTAs.
- Use it once in the page, not twice.
- Center it in a wide but calm product-visual band.

Treatment:

- The image should sit on a light surface, not inside a heavy dark frame.
- A subtle border, shadow, or background tint is acceptable.
- The visual container should be lower contrast than the current implementation.
- The diagram must remain readable on desktop.
- On mobile, scale the visual to fit width or provide a controlled horizontal scroll only for the image area.

### Overview Section

Replace the numbered feature list with one clean three-column capability row.

Capabilities:

- `Preserve intent`
  Requirements, constraints, and acceptance criteria stay attached to the run.
- `Review before code`
  Plans and validation appear before workspace changes.
- `Record delivery`
  Tests, review, approvals, and delivery result remain connected.

Presentation:

- Use very simple columns.
- No large icons.
- No repeated card chrome.
- No numbered labels unless they are tiny and purely structural.
- Keep each body line short.

### Flow Section

Do not repeat the SVG.

Instead, explain the six stages as a minimal horizontal or wrapped sequence:

1. Requirement
2. Design
3. Code
4. Test
5. Review
6. Delivery

Each stage gets one short phrase. The sequence should feel like a navigation rail or process strip, not a grid of cards.

The section heading should be short:

`One path, six visible stages.`

### Control Section

Use one section to explain the product's key difference:

`Human control stays in the workflow.`

Content should mention approvals, tool confirmations, retry, rollback, and delivery result as first-class workflow events. Keep this as one focused text block plus a small ordered list or inline event row.

Do not create a dramatic before/after contrast block. The previous contrast section contributed to visual noise.

### Start Section

End with a compact CTA band.

Content:

- Heading: `Run the workflow from the console.`
- Primary CTA: `Open Console`
- Secondary CTA: `Read Documentation`

Presentation:

- Centered.
- Light background.
- No command block by default.
- No footer-style link farm.

## Visual Direction

Physical scene: a technical evaluator opens the page in a browser during a short product scan and needs to understand the product without reading documentation or entering the console.

Theme:

- Light, clean, and ordered.
- More Feishu-style product website than developer dashboard.
- Calm enough for a business/product audience, precise enough for a technical audience.

Color strategy:

- Restrained.
- Near-white page surface with slightly tinted blue-gray neutrals.
- One primary blue accent for CTAs and active states.
- One restrained teal accent for pipeline semantics.
- Avoid large dark panels.
- Avoid multi-color section treatments.
- Use OKLCH for authored colors.
- Do not use pure black or pure white.

Typography:

- Use the existing system font stack unless a separate typography decision is approved.
- H1 should feel large but not aggressive.
- H2 headings should be clearly smaller than H1.
- Body text should remain between 65 and 75 characters per line.
- Do not use viewport-width font scaling.
- Do not use gradient text.
- Do not use all-caps body text.

Layout:

- Prefer centered composition for hero and section headings.
- Use a maximum content width around 1120px to 1200px.
- Use fewer sections with stronger spacing.
- Avoid nested cards.
- Avoid dense repeated tile grids.
- Keep border radius at 8px or below.
- Keep each viewport focused on one main idea.

Motion:

- Use subtle hover and focus states.
- Smooth scrolling for section anchors is acceptable.
- Do not animate layout properties.
- Respect reduced-motion preferences.
- No entrance animation is required for the next implementation.

## Interaction Requirements

- Header anchors scroll to page sections.
- `Open Console` links to `/console`.
- `View Flow` scrolls to the flow section.
- `Docs` and `Read Documentation` link to the repository README or docs index.
- Header section links should not trigger full document navigation in tests.
- The delivery flow image must have meaningful alt text.

## Explicit Removal From Current Implementation

The next implementation must remove these current-version patterns:

- Left-aligned split hero.
- Dark framed hero diagram.
- Repeated delivery-flow SVG.
- Large numbered feature rows.
- Six boxed stage tiles.
- Before/after contrast cards.
- Decorative brand dot in the header.
- Multiple competing section art directions.

## Accessibility Requirements

- Keep semantic heading order.
- Provide visible focus states for all links.
- Maintain WCAG AA text contrast.
- Ensure 320px mobile width has no horizontal page overflow.
- If the flow image scrolls horizontally on mobile, the scroll must be limited to the image container.
- The page must remain usable with reduced motion.

## Implementation Boundaries

Expected files:

- `frontend/src/pages/HomePage.tsx`
- `frontend/src/styles/global.css`
- `frontend/src/pages/__tests__/HomePage.test.tsx`
- `frontend/src/pages/__tests__/ConsolePage.test.tsx`, only if route expectations need to match the rewritten homepage

Do not modify console feature components.

Do not modify backend code.

Do not add new dependencies for this redesign.

Do not use `assets/agent-orchestration-architecture.svg`.

## Verification Plan

Run:

- `npm --prefix frontend run build`
- `npm --prefix frontend run test -- --run`

Preview on a port other than `5173`, such as `5174`.

Use browser screenshots or Playwright checks for:

- Desktop first viewport: clean centered hero, CTAs, one delivery-flow visual, and a visible hint of the next section.
- Mobile first viewport at 390px and 320px: no text overlap, no page-level horizontal overflow, header remains usable.
- The delivery-flow image loads.
- The architecture diagram is not referenced.
- `/console` remains reachable.
