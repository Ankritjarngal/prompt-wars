# Decisions

These are settled. Do not reopen them without adding a new dated row.

| Date | Decision | Why |
| --- | --- | --- |
| 2026-10-28 | Build local-only. No Render or Vercel work in this pass. | The event can run on one laptop. Hosting can be added later without changing the app shape. |
| 2026-10-28 | Stack is FastAPI, SQLite, and server-rendered pages with plain JS. No Node build. | One process on one laptop. Phones on the LAN just open a URL. |
| 2026-10-28 | Round score is the **sum** of the three counting scores, 0–300. | Chosen over an average. Each image still scores 0–100 before the sum. |
| 2026-10-28 | All 3 images are visible at once. A score shows as soon as that upload is scored. | Players can use either slot on any image until both slots are filled or time runs out. |
| 2026-10-28 | Two slots per image. A filled slot cannot be replaced. The higher score counts. If the two scores tie, the earlier upload counts. | "Best one counts." A failed score deletes that slot so the player can try again. A corrupt file is rejected before the slot is taken. |
| 2026-10-28 | A missing image counts as 0. | Someone who skips an image is still ranked. |
| 2026-10-28 | Rank order is: higher round total, then higher sum of raw LPIPS similarity on the counting uploads, then earlier timestamp of the latest counting upload, then entry code. | The brief's tie-break (LPIPS, then earlier time) adapted to three images. Entry code makes the order deterministic. |
| 2026-10-28 | Players see their own total and rank. The admin page is the room leaderboard. | The brief separates the player result from the admin board. |
| 2026-10-28 | Admin uses a username and password from `.env`, on `/admin`. That is not an entry code. | Players must not land in the control panel by guessing a code. |
| 2026-10-28 | One active player session per code. A new login replaces the old token. | Stops one code being used on two phones at once. |
| 2026-10-28 | Round 1 is open to every entry code. A later round is open only to people the admin confirmed from the previous round. | Everyone logs in first. Advancement is a gate, not a new account. |
| 2026-10-28 | Ending a round only **proposes** the top N. Nothing advances until the admin confirms. The admin can check and uncheck any people, including several at once. | Covers cheaters, no-shows, and pulling people up from below the cut. |
| 2026-10-28 | Editing the advance checkboxes clears the confirmed flag. The next round cannot be activated until they confirm again. | A half-edited list must not count as final. |
| 2026-10-28 | The advance list locks when the **next** round is activated. | After the next round starts, the previous cut must not change underneath it. |
| 2026-10-28 | This build cannot activate Round 2 or Round 3. Their cards still store cut size, notes, and files, and Round 2 shows who Round 1 confirmed. | The gate is real for the next agent. The attempt pages do not exist yet, so going live would show a broken task. |
| 2026-10-28 | Adding minutes while the round is live moves the end time forward. Scores stay. | The usual "we need more time" case. |
| 2026-10-28 | Adding minutes after the round has ended reopens it, keeps scores, and clears the unfrozen advance list. | The result is no longer final. Confirmed names go back to proposed. |
| 2026-10-28 | Extend and restart are refused once this round's advance list is frozen. | Round 2 would already be using that list. Undo the later round first. |
| 2026-10-28 | Restart requires the admin to type `RESTART`. It deletes that round's uploads and scores, returns the round to draft, and clears its advance list. Entry codes and reference images stay. | Worst-case recovery. Reference images stay so they do not have to be uploaded again unless they were the problem. |
| 2026-10-28 | Reference images can be replaced only while the round is in draft. | Changing an image under existing scores would make those scores meaningless. Replace, then activate. To change images after a start, restart first. |
| 2026-10-28 | Copy checks flag an upload and still count it until an admin voids that slot. The player is not told. | A false positive must not zero someone during the round. Voiding drops that slot. The other slot counts, or the image contributes 0. |
| 2026-10-28 | Voiding does not rewrite the advance checkboxes. The admin presses "Suggest top N" to rebuild the suggestion from the new ranking. | The admin may already have customized the list. An automatic rewrite would erase that. |
| 2026-10-28 | Each upload may include a prompt note, up to 2000 characters. It is stored and not scored. | The brief asks for the prompt when the top submissions are reviewed by hand. |
| 2026-10-28 | Images are resized to 224×224 bicubic for scoring, not 256. | DINOv2 ViT-S/14 needs a side divisible by 14. The brief's 256 was an example. |
| 2026-10-28 | Weights are LPIPS Alex 50%, SSIM 30%, DINOv2 ViT-S/14 20%, each scaled between a per-image floor and ceiling, then summed to 0–100. | From the organizer brief. Alex is the smaller LPIPS network so a laptop CPU can keep up. |
| 2026-10-28 | Ceiling is the reference scored against itself. Floor is the worse of a blank gray image and a noise image seeded with 0. | Seeded noise keeps calibration repeatable. "Worse" means the lower raw similarity. |
| 2026-10-28 | Scoring runs on CPU in fp32, one upload at a time, models loaded at startup. An upload accepted before the deadline is still scored if the clock hits zero while it waits. | Deterministic and fair. The first upload should not pay the model-load cost. |
| 2026-10-28 | The original upload bytes are stored. The server does not re-encode the reference. | Exact-file copy detection has to compare the bytes the player could have saved from the page. |
| 2026-10-28 | Near-copy perceptual hash is `imagehash.phash` (size 8) with Hamming distance 8 or less. SSIM flag is raw SSIM above 0.95. | The brief said "near-identical hash" and "SSIM above 0.95" but did not give a hash distance. 8 is wide enough to catch a screenshot, and void is manual. |
| 2026-10-28 | Tests and the UI can run with `SKIP_MODELS=1`, which uses a fake scorer. Real LPIPS and DINOv2 live in `requirements-scoring.txt`. | Torch is a large install. Game rules must be testable without downloading model weights. Event day installs both requirement files. |
| 2026-10-28 | Entry codes use `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`, 8 characters. | Avoids 0/O and 1/I on a printed slip. |
| 2026-10-28 | Admin actions are appended to a log the panel shows. | If something is changed mid-event, there is a record of who did what from this app. |
| 2026-10-28 | The repo is private. | It will hold the shape of an event tool. Entry codes and `.env` still must not be committed. `data/` is gitignored. |
| 2026-10-28 | Cut size is a number the admin types, default 30 / 10 / 3, allowed range 1–1000. It is not tied to 50 players. | A room of 55 or 60 uses the same app. Generate that many codes, then set how many advance. |
| 2026-10-28 | Stress tests run on the laptop against the real HTTP app with the fake scorer. No cloud deploy for this pass. | Sixty sequential players and sixty parallel uploads finish locally in a few seconds. A free host that sleeps would make that test less honest, and the real models still belong on the event machine. |
