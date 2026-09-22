# Deactivated product surfaces

These frontend pages are preserved verbatim in Next.js private folders. The
underscore prefix excludes each folder and its contents from App Router routing.

| Previous URL | Preserved implementation |
| --- | --- |
| `/portfolio` | `app/_portfolio/page.tsx` |
| `/history` | `app/_history/page.tsx` |
| `/strategy` | `app/_strategy/page.tsx` |
| `/how-it-works` | `app/_how-it-works/page.tsx` |

Pricing was a navigation link to `/#pricing`, not a standalone route or pricing
implementation. Its navigation entry and homepage anchor were removed; the
homepage feature descriptions are retained. `/pricing` is not a registered route.
URL fragments are handled by the browser, so `/#pricing` still loads the homepage
but no longer targets a section.

To restore a page, remove the directory's leading underscore and restore its
navigation entry and any desired CTAs. Directory depth is unchanged, preserving
relative imports. Backend APIs, services, data, shared components and dependencies
remain intact. Portfolio Monitor (`/portfolio-monitor`) remains active.
