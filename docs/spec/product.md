# Product: OpenMedCheck

- Status: Approved <!-- Draft | In review | Approved -->
- Last updated: 2026-10-17
- Input: [research notes](../discovery/research-notes.md)

> The open-source check that alerts ED doctors when a prescription conflicts with the patient's
> labs, diagnoses or notes — and stays silent when it doesn't. Built with Gemma 4, runs locally.

Concept demonstrator with synthetic patients only. **Not a medical device, not CE-marked, not
for clinical use.** Wording rule: OpenMedCheck checks a medication order *against* the
patient's diagnoses, labs and notes; it never reviews or makes diagnoses.

## Problem
Emergency physicians and on-call MIR residents in Spanish hospitals sign medication orders
under heavy time pressure, often just as creatinine/eGFR results arrive. Severe errors are
predictable: an NSAID for a patient on daily aspirin with suspected acute coronary syndrome,
or a renally cleared antibiotic at full dose with eGFR < 30.

The EHR prescribing modules (Diraya, Orion Clinic, IANUS, HCIS/Selene, ECAP…) check orders
against drug databases (e.g. Bot PLUS). Those checks are mostly drug-pair tables that ignore
labs and acuity. They show SmPC text instead of an alternative, and they can't see the ED's
free-text impression ("suspected ACS"), because coded diagnoses only arrive with the
discharge report. Clinicians override half to over 90% of medication alerts, depending on
alert type and setting (49–96%, van der Sijs 2006; 46–96%, JMIR 2020; 64% in one ED, Yoo
2020). The alert that matters gets lost in the noise. Lab-aware commercial products exist
(FDB Targeted Medication Warnings, Sentri7). What none of them do is read the free-text ED
note at order time, answer with a concrete alternative and offer a verifiable escalate-only
safety invariant in a self-hosted deployment.

## Users and personas
| Persona | Needs | Current pain |
|---|---|---|
| ED physician / MIR resident (end user) | Sign an order without a missed conflict in seconds; get a dose or a substitute when it conflicts; no extra clicks or lectures | Context-blind pop-ups, SmPC text dumps, manual MDCalc/UpToDate/CIMA lookups |
| Hospital pharmacy service (buyer, story only) | Fewer preventable adverse drug events; auditable prescribing safety | Rule-only drug databases and in-house rule sets that are costly to maintain |
| CMIO / clinical IT (buyer, story only) | EHR-adjacent safety tooling, self-hosted, FHIR-ready later | Vendor modules they can't extend |
| Challenge judge / DEV reader (demo audience) | Understand the idea in under a minute; try it live; trust that the model can't overrule safety rules | — |

## Goals
- G-1: Show that a prescribing check can read the free-text ED note and labs at order time and
  return **one** triage-coded decision card with a concrete alternative, staying silent when
  nothing conflicts.
- G-2: Make safety verifiable. Deterministic rules decide the floor; the model may only
  escalate, never downgrade. The invariant is covered by automated tests.
- G-3: Run open-weights Gemma 4 fully locally (Ollama) with zero egress of patient context,
  and document the self-hosted GCP reference architecture a hospital would deploy (not
  deployed in this version).
- G-4: Submit a working, clinically reviewed local demo (open-source repo, demo video/GIF) and
  a DEV post to the DEV Hacktoberfest Open-Source AI Challenge, Week 2 ("Side Hustle" +
  "Best Use of Gemma"), by **Sun 2026-10-18 22:00 CEST**.

