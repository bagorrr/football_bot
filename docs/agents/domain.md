# Domain Docs

This repository initially uses a single-context domain-documentation layout.

## Before exploring

Read the following when they exist:

- `CONTEXT.md` at the repository root;
- relevant ADRs under `docs/adr/`.

If these files do not exist yet, proceed silently. Do not create empty domain documentation pre-emptively.

`grill-with-docs` and `domain-modeling` create and update them when terminology or durable decisions are actually resolved.

## Layout

```text
/
├── CONTEXT.md
├── docs/
│   └── adr/
└── apps/
```

`CONTEXT.md` contains the shared domain language and distinctions that agents need repeatedly.

`docs/adr/` contains hard-to-reverse or cross-cutting decisions, including their context, chosen option, rejected alternatives, and consequences.

## Use the glossary vocabulary

When code, tests, issues, or specifications name a domain concept, use the term defined in `CONTEXT.md`.

Do not introduce synonyms for established concepts. If an important concept is missing or overloaded, resolve it through `domain-modeling`.

## Flag ADR conflicts

If proposed work contradicts an existing ADR, identify the conflict explicitly rather than silently overriding the earlier decision.

## Evolution to multiple contexts

Do not create per-application `CONTEXT.md` files merely because the repository contains several deployables.

Move to a multi-context layout only after stable domain boundaries emerge. At that point:

- create a root `CONTEXT-MAP.md`;
- keep system-wide ADRs under `docs/adr/`;
- place context-specific `CONTEXT.md` and ADRs beside the corresponding context.
