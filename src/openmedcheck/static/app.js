"use strict";

// OpenMedCheck UI. All dynamic text is inserted with textContent; no markup is ever built
// from strings (NFR-001, design: output encoding). Nothing is stored in the browser.

const RANGES = {
  "context.age": { label: "Age", min: 18, max: 110, integer: true, required: true },
  "context.weight_kg": { label: "Weight", min: 30, max: 250, required: true },
  "context.labs.creatinine_mg_dl": { label: "Creatinine", min: 0.1, max: 20 },
  "context.labs.egfr_ml_min_1_73m2": { label: "eGFR", min: 0, max: 200 },
};
const REQUIRED_TEXT = {
  "order.dose_text": "Dose",
  "order.frequency": "Frequency",
};
const STATUS_VIEW = {
  BLOCKED: { cls: "status-blocked", icon: "⛔", label: "Blocked" },
  WARNING: { cls: "status-warning", icon: "⚠", label: "Warning" },
  NO_ISSUE: { cls: "status-ok", icon: "✔", label: "No issue found by these checks" },
};
const CONDITION_LABELS = {
  ACS: "acute coronary syndrome",
  ACTIVE_GI_BLEED: "active gastrointestinal bleed",
};
const NO_MODEL_NOTE = "Model check unavailable — rules only";
const HEALTH_POLL_MS = 3000;
const HEALTH_POLL_MAX = 40;

const state = {
  seq: 0,
  checking: false,
  card: null,
  resolved: false,
  signed: false,
  drugs: [],
  hidden: { patient_id: "", diagnoses: [], chronic_medications: [], allergies: [] },
};

const $ = (id) => document.getElementById(id);
const fields = () => Array.from(document.querySelectorAll("[data-path]"));
const fieldFor = (path) => document.querySelector(`[data-path="${path}"]`);

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.cls) node.className = options.cls;
  if (options.text !== undefined) node.textContent = options.text;
  for (const [name, value] of Object.entries(options.attrs || {})) node.setAttribute(name, value);
  for (const child of children) node.appendChild(child);
  return node;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

// ---------- model status line (REQ-014, AC-011.2) ----------

let healthPolls = 0;
let healthTimer = null;

function setModelStatus(text, cls) {
  const line = $("model-status");
  line.textContent = text;
  line.className = `model-status ${cls}`;
}

function showHealth(health) {
  const tag = health.model || health.model_tag || "";
  const suffix = tag ? ` (${tag})` : "";
  if (health.state === "ready" || health.status === "ready") {
    setModelStatus(`Model ready${suffix}`, "model-ready");
    return "ready";
  }
  if (health.state === "warming" || health.status === "warming") {
    setModelStatus("Model warming…", "model-warming");
    return "warming";
  }
  setModelStatus("Model unavailable — rules-only checks", "model-unavailable");
  return "unavailable";
}

async function refreshHealth(resetPolls = false) {
  window.clearTimeout(healthTimer);
  if (resetPolls) healthPolls = 0;
  let outcome = "unavailable";
  try {
    const response = await fetch("/api/model/health");
    if (response.ok) outcome = showHealth(await response.json());
    else setModelStatus("Model status unavailable — rules-only checks", "model-unavailable");
  } catch (_error) {
    setModelStatus("Model status unavailable — rules-only checks", "model-unavailable");
  }
  healthPolls += 1;
  if (outcome === "warming" && healthPolls < HEALTH_POLL_MAX) {
    healthTimer = window.setTimeout(() => refreshHealth(), HEALTH_POLL_MS);
  }
}

