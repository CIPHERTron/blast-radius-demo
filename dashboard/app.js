// Blast Radius Dashboard - polls all 4 services and renders state.
// All requests go through absolute URLs because the downstream services
// run on different ports than the dashboard host.

const SERVICES = {
  checkout: { url: "http://localhost:8000", port: ":8000" },
  inventory: { url: "http://localhost:8001", port: ":8001" },
  payment: { url: "http://localhost:8002", port: ":8002" },
  notification: { url: "http://localhost:8003", port: ":8003" },
};

const POLL_INTERVAL_MS = 1000;

async function fetchJSON(url, opts = {}) {
  const res = await fetch(url, { ...opts, cache: "no-store" });
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

async function getHealth(service) {
  try {
    return await fetchJSON(`${SERVICES[service].url}/health`);
  } catch (e) {
    return null;
  }
}

async function getState(service) {
  try {
    return await fetchJSON(`${SERVICES[service].url}/state`);
  } catch (e) {
    return null;
  }
}

function setHealthClass(cardEl, health, state) {
  cardEl.classList.remove("healthy", "unhealthy", "broken");
  if (!health) {
    cardEl.classList.add("unhealthy");
    return;
  }
  // Checkout in BROKEN mode is "alive but bad" -> warn color.
  if (state && state.broken_build === true) {
    cardEl.classList.add("broken");
  } else {
    cardEl.classList.add("healthy");
  }
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function setBadActive(id, active) {
  const el = document.getElementById(id);
  if (!el) return;
  if (active) el.classList.add("bad-active");
  else el.classList.remove("bad-active");
}

function fmtMoney(n) {
  return `$${(Number(n) || 0).toFixed(2)}`;
}

// ---- Render each service card ---------------------------------------------

function renderCheckout(health, state) {
  const card = document.getElementById("card-checkout");
  setHealthClass(card, health, state || health);

  const version = (state && state.version) || (health && health.version) || "?";
  card.querySelector(".version").textContent = `v${version}`;

  const broken = (state && state.broken_build) || (health && health.broken_build);
  setText("checkout-build", broken ? "BROKEN (v1.0.1)" : "healthy (v1.0.0)");
  const buildEl = document.getElementById("checkout-build");
  buildEl.classList.toggle("bad", !!broken);

  if (state) {
    setText("checkout-success", state.blast_radius.successful_orders);
    setText("checkout-stuck", state.blast_radius.stuck_orders);
    setBadActive("checkout-stuck", state.blast_radius.stuck_orders > 0);
  }
}

function renderInventory(health, state) {
  const card = document.getElementById("card-inventory");
  setHealthClass(card, health, state);

  const version = (state && state.version) || (health && health.version) || "?";
  card.querySelector(".version").textContent = `v${version}`;

  if (state) {
    const stockSummary = Object.entries(state.stock)
      .map(([sku, qty]) => `${sku.replace("SKU-", "")}:${qty}`)
      .join("  ");
    setText("inventory-stock", stockSummary || "—");
    setText("inventory-stuck", state.stuck_reservation_count);
    setBadActive("inventory-stuck", state.stuck_reservation_count > 0);
  }
}

function renderPayment(health, state) {
  const card = document.getElementById("card-payment");
  setHealthClass(card, health, state);

  const version = (state && state.version) || (health && health.version) || "?";
  card.querySelector(".version").textContent = `v${version}`;

  if (state) {
    setText("payment-confirmed", fmtMoney(state.total_confirmed));
    setText("payment-orphaned", fmtMoney(state.total_orphaned));
    setBadActive("payment-orphaned", state.total_orphaned > 0);
  }
}

function renderNotification(health, state, checkoutState) {
  const card = document.getElementById("card-notification");
  setHealthClass(card, health, state);

  const version = (state && state.version) || (health && health.version) || "?";
  card.querySelector(".version").textContent = `v${version}`;

  if (state) {
    setText("notification-sent", state.sent_count);
    const missed = checkoutState
      ? checkoutState.blast_radius.stuck_orders
      : 0;
    setText("notification-missed", missed);
    setBadActive("notification-missed", missed > 0);
  }
}

// ---- Orders table ---------------------------------------------------------

const STEP_LABEL = {
  ok: { cls: "step-ok", glyph: "✓" },
  failed: { cls: "step-failed", glyph: "✕" },
  skipped: { cls: "step-skipped", glyph: "—" },
  pending: { cls: "step-pending", glyph: "·" },
};

function stepCell(status) {
  const meta = STEP_LABEL[status] || STEP_LABEL.pending;
  return `<span class="step ${meta.cls}" title="${status}">${meta.glyph}</span>`;
}

function renderOrders(checkoutState) {
  const tbody = document.getElementById("orders-tbody");
  if (!checkoutState || !checkoutState.orders || checkoutState.orders.length === 0) {
    tbody.innerHTML = `<tr class="empty"><td colspan="10">No orders yet. Click "Place test order" above.</td></tr>`;
    return;
  }

  const rows = checkoutState.orders.map((o) => {
    const isBlast = o.status === "blast_radius";
    const customer = o.customer || "—";
    const built = o.checkout_version || "?";
    return `
      <tr class="${isBlast ? "row-blast" : ""}">
        <td>${o.order_id}</td>
        <td>${customer}</td>
        <td>${fmtMoney(o.amount)}</td>
        <td>${stepCell(o.steps.reserve)}</td>
        <td>${stepCell(o.steps.charge)}</td>
        <td>${stepCell(o.steps.notify)}</td>
        <td>${stepCell(o.steps.commit)}</td>
        <td>${stepCell(o.steps.confirm)}</td>
        <td><span class="status-pill status-${o.status}">${o.status.replace("_", " ")}</span></td>
        <td>v${built}</td>
      </tr>`;
  });

  tbody.innerHTML = rows.join("");
}

// ---- Blast radius banner --------------------------------------------------

function renderBanner(checkoutState, paymentState, inventoryState) {
  const banner = document.getElementById("blast-banner");
  const summary = document.getElementById("blast-summary");

  const stuckOrders = checkoutState ? checkoutState.blast_radius.stuck_orders : 0;
  const stuckReservations = inventoryState
    ? inventoryState.stuck_reservation_count
    : 0;
  const orphanedCharges = paymentState ? paymentState.orphaned_count : 0;
  const orphanedAmount = paymentState ? paymentState.total_orphaned : 0;

  if (stuckOrders > 0 || stuckReservations > 0 || orphanedCharges > 0) {
    banner.classList.remove("banner-hidden");
    summary.innerHTML = `
      Bad checkout deploy left
      <strong>${stuckOrders}</strong> stuck order${stuckOrders === 1 ? "" : "s"} &middot;
      <strong>${stuckReservations}</strong> stuck inventory reservation${stuckReservations === 1 ? "" : "s"} &middot;
      <strong>${orphanedCharges}</strong> orphaned charge${orphanedCharges === 1 ? "" : "s"} totaling <strong>${fmtMoney(orphanedAmount)}</strong> &middot;
      <strong>${stuckOrders}</strong> missed notification${stuckOrders === 1 ? "" : "s"}.
    `;
  } else {
    banner.classList.add("banner-hidden");
  }
}

// ---- Main poll loop -------------------------------------------------------

async function tick() {
  const [
    checkoutHealth,
    inventoryHealth,
    paymentHealth,
    notificationHealth,
    checkoutState,
    inventoryState,
    paymentState,
    notificationState,
  ] = await Promise.all([
    getHealth("checkout"),
    getHealth("inventory"),
    getHealth("payment"),
    getHealth("notification"),
    getState("checkout"),
    getState("inventory"),
    getState("payment"),
    getState("notification"),
  ]);

  renderCheckout(checkoutHealth, checkoutState);
  renderInventory(inventoryHealth, inventoryState);
  renderPayment(paymentHealth, paymentState);
  renderNotification(notificationHealth, notificationState, checkoutState);
  renderOrders(checkoutState);
  renderBanner(checkoutState, paymentState, inventoryState);
}

setInterval(tick, POLL_INTERVAL_MS);
tick();

// ---- Buttons --------------------------------------------------------------

const SAMPLE_CUSTOMERS = [
  { customer: "alice@example.com", cart: [{ sku: "SKU-TSHIRT", qty: 1 }, { sku: "SKU-STICKER", qty: 2 }], amount: 29.99 },
  { customer: "bob@example.com", cart: [{ sku: "SKU-MUG", qty: 2 }], amount: 24.50 },
  { customer: "carol@example.com", cart: [{ sku: "SKU-HOODIE", qty: 1 }], amount: 65.00 },
  { customer: "dan@example.com", cart: [{ sku: "SKU-STICKER", qty: 5 }], amount: 12.00 },
  { customer: "eve@example.com", cart: [{ sku: "SKU-TSHIRT", qty: 2 }, { sku: "SKU-MUG", qty: 1 }], amount: 49.99 },
];

let customerIdx = 0;
function nextSampleOrder() {
  const o = SAMPLE_CUSTOMERS[customerIdx % SAMPLE_CUSTOMERS.length];
  customerIdx += 1;
  return o;
}

async function placeOrder() {
  const body = nextSampleOrder();
  const lastEl = document.getElementById("last-order");
  lastEl.textContent = "Placing order...";
  try {
    const res = await fetch(`${SERVICES.checkout.url}/checkout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      const data = await res.json();
      lastEl.textContent = `${data.order_id} -> ${data.status}`;
    } else {
      const text = await res.text();
      lastEl.textContent = `Order failed: HTTP ${res.status} ${text.slice(0, 80)}`;
    }
  } catch (e) {
    lastEl.textContent = `Order error: ${e.message}`;
  }
  tick();
}

async function placeBurst(n) {
  for (let i = 0; i < n; i++) {
    await placeOrder();
  }
}

document.getElementById("place-order").addEventListener("click", () => placeOrder());
document
  .getElementById("place-order-burst")
  .addEventListener("click", () => placeBurst(5));

async function deploy(version) {
  const lastEl = document.getElementById("last-order");
  lastEl.textContent = `Deploying ${version === "good" ? "v1.0.0" : "v1.0.1-broken"}...`;
  try {
    await fetch(`${SERVICES.checkout.url}/admin/deploy`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version }),
    });
  } catch (e) {
    // Expected: the service may die mid-response.
  }
  // Wait for restart, then poll a few times.
  setTimeout(tick, 1500);
  setTimeout(tick, 3000);
  setTimeout(() => {
    lastEl.textContent = `Deployed ${version === "good" ? "v1.0.0 (good)" : "v1.0.1 (broken)"}.`;
    tick();
  }, 4500);
}

document.getElementById("deploy-good").addEventListener("click", () => deploy("good"));
document.getElementById("deploy-bad").addEventListener("click", () => deploy("bad"));

document.getElementById("reset").addEventListener("click", async () => {
  const lastEl = document.getElementById("last-order");
  lastEl.textContent = "Resetting state...";
  try {
    await fetch(`${SERVICES.checkout.url}/admin/reset`, { method: "POST" });
    lastEl.textContent = "State reset across all services.";
  } catch (e) {
    lastEl.textContent = `Reset error: ${e.message}`;
  }
  tick();
});