## Success metrics
| Metric | Target | How it is measured |
|---|---|---|
| Presets produce the expected card | 3/3 presets (A BLOCKED, B WARNING, C silent pass) | Automated preset tests + live demo |
| Gemma adds value beyond rules | Preset A: rules alone pass, final card is BLOCKED because Gemma read the free-text note | Preset A test asserts the rules verdict and the final verdict separately |
| Safety invariant holds | 100% of invariant tests pass (no downgrade, rules-BLOCKED final, alternatives re-checked, invalid output → rules card) | pytest invariant suite |
| Rules card latency | Rules verdict shown in < 200 ms | Local measurement script |
| Model card latency | Measured and reported on the local machine (target set in requirements once Q-4 is answered) | Local latency script, 20 calls over the 3 presets |
| Valid model output | ≥ 95% of Gemma responses validate against the card schema | Same 20-call run |
| Clinical review | Specialist finds no critical error in the rule table and the 3 cards | Review notes recorded in the repo; quote in the post |
| Runs for others | A reader can start the demo locally with the README steps (Ollama + app) | Fresh-clone run-through before submission |
| Cost | €0 cloud spend | No cloud resources created |
| Delivery | Public repo + demo video/GIF + DEV post submitted before Sun 2026-10-18 22:00 CEST | Submission confirmation |

## Scope
### In scope (this version)
- Three synthetic presets:
  - A: suspected ACS **only in the free-text note** + chronic aspirin + proposed
    dexketoprofen → BLOCKED, alternative paracetamol.
  - B: eGFR < 30 + ciprofloxacin → WARNING, renal adjustment.
  - C: benign case, normal renal function, standard analgesic → silent pass.
- Editable chart limited to eGFR / creatinine (and CrCl inputs), the free-text note and the
  proposed drug, chosen from a fixed list of about 15 drugs.
- Layer 1: about 6 deterministic rules (renal cut-offs, NSAID + antiplatelet + coded ACS,
  NSAID + active GI bleed, exact-match allergy).
- Layer 2: Gemma 4 E4B decision card under the escalate-only invariant. Alternatives come only
  from the rule table and are re-checked by Layer 1.
- The rules card shows first and is then replaced by the final card (no streaming). One-click
  alternative rewrites the order and re-evaluates.
- Green state labelled "No issue found by these checks" (not "approved/safe").
- "Not for clinical use — synthetic patients" banner.
- Runs entirely on the developer's machine: local web UI + API + rules, Gemma 4 via a local
  Ollama server; no outbound network calls with patient context.
- Infrastructure **documented, not implemented**, as the last piece of work: the GCP
  reference architecture (Cloud Run + L4 GPU, internal-only model ingress, zero egress, cost
  estimate) and a step-by-step deployment plan, in design.md and an ADR.
- Tests for the invariant and the presets; latency/validity measurement; 60 s demo GIF/video;
  DEV post.

### Non-goals (explicitly out of scope)
- Implementing GCP infrastructure: no cloud deployment, no hosted public demo URL, no
  Terraform code written or applied. The existing `infra/` scaffold stays untouched.
- EHR / HL7 FHIR integration.
- User accounts, authentication, multi-tenancy.
- Persistence of any patient context; audit history.
- Fine-tuning; MedGemma.
- A full drug database or drugs outside the fixed list.
- Spanish/Catalan UI localisation.
- Reporting or dashboards for buyers.
- Any clinical use, medical-device claim or efficacy claim (e.g. "reduces ADEs").
- Making, reviewing or suggesting diagnoses.
- Real patient data, ever.

## Constraints
- Deadline: feature freeze Sun 2026-10-18 12:00 CEST; post drafting from 13:00; submission by
  22:00 CEST (official cut-off 23:59 PDT).
- Budget: €0 cloud spend (no deployment). The documented GCP architecture targets ≤ €25 for a
  demo week at scale to zero, as an estimate only.
- Order of work: product and local implementation only; infrastructure documentation last.
- Mandated tech: Gemma 4 (open weights, Apache-2.0) served by Ollama; Python. Documented
  target: GCP europe-west1.
- Licence: Apache-2.0.
- Regulatory framing: in real use this would be special-category health data (GDPR Art. 9) and
  a medical device (MDR Rule 11, likely class IIa–IIb). Here it is a demonstrator: synthetic
  data, disclaimers, no clinical claims.