async function warmUp() {
  try {
    await fetch("/api/model/warmup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  } catch (_error) {
    // Warm-up is best effort; the status line reports the outcome.
  }
}

// ---------- form <-> request ----------

function populateDrugs(drugs) {
  const select = $("f-drug");
  clear(select);
  for (const drug of drugs) {
    select.appendChild(el("option", { text: drug.name, attrs: { value: drug.drug_id } }));
  }
}

function drugName(drugId) {
  const drug = state.drugs.find((item) => item.drug_id === drugId);
  return drug ? drug.name : drugId;
}

function listText(items, mapper = (item) => item) {
  return items.length ? items.map(mapper).join(", ") : "none";
}

function fillForm(request) {
  const { context, order } = request;
  $("f-age").value = context.age;
  $("f-sex").value = context.sex;
  $("f-weight").value = context.weight_kg;
  $("f-reason").value = context.reason_for_consult;
  $("f-creatinine").value = context.labs.creatinine_mg_dl ?? "";
  $("f-egfr").value = context.labs.egfr_ml_min_1_73m2 ?? "";
  $("f-note").value = context.ed_note;
  $("f-drug").value = order.drug_id;
  $("f-dose").value = order.dose_text;
  $("f-route").value = order.route;
  $("f-frequency").value = order.frequency;
  state.hidden = {
    patient_id: context.patient_id,
    diagnoses: context.diagnoses,
    chronic_medications: context.chronic_medications,
    allergies: context.allergies,
  };
  $("ro-conditions").textContent = listText(
    context.diagnoses,
    (code) => CONDITION_LABELS[code] || code,
  );
  $("ro-chronic").textContent = listText(context.chronic_medications, drugName);
  $("ro-allergies").textContent = listText(context.allergies);
}

function numberOrNull(value) {
  return value.trim() === "" ? null : Number(value);
}

function buildRequest() {
  return {
    context: {
      patient_id: state.hidden.patient_id,
      age: numberOrNull($("f-age").value),
      sex: $("f-sex").value,
      weight_kg: numberOrNull($("f-weight").value),
      reason_for_consult: $("f-reason").value,
      ed_note: $("f-note").value,
      diagnoses: state.hidden.diagnoses,
      chronic_medications: state.hidden.chronic_medications,
      allergies: state.hidden.allergies,
      labs: {
        creatinine_mg_dl: numberOrNull($("f-creatinine").value),
        egfr_ml_min_1_73m2: numberOrNull($("f-egfr").value),
      },
    },
    order: {
      drug_id: $("f-drug").value,
      dose_text: $("f-dose").value.trim(),
      route: $("f-route").value,
      frequency: $("f-frequency").value.trim(),
    },
  };
}

// ---------- inline validation (AC-007.3) ----------

function errorNodeFor(input) {
  return $(input.getAttribute("aria-describedby"));
}

function setFieldError(input, message) {
  const node = errorNodeFor(input);
  node.textContent = message;
  node.hidden = false;
  input.setAttribute("aria-invalid", "true");
}

function clearFieldError(input) {
  const node = errorNodeFor(input);
  node.textContent = "";
  node.hidden = true;
  input.removeAttribute("aria-invalid");
}

function clearErrors() {
  for (const input of fields()) {
    const node = errorNodeFor(input);
    node.textContent = "";
    node.hidden = true;
    input.removeAttribute("aria-invalid");
  }
  $("form-error").hidden = true;
  $("form-error").textContent = "";
}

function showFormError(message) {
  $("form-error").textContent = message;
  $("form-error").hidden = false;
}

function validate() {
  clearErrors();
  let first = null;
  const fail = (path, message) => {
    const input = fieldFor(path);
    setFieldError(input, message);
    first = first || input;
  };
  for (const [path, rule] of Object.entries(RANGES)) {
    const raw = fieldFor(path).value.trim();
    if (fieldFor(path).validity && fieldFor(path).validity.badInput) {
      fail(path, `${rule.label} must be a number.`);
      continue;
    }
    if (raw === "") {
      if (rule.required) fail(path, `${rule.label} is required.`);
      continue;
    }
    const value = Number(raw);
    if (!Number.isFinite(value) || value < rule.min || value > rule.max) {
      fail(path, `${rule.label} must be between ${rule.min} and ${rule.max}.`);
    } else if (rule.integer && !Number.isInteger(value)) {
      fail(path, `${rule.label} must be a whole number.`);
    }
  }
  for (const [path, label] of Object.entries(REQUIRED_TEXT)) {
    if (fieldFor(path).value.trim() === "") fail(path, `${label} is required.`);
  }
  if (first) first.focus();
  return first === null;
}

function showServerErrors(problem) {
  clearErrors();
  let first = null;
  let unmapped = false;
  for (const item of problem.errors || []) {
    const input = fieldFor(item.field);
    if (input) {
      setFieldError(input, item.message);
      first = first || input;
    } else {
      unmapped = true;
    }
  }
  if (unmapped || !first) showFormError(problem.detail || "The request was not accepted.");
  if (first) first.focus();
}

// ---------- card rendering (AC-008.x) ----------

function renderStatusHeader(card) {
  const view = STATUS_VIEW[card.status];
  return el("div", { cls: "status-badge" }, [
    el("span", { cls: "status-icon", text: view.icon, attrs: { "aria-hidden": "true" } }),
    el("span", { cls: "status-label", text: view.label }),
  ]);
}

function actionText(card) {
  if (card.status === "BLOCKED") {
    const choice = card.alternative ? "Use the alternative or acknowledge" : "Acknowledge";
    return `Action required: this order conflicts with the patient context. ${choice} before signing.`;
  }
  return "Review before signing: check the points below.";
}

function renderWhy(card) {
  const section = el("section", { cls: "card-section" }, [
    el("h3", { text: "Why" }),
    el("p", { text: card.rationale }),
  ]);
  const unseen = card.fired_rules.filter((rule) => !card.rationale.includes(rule.reason));
  if (unseen.length) {
    const list = el("ul");
    for (const rule of unseen) {
      list.appendChild(el("li", { text: `${rule.rule_id}: ${rule.reason}` }));
    }
    section.appendChild(list);
  }
  if (card.fired_rules.length) {
    section.appendChild(
      el("p", {
        cls: "rule-ids",
        text: `Rules fired: ${card.fired_rules.map((rule) => rule.rule_id).join(", ")}`,
      }),
    );
  }
  if (card.renal_adjustment_required) {
    const crcl = card.crcl_ml_min === null ? "" : ` (estimated CrCl ${card.crcl_ml_min} mL/min)`;
    section.appendChild(el("p", { cls: "renal-flag", text: `Renal adjustment required${crcl}` }));
  }
  return section;
}

function renderAlternative(card) {
  const alt = card.alternative;
  const details = [alt.dose_text, alt.route, alt.frequency].filter((part) => part).join(" · ");
  const useButton = el("button", {
    cls: "secondary",
    text: "Use alternative",
    attrs: { type: "button", id: "use-alternative" },
  });
  useButton.addEventListener("click", () => useAlternative(alt));
  return el("section", { cls: "card-section" }, [
    el("h3", { text: "Alternative" }),
    el("p", { cls: "alt-name", text: alt.name }),
    el("p", { text: details }),
    el("p", { text: alt.reason }),
    useButton,
  ]);
}

function renderActions(card) {
  const wrapper = el("div", { cls: "card-actions" });
  const acknowledge = el("button", {
    cls: "secondary",
    text: "Acknowledge and keep order",
    attrs: { type: "button", id: "acknowledge" },
  });
  acknowledge.addEventListener("click", () => {
    state.resolved = true;
    acknowledge.disabled = true;
    acknowledge.textContent = "Acknowledged";
    updateSign();
    $("sign-button").focus();
  });
  wrapper.appendChild(acknowledge);
  return wrapper;
}

function renderCard(card, { checking }) {
  const area = $("card-area");
  const hadFocus = area.contains && area.contains(document.activeElement);
  clear(area);
  area.setAttribute("aria-busy", checking ? "true" : "false");
  const view = STATUS_VIEW[card.status];
  const container = el("article", { cls: `card ${view.cls}` });
  if (checking) {
    container.appendChild(el("p", { cls: "checking", text: "Checking context…" }));
  }
  container.appendChild(renderStatusHeader(card));
  if (card.status === "NO_ISSUE") {
    container.classList.add("card-compact");
    if (card.renal_adjustment_required || card.fired_rules.length) {
      container.appendChild(renderWhy({ ...card, rationale: "" }));
    }
  } else {
    container.appendChild(el("p", { cls: "action-required", text: actionText(card) }));
    container.appendChild(el("h3", { cls: "headline", text: card.headline }));
    container.appendChild(renderWhy(card));
    if (card.alternative && !checking) container.appendChild(renderAlternative(card));
    if (card.status === "BLOCKED" && !checking) container.appendChild(renderActions(card));
  }
  if (card.model_note) {
    container.appendChild(el("p", { cls: "model-note", text: card.model_note }));
  }
  area.appendChild(container);
  if (hadFocus) $("result-heading").focus();
  if (area.scrollIntoView) area.scrollIntoView({ block: "nearest" });
}

function renderMessage(text, cls) {
  const area = $("card-area");
  clear(area);
  area.setAttribute("aria-busy", "false");
  area.appendChild(el("p", { cls, text }));
}

// ---------- sign button (AC-008.2, AC-008.7, AC-008.8) ----------

function updateSign() {
  const card = state.card;
  const blockedUnresolved = card !== null && card.status === "BLOCKED" && !state.resolved;
  const allowed = card !== null && !state.checking && !blockedUnresolved && !state.signed;
  $("sign-button").disabled = !allowed;
  let hint = "";
  if (state.checking) hint = "Waiting for the check to finish.";
  else if (blockedUnresolved) {
    hint = card.alternative
      ? "Choose “Use alternative” or “Acknowledge and keep order” first."
      : "Choose “Acknowledge and keep order” first.";
  }
  $("sign-hint").textContent = hint;
}

function signOrder() {
  if ($("sign-button").disabled) return;
  state.signed = true;
  $("sign-result").textContent = "Order signed (demo — nothing stored)";
  updateSign();
}

// ---------- evaluation flow (REQ-008) ----------

async function postJson(path, body) {
  return fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function resetOutcome() {
  state.card = null;
  state.resolved = false;
  state.signed = false;
  $("sign-result").textContent = "";
}

function invalidate() {
  // Any edit makes the shown card stale: drop in-flight responses and the card itself.
  state.seq += 1;
  state.checking = false;
  resetOutcome();
  $("check-button").disabled = state.hidden.patient_id === "";
  if (!$("card-area").textContent.startsWith("Inputs changed")) {
    renderMessage("Inputs changed. Press “Check order” to evaluate.", "placeholder");
  }
  updateSign();
}

async function evaluate() {
  if (!validate()) return;
  const request = buildRequest();
  state.seq += 1;
  const mine = state.seq;
  resetOutcome();
  state.checking = true;
  updateSign();
  renderMessage("Checking context…", "checking");
  $("card-area").setAttribute("aria-busy", "true");

  const finalRequest = runFinal(request, mine);
  let rules;
  try {
    const response = await postJson("/api/check/rules", request);
    if (mine !== state.seq) return;
    if (response.status === 422) {
      state.seq += 1; // drop the pending final request
      showServerErrors(await response.json());
      finishWithMessage("Fix the highlighted fields, then check again.");
      return;
    }
    if (!response.ok) throw new Error(`rules check failed: ${response.status}`);
    rules = await response.json();
  } catch (_error) {
    // Other rules failures: let the final request settle the card (or the fallback).
    return;
  }
  if (mine !== state.seq) return;
  if (!state.card) {
    state.card = rules;
    renderCard(rules, { checking: true });
    updateSign();
  }
  await finalRequest;
}

function finishWithMessage(text) {
  state.checking = false;
  state.card = null;
  renderMessage(text, "placeholder");
  updateSign();
}

async function runFinal(request, mine) {
  let card = null;
  try {
    const response = await postJson("/api/check", request);
    if (response.ok) card = await response.json();
  } catch (_error) {
    card = null;
  }
  if (mine !== state.seq) return;
  // Rules card must have arrived or the final card stands alone; either way it is final.
  if (card === null) {
    await settleWithRulesOnly(request, mine);
    return;
  }
  state.card = card;
  state.checking = false;
  renderCard(card, { checking: false });
  if (card.source === "rules") setModelStatus(NO_MODEL_NOTE, "model-unavailable");
  else refreshHealth();
  updateSign();
}

async function settleWithRulesOnly(request, mine) {
  // /api/check missing or failing: keep the rules card and say the model is unavailable.
  setModelStatus(NO_MODEL_NOTE, "model-unavailable");
  let rules = state.card;
  if (!rules) {
    try {
      const response = await postJson("/api/check/rules", request);
      if (response.ok) rules = await response.json();
    } catch (_error) {
      rules = null;
    }
    if (mine !== state.seq) return;
  }
  if (!rules) {
    finishWithMessage("The check could not be completed. Nothing was evaluated.");
    return;
  }
  rules.model_note = rules.model_note || NO_MODEL_NOTE;
  state.card = rules;
  state.checking = false;
  renderCard(rules, { checking: false });
  updateSign();
}

function useAlternative(alt) {
  $("f-drug").value = alt.drug_id;
  if (!alt.route || !alt.frequency) {
    // Unreviewed dose (NFR-011): the UI never invents one. The clinician enters it.
    $("f-dose").value = "";
    $("f-frequency").value = "";
    invalidate();
    showFormError(`${alt.name} selected. Enter the dose and frequency per SmPC, then press “Check order”.`);
    $("f-dose").focus();
    return;
  }
  $("f-dose").value = alt.dose_text;
  $("f-route").value = alt.route;
  $("f-frequency").value = alt.frequency;
  evaluate();
}

// ---------- presets and start-up ----------

async function loadPreset(presetId) {
  try {
    await drugsReady;
    const response = await fetch(`/api/presets/${encodeURIComponent(presetId)}`);
    if (!response.ok) throw new Error(String(response.status));
    const preset = await response.json();
    clearErrors();
    fillForm(preset.request);
    $("preset-title").textContent = `Preset ${preset.preset_id}: ${preset.title}`;
    $("synthetic-label").textContent = preset.synthetic_label;
    for (const button of document.querySelectorAll(".preset-button")) {
      button.setAttribute("aria-pressed", String(button.dataset.preset === preset.preset_id));
    }
    $("check-button").disabled = false;
    await evaluate();
  } catch (_error) {
    showFormError("The preset could not be loaded.");
  }
}

let drugsReady = Promise.resolve();

async function loadDrugs() {
  try {
    const response = await fetch("/api/drugs");
    if (!response.ok) throw new Error(String(response.status));
    state.drugs = await response.json();
    populateDrugs(state.drugs);
  } catch (_error) {
    showFormError("The drug list could not be loaded.");
  }
}

function init() {
  for (const button of document.querySelectorAll(".preset-button")) {
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", () => loadPreset(button.dataset.preset));
  }
  for (const input of fields()) {
    input.addEventListener("input", () => {
      clearFieldError(input);
      invalidate();
    });
    input.addEventListener("change", invalidate);
  }
  $("check-form").addEventListener("submit", (event) => {
    event.preventDefault();
    evaluate();
  });
  $("sign-button").addEventListener("click", signOrder);
  drugsReady = loadDrugs();
  warmUp().then(() => refreshHealth(true));
  refreshHealth(true);
}

document.addEventListener("DOMContentLoaded", init);
