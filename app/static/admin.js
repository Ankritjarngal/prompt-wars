const login = document.querySelector("#login");
const panel = document.querySelector("#panel");
const loginError = document.querySelector("#login-error");
const roundsRoot = document.querySelector("#rounds");
let dirty = false;
let built = false;
let listening = false;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  const response = await fetch("/api/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: document.querySelector("#username").value,
      password: document.querySelector("#password").value,
    }),
  });
  const body = await response.json();
  if (!response.ok) {
    loginError.textContent = body.detail || "Login failed";
    return;
  }
  tick();
});

document.querySelector("#make-codes").addEventListener("click", async () => {
  const count = Number(document.querySelector("#code-count").value);
  const response = await fetch("/api/admin/codes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ count }),
  });
  const body = await response.json();
  if (!response.ok) {
    alert(body.detail || "Could not generate codes");
    return;
  }
  tick();
});

function roundCard(round) {
  const lockedImages = round.status !== "draft";
  return `
    <section class="card" data-round="${round.id}">
      <h2>${round.name}</h2>
      <p class="muted">Status: <strong data-status="${round.id}">${round.status}</strong>
        <span data-ends="${round.id}"></span></p>
      <div class="row">
        <label>Minutes <input data-field="duration" type="number" min="1" max="240" value="${round.duration_minutes}" ${round.status === "draft" ? "" : "disabled"}></label>
        <label>People who advance <input data-field="cut" type="number" min="1" max="1000" value="${round.cut_size}" ${round.advancement_frozen ? "disabled" : ""}></label>
      </div>
      <p class="help">Set “people who advance” to whatever the room needs. 30 is only the default for a 50-person round.</p>
      <label>Notes <textarea data-field="notes" rows="2">${escapeHtml(round.notes)}</textarea></label>
      <button type="button" data-action="save">Save settings</button>
      ${round.playable ? `
        <div class="refs" data-refs="${round.id}">
          ${[1, 2, 3].map((slot) => {
            const ref = round.references.find((item) => item.slot === slot);
            return `<div><p>Image ${slot}</p>${ref ? `<img alt="" src="${ref.url}">` : "<p class='muted'>Not set</p>"}
              ${lockedImages ? "" : `<input type="file" accept="image/png,image/jpeg" data-ref="${slot}">`}</div>`;
          }).join("")}
        </div>
        <div class="row">
          <button type="button" data-action="activate" ${round.status === "draft" ? "" : "disabled"}>Activate</button>
          <input data-field="minutes" type="number" min="1" max="180" value="5">
          <button type="button" data-action="extend">Add minutes</button>
          <button type="button" class="ghost" data-action="end">End round</button>
        </div>
        <div class="row">
          <input data-field="restart" placeholder="Type RESTART">
          <button type="button" class="hot" data-action="restart">Restart round</button>
          <a class="button ghost" href="/api/admin/export.csv?round_id=${round.id}">Download CSV</a>
        </div>
        <h3>Leaderboard</h3>
        <div data-board="${round.id}"></div>
        <h3>Who advances</h3>
        <div class="checks" data-advance="${round.id}"></div>
        <div class="row">
          <button type="button" data-action="suggest">Suggest top N</button>
          <button type="button" data-action="selection">Save selection</button>
          <button type="button" data-action="confirm">Confirm advancement</button>
        </div>
        <p data-confirm="${round.id}"></p>
      ` : `
        <p class="help">Attempt page is not built yet. You can store the cut, notes, and files. Activate stays off.</p>
        <input type="file" data-material>
        <ul data-files="${round.id}"></ul>
        <h3>People who can enter</h3>
        <ul data-entrants="${round.id}"></ul>
      `}
    </section>`;
}

function paintBoard(round) {
  const board = roundsRoot.querySelector(`[data-board="${round.id}"]`);
  if (!board) return;
  const rows = round.leaderboard.map((row) => {
    const flags = row.submissions.filter((sub) => sub.flag_reason).map((sub) =>
      `<div class="flag">Image ${sub.image_slot} attempt ${sub.attempt}: ${sub.flag_reason}
        ${sub.voided ? "(voided)" : `<button type="button" data-void="${sub.id}">Void</button>`}
        <a href="${sub.url}" target="_blank">file</a></div>`
    ).join("");
    return `<tr><td>${row.rank}</td><td>${row.code}</td><td>${Number(row.total).toFixed(1)}</td><td>${flags}</td></tr>`;
  }).join("");
  board.innerHTML = `<table><thead><tr><th>#</th><th>Code</th><th>Total</th><th>Flags</th></tr></thead><tbody>${rows}</tbody></table>`;
  board.querySelectorAll("[data-void]").forEach((button) => {
    button.addEventListener("click", async () => {
      await fetch(`/api/admin/submissions/${button.dataset.void}/void`, { method: "POST" });
      tick();
    });
  });
}

function paintAdvance(round) {
  const box = roundsRoot.querySelector(`[data-advance="${round.id}"]`);
  if (!box || dirty) return;
  box.innerHTML = round.advancement.map((row) => `
    <label>
      <input type="checkbox" value="${row.participant_id}" ${row.included ? "checked" : ""} ${round.advancement_frozen ? "disabled" : ""}>
      ${row.rank}. ${row.code} (${Number(row.total).toFixed(1)})
    </label>`).join("") || "<p class='muted'>End the round to choose who advances.</p>";
  box.querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", () => { dirty = true; });
  });
  const note = roundsRoot.querySelector(`[data-confirm="${round.id}"]`);
  if (note) {
    note.textContent = round.advancement_confirmed
      ? "Advancement is confirmed. Editing the checks will require confirming again."
      : "Not confirmed yet. Only a confirmed list can enter the next round.";
  }
}