- Team: one developer with a clinical specialist reviewing: rule table + rules cards Sat
  2026-10-17 before 22:00; the 3 final cards Sun morning before feature freeze.

## Glossary
| Term | Meaning |
|---|---|
| ED | Emergency department |
| MIR | Medical resident in the Spanish training system |
| Order / proposed prescription | The single drug, dose, route and frequency being checked |
| PatientContext | Synthetic patient data sent with one order (demographics, note, diagnoses, meds, allergies, labs) |
| Decision card | The one result shown per order: status, risk tier, headline, rationale, renal flag, alternative |
| Layer 1 / rules | Deterministic, code-defined safety rules |
| Layer 2 / model | Gemma 4 reasoning over the context, incl. the free-text note |
| Escalate-only invariant | Final status = stricter of rules and model; model can't downgrade; rules-BLOCKED is final |
| Preset | One of the three fixed synthetic cases A, B, C |
| eGFR / CrCl | Estimated glomerular filtration rate / creatinine clearance (Cockcroft-Gault) |
| SmPC | Summary of Product Characteristics (AEMPS CIMA) |
| ACS | Acute coronary syndrome |

## Open questions
- [x] Q-1: ~~Cloud Run L4 price in europe-west1.~~ Closed with a caveat (2026-10-17): NVIDIA L4
  US$0.0001867 per second without zonal redundancy (US$0.672/h), US$0.0002909 with, per
  https://cloud.google.com/run/pricing (instance-based billing, default region table; the
  europe-west1 row could not be selected, see design.md Cost estimate). For the documented
  estimate only.
- [x] Q-2: ~~L4 GPU quota in the GCP project.~~ Not needed: no deployment (2026-10-17).
- [ ] Q-3: Exact Gemma 4 size naming (E4B) and Ollama tag `gemma4:e4b`, from the model card.
- [x] Q-4: Local hardware → NVIDIA GPU with ≥ 8 GB VRAM (answered 2026-10-17); targets in
  NFR-004.
- [ ] Q-5: Preset B dose: numeric (CrCl-based, SmPC-cited) only if the specialist signs it off
  today; otherwise "renal adjustment required — consult SmPC".
- [x] Q-6: ~~Do the Week 2 "Side Hustle" / "Best Use of Gemma" rules require a live hosted demo?~~
  Closed (2026-10-17): no. Source: DEV Events API `full_details` for event 80 "Hacktoberfest
  Open-Source AI Challenge: Week 2" (https://dev.to/challenges/hf26), read 2026-10-17. A hosted
  demo is not required; a demo video or GIF suffices. The post must say what was built and who
  would pay for it, show a demo and explain why open innovation matters; required tag
  `#hf26challenge`; a first user is a bonus. Judging: Writing Quality (weighted most),
  Relevance, Creativity, Technical Execution, optional partner technology; featured category
  "Best Use of Gemma". Submissions are due **Oct 18, 11:59 PM PDT (= Oct 19, 08:59 CEST)**, which
  is later than the 22:00 CEST anchor used in G-4 and Constraints; 22:00 CEST stays as the
  project's own, earlier target.

## Assumptions
- A-1: UI, synthetic patient records and notes in English; drugs shown by their international
  non-proprietary name (e.g. dexketoprofen, aspirin), not by brand.
- ~~A-2: The judging period lies within the €25 budget at scale to zero.~~ Obsolete: no
  deployment (2026-10-17).
- A-3: The specialist's review is enough clinical validation for a demonstrator; no further
  clinical validation is in scope.
- A-4: Status values are `NO_ISSUE` / `WARNING` / `BLOCKED` (not `APPROVED`), to avoid
  automation bias.
- A-5: Missing renal labs for a drug with a renal rule → at least `WARNING`, "renal function
  unknown".
- A-6: Adults only (age 18–110); paediatric dosing out of scope.
- A-7: Candidate drug list in design.md (data model); the final list, thresholds and doses
  come from the cited SmPCs and the specialist review.
