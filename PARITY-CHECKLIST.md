# Console parity checklist — page by page, section by section

Every row below was extracted from the reference source
(`reference-ui/app/page.tsx`, 1039 lines) — not from the screenshots, and not
guessed. Line ranges are the exact component boundaries.

**Status key:** `[ ]` not started · `[~]` partial · `[x]` done & verified in browser

---

## Done already (foundation)

- [x] **Stylesheet ported** — all 1,672 rules, all 71 media blocks, scoped under
      `.pf-shell`, colours mapped to tokens. Live on the VPS.
- [x] **Nav** — 10 items, correct order, correct grouping (PLATFORM ×7 / SYSTEM ×3),
      badge on Organizations, live dot on System Health, label
      "Backups & Recovery".
- [x] **Billing data layer** — `/platform/billing` returns real plan prices,
      tenant counts, usage and projected AI cost.

---

## 1. Overview — `Overview` (lines 103–162) — **DONE**

- [x] 4 × `MetricCard` — Organizations · Active users · Monthly revenue · Messages used
- [x] **Revenue overview** — `Last 6 months⌄`
- [x] **Plan distribution** — donut + legend
- [x] **Recent organizations** — `View all →`, row click through
- [x] **Platform usage** — two rings, backed by real allowance data
- [x] `↗ Export report` writes real CSV
- [x] Verified in browser: 16/16 text checks, 0 console errors

## 2. Organizations — `Organizations` (lines 163–214) — **DONE**

- [x] Columns exactly: Organization · Email · Plan · Status · Messages · Joined
- [x] Email as a `mailto:` link, click-through suppressed on the row
- [x] Messages reads "used / allowed"; count alone on an unlimited plan
- [x] `＋ Add organization` moved into the toolbar, where the reference has it
- [x] Row menu: `↗ View details` / `⌫ Remove organization`
- [x] Search + plan/status filters, `Clear filters`
- [x] "Showing N of M organizations · filters applied"
- [x] Verified in browser: filter 6 → 4 rows, 6 mailto links, 0 console errors

## 3. Organization detail — `OrganizationDetail` (215–323) — **DONE**

- [x] Tabs exactly: Overview · Members · Chats · Features · Usage · Billing · Audit
      (Knowledge and Integrations appended — real features the reference lacks)
- [x] Header: `Suspend` + `Enter support mode`
- [x] Aside: **Account health** and **Quick admin actions** with the reference's
      four tiles — Manage subscription · Manage members · Support mode ·
      Suspend account
- [x] Billing tab added (plan, next invoice, payment method)
- [x] Verified in browser: all 7 tabs render, 0 console errors

## 4. Plans & Limits — `Plans` (lines 328–388)

- [x] **Plan limits** panel — `✎ Edit limits` → `Cancel` / `Save limits`
- [x] Apply dialog — `×` / `Back to editing` / `Confirm & save changes`
- [x] `Edit plan limits` per plan card
- [ ] **Complete feature availability** panel — `✎ Edit features` → `Save features`
- [ ] Columns: Limit · Free · Base · Pro *(ours has 4 tiers incl. Scale — keep ours, real data)*
- [ ] Integration picker modal — `×`

## 5. Users — `Users` (lines 389–459)

- [ ] Columns: User · Organization · Role · Status · Last active
- [ ] `＋ Add user` → modal (3 inputs, 5 selects) → `Add user` / `Cancel` / `×`
- [ ] Remove flow → confirm → `Remove user` / `Cancel` / `×`
- [ ] Filters + search + sort + pagination

## 6. AI Configuration — `SimpleAIConfiguration` (lines 570–628)

Note: the repo has a second, richer `AIConfiguration` (524–569) that is **not
wired up**. `SimpleAIConfiguration` is what the app renders.

- [x] **AI model setup** panel — 3 numbered steps
- [x] Text / Image provider + model selects, `Update key`
- [x] Fallback toggle + model
- [x] Routing summary strip
- [ ] Verify against reference at 1440 and 375

