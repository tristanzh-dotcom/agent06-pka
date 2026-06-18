# PKA Org-Chart Retrieval Disambiguation SDD

Date: 2026-06-18

## Goal

Org-chart retrieval must choose evidence by the user's structural intent, not by a single global page preference.

## Decision

1. Anchored-chain queries prefer the named ancestor chain.
   - Examples: `Marcus 下面负责中国的是谁`, `who leads China under him`, `who does Marcus report to`.
   - Expected behavior: keep the page containing the explicit named anchor before unrelated detailed pages.
   - Reason: the user is asking within a specific hierarchy, so cross-page detail charts can contaminate the answer.

2. Unanchored entity/team queries prefer the detailed page.
   - Examples: `Who is responsible for Jim Morgan?`, `Who leads Vehicle Connected & Data Platform?`.
   - Expected behavior: allow the detailed context page to rank before the global overview if it directly contains the queried entity/team.
   - Reason: without an ancestor anchor, the detailed chart is usually the highest-quality evidence for that entity or function.

3. Function words must never become focus tokens.
   - Examples: `and`, `structurally`, `report`, `under`, `who`, `what`.
   - Expected behavior: these words must not expand focus pages, because they appear across many org-chart chunks and collapse disambiguation.

## Acceptance Criteria

- Marcus global-site questions return the Page 2 first-line structure before APAC/I&C detail pages.
- English variants using `leads`, `report to`, and `structurally under` trigger org-chart relation handling.
- Unanchored detailed queries can return detailed pages first when those pages directly match the queried entity/team.
- Regression tests cover both anchored and unanchored behavior.
