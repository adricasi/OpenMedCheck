"use strict";

// OpenMedCheck UI. All dynamic text is inserted with textContent; no markup is ever built
// from strings (NFR-001, design: output encoding). Nothing is stored in the browser.

const RANGES = {
  "context.age": { label: "Age", min: 18, max: 110, integer: true, required: true },
  "context.weight_kg": { label: "Weight", min: 30, max: 250, required: true },
  "context.labs.creatinine_mg_dl": { label: "Creatinine", min: 0.1, max: 20 },
  "context.labs.egfr_ml_min_1_73m2": { label: "eGFR", min: 0, max: 200 },
  "context.labs.potassium_mmol_l": { label: "Potassium", min: 1.5, max: 9 },
  "context.labs.platelets_per_ul": { label: "Platelets", min: 1000, max: 2000000 },
};
const REQUIRED_TEXT = {
  "order.drug_id": "Drug",
  "order.dose_text": "Dose",
  "order.frequency": "Frequency",
};
const STATUS_VIEW = {
  BLOCKED: { cls: "status-blocked", icon: "✕", label: "Blocked" },
  WARNING: { cls: "status-warning", icon: "!", label: "Warning" },
  NO_ISSUE: { cls: "status-ok", icon: "✓", label: "No issue found by these checks" },
};
const CONDITION_LABELS = {
  ACS: "acute coronary syndrome",
  ACTIVE_GI_BLEED: "active gastrointestinal bleed",
  HEART_FAILURE: "heart failure",
  PREGNANCY: "pregnancy",
};
const NO_MODEL_NOTE = "Model check unavailable — rules only";
const VERIFYING_TEXT = "Verifying the prescription with Gemma…";
// AC-005.3: same fixed text as the server's fallback; the note was not read, so no green card.
const NOTE_UNCHECKED_HEADLINE = "Free-text note not checked";
const NOTE_UNCHECKED_RATIONALE =
  "The model check was unavailable, so the free text (ED note and past medical history) was not " +
  "checked. The rules found no conflict in the coded data; review it before signing.";
// Test helper for custom patients (AC-007.6): an NSAID so the check has something to look at.
const SAMPLE_ORDER = { drug_id: "ibuprofen", dose_text: "400 mg", route: "PO", frequency: "every 8 hours" };
const EMPTY_ORDER = { drug_id: "", dose_text: "", route: "PO", frequency: "" };
const HEALTH_POLL_MS = 3000;
const HEALTH_POLL_MAX = 40;

const state = {
  seq: 0,
  checking: false,
  card: null,
  resolved: false,
  signed: false,
  drugs: [],
  record: null,
  scenarioEdited: false,
  templates: [],
  rooms: [],
  activeRoom: null,
  roomCounter: 0,
  hidden: { patient_id: "", diagnoses: [], history: [], chronic_medications: [], allergies: [] },
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
  select.appendChild(el("option", { text: "Select a drug", attrs: { value: "" } }));
  const chronic = $("f-chronic");
  clear(chronic);
  for (const drug of drugs) {
    select.appendChild(el("option", { text: drug.name, attrs: { value: drug.drug_id } }));
    const box = el("input", { attrs: { type: "checkbox", value: drug.drug_id, "data-history": "" } });
    chronic.appendChild(el("label", {}, [box, document.createTextNode(` ${drug.name}`)]));
  }
}

function drugName(drugId) {
  const drug = state.drugs.find((item) => item.drug_id === drugId);
  return drug ? drug.name : drugId;
}

function listText(items, mapper = (item) => item) {
  return items.length ? items.map(mapper).join(", ") : "none";
}

