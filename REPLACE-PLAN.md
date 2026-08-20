# REPLACE-PLAN — what changes in this repo

Phase 0. No code changed yet. Awaiting approval.

## The brief's demolition phase does not apply here

The brief assumes the existing console is a different, older design being
rip-and-replaced. That is not the situation. This console was **built from this
same reference** over the preceding sessions, using our own tokens because you
asked for that explicitly:

> "make sure the ui ux same but for the font and colors use the current code ones"

It is 7,996 lines, wired to real endpoints, with no mocks and no dead controls,
covered by 2,677 backend and 385 frontend tests. Rule 7 ("no blending old with
new") is aimed at two design systems coexisting — there is only one here.

**So there is nothing to demolish, and Phase 1 should be skipped.** Deleting and
rebuilding would discard working, tested code to fix problems you have not
reported; everything you have raised recently has been a specific defect, each
of which was found and fixed. If you disagree, say so and I will delete as
instructed — but I am not going to do it silently.

What follows is therefore a **modify plan**, not a delete plan.

## KEEP — everything, with changes in place

| Area | Files | Why |
|---|---|---|
| Views | `views/platform/*.vue` (11) | Already the reference's information architecture; gaps closed per page in Phase 4 |
| Layout | `layouts/PlatformLayout.vue` | Nav order/grouping already matches the live demo |
| Primitives | `components/platform/ui/*.vue` (7) | Pf* components are this console's design system |
| Dialogs | `PfApplyChangesDialog.vue`, `TranscriptModal.vue` | Both wired and tested |
| Styles | `assets/styles/platform.css` | See scoping note below |
| Data | `services/platform.ts` | Real endpoints, no mocks |
| Backend | `api/platform_*.py`, `core/platform_auth.py`, `services/features.py`, `services/platform_ai.py` | Console API and its guard |

## DELETE — nothing

No file in the console area is superseded, duplicated, or orphaned.

## Shared files both areas touch

Rule 8 says out-of-scope pages must not change. Current state and plan:

| File | Shared with tenant app? | Plan |
|---|---|---|
| `assets/styles/platform.css` | **No** — every rule is scoped under `.pf-shell` | Extend in place. Already safe by construction. |
| `assets/styles/design-tokens.css` | **Yes** — `:root` tokens used app-wide | **Do not redefine existing tokens.** Any new token gets a `--pf-` prefix. |
| `router/index.ts` | Yes | `/platform` children only; no other route touched |
| `components/layout/navItems.ts` | Yes | Console link only |

One caveat worth stating: the apply-changes dialog teleports to `<body>`, i.e.
outside `.pf-shell`, so its rules are necessarily unscoped. They are namespaced
`.pf-modal*` and were the source of a real bug already (unstyled button,
invisible label). Any further teleported component must carry its own styles.

## Feature-parity map

| Reference | Ours | Status |
|---|---|---|
| Overview | `OverviewView.vue` | Present |
| Organizations + detail | `OrganizationsView` / `OrganizationDetailView` | Present, 8 detail tabs |
| Users | `UsersView.vue` | Present |
| Plans & Limits | `PlansView.vue` | Present; edit + apply-policy working |
| Billing | `BillingView.vue` | **Setup state only — real gap** |
| System Health | `HealthView.vue` | Present |
| Audit Logs | `AuditView.vue` | Present |
| Analytics dashboard | `AnalyticsView.vue` | Present |
| Analytics: knowledge, costs | — | **Missing (previews 12, 13)** |
| AI Configuration | `AIConfigView.vue` | Present (ported from live demo) |
| Backups | `BackupsView.vue` | Ours only; setup state pending S3 config |
| Support mode | — | **Reference preview is broken; needs your decision** |

## Dependencies

- **Added by this port:** none. No Tailwind, no React, no icon library — the
  approved approach is hand-porting into the existing Vue stack.
- **Unused after this port:** none, since nothing is deleted.

## Branch

The brief asks for `super-admin-ui-replacement`. Given this is a modify rather
than a replace, I propose `console-visual-parity`. Current work is committed on
`main` and pushed, so the present state is recoverable either way.

## Still outstanding from earlier work

Not part of this port, but unfinished and worth not losing:

- **`META_APP_SECRET`** is still `PASTE_YOUR_APP_SECRET_HERE`. WhatsApp and
  Messenger cannot receive messages until the real 32-hex-character secret is in
  `.env`. Everything else on that path is verified working (callback URL,
  handshake 200/403, credentials valid).
