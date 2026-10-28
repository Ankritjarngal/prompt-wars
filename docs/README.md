# Prompt Wars docs

Start here. These notes are the source of truth for the event app. They record what was agreed in planning, plus the implementation decisions made while building it. If chat history and this folder disagree, follow this folder.

The app is a local Round 1 site for a live event called Prompt Wars. Later rounds have a place in the admin panel, and their play pages are not built.

## Read in this order

1. [overview.md](overview.md) — what the event is and what this repo is for
2. [decisions.md](decisions.md) — choices that are already made, and why
3. [admin-panel.md](admin-panel.md) — every admin privilege and the round lifecycle
4. [player-flow.md](player-flow.md) — what a participant sees and when they are allowed in
5. [scoring.md](scoring.md) — Round 1 score, tie-breaks, calibration, copy flags
6. [architecture.md](architecture.md) — stack, data model, HTTP API, file layout
7. [status.md](status.md) — what is actually in the repo right now

## How to keep these docs honest

When a behavior changes, update the relevant doc and add a row to [decisions.md](decisions.md). Update [status.md](status.md) at the end of each core step so the next person can see what is done.
