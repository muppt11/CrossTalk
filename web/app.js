import { createCarousel } from "/carousel.js";
import { createTextMorph } from "/text-morph.js";
import { initReveal, observeAll } from "/reveal.js";

const STORAGE_KEY = "crosstalk.v1";
const MAX_REPOS = 10;
const MIN_REPOS = 2;
const REPO_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const TIER_CLASSES = {
  "S-TIER MATCH": "tier-s",
  "A-TIER MATCH": "tier-a",
  "SOLID MATCH": "tier-solid",
  COMPETING: "tier-competing",
};

const $ = (id) => document.getElementById(id);
const selected = [];
let searchToken = 0;
let confettiFrame = 0;
const AVATAR_PREFIX = "https://avatars.githubusercontent.com/";
const auth = { configured: false, signedIn: false, login: "", avatar: "" };
const cache = { search: [], mine: null };
let mode = "search";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setStatus(node, message, isError = false) {
  node.textContent = message;
  node.classList.toggle("is-error", isError);
}

/* ---------- persistence (streak + achievements) ---------- */

function loadStore() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return {
      streak: Number(raw?.streak) || 0,
      achievements: Array.isArray(raw?.achievements) ? raw.achievements : [],
    };
  } catch {
    return { streak: 0, achievements: [] };
  }
}

function saveStore(store) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // Storage can be blocked (private mode); the streak just won't persist.
  }
}

function renderStreak(store) {
  const badge = $("streak");
  badge.hidden = store.streak <= 0;
  badge.textContent = `${store.streak} S-Tier`;
  badge.title = `${store.streak} S-Tier match${store.streak === 1 ? "" : "es"} found`;
}

/* ---------- toasts + confetti ---------- */

function toast(message, delay = 0) {
  window.setTimeout(() => {
    const node = el("div", "toast", message);
    $("toasts").appendChild(node);
    window.setTimeout(() => node.remove(), 3700);
  }, delay);
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function confetti() {
  if (prefersReducedMotion()) return;
  window.cancelAnimationFrame(confettiFrame);
  const canvas = $("confetti");
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  canvas.width = window.innerWidth * dpr;
  canvas.height = window.innerHeight * dpr;
  ctx.scale(dpr, dpr);

  const colors = ["#f3784b", "#b9e6d5", "#17221f"];
  const pieces = Array.from({ length: 90 }, () => ({
    x: window.innerWidth / 2,
    y: window.innerHeight * 0.35,
    vx: (Math.random() - 0.5) * 12,
    vy: -Math.random() * 10 - 3,
    size: 5 + Math.random() * 5,
    rotation: Math.random() * Math.PI,
    spin: (Math.random() - 0.5) * 0.4,
    color: colors[Math.floor(Math.random() * colors.length)],
  }));
  const duration = 1800;
  const startedAt = performance.now();

  function frame(now) {
    const elapsed = now - startedAt;
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    for (const piece of pieces) {
      piece.vy += 0.35;
      piece.vx *= 0.99;
      piece.x += piece.vx;
      piece.y += piece.vy;
      piece.rotation += piece.spin;
      ctx.save();
      ctx.globalAlpha = Math.max(0, 1 - elapsed / duration);
      ctx.translate(piece.x, piece.y);
      ctx.rotate(piece.rotation);
      ctx.fillStyle = piece.color;
      ctx.fillRect(-piece.size / 2, -piece.size / 2, piece.size, piece.size * 0.6);
      ctx.restore();
    }
    if (elapsed < duration) confettiFrame = requestAnimationFrame(frame);
    else ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
  }
  confettiFrame = requestAnimationFrame(frame);
}

$("replay-confetti").addEventListener("click", () => confetti());

/* ---------- API ---------- */

async function api(path, options) {
  const response = await fetch(path, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    // Non-JSON error body; fall through to the generic message.
  }
  if (!response.ok) {
    const error = new Error(payload?.error || `Request failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

/* ---------- discover + selection ---------- */

const carousel = createCarousel($("carousel"), { onToggle: toggleRepo });

function renderChips() {
  const list = $("chips");
  list.replaceChildren();
  for (const name of selected) {
    const item = el("li", "chip");
    item.appendChild(el("span", "", name));
    const remove = el("button", "", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${name}`);
    remove.addEventListener("click", () => toggleRepo(name));
    item.appendChild(remove);
    list.appendChild(item);
  }
  carousel.setSelected(new Set(selected));
}

function toggleRepo(name) {
  const index = selected.indexOf(name);
  if (index >= 0) {
    selected.splice(index, 1);
  } else if (selected.length >= MAX_REPOS) {
    setStatus($("analyze-status"), `Up to ${MAX_REPOS} projects per analysis.`, true);
    return;
  } else {
    selected.push(name);
  }
  setStatus($("analyze-status"), "");
  renderChips();
}

$("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = $("search-input").value.trim();
  const status = $("search-status");
  if (query.length < 2) {
    setStatus(status, "Enter at least two characters to search GitHub.", true);
    return;
  }
  const token = ++searchToken;
  setStatus(status, "Searching public repositories…");
  try {
    const items = await api(`/api/search?q=${encodeURIComponent(query)}`);
    if (token !== searchToken) return;
    cache.search = items;
    carousel.setItems(items);
    carousel.setSelected(new Set(selected));
    setStatus(status, items.length ? `Top ${items.length} public repositories for “${query}”, ranked by stars.` : "No repositories found.");
  } catch (error) {
    if (token === searchToken) setStatus(status, error.message, true);
    if (error.status === 401) loadMe();
  }
});

