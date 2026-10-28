# Admin panel

The admin signs in at `/admin` with `ADMIN_USERNAME` and `ADMIN_PASSWORD` from `.env`. A successful login sets an httpOnly cookie named `pw_admin`. It does not use the player session. Opening `/admin` never shows the player attempt page.

The panel is the only place that changes the event. Players cannot set images, change the clock, or decide who advances.

## Privileges

The admin can:

1. Generate entry codes, any count from 1 to 200 at a time. Codes already created stay. The panel lists every code so they can be copied onto slips. Generating codes does not start a round.
2. Set Round 1's three reference images by uploading a PNG or JPG into slot 1, 2, or 3. Replacing a slot is allowed only in draft. The stored file is the original bytes.
3. Set each round's duration in minutes and its cut size. Round 1 defaults are 40 minutes and a cut of 30. Round 2 defaults are 50 minutes and 10. Round 3 defaults are 20 minutes and 3.
4. Edit a free-text note on each round.
5. Upload and delete material files on Round 2 and Round 3 (puzzle sheets, datasets, anything the later rounds will need). These files are storage only. Nothing reads them as a game yet.
6. Activate Round 1 when all 3 reference images are set and no other round is live. Activate stores the server start and end time (`now + duration`) and reveals the images to players.
7. Add 1 to 180 minutes. During a live round this pushes the end time forward and leaves scores in place. After the round has ended, and before the advance list is frozen, this reopens the round, keeps scores, and clears the advance list.
8. End the round early. If the clock expires first, the server ends it the same way. Uploads lock. The top N people by the rank rules are pre-checked. The list is not confirmed yet.
9. Void one submission slot. The slot stops counting. Rank updates. The advance checkboxes do not change until the admin clicks **Suggest top N**.
10. Open a flagged upload next to its reference. Flags are `exact copy`, `near copy`, and `ssim`. See [scoring.md](scoring.md).
11. Click **Suggest top N** to re-check the current top of the ranking. This replaces the checkbox selection and clears the confirmed flag.
12. Check or uncheck any participants, including many at once, then save that selection. Saving also clears the confirmed flag.
13. Confirm advancement. That writes the checked people as the only list allowed into the next round. Confirm is allowed with any number of people, including more than the cut size.
14. Change that list again until the next round is activated. Any edit requires a new confirm.
15. Restart Round 1 by typing `RESTART`. This deletes Round 1 uploads and scores, clears its advance list, and returns it to draft. Codes, notes, material files, and the three reference images stay.
16. Export a CSV of the Round 1 ranking, per-image scores, flags, voids, and whether that person is currently checked to advance.
17. Read the action log. The log records activate, extend, end, auto-end, void, suggest, selection changes, confirm, restart, code generation, image replacement, and settings changes.

The admin cannot:

- Activate Round 2 or Round 3 in this build. The button is absent and the API returns an error. Play for those rounds is not implemented.
- Edit the advance list, extend, or restart a round whose advance list is frozen.
- Replace Round 1 images while that round is live or ended. Restart first, which returns it to draft.
- Delete entry codes in this build. Generate the right number before the event. Unused codes are harmless.
- Auto-disqualify a flagged upload. Void is the removal tool, and it is one slot at a time.

## Round lifecycle

A round is `draft`, `live`, or `ended`. Only one round may be live.

```text
draft --activate--> live --end or clock--> ended
  ^                   |                      |
  |                   | add minutes          | add minutes (if not frozen)
  |                   v                      v
  |                 live                   live
  |
  +---- type RESTART, from live or ended, if not frozen
```

Ending a round:

- Sets status to `ended`.
- Inserts every participant into the advance list for this round, with the top `cut_size` checked and everyone else unchecked.
- Leaves `advancement_confirmed` at 0.

Confirming:

- Sets `advancement_confirmed` to 1.
- Does not start the next round.
- Players then see either that they advanced or that they did not. See [player-flow.md](player-flow.md).

Freezing:

- Happens when the next round is activated.
- This build never activates Round 2, so a Round 1 list will not freeze until a later version adds that activate path. The column and the checks still exist so that path cannot forget the lock.
- While frozen, the checkbox list is read-only, and extend/restart of the earlier round are rejected.

## Suggested event-day sequence

1. Generate codes and hand them out.
2. Upload the 3 real reference images while Round 1 is draft.
3. Check duration and cut size.
4. Activate when the room is ready.
5. Watch the board. Void copy flags if a review says so, then press Suggest top N if the checked names should follow the new rank.
6. Add minutes if the room needs them.
7. End the round, adjust the checkboxes, confirm.
8. Use Restart only when the round itself should be thrown away.
