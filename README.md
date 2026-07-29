# Football Matchmaking Bot

Greenfield Telegram product for turning consent-covered football posts into
normalized opportunities with model-assisted classification and recommending
relevant results to users.

The current PoC ingests every observable message from each enabled Source Chat
and performs bounded model classification through Codex CLI authenticated with
ChatGPT-managed Codex access. A durable application worker, not Codex, owns
Telegram state and the job queue.

## Project documents

- [Delivery roadmap](docs/product/roadmap.md)
- [Language onboarding](docs/product/language-onboarding.md)
- [Conversational onboarding](docs/product/onboarding-flow.md)
- [Location resolution](docs/product/location-resolution.md)
- [Search-direction taxonomy](docs/product/search-direction-taxonomy.md)
- [Opportunity fields and discovery details](docs/product/opportunity-fields-and-discovery-details.md)
- [Source Message classification pipeline](docs/product/classification-pipeline.md)
- [Source Chat consent basis](docs/product/source-consent.md)
- [Proposed repository structure](docs/product/repository-structure.md)
- [Architecture decisions](docs/adr/)
- [Agent workflow](AGENTS.md)

Product terminology and durable decisions are created through `grill-with-docs` as they are resolved.