$("manual-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("manual-input");
  const value = input.value.trim().replace(/^https?:\/\/github\.com\//i, "").replace(/\/$/, "");
  if (!REPO_PATTERN.test(value)) {
    setStatus($("analyze-status"), "Use the format owner/repo, for example expressjs/express.", true);
    return;
  }
  if (!selected.includes(value)) toggleRepo(value);
  input.value = "";
});

/* ---------- analysis ---------- */

$("analyze-btn").addEventListener("click", async () => {
  const status = $("analyze-status");
  if (selected.length < MIN_REPOS) {
    setStatus(status, `Pick at least ${MIN_REPOS} projects first.`, true);
    return;
  }
  const button = $("analyze-btn");
  button.disabled = true;
  setStatus(status, "Reading READMEs and scoring…");
  try {
    const report = await api("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repositories: selected }),
    });
    setStatus(status, "");
    renderResults(report, selected.length);
    celebrate(report);
  } catch (error) {
    setStatus(status, error.message, true);
    if (error.status === 401) loadMe();
  } finally {
    button.disabled = false;
  }
});

function celebrate(report) {
  const store = loadStore();
  let delay = 0;
  if (!store.achievements.includes("first_analysis")) {
    store.achievements.push("first_analysis");
    toast("Achievement unlocked: first analysis complete", delay);
    delay += 700;
  }
  const sTierCount = (report.overlaps || []).filter((pair) => pair.tier === "S-TIER MATCH").length;
  if (sTierCount > 0) {
    store.streak += sTierCount;
    confetti();
    if (!store.achievements.includes("first_s_tier")) {
      store.achievements.push("first_s_tier");
      toast("Achievement unlocked: first S-Tier match", delay);
      delay += 700;
    }
    toast(`${store.streak} S-Tier match${store.streak === 1 ? "" : "es"} found so far`, delay);
  }
  saveStore(store);
  renderStreak(store);
}

/* ---------- results ---------- */

function meter(label, score, muted = false) {
  const clamped = Math.max(0, Math.min(Number(score) || 0, 100));
  const root = el("div", "meter");
  const row = el("div", "meter-row");
  row.append(el("span", "", label), el("span", "", `${clamped}%`));
  const track = el("div", "meter-track");
  const fill = el("div", muted ? "meter-fill is-muted" : "meter-fill");
  fill.style.width = "0%";
  track.appendChild(fill);
  root.append(row, track);
  requestAnimationFrame(() => requestAnimationFrame(() => { fill.style.width = `${clamped}%`; }));
  return root;
}