function fillContext(context) {
  $("f-age").value = context.age ?? "";
  $("f-sex").value = context.sex;
  $("f-weight").value = context.weight_kg ?? "";
  $("f-reason").value = context.reason_for_consult;
  $("f-creatinine").value = context.labs.creatinine_mg_dl ?? "";
  $("f-egfr").value = context.labs.egfr_ml_min_1_73m2 ?? "";
  $("f-potassium").value = context.labs.potassium_mmol_l ?? "";
  $("f-platelets").value = context.labs.platelets_per_ul ?? "";
  $("f-note").value = context.ed_note;
  $("f-past-history").value = context.past_history || "";
  renderNoteView();
  state.hidden = {
    patient_id: context.patient_id,
    diagnoses: [...context.diagnoses],
    history: [...(context.history || [])],
    chronic_medications: [...context.chronic_medications],
    allergies: [...context.allergies],
  };
  showHistory();
}

function fillOrder(order) {
  $("f-drug").value = order.drug_id;
  $("f-dose").value = order.dose_text;
  $("f-route").value = order.route;
  $("f-frequency").value = order.frequency;
}

function showHistory() {
  const { diagnoses, chronic_medications: chronic, allergies } = state.hidden;
  $("ro-conditions").textContent = listText(diagnoses, (code) => CONDITION_LABELS[code] || code);
  $("ro-chronic").textContent = listText(chronic, drugName);
  $("ro-allergies").textContent = listText(allergies);
  for (const box of document.querySelectorAll(".conditions input")) {
    box.checked = diagnoses.includes(box.value);
  }
  for (const box of $("f-chronic").querySelectorAll("input")) box.checked = chronic.includes(box.value);
  $("f-allergies").value = allergies.join(", ");
}