## 7. Billing — `Billing` (lines 629–733)

- [x] Data layer (real)
- [ ] Period bar — period select + custom date range (2 inputs)
- [ ] Finance overview — MRR card · API reserve card · quick stats
- [ ] **Revenue trend** — bars + `$3k/$2k/$1k/$0` scale + legend + footer
- [ ] **Customer plan mix** — donut + legend + paid conversion
- [ ] **AI cost monitor** — conic gauge + provider list + reserve status
- [ ] **Plan performance** — Plan · Customers · MRR · Messages used · Usage · Est. AI cost + totals row
- [ ] **Monthly revenue allocation** — breakdown + "not deducted here" note
- [ ] **Message capacity** + **Sales health**
- [ ] **Customer subscriptions** — Organization · Plan · Seats · Monthly revenue · Messages · Est. AI cost · Renewal · Status
- [ ] `Export CSV`, `＋ Create invoice`, footer pagination

## 8. Analytics — `Analytics` (lines 734–810)

- [ ] Filter panel (1 input, 3 selects) + `Clear filters`
- [ ] KPI row
- [ ] **Conversation volume** · **Channel mix** · **Resolution outcomes**
- [ ] **Plan utilization** · **Top organizations** · **AI usage & estimated cost**
- [ ] `View all →`

## 9. System Health — `Health` (lines 811–815)

Only 5 lines in the reference — it is a thin page.

- [ ] **All core systems operational** banner
- [ ] **Recent incidents** panel

## 10. Backups & Recovery — `OneDriveBackups` (lines 916–990)

The app renders `OneDriveBackups`; `Backups` and `SimpleBackups` exist but are
unused.

- [ ] **Download to local computer**
- [ ] **Microsoft OneDrive connection** — `Connect & test` / `Disconnect`
- [ ] **OneDrive backup schedule** (9 inputs, 4 selects)
- [ ] **OneDrive backup history** — Created · Method · Contents · Destination · Size · Status
- [ ] `Run backup now`

## 11. Audit Logs — `Audit` (lines 991–1005)

- [ ] Search input
- [ ] `All actions⌄` and `Last 30 days⌄` filters
- [ ] `Export`

---

## Cross-cutting (applies to every page)

- [ ] Filters combine AND across fields, OR within a field
- [ ] Filter state in URL query params
- [ ] Search debounced ~300ms, resets to page 1
- [ ] Sort cycles asc → desc → none with correct indicator
- [ ] Pagination: prev/next disabled states, accurate "Showing X–Y of Z"
- [ ] Row selection: individual, select-all, indeterminate header
- [ ] Modals: Escape, overlay click, `×`, focus trap, scroll lock
- [ ] Four states everywhere: loading skeleton · empty · error+retry · populated
- [ ] "No data yet" distinct from "no results for these filters"
- [ ] Responsive at 375 / 768 / 1024 / 1440
- [ ] Light and dark both correct
- [ ] Keyboard: tab order, focus rings, Enter/Space, arrows in menus

## Deliberate differences (flagged, not accidental)

| Reference | Ours | Why |
|---|---|---|
| Hardcoded light-theme hexes | Mapped to tokens | Reference is light-only; this product ships both themes |
| 3 plans (Free/Base/Pro) | 4 (Free/Starter/Pro/Scale) | Ours is the real catalog |
| `48` organizations, mock rows | Real counts from the database | No mocks — your rule |
| Payment status "Paid"/"Past due" | "Unbilled" / "Free" | No payment processor connected; "Paid" would be invented |
| `Enter support mode` | Not built | Reference preview is broken and there is no backend for it |

## Still blocking (unrelated to this port)

- **`META_APP_SECRET`** is still `PASTE_YOUR_APP_SECRET_HERE` — WhatsApp and
  Messenger cannot receive messages until the real 32-hex secret is in `.env`.
- **`pro` price is 14901 cents**, not 14900. Audit log shows an earlier save of
  mine did it. Harmless, but I want the cause before touching prices again.