function tagRow(label, items) {
  const wrap = el("div", "tag-row");
  wrap.appendChild(el("p", "eyebrow", label));
  const group = el("div", "tag-group");
  for (const item of items) group.appendChild(el("span", "tag", item));
  wrap.appendChild(group);
  return wrap;
}

function pairCard(pair, dual) {
  const card = el("article", "pair");
  const head = el("div", "pair-head");
  if (dual) {
    head.append(el("span", "rank", `#${pair.rank}`), el("span", `tier ${TIER_CLASSES[pair.tier] || "tier-solid"}`, pair.tier));
  }
  card.appendChild(head);
  card.appendChild(el("p", "pair-names", `${pair.repository_a} × ${pair.repository_b}`));

  const meters = el("div", "pair-meters");
  if (dual) {
    meters.append(meter("Composability", pair.composability_score), meter("Redundancy", pair.redundancy_score, true));
  } else {
    meters.appendChild(meter("Overlap", pair.score));
  }
  card.appendChild(meters);

  const details = el("div", "pair-details");
  details.hidden = true;
  details.appendChild(el("p", "", dual ? pair.evidence : pair.reason));
  if (dual) details.appendChild(el("p", "", `Next step: ${pair.next_step}`));

  const toggle = el("button", "text-link", "Details");
  toggle.type = "button";
  toggle.setAttribute("aria-expanded", "false");
  toggle.addEventListener("click", () => {
    details.hidden = !details.hidden;
    toggle.setAttribute("aria-expanded", String(!details.hidden));
    toggle.textContent = details.hidden ? "Details" : "Hide details";
  });
  card.append(toggle, details);
  return card;
}

const scoreMorph = createTextMorph($("score-morph"));

function renderResults(report, count) {
  const dual = "avg_composability_score" in report;
  const composability = dual ? report.avg_composability_score : report.overlap_score;

  $("score").textContent = `${composability}%`;
  scoreMorph.setWords(
    dual
      ? [`${composability}% composable`, `${report.avg_redundancy_score}% redundant`]
      : [`${composability}% reuse potential`],
  );
  const redundancy = $("redundancy-meter");
  redundancy.replaceChildren();
  if (dual) redundancy.appendChild(meter("Redundancy", report.avg_redundancy_score, true));
  $("analyzed-count").textContent = `${count} projects analyzed`;
  const hasSTier = (report.overlaps || []).some((pair) => pair.tier === "S-TIER MATCH");
  $("replay-confetti").hidden = !hasSTier || prefersReducedMotion();

  $("summary").textContent = report.summary;
  const tags = $("tags");
  tags.replaceChildren(tagRow("Shared capabilities", report.shared_capabilities || []));
  if (dual) tags.appendChild(tagRow("Complementary pairings", report.composable_pairings || []));
  $("recommendation").textContent = `Suggested next step: ${report.recommendation}`;

  const pairs = $("pairs");
  pairs.replaceChildren();
  if ((report.overlaps || []).length === 0) {
    pairs.appendChild(el("p", "section-note", "No meaningful overlap pairs were found in the README excerpts."));
  }
  for (const pair of report.overlaps || []) pairs.appendChild(pairCard(pair, dual));

  const projects = $("projects");
  projects.replaceChildren();
  for (const project of report.project_summaries || []) {
    const row = el("div", "project");
    row.append(el("strong", "", project.repository), el("span", "", project.primary_focus));
    projects.appendChild(row);
  }

  const sources = $("sources");
  sources.replaceChildren();
  for (const [repo, readme] of Object.entries(report.sources || {})) {
    const details = el("details");
    details.appendChild(el("summary", "", `README excerpt · ${repo}`));
    details.appendChild(el("pre", "", readme));
    sources.appendChild(details);
  }

  observeAll($("results"));
  $("results").hidden = false;
  $("nav-results").hidden = false;
  $("results").scrollIntoView();
}

