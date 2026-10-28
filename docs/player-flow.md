# Player flow

A player opens `/` and enters an entry code. The server sets an httpOnly cookie named `pw_session`. One code has one token. Logging in on a second browser invalidates the first. The first browser's next request returns to the login screen.

Logging in does not grant a round. It only identifies the person.

Reference images are not sent to the browser until Round 1 is live and this player is allowed to attempt it.

## What they see

The player page polls `GET /api/me` about every 2 seconds.

| Situation | Screen |
| --- | --- |
| No round is live, Round 1 is still draft | Waiting room. "You're in. Waiting for Image Wars to start." |
| Round 1 is live and they are eligible | The attempt. Timer, 3 images, 2 slots each, running total out of 300, own rank. |
| Round 1 is live and they are not eligible | Blocked. They cannot upload. Round 1 eligibility is everyone, so this is for later rounds. |
| Round 1 has ended and the admin has not confirmed | "Round over. Stand by for results." Their total and rank stay visible. Slots are locked. |
| Round 1 has ended, confirm is in, and they are checked | "You advanced. Waiting for the next round." |
| Round 1 has ended, confirm is in, and they are not checked | "You did not advance." |
| A later round is live, they are on its incoming list, but that round has no attempt page | Treated as unavailable. This build does not activate those rounds. |

They never see copy flags, other people's scores, the admin log, or the advance checklist.

## Attempt rules

- The clock on screen is computed from `ends_at` and `server_now` returned by the server. The browser clock is not trusted.
- Each image shows the reference and two slots, Attempt 1 and Attempt 2.
- An empty slot accepts one PNG or JPG up to `MAX_UPLOAD_MB` (default 8), plus an optional prompt note.
- The slot changes to "scoring" immediately. When the worker finishes, the score appears on that slot.
- The counting score for an image is the higher scored, non-voided slot. The card marks which one counts. A tie keeps the earlier upload.
- The header total is the sum of the three counting scores.
- A filled slot cannot be overwritten. The other slot on that image is a separate attempt.
- After both slots are filled, that image accepts nothing else.
- After the server end time, every upload is rejected, including ones already picked in the file dialog.
- A file that is not a readable PNG or JPG is rejected and does not fill the slot.
- If the scorer itself fails, the slot is emptied and the error is shown on that slot so they can submit again.

## Eligibility rule

- Round 1: every participant row is eligible.
- Round N greater than 1: the previous round must have `advancement_confirmed = 1`, and this participant must be checked on that round's advance list.

The player stays logged in either way. The gate only hides the attempt.
