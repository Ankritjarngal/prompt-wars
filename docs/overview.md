# Overview

Prompt Wars is a 2–3 hour, three-round prompting event for about 50 people. Scores are computed by code. There is no paid AI API and no human judge during play. People use their own free chatbot and image tools. This app only collects entries and scores them.

Cuts are 50 → 30 → 10 → top 3. Scores reset in spirit after each round: only the confirmed advance list carries forward. The organizer brief (27 Oct 2026) is the background. This repo follows that brief except where [decisions.md](decisions.md) records a change.

## What this repo builds

A single Python app that runs on the event laptop and is reachable on the local network.

- Entry-code login for players, one active session per code.
- A separate admin login and a full control panel.
- Round 1, Image Wars, fully playable.
- Round 2 and Round 3 present in the admin panel so their cut size, notes, and files can be stored, and so the advance gate exists. Their attempt pages and scorers are not built.

## Round 1 in one paragraph

When an admin activates Image Wars, every logged-in player sees the same 3 reference images. Each image has 2 upload slots. Each upload is scored immediately and the score is shown on that slot. The better slot counts for that image. The person's round score is the sum of the three counting scores, from 0 to 300. At the end, the top of the ranking is proposed as the people who advance. The admin can add or remove people, then confirm. Only the confirmed list can enter the next round.

## What is deliberately not in this build

- Round 2 cipher puzzles and the answer checker
- Round 3 dataset, JSON scoring, and chat-only prompt task
- Deployment to Render, Vercel, or any other host
- A public player leaderboard (players see only their own score and rank)
- Automatic disqualification

Deployment can happen later by running this same process on an always-on machine. Do not rewrite it as a serverless app. The scorer loads PyTorch models and keeps one score queue in memory. Vercel cannot do that. Free hosts that sleep or wipe the disk are a bad fit for event day. This build does not add that deploy path.