/* ---------- GitHub sign-in ---------- */

function renderAuth() {
  $("auth-link").hidden = auth.signedIn;
  $("auth-user").hidden = !auth.signedIn;
  $("discover-tabs").hidden = !auth.signedIn;
  if (auth.signedIn) {
    $("auth-login").textContent = auth.login;
    const avatar = $("auth-avatar");
    const valid = auth.avatar.startsWith(AVATAR_PREFIX);
    avatar.hidden = !valid;
    if (valid) avatar.src = auth.avatar;
  } else if (mode === "mine") {
    setMode("search");
  }
}

async function loadMe() {
  try {
    const me = await api("/api/me");
    auth.configured = Boolean(me.configured);
    auth.signedIn = Boolean(me.signed_in);
    auth.login = me.login || "";
    auth.avatar = me.avatar_url || "";
  } catch {
    auth.signedIn = false;
  }
  renderAuth();
}

async function loadMine() {
  const status = $("search-status");
  setStatus(status, "Loading your repositories…");
  try {
    const items = await api("/api/my-repos");
    if (mode !== "mine") return;
    cache.mine = items;
    carousel.setItems(items);
    carousel.setSelected(new Set(selected));
    setStatus(status, items.length ? `${items.length} of your repositories, most recently pushed first.` : "No repositories found on your account.");
  } catch (error) {
    if (mode === "mine") setStatus(status, error.message, true);
    if (error.status === 401) loadMe();
  }
}

function setMode(next) {
  mode = next;
  const mine = next === "mine";
  $("tab-search").classList.toggle("is-active", !mine);
  $("tab-search").setAttribute("aria-selected", String(!mine));
  $("tab-mine").classList.toggle("is-active", mine);
  $("tab-mine").setAttribute("aria-selected", String(mine));
  $("search-form").hidden = mine;
  setStatus($("search-status"), "");
  if (mine) {
    if (cache.mine) {
      carousel.setItems(cache.mine);
      carousel.setSelected(new Set(selected));
    } else {
      loadMine();
    }
  } else {
    carousel.setItems(cache.search);
    carousel.setSelected(new Set(selected));
  }
}

function clearPrivateData() {
  // Drop anything fetched with the old session so private repo names and README text
  // don't linger on screen after sign-out.
  cache.mine = null;
  cache.search = [];
  selected.length = 0;
  carousel.setItems([]);
  renderChips();
  $("results").hidden = true;
  $("nav-results").hidden = true;
  $("sources").replaceChildren();
  $("pairs").replaceChildren();
  setStatus($("search-status"), "");
  setStatus($("analyze-status"), "");
}

$("auth-link").addEventListener("click", () => {
  if (!auth.configured) {
    setStatus(
      $("search-status"),
      "GitHub sign-in isn't set up yet. Add GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET (see the README), then restart the server.",
      true,
    );
    toast("GitHub sign-in isn't set up yet. Register an OAuth app first (see the README).");
    $("discover").scrollIntoView();
    return;
  }
  window.location.assign("/auth/login");
});

$("auth-signout").addEventListener("click", async () => {
  try {
    await fetch("/auth/logout", { method: "POST" });
  } finally {
    auth.signedIn = false;
    auth.login = "";
    auth.avatar = "";
    setMode("search");
    clearPrivateData();
    renderAuth();
  }
});

$("tab-search").addEventListener("click", () => setMode("search"));
$("tab-mine").addEventListener("click", () => setMode("mine"));

const authOutcome = new URLSearchParams(window.location.search).get("auth");
if (authOutcome) {
  toast(authOutcome === "denied" ? "GitHub sign-in was cancelled." : "GitHub sign-in failed. Try again.");
  window.history.replaceState(null, "", window.location.pathname + window.location.hash);
}

initReveal();
renderStreak(loadStore());
renderChips();
loadMe();
