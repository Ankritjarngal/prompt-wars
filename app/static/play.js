const login = document.querySelector("#login");
const loginForm = document.querySelector("#login-form");
const loginError = document.querySelector("#login-error");
const statusCard = document.querySelector("#status");
const play = document.querySelector("#play");

let clock = null;
let builtFor = "";

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  const response = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code: loginForm.code.value }),
  });
  const body = await response.json();
  if (!response.ok) {
    loginError.textContent = body.detail || "Could not enter";
    return;
  }
  tick();
});

function formatLeft(ms) {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function render(data) {
  const playing = data.screen === "play";
  login.classList.toggle("hidden", true);
  statusCard.classList.toggle("hidden", playing);
  play.classList.toggle("hidden", !playing);
  if (!playing) {
    if (clock) cancelAnimationFrame(clock);
    const round = data.round;
    const score = round && round.score != null && data.screen !== "waiting"
      ? `<p>Your total ${Number(round.score).toFixed(1)} / 300 · rank ${round.rank} of ${round.player_count}</p>`
      : "";
    statusCard.innerHTML = `<h2>${data.message}</h2>${score}<p class="muted">Signed in as ${data.participant.code}</p>`;
    builtFor = "";
    return;
  }
  const signature = data.round.images.map((image) => image.reference_id).join(",");
  if (builtFor !== signature) {
    builtFor = signature;
    play.innerHTML = `
      <section class="card meta">
        <div>
          <p class="mark">${data.participant.code}</p>
          <p class="total" id="total"></p>
          <p id="rank"></p>
        </div>
        <p class="timer" id="timer"></p>
      </section>
      <div class="grid">
        ${data.round.images.map((image) => `
          <article class="image-card" data-image="${image.slot}">
            <h2>Image ${image.slot}</h2>
            <img alt="Reference ${image.slot}" src="${image.url}">
            <p>Counting: <strong data-count="${image.slot}">0</strong></p>
            <div class="slots">
              ${image.attempts.map((attempt) => `
                <div class="slot">
                  <strong>Attempt ${attempt.attempt}</strong>
                  <span data-slot="${image.slot}-${attempt.attempt}"></span>
                  <form data-upload="${image.slot}-${attempt.attempt}">
                    <input type="file" accept="image/png,image/jpeg" required>
                    <input class="note" type="text" maxlength="2000" placeholder="Prompt note, optional">
                    <button type="submit">Upload</button>
                    <p class="error"></p>
                  </form>
                </div>
              `).join("")}
            </div>
          </article>
        `).join("")}
      </div>`;
    play.querySelectorAll("form").forEach((form) => {
      form.addEventListener("submit", (event) => submitUpload(event, form));
    });
  }
  document.querySelector("#total").textContent = `${Number(data.round.score || 0).toFixed(1)} / 300`;
  document.querySelector("#rank").textContent = `Rank ${data.round.rank} of ${data.round.player_count}`;
  if (clock) cancelAnimationFrame(clock);
  const offset = Date.parse(data.server_now) - Date.now();
  const ends = Date.parse(data.round.ends_at);
  const paint = () => {
    const left = ends - (Date.now() + offset);
    const node = document.querySelector("#timer");
    if (node) node.textContent = formatLeft(left);
    clock = requestAnimationFrame(paint);
  };
  paint();
  for (const image of data.round.images) {
    const count = play.querySelector(`[data-count="${image.slot}"]`);
    count.textContent = `${Number(image.counting_score || 0).toFixed(1)}`;
    for (const attempt of image.attempts) {
      const node = play.querySelector(`[data-slot="${image.slot}-${attempt.attempt}"]`);
      const form = play.querySelector(`[data-upload="${image.slot}-${attempt.attempt}"]`);
      if (attempt.status === "scored") {
        const counts = image.counting_attempt === attempt.attempt ? " · counts" : "";
        node.innerHTML = `<span class="counts">${Number(attempt.total_score).toFixed(1)}${counts}</span>`;
        form.classList.add("hidden");
      } else if (attempt.status === "queued") {
        node.textContent = "Scoring…";
        form.classList.add("hidden");
      } else if (attempt.status === "error") {
        node.textContent = "";
        form.classList.remove("hidden");
        form.querySelector(".error").textContent = attempt.error;
      } else {
        node.textContent = "Empty";
        form.classList.remove("hidden");
      }
    }
  }
}

async function submitUpload(event, form) {
  event.preventDefault();
  const [referenceSlot, attempt] = form.dataset.upload.split("-");
  const error = form.querySelector(".error");
  error.textContent = "";
  const body = new FormData();
  body.set("reference_slot", referenceSlot);
  body.set("attempt", attempt);
  body.set("prompt", form.querySelector(".note").value);
  body.set("file", form.querySelector("input[type=file]").files[0]);
  const response = await fetch("/api/uploads", { method: "POST", body });
  const payload = await response.json();
  if (!response.ok) {
    error.textContent = payload.detail || "Upload failed";
    return;
  }
  tick();
}

async function tick() {
  const response = await fetch("/api/me");
  if (response.status === 401) {
    login.classList.remove("hidden");
    statusCard.classList.add("hidden");
    play.classList.add("hidden");
    return;
  }
  render(await response.json());
}

tick();
setInterval(tick, 2000);