function paint(data) {
  login.classList.add("hidden");
  panel.classList.remove("hidden");
  const mode = document.querySelector("#mode");
  if (data.scoring_mode === "fake") {
    mode.classList.remove("hidden");
    mode.textContent = "Dry-run scorer is on. Scores are not real image similarity. Unset SKIP_MODELS before the event.";
  }
  document.querySelector("#codes").value = data.codes.map((row) => row.code).join("\n");
  if (!built) {
    roundsRoot.innerHTML = data.rounds.map(roundCard).join("");
    built = true;
    if (!listening) {
      roundsRoot.addEventListener("click", onClick);
      roundsRoot.addEventListener("change", onChange);
      listening = true;
    }
  }
  for (const round of data.rounds) {
    const status = roundsRoot.querySelector(`[data-status="${round.id}"]`);
    if (status) status.textContent = round.status;
    const ends = roundsRoot.querySelector(`[data-ends="${round.id}"]`);
    if (ends) ends.textContent = round.ends_at ? ` · ends ${round.ends_at}` : "";
    paintBoard(round);
    paintAdvance(round);
    const files = roundsRoot.querySelector(`[data-files="${round.id}"]`);
    if (files) files.innerHTML = round.files.map((file) => `<li>${escapeHtml(file.filename)} <button type="button" data-delete-file="${round.id}:${file.id}">Remove</button></li>`).join("");
    const entrants = roundsRoot.querySelector(`[data-entrants="${round.id}"]`);
    if (entrants) entrants.innerHTML = round.entrants.map((row) => `<li>${row.code}</li>`).join("") || "<li>No one is confirmed yet.</li>";
  }
  document.querySelector("#log").innerHTML = data.actions.map((row) => `<li>${row.at} · ${row.action} · ${row.detail}</li>`).join("");
}

async function onClick(event) {
  const button = event.target.closest("button");
  if (!button) return;
  const card = button.closest("[data-round]");
  if (!card) return;
  const id = card.dataset.round;
  const action = button.dataset.action;
  if (button.dataset.deleteFile) {
    const [roundId, fileId] = button.dataset.deleteFile.split(":");
    await fetch(`/api/admin/rounds/${roundId}/files/${fileId}`, { method: "DELETE" });
    tick();
    return;
  }
  if (!action) return;
  let response;
  if (action === "save") {
    response = await fetch(`/api/admin/rounds/${id}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        duration_minutes: Number(card.querySelector("[data-field=duration]").value),
        cut_size: Number(card.querySelector("[data-field=cut]").value),
        notes: card.querySelector("[data-field=notes]").value,
      }),
    });
  } else if (action === "activate") {
    response = await fetch(`/api/admin/rounds/${id}/activate`, { method: "POST" });
  } else if (action === "extend") {
    response = await fetch(`/api/admin/rounds/${id}/extend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ minutes: Number(card.querySelector("[data-field=minutes]").value) }),
    });
  } else if (action === "end") {
    response = await fetch(`/api/admin/rounds/${id}/end`, { method: "POST" });
    dirty = false;
  } else if (action === "restart") {
    response = await fetch(`/api/admin/rounds/${id}/restart`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: card.querySelector("[data-field=restart]").value }),
    });
    dirty = false;
    built = false;
  } else if (action === "suggest") {
    response = await fetch(`/api/admin/rounds/${id}/suggest`, { method: "POST" });
    dirty = false;
  } else if (action === "selection") {
    const ids = [...card.querySelectorAll("[data-advance] input:checked")].map((input) => Number(input.value));
    response = await fetch(`/api/admin/rounds/${id}/advancement`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ participant_ids: ids }),
    });
    dirty = false;
  } else if (action === "confirm") {
    response = await fetch(`/api/admin/rounds/${id}/advancement/confirm`, { method: "POST" });
  }
  if (response) {
    const body = await response.json().catch(() => ({}));
    if (!response.ok) alert(body.detail || "That did not work");
  }
  tick();
}

async function onChange(event) {
  const input = event.target;
  if (input.dataset.ref) {
    const card = input.closest("[data-round]");
    const body = new FormData();
    body.set("file", input.files[0]);
    const response = await fetch(`/api/admin/rounds/${card.dataset.round}/references/${input.dataset.ref}`, {
      method: "POST",
      body,
    });
    const payload = await response.json();
    if (!response.ok) alert(payload.detail || "Could not save the image");
    built = false;
    tick();
  }
  if (input.dataset.material) {
    const card = input.closest("[data-round]");
    const body = new FormData();
    body.set("file", input.files[0]);
    const response = await fetch(`/api/admin/rounds/${card.dataset.round}/files`, { method: "POST", body });
    const payload = await response.json();
    if (!response.ok) alert(payload.detail || "Could not store the file");
    tick();
  }
}

async function tick() {
  const response = await fetch("/api/admin/state");
  if (response.status === 401) {
    login.classList.remove("hidden");
    panel.classList.add("hidden");
    return;
  }
  paint(await response.json());
}

tick();
setInterval(tick, 2000);
