# Issue tracker: GitHub

Issues, specifications, Wayfinder maps, and implementation tickets for this repository live in GitHub Issues. Use the `gh` CLI for tracker operations.

The GitHub repository is `bagorrr/football_bot`; the local `origin` remote points to it.

## Conventions

- Create an issue: `gh issue create --title "..." --body "..."`
- Read an issue: `gh issue view <number> --comments`
- List issues: `gh issue list --state open`
- Comment: `gh issue comment <number> --body "..."`
- Apply a label: `gh issue edit <number> --add-label "..."`
- Remove a label: `gh issue edit <number> --remove-label "..."`
- Close an issue: `gh issue close <number> --comment "..."`

Infer the repository from `git remote -v`; `gh` resolves `bagorrr/football_bot` automatically from the configured remote.

## Pull requests as a triage surface

**PRs as a request surface: no.**

External pull requests are not included in the triage queue unless this flag is explicitly changed later.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.

## Wayfinding operations

The Wayfinder map is a single GitHub issue labelled `wayfinder:map`.

- **Map:** one issue containing Destination, Notes, Decisions so far, Not yet specified, and Out of scope.
- **Decision ticket:** a child issue linked to the map.
- **Ticket types:** `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task`.
- **Claim:** assign the issue before starting work.
- **Blocking:** use GitHub native issue dependencies where available.
- **Fallback blocking:** add `Blocked by: #<number>` to the ticket body.
- **Frontier:** open, unassigned child issues with no open blocker.
- **Resolve:** record the answer in a comment, close the ticket, and add a short linked gist to the map's Decisions so far section.

A Wayfinder ticket records a decision or an investigation result, not an implementation slice.
