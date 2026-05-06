# Website Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the busy first-pass homepage with a cleaner Feishu-inspired brand website that uses a centered hero, one delivery-flow visual, and a small number of ordered sections.

**Architecture:** Keep the console route and app shell behavior unchanged. Implement the home page as semantic React markup in `HomePage.tsx` and page-scoped CSS in `global.css`, with `agent-delivery-flow.svg` used once as the primary product visual.

**Tech Stack:** React 18, React Router, Vite, Vitest, Testing Library, CSS with OKLCH color tokens.

---

### Task 1: Focused Homepage Contract

**Files:**
- Modify: `frontend/src/pages/__tests__/HomePage.test.tsx`
- Modify: `frontend/src/pages/__tests__/ConsolePage.test.tsx`

- [x] **Step 1: Update the homepage test for the revised spec**

Assert the new centered-homepage contract:

```tsx
expect(
  screen.getByRole("heading", {
    level: 1,
    name: /make delivery work traceable/i,
  }),
).toBeTruthy();
expect(screen.getByRole("navigation", { name: /website sections/i })).toBeTruthy();
expect(screen.getByRole("link", { name: "Overview" }).getAttribute("href")).toBe("#overview");
expect(screen.getByRole("link", { name: "Flow" }).getAttribute("href")).toBe("#flow");
expect(screen.getByRole("link", { name: "Control" }).getAttribute("href")).toBe("#control");
expect(screen.getByRole("link", { name: "Start" }).getAttribute("href")).toBe("#start");
expect(screen.getByRole("link", { name: "Docs" }).getAttribute("href")).toContain("github.com");
expect(screen.getAllByRole("img", { name: /ai devflow engine delivery flow/i })).toHaveLength(1);
expect(screen.getByText(/preserve intent/i)).toBeTruthy();
expect(screen.getByText(/human control stays in the workflow/i)).toBeTruthy();
expect(screen.queryByAltText(/orchestration architecture/i)).toBeNull();
```

Update the console route test to expect `Make delivery work traceable.` on the home route.

- [x] **Step 2: Run focused tests and confirm RED**

Run:

```powershell
npm --prefix frontend run test -- --run src/pages/__tests__/HomePage.test.tsx src/pages/__tests__/ConsolePage.test.tsx
```

Expected: FAIL because the current first-pass implementation still has the old `Make requirement-to-delivery work traceable.` headline, repeated flow image, and old section labels.

### Task 2: Simplified Homepage Markup

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx`

- [x] **Step 1: Replace busy page structure**

Implement:

- Home-only website header with `Overview`, `Flow`, `Control`, `Start`, `Docs`, `Open Console`.
- Centered hero with `Make delivery work traceable.`
- One `agent-delivery-flow.svg` figure below hero CTA.
- Overview section with three simple capability columns.
- Flow section with six compact stage steps.
- Control section with one focused text block and inline event row.
- Start section with compact CTA band.

- [x] **Step 2: Run focused tests**

Run:

```powershell
npm --prefix frontend run test -- --run src/pages/__tests__/HomePage.test.tsx src/pages/__tests__/ConsolePage.test.tsx
```

Expected: PASS.

### Task 3: Restrained Feishu-Style CSS

**Files:**
- Modify: `frontend/src/styles/global.css`

- [x] **Step 1: Replace busy homepage styling**

Remove or neutralize the first-pass homepage styling patterns:

- left/right hero split
- dark diagram panels
- repeated stage tile grid
- numbered feature rows
- before/after contrast cards
- decorative brand dot

Add restrained styles:

- near-white background
- compact sticky header
- centered hero
- one light product visual container
- simple three-column overview row
- compact process strip
- clean CTA band
- mobile-first responsive behavior with no page-level horizontal overflow

- [x] **Step 2: Build**

Run:

```powershell
npm --prefix frontend run build
```

Expected: PASS.

### Task 4: Focused Verification And Preview

**Files:**
- No source edits expected.

- [x] **Step 1: Run focused tests only**

Run:

```powershell
npm --prefix frontend run test -- --run src/pages/__tests__/HomePage.test.tsx src/pages/__tests__/ConsolePage.test.tsx
```

Expected: PASS.

- [x] **Step 2: Preview on non-5173 port**

Use the existing `5174` Vite server if it is still running. Otherwise run:

```powershell
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5174
```

- [x] **Step 3: Visual checks**

Use browser screenshots or Playwright checks at 1440px, 390px, and 320px:

- first viewport is clean, centered, and ordered
- only one delivery-flow image is present
- the architecture diagram is absent
- no page-level horizontal overflow
- a hint of the next section is visible in the first viewport
- `/console` remains reachable
