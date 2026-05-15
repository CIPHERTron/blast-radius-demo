// PIPA Metrics Generator dashboard - polls /state every 1s and drives buttons.

const POLL_MS = 1000;

async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, { ...opts, cache: "no-store" });
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

// ---------- rendering ----------

function setText(sel, value) {
  document.querySelectorAll(sel).forEach((el) => (el.textContent = value));
}

function fmtPct(x) { return `${(Number(x) || 0).toFixed(2)}%`; }
function fmtMs(x)  { return `${(Number(x) || 0).toFixed(1)} ms`; }
function fmtMb(x)  { return `${(Number(x) || 0).toFixed(1)} MiB`; }
function fmtRps(x) { return `${(Number(x) || 0).toFixed(1)} rps`; }

function updateCard(svc, snap) {
  const card = document.getElementById(`card-${svc}`);
  if (!card) return;

  card.classList.remove("healthy", "degraded", "critical");
  const lbl = (snap.health_label || "").toLowerCase();
  card.classList.add(lbl);
  card.querySelector(".health-label").textContent = snap.health_label;

  const errEl = card.querySelector(".m-err");
  errEl.textContent = fmtPct(snap.error_rate_pct);
  errEl.classList.toggle("bad-active", snap.error_rate_pct >= 5);
  errEl.classList.toggle("warn-active", snap.error_rate_pct >= 1 && snap.error_rate_pct < 5);

  const p99El = card.querySelector(".m-p99");
  p99El.textContent = fmtMs(snap.latency_p99_ms);
  p99El.classList.toggle("bad-active", snap.latency_p99_ms >= 2000);
  p99El.classList.toggle("warn-active", snap.latency_p99_ms >= 500 && snap.latency_p99_ms < 2000);

  const cpuEl = card.querySelector(".m-cpu");
  cpuEl.textContent = `${snap.cpu_pct.toFixed(1)}%`;
  cpuEl.classList.toggle("bad-active", snap.cpu_pct >= 85);
  cpuEl.classList.toggle("warn-active", snap.cpu_pct >= 70 && snap.cpu_pct < 85);

  card.querySelector(".m-mem").textContent = fmtMb(snap.memory_mb);
  card.querySelector(".m-rps").textContent = fmtRps(snap.request_rate_rps);
}

function renderTimeline(state) {
  const fill = document.getElementById("timeline-fill");
  const txt  = document.getElementById("timeline-text");
  if (!state.timeline_total_s) {
    fill.style.width = "0%";
    txt.textContent = state.timeline_running ? "running" : "stopped";
    return;
  }
  const pct = Math.min(100, (state.timeline_elapsed_s / state.timeline_total_s) * 100);
  fill.style.width = `${pct}%`;
  if (state.timeline_running) {
    txt.textContent = `phase ${state.timeline_phase_idx + 1}/${state.timeline_phase_count} \u2014 ${state.timeline_elapsed_s.toFixed(0)}s / ${state.timeline_total_s}s`;
  } else if (state.timeline_elapsed_s > 0) {
    txt.textContent = `paused \u2014 ${state.timeline_elapsed_s.toFixed(0)}s / ${state.timeline_total_s}s`;
  } else {
    txt.textContent = "stopped";
  }
}

function renderPushStatus(state) {
  const el = document.getElementById("push-results");
  if (!state.last_push_results) { el.textContent = "(no pushes yet)"; return; }
  const lines = Object.entries(state.last_push_results).map(([svc, status]) => {
    const cls = status === "ok" ? "ok" : "err";
    return `<span class="${cls}">${svc}: ${status}</span>`;
  });
  const ts = state.last_push_ts ? new Date(state.last_push_ts * 1000).toLocaleTimeString() : "-";
  el.innerHTML = `tick #${state.tick_count} @ ${ts} &nbsp; \u2014 &nbsp; ${lines.join("&nbsp;&nbsp;")}`;
}

function renderConfig(state) {
  if (!state.config) return;
  const c = state.config;
  document.getElementById("config").textContent =
    `pushgateway=${c.pushgateway_url} \u00b7 job=${c.job} \u00b7 interval=${c.push_interval_s}s${c.dry_run ? " \u00b7 DRY-RUN" : ""}`;
}

function renderScenarioButtons(scenarios, current) {
  const root = document.getElementById("scenario-buttons");
  if (root.dataset.rendered === "1") {
    root.querySelectorAll(".scenario-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.scenario === current);
    });
    return;
  }
  root.innerHTML = "";
  for (const s of scenarios) {
    const btn = document.createElement("button");
    btn.className = "btn scenario-btn" + (s.name === current ? " active" : "");
    btn.dataset.scenario = s.name;
    btn.textContent = s.name;
    btn.title = s.description || "";
    btn.addEventListener("click", () => switchScenario(s.name));
    root.appendChild(btn);
  }
  root.dataset.rendered = "1";
}

// ---------- actions ----------

async function tick() {
  try {
    const state = await fetchJSON("/state");
    document.getElementById("scenario-name").textContent = state.scenario;
    document.getElementById("scenario-desc").textContent = state.scenario_description || "";
    renderConfig(state);
    renderTimeline(state);
    renderPushStatus(state);
    for (const [svc, snap] of Object.entries(state.services)) updateCard(svc, snap);
    if (window.__scenariosLoaded) {
      const root = document.getElementById("scenario-buttons");
      root.querySelectorAll(".scenario-btn").forEach((b) => {
        b.classList.toggle("active", b.dataset.scenario === state.scenario);
      });
    }
  } catch (e) {
    console.error(e);
  }
}

async function switchScenario(name) {
  await fetch(`/scenario/${name}`, { method: "POST" });
  tick();
}

async function startTimeline() {
  await fetch("/timeline/start", { method: "POST" });
  tick();
}
async function stopTimeline() {
  await fetch("/timeline/stop", { method: "POST" });
  tick();
}
async function resetTimeline() {
  await fetch("/timeline/reset", { method: "POST" });
  tick();
}

async function init() {
  const sc = await fetchJSON("/scenarios");
  renderScenarioButtons(sc.scenarios, "steady");
  window.__scenariosLoaded = true;
  document.getElementById("timeline-start").addEventListener("click", startTimeline);
  document.getElementById("timeline-stop").addEventListener("click", stopTimeline);
  document.getElementById("timeline-reset").addEventListener("click", resetTimeline);
  setInterval(tick, POLL_MS);
  tick();
}

init();
