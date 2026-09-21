# RES-108 fixed-viewport evidence

Captured by Playwright at **1600×1000** against deterministic representative app flows on
2026-09-21. The files are intentionally kept outside `apps/web/test-results/` so the review
set is stable and directly inspectable.

1. [Catalog landing](../../output/playwright/res-108/01-catalog.png)
2. [Session Overview](../../output/playwright/res-108/02-session-overview.png)
3. [Signals](../../output/playwright/res-108/03-signals.png)
4. [Field](../../output/playwright/res-108/04-field.png)
5. [Pose](../../output/playwright/res-108/05-pose.png)
6. [Compare](../../output/playwright/res-108/06-compare.png)
7. [Method / Provenance](../../output/playwright/res-108/07-method-provenance.png)
8. [Quality](../../output/playwright/res-108/08-quality.png)
9. [Runs](../../output/playwright/res-108/09-runs.png)

Browser-console inspection ran as part of the renderer smoke and visual suites. No page errors
or console errors were observed; the R3F route emits the known upstream `THREE.Clock` deprecation
warning from the installed renderer dependency.