function readHistory() {
  // History editors write into state.hidden, which buildRequest sends (AC-007.5).
  state.hidden.diagnoses = Array.from(document.querySelectorAll(".conditions input"))
    .filter((box) => box.checked)
    .map((box) => box.value);
  state.hidden.chronic_medications = Array.from($("f-chronic").querySelectorAll("input"))
    .filter((box) => box.checked)
    .map((box) => box.value);
  state.hidden.allergies = $("f-allergies")
    .value.split(",")
    .map((item) => item.trim())
    .filter((item) => item !== "");
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
      past_history: $("f-past-history").value,
      diagnoses: state.hidden.diagnoses,
      history: state.hidden.history,
      chronic_medications: state.hidden.chronic_medications,
      allergies: state.hidden.allergies,
      labs: {
        creatinine_mg_dl: numberOrNull($("f-creatinine").value),
        egfr_ml_min_1_73m2: numberOrNull($("f-egfr").value),
        potassium_mmol_l: numberOrNull($("f-potassium").value),
        platelets_per_ul: numberOrNull($("f-platelets").value),
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

// ---------- simulated record and scenario editing (AC-006.5, AC-007.1, AC-007.4) ----------

const RECORD_SOURCE = "From the patient record (simulated)";
const EDITED_SOURCE = "Edited scenario (demo only) — not the record";
const NEW_PATIENT_SOURCE = "New custom patient (demo only) — enter the record, then save";
const CUSTOM_SOURCE = "Custom patient (demo only) — entered in this page";
const AUTOFILL_STATUS = "Test prescription filled";

const SEX_LABELS = { M: "Male", F: "Female" };

const SVG_NS = "http://www.w3.org/2000/svg";
// One ECG complex (P, QRS, T) repeated: the loading trace while Gemma reads the note.
const ECG_PATH =
  "M0 22 H18 l4 -4 l4 4 H34 l3 6 l5 -24 l5 30 l3 -12 H62 q6 -9 12 0 H100 " +
  "l4 -4 l4 4 H116 l3 6 l5 -24 l5 30 l3 -12 H144 q6 -9 12 0 H200";

function svgEl(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}

function ecgTrace() {
  const svg = svgEl("svg", {
    class: "ecg",
    viewBox: "0 0 200 40",
    preserveAspectRatio: "none",
    "aria-hidden": "true",
    focusable: "false",
  });
  svg.appendChild(svgEl("path", { class: "ecg-line", d: ECG_PATH, pathLength: "100" }));
  return svg;
}

const NEGATED_BEFORE = /\b(no|not|denies|denied|without|negative for|ruled out)\b[^.;\n]*$/i;

function noteLocked() {
  return $("f-note").hidden;
}

function quoteRanges(text, quotes) {
  // Case-insensitive, spacing-tolerant position of one mention per quote; overlaps merged. The
  // verifier checked that a non-negated mention exists, not which one, so the first mention not
  // just after a negation in its clause is marked (else the first).
  const ranges = [];
  for (const quote of quotes) {
    const words = quote.trim().split(/\s+/).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    if (!words.length || !words[0]) continue;
    const matches = [...text.matchAll(new RegExp(words.join("\\s+"), "gi"))];
    if (!matches.length) continue;
    const match =
      matches.find((m) => !NEGATED_BEFORE.test(text.slice(Math.max(0, m.index - 40), m.index))) ||
      matches[0];
    ranges.push([match.index, match.index + match[0].length]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const range of ranges) {
    const last = merged[merged.length - 1];
    if (last && range[0] <= last[1]) last[1] = Math.max(last[1], range[1]);
    else merged.push([...range]);
  }
  return merged;
}

function renderNoteView(quotes = []) {
  // Both free-text fields, each showing the quotes found in it.
  renderTextView($("note-view"), $("f-note").value, "No free-text note recorded.", quotes);
  renderTextView(
    $("past-history-view"),
    $("f-past-history").value,
    "No past medical history recorded.",
    quotes,
  );
}

function renderTextView(view, text, emptyText, quotes) {
  // Free text as text nodes, with the clinician's quoted evidence marked (textContent only).
  clear(view);
  if (!text) {
    view.appendChild(el("span", { cls: "note-empty", text: emptyText }));
    return;
  }
  let at = 0;
  for (const [start, end] of quoteRanges(text, quotes)) {
    if (start > at) view.appendChild(document.createTextNode(text.slice(at, start)));
    // <mark> is not announced by most screen readers, so the evidence is named in hidden text.
    const mark = el("mark", { cls: "evidence-mark" });
    mark.append(
      el("span", { cls: "visually-hidden", text: "[evidence: " }),
      text.slice(start, end),
      el("span", { cls: "visually-hidden", text: "]" }),
    );
    view.appendChild(mark);
    at = end;
  }
  if (at < text.length) view.appendChild(document.createTextNode(text.slice(at)));
}

function evidenceOf(card) {
  return card.fired_rules.flatMap((rule) => rule.evidence || []);
}

function setRecordEditable(editable) {
  for (const input of document.querySelectorAll("[data-record]")) {
    // A select has no read-only state, so a read-only text copy stands in while locked.
    if (input.tagName === "SELECT") input.hidden = !editable;
    else input.readOnly = !editable;
  }
  $("f-sex-text").value = SEX_LABELS[$("f-sex").value] || "";
  $("f-sex-text").hidden = editable;
  // The locked note is shown as text so the evidence can be highlighted in place.
  $("f-note").hidden = !editable;
  $("note-view").hidden = editable;
  $("f-past-history").hidden = !editable;
  $("past-history-view").hidden = editable;
  if (!editable) renderNoteView();
  document.querySelector(".history-view").hidden = editable;
  document.querySelector(".history-edit").hidden = !editable;
  $("edit-scenario").checked = editable;
  $("record").classList.toggle("record-editing", editable);
  const room = state.activeRoom;
  const unsaved = room !== null && room.custom && !room.saved;
  let source = editable ? EDITED_SOURCE : RECORD_SOURCE;
  if (room !== null && room.custom) source = unsaved ? NEW_PATIENT_SOURCE : CUSTOM_SOURCE;
  if (room !== null && room.custom && editable && !unsaved) source = EDITED_SOURCE;
  document.querySelector(".record-source").textContent = source;
  for (const button of document.querySelectorAll(".save-patient-button")) button.hidden = !unsaved;
  document.querySelector(".edit-toggle").hidden = unsaved;
}

function toggleScenarioEditing() {
  const editable = $("edit-scenario").checked;
  if (!editable && state.record && state.scenarioEdited) {
    // Leaving edit mode restores the record; the drafted order is kept.
    fillContext(state.record.context);
    clearErrors();
    state.scenarioEdited = false;
    invalidate();
    $("record-status").textContent = "Record restored; scenario edits discarded.";
  } else {
    $("record-status").textContent = "";
  }
  setRecordEditable(editable);
}

function showPayload(request = buildRequest()) {
  $("payload-body").textContent = JSON.stringify(request, null, 2);
  $("payload").hidden = false;
}

function contextSummary(context) {
  const sex = SEX_LABELS[context.sex] || context.sex;
  const reason = context.reason_for_consult || "no reason recorded";
  return `${sex}, ${context.age} · ${reason}`;
}

function roomSummary(room) {
  if (room.custom && !room.saved) return `${room.name} · new custom patient`;
  return `${room.name} · ${contextSummary(room.context)}`;
}

function templateLabel(preset) {
  return `${contextSummary(preset.request.context)} — ${preset.title}`;
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
  $("order-error").textContent = "";
  $("order-error").hidden = true;
  $("e-allergies").textContent = "";
  $("e-allergies").hidden = true;
  $("f-allergies").removeAttribute("aria-invalid");
  $("form-error").hidden = true;
  $("form-error").textContent = "";
}

function showOrderError(message) {
  $("order-error").textContent = message;
  $("order-error").hidden = false;
}

function announce(message) {
  $("verify-status").textContent = message;
}

function moveFocusOutOfCard() {
  // The card is about to be replaced; keep keyboard focus nearby (WCAG 2.4.3).
  if ($("card-area").contains(document.activeElement)) $("result-heading").focus();
}

function showFormError(message) {
  $("form-error").textContent = message;
  $("form-error").hidden = false;
}

function validate(scope = "all") {
  // scope "record" checks only the patient fields (saving a custom patient, AC-007.5).
  clearErrors();
  let first = null;
  const inScope = (path) => scope === "all" || path.startsWith("context.");
  const fail = (path, message) => {
    const input = fieldFor(path);
    setFieldError(input, message);
    first = first || input;
  };
  for (const [path, rule] of Object.entries(RANGES)) {
    if (!inScope(path)) continue;
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
    if (inScope(path) && fieldFor(path).value.trim() === "") fail(path, `${label} is required.`);
  }
  if (state.hidden.allergies.some((item) => item.length > 64)) {
    const input = $("f-allergies");
    $("e-allergies").textContent = "Each allergy must be at most 64 characters.";
    $("e-allergies").hidden = false;
    input.setAttribute("aria-invalid", "true");
    first = first || input;
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
  // Rules that fired because Gemma found the fact in the note show the doctor's words (AC-003.7).
  for (const rule of card.fired_rules) {
    for (const quote of rule.evidence || []) {
      section.appendChild(el("p", { cls: "note-evidence", text: `From the clinician's note: “${quote}”` }));
    }
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

function renderCard(card) {
  const area = $("card-area");
  const hadFocus = area.contains && area.contains(document.activeElement);
  clear(area);
  area.setAttribute("aria-busy", "false");
  const view = STATUS_VIEW[card.status];
  // A triage tag: coloured band, eyelet and tear line (START tag colours, ED familiar).
  const container = el("article", { cls: `card tag ${view.cls}` });
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
    if (card.alternative) container.appendChild(renderAlternative(card));
    if (card.status === "BLOCKED") container.appendChild(renderActions(card));
  }
  if (card.model_note) {
    container.appendChild(el("p", { cls: "model-note", text: card.model_note }));
  }
  area.appendChild(container);
  if (hadFocus) $("result-heading").focus();
  revealResult(area);
}

function revealResult(area) {
  // On a phone the verdict sits far below the order form: bring its top into view.
  if (!area.scrollIntoView) return;
  const top = area.getBoundingClientRect().top;
  const offscreen = top < 0 || top > window.innerHeight * 0.6;
  area.scrollIntoView({ block: offscreen ? "start" : "nearest" });
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
  const room = state.activeRoom;
  const unsaved = room !== null && room.custom && !room.saved;
  $("check-button").disabled = room === null || unsaved;
  $("check-hint").textContent = unsaved ? "Save the patient first." : "";
  if (room && !$("payload").hidden) showPayload();
  if (room && noteLocked()) renderNoteView(); // stale evidence highlights go
  const message = "Inputs changed. Press “Verify prescription” to check again.";
  if (!$("result-panel").hidden && $("card-area").textContent !== message) {
    moveFocusOutOfCard();
    renderMessage(message, "placeholder");
  }
  updateSign();
}

function hideResults() {
  $("payload").hidden = true;
  invalidate();
  clear($("card-area"));
  $("result-panel").hidden = true;
  announce("");
}

async function evaluate() {
  if (!document.querySelector(".history-edit").hidden) readHistory();
  if (!validate()) return;
  const request = buildRequest();
  showPayload(request);
  state.seq += 1;
  const mine = state.seq;
  resetOutcome();
  if (noteLocked()) renderNoteView(); // the previous card's evidence does not carry over
  state.checking = true;
  updateSign();
  $("result-panel").hidden = false;
  moveFocusOutOfCard();
  renderMessage(VERIFYING_TEXT, "checking");
  $("card-area").prepend(ecgTrace());
  announce(VERIFYING_TEXT);
  $("card-area").setAttribute("aria-busy", "true");

  // One request: the final card (rules + model, or rules only on fallback, AC-008.1, REQ-005).
  let card = null;
  try {
    const response = await postJson("/api/check", request);
    if (mine !== state.seq) return;
    if (response.status === 422) {
      const problem = await response.json();
      if (mine !== state.seq) return;
      showServerErrors(problem);
      finishWithMessage("Fix the highlighted fields, then verify again.");
      return;
    }
    if (response.ok) card = await response.json();
  } catch (_error) {
    card = null;
  }
  if (mine !== state.seq) return;
  if (card === null) {
    await settleWithRulesOnly(request, mine);
    return;
  }
  state.card = card;
  state.checking = false;
  renderCard(card);
  if (noteLocked()) renderNoteView(evidenceOf(card));
  announceCard(card);
  if (card.source === "rules") setModelStatus(NO_MODEL_NOTE, "model-unavailable");
  else refreshHealth();
  updateSign();
}

function announceCard(card) {
  announce(`Verification complete: ${STATUS_VIEW[card.status].label}.`);
}

function finishWithMessage(text) {
  state.checking = false;
  state.card = null;
  renderMessage(text, "placeholder");
  announce(text);
  updateSign();
}

async function settleWithRulesOnly(request, mine) {
  // /api/check missing or failing: fall back to the rules card and say the model is unavailable.
  let rules = null;
  try {
    const response = await postJson("/api/check/rules", request);
    if (response.ok) rules = await response.json();
  } catch (_error) {
    rules = null;
  }
  if (mine !== state.seq) return;
  setModelStatus(NO_MODEL_NOTE, "model-unavailable");
  if (!rules) {
    finishWithMessage("The check could not be completed. Nothing was evaluated.");
    return;
  }
  rules.model_note = rules.model_note || NO_MODEL_NOTE;
  if (rules.status === "NO_ISSUE") {
    rules.status = "WARNING";
    rules.risk_level = "MODERATE";
    rules.headline = NOTE_UNCHECKED_HEADLINE;
    rules.rationale = NOTE_UNCHECKED_RATIONALE;
  }
  state.card = rules;
  state.checking = false;
  renderCard(rules);
  announceCard(rules);
  updateSign();
}

function useAlternative(alt) {
  $("f-drug").value = alt.drug_id;
  if (!alt.route || !alt.frequency) {
    // Unreviewed dose (NFR-011): the UI never invents one. The clinician enters it.
    $("f-dose").value = "";
    $("f-frequency").value = "";
    invalidate();
    showOrderError(
      `${alt.name} selected. Enter the dose and frequency per SmPC, check the route, then press “Verify prescription”.`,
    );
    $("f-dose").focus();
    return;
  }
  $("f-dose").value = alt.dose_text;
  $("f-route").value = alt.route;
  $("f-frequency").value = alt.frequency;
  evaluate();
}

// ---------- rooms, templates and start-up (AC-006.5, AC-006.7, AC-007.5, AC-007.6) ----------

function copyContext(context) {
  return JSON.parse(JSON.stringify(context));
}

function roomFromTemplate(preset, name) {
  state.roomCounter += 1;
  return {
    id: `room-${state.roomCounter}`,
    name,
    custom: false,
    saved: true,
    title: preset.title,
    syntheticLabel: preset.synthetic_label,
    context: copyContext(preset.request.context),
    demoOrder: { ...preset.request.order },
  };
}

function customRoom() {
  state.roomCounter += 1;
  const number = state.rooms.filter((room) => room.custom).length + 1;
  return {
    id: `room-${state.roomCounter}`,
    name: `Custom patient ${number}`,
    custom: true,
    saved: false,
    title: "",
    syntheticLabel: "Custom patient (demo only) — enter invented data, never a real person's",
    context: {
      patient_id: `SYN-CUSTOM-${number}`,
      age: null,
      sex: "F",
      weight_kg: null,
      reason_for_consult: "",
      ed_note: "",
      past_history: "",
      diagnoses: [],
      history: [],
      chronic_medications: [],
      allergies: [],
      labs: {
        creatinine_mg_dl: null,
        egfr_ml_min_1_73m2: null,
        potassium_mmol_l: null,
        platelets_per_ul: null,
      },
    },
    demoOrder: null,
  };
}

function renderRooms() {
  const list = $("patient-list");
  clear(list);
  for (const room of state.rooms) {
    const pressed = state.activeRoom !== null && state.activeRoom.id === room.id;
    // Bed code and summary as two parts; the accessible name stays "Bed 3 Male, 64 · …".
    const summary = roomSummary(room).slice(room.name.length).replace(/^ · /, "");
    const button = el("button", { cls: "patient-button", attrs: { type: "button", "data-room": room.id } }, [
      el("span", { cls: "room-code", text: room.name }),
      el("span", { cls: "room-summary", text: ` ${summary}` }),
    ]);
    if (pressed) button.setAttribute("aria-current", "true");
    button.addEventListener("click", () => selectRoom(room));
    list.appendChild(el("li", {}, [button]));
  }
}

function selectRoom(room) {
  state.activeRoom = room;
  state.record = { context: room.context };
  state.scenarioEdited = false;
  clearErrors();
  fillContext(room.context);
  fillOrder(EMPTY_ORDER);
  setRecordEditable(room.custom && !room.saved);
  $("record-status").textContent = "";
  $("record").hidden = false;
  $("order-fields").hidden = false;
  $("order-empty").hidden = true;
  $("preset-title").textContent = room.custom
    ? roomSummary(room)
    : `${roomSummary(room)} — demo case: ${room.title}`;
  $("synthetic-label").textContent = room.syntheticLabel;
  renderRooms();
  hideResults(); // results stay hidden until "Verify prescription" (AC-008.1)
  $("chart-heading").focus();
}

function saveCustomPatient() {
  const room = state.activeRoom;
  readHistory();
  showHistory();
  if (!validate("record")) return;
  room.context = buildRequest().context;
  room.saved = true;
  state.record = { context: room.context };
  state.scenarioEdited = false;
  setRecordEditable(false);
  $("preset-title").textContent = roomSummary(room);
  $("record-status").textContent = "Patient saved for this page.";
  renderRooms();
  invalidate();
  announce("Patient saved for this page. Write the prescription next.");
  $("f-drug").focus();
}

function autofillPrescription() {
  const room = state.activeRoom;
  if (room === null) return;
  const order = room.demoOrder || SAMPLE_ORDER;
  fillOrder(order);
  clearErrors();
  invalidate();
  announce(`${AUTOFILL_STATUS}: ${drugName(order.drug_id)} ${order.dose_text}, ${order.route}, ${order.frequency}.`);
  $("check-button").focus();
}

function nextRoomName() {
  const used = new Set(state.rooms.map((room) => room.name));
  let number = 1;
  while (used.has(`Bed ${number}`)) number += 1;
  return `Bed ${number}`;
}

function toggleAddRoom(open) {
  $("add-room-form").hidden = !open;
  $("add-room-button").setAttribute("aria-expanded", String(open));
  if (open) {
    $("room-name").value = nextRoomName();
    $("e-room-name").hidden = true;
    $("room-name").removeAttribute("aria-invalid");
    $("room-name").focus();
  } else {
    $("add-room-button").focus();
  }
}

function createRoom(event) {
  event.preventDefault();
  const name = $("room-name").value.trim();
  if (name === "") {
    $("e-room-name").textContent = "Room name is required.";
    $("e-room-name").hidden = false;
    $("room-name").setAttribute("aria-invalid", "true");
    $("room-name").focus();
    return;
  }
  const preset = state.templates.find((item) => item.preset_id === $("room-template").value);
  if (!preset) return;
  const room = roomFromTemplate(preset, name);
  state.rooms.push(room);
  $("add-room-form").hidden = true;
  $("add-room-button").setAttribute("aria-expanded", "false");
  selectRoom(room);
}

function addPatient() {
  if (!$("add-room-form").hidden) toggleAddRoom(false);
  const room = customRoom();
  state.rooms.push(room);
  selectRoom(room);
  $("f-age").focus();
}

async function loadRooms() {
  try {
    await drugsReady;
    const response = await fetch("/api/presets");
    if (!response.ok) throw new Error(String(response.status));
    state.templates = await response.json();
    const select = $("room-template");
    clear(select);
    for (const preset of state.templates) {
      select.appendChild(el("option", { text: templateLabel(preset), attrs: { value: preset.preset_id } }));
    }
    state.rooms = state.templates
      .filter((preset) => preset.bed !== null)
      .map((preset) => roomFromTemplate(preset, preset.bed));
    renderRooms();
  } catch (_error) {
    showFormError("The rooms could not be loaded.");
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
  // Delegated: the chronic-medication checkboxes are created after the drug list loads.
  const historyEditor = document.querySelector(".history-edit");
  historyEditor.addEventListener("change", (event) => {
    if (!event.target.hasAttribute("data-history")) return;
    readHistory();
    showHistory();
    state.scenarioEdited = true;
    invalidate();
  });
  $("f-allergies").addEventListener("input", () => {
    // Typing makes the shown card stale at once, before the field loses focus (AC-008.7).
    state.scenarioEdited = true;
    invalidate();
  });
  for (const input of fields()) {
    const edited = () => {
      if (input.hasAttribute("data-record")) state.scenarioEdited = true;
      invalidate();
    };
    input.addEventListener("input", () => {
      clearFieldError(input);
      edited();
    });
    input.addEventListener("change", edited);
  }
  $("check-form").addEventListener("submit", (event) => {
    event.preventDefault();
    evaluate();
  });
  $("sign-button").addEventListener("click", signOrder);
  $("edit-scenario").addEventListener("change", toggleScenarioEditing);
  for (const button of document.querySelectorAll(".save-patient-button")) {
    button.addEventListener("click", saveCustomPatient);
  }
  $("add-room-form").addEventListener("keydown", (event) => {
    if (event.key === "Escape") toggleAddRoom(false);
  });
  $("autofill-button").addEventListener("click", autofillPrescription);
  $("add-room-button").addEventListener("click", () => toggleAddRoom($("add-room-form").hidden));
  $("add-room-cancel").addEventListener("click", () => toggleAddRoom(false));
  $("add-room-form").addEventListener("submit", createRoom);
  $("add-patient-button").addEventListener("click", addPatient);
  drugsReady = loadDrugs();
  loadRooms();
  warmUp().then(() => refreshHealth(true));
  refreshHealth(true);
}

document.addEventListener("DOMContentLoaded", init);
