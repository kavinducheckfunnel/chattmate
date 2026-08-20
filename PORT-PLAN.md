# PORT-PLAN — super-admin-ui → ChatterMate console

Phase 0 inventory. No app code written. Awaiting approval before Phase 1.

## 1. What the reference actually is

Read from `https://github.com/DeemalV/super-admin-ui` (branch `main`) over the
GitHub API — **`reference-ui/` was never cloned locally**, so the clone step in
the brief did not run.

| | Reference | This project |
|---|---|---|
| Framework | Next.js 15 / **React 19.2.6** | **Vue 3.5.13** |
| Styling | **Tailwind 4.2.1** + `app/globals.css` | Custom CSS tokens, **no Tailwind** |
| Build | Vite 8.0.13 | Vite 6.0.5 |
| TypeScript | 5.9.3 | 5.6.3 |
| Dependencies | 26 | 66 |

The whole reference UI is **one file**: `app/page.tsx`, 1039 lines. There is no
component library, no router, no data layer — `app/layout.tsx` and
`app/globals.css` are the only other source files. `db/`, `worker/` and
`drizzle/` are scaffolding from the starter template and are not used by the UI.

**Consequence for the brief's hard rules.** Rules 2 ("copy the file, adapt
imports only"), 3 ("identical class strings"), and 4 ("match the reference's
package.json") cannot be satisfied literally: a React file cannot be dropped
into a Vue app, and the class strings are Tailwind utilities that do not exist
here. Adding Tailwind globally would also violate rule 8, which forbids
affecting out-of-scope pages. **Approved approach: keep Vue, close the visual
gaps by hand, screen by screen.**

## 2. The design previews are the usable reference

`design-previews/` holds 13 PNGs. These are more useful than the Tailwind
classes, because they show the intended result rather than the mechanism.

| Preview | Maps to our view | Notes |
|---|---|---|
| 01-overview | `OverviewView.vue` | |
| 02-organizations | `OrganizationsView.vue` | |
| 03-organization-details | `OrganizationDetailView.vue` | |
| 04-support-mode | — | **Broken preview**: renders an empty sidebar fragment only. No usable design, and no equivalent page exists here. Flagged for your decision (rule 9). |
| 05-plans-limits | `PlansView.vue` | |
| 06-users | `UsersView.vue` | |
| 07-billing | `BillingView.vue` | **Largest functional gap — see §4** |
| 08-system-health | `HealthView.vue` | |
| 09-audit-logs | `AuditView.vue` | |
| 10-mobile-overview | `OverviewView.vue` @ 375px | |
| 11-analytics-dashboard | `AnalyticsView.vue` | |
| 12-analytics-knowledge(-cost) | `AnalyticsView.vue` | Sub-view; we have no equivalent tab |
| 13-analytics-costs | `AnalyticsView.vue` | Sub-view; we have no equivalent tab |

**The previews are stale.** `07-billing.png` shows a 7-item nav (Overview,
Organizations, Users, Plans & Limits, Billing / System Health, Audit Logs). The
live demo screenshots you sent show 9 items, including AI Configuration,
Analytics and Backups. So `page.tsx` has moved on since the PNGs were taken.
**Where they disagree, I will follow the live demo and your screenshots, not the
PNGs.** Confirm that is what you want.

Also: the previews are **light-themed**; our deployment currently renders dark.
Both support both themes, so this is a theme setting rather than drift — but it
means a naive side-by-side will look far more different than it is.

## 3. Our current console (the thing being closed against)

7,996 lines across:

- **Views (11)** — `views/platform/`: Overview, Organizations, OrganizationDetail,
  Users, Plans, AIConfig, Billing, Analytics, Health, Backups, Audit
- **Layout** — `layouts/PlatformLayout.vue`
- **Components (9)** — `components/platform/`: PfApplyChangesDialog,
  TranscriptModal, platformIcons.ts, and `ui/`: PfBars, PfDonut, PfMetric,
  PfPage, PfPill, PfProgress, PfRing
- **Styles** — `assets/styles/platform.css`, every rule scoped under `.pf-shell`
- **Data** — `services/platform.ts` against real endpoints. **No mocks anywhere.**

## 4. Known gaps, by page

Per your answer, both functional and visual work is needed. What I already know:

| Page | Functional gap | Visual gap |
|---|---|---|
| Billing | **Largest.** Reference shows 4 stat cards (MRR, active subscriptions, upcoming renewals, failed payments) and a "Recent subscriptions" table with Export CSV and a per-row menu. Ours shows a Stripe setup state instead. Needs real endpoints. | Full page |
| Analytics | Reference has knowledge and cost sub-views (previews 12, 13); we have neither | Sub-navigation missing |
| Plans & Limits | Recently fixed (edit/save works, values persist) | Diff still to do |
| Overview / Organizations / Users / Health / Audit | To be assessed per page in Phase 4 | To be assessed |
| AI Configuration | Built to the live demo; ported already | Diff still to do |
| Backups | Shows a setup state — needs an S3 endpoint/bucket/key | — |

## 5. Data layer

Real backend, already wired: `frontend/src/services/platform.ts` →
`/api/v1/platform/*`, session-cookie auth, guarded by `require_platform_admin`
(404 not 403, so the console's existence is not disclosed). Backend suite:
2677 passing. Frontend: 385 passing.

No mock layer is needed or wanted. Where the reference shows data we do not yet
serve (billing being the main case), the work is a **new endpoint**, not a mock.

## 6. What I need from you before Phase 1

1. **Stale previews** — confirm the live demo wins over the PNGs where they differ.
2. **`04-support-mode`** — the preview is broken and we have no such page. Drop it,
   or describe what it should do?
3. **Analytics sub-views** (knowledge, costs) — build these, or leave Analytics as is?
4. **Billing** — it needs a real data source. Stripe (needs keys), or derive from
   our own `plans` + `organizations` tables (no keys, but no real payment status)?
5. **Page order for Phase 4** — the brief asks for one page per turn. Proposed:
   Billing → Analytics → Overview → Organizations → Users → Plans → Health → Audit.
