# Research notes: OpenMedCheck (formerly PrescribeGuard AI)

Every factual claim has a
source link and access date; estimates are labelled as estimates. All accessed 2026-10-17.
Most findings come from search summaries rather than full-text reads.

## Competitors and alternatives
- Bot PLUS (Consejo General de Colegios Farmacéuticos) — national drug database with
  interaction search, integrated into dispensing and e-prescription software (IB-Salut documents
  integration). Pricing not found.
  https://www.farmaceuticos.com/pam/temas/bot-plus-al-dia/busqueda-de-interacciones-en-bot-plus/
- MedAware (Israel, 2012) — ML-based medication-error alerts on top of the EHR; customers incl.
  Ballad Health; $8M Series A (2017). Pricing not found.
  https://www.mobihealthnews.com/news/new-8m-medaware-uses-ai-spot-preventable-prescription-errors
- Hospital in-house rule sets — e.g. Hospital Infanta Leonor assisted e-prescribing with 62
  relevant interactions and 531 drugs with renal adjustment (source not captured). Buyers may build
  rather than buy.
- Not researched: Vidal Vademecum, Medimecum, Lexicomp/UpToDate, Medi-Span, Micromedex.

### "Does this already exist?" pass (2026-10-17)
- FDB Targeted Medication Warnings — patient-specific, EHR-embedded alerts that use labs and
  co-medication to fire only for at-risk patients (e.g. hyperkalaemia). Customer-reported: Community
  Health cut 250,000 alerts and overrides 92% → 76% with 10 modified alerts; FDB poster (May 2026):
  −70% pharmacy alerts. Vendor/customer sources only.
  https://www.healthcareitnews.com/news/fdb-talks-well-timed-patient-specific-clinical-decision-support-himss24 ,
  https://www.biospace.com/fdb-releases-patient-specific-medication-decision-support-solution-for-use-in-ehr-workflow ,
  https://digital-release.wboy.com/business/press-releases/cision/20260515LA60638/amia-amplify-poster-session-fdb-pharmacists-show-patient-specific-medication-guidance-can-reduce-pharmacy-alerts-by-70
- Wolters Kluwer Sentri7 — pharmacy surveillance on EHR labs/orders/vitals; precision renal dosing
  with Lexicomp content. https://www.wolterskluwer.com/en/solutions/solesource/sentri7/precision-renal-dosing
- VigiLanz — real-time surveillance of orders + labs, flags improper dosing (John Muir Health).
  https://www.beckershospitalreview.com/quality/reducing-adverse-drug-events-at-john-muir-health.html
- Research, LLM as medication-safety CDS: Singapore prospective study, 16 specialties, LLM +
  pharmacist co-pilot best at 61% accuracy, ~1.5× detection of high-harm errors vs pharmacist alone
  (Cell Reports Medicine 2025). https://pmc.ncbi.nlm.nih.gov/articles/PMC12629785/ ; earlier
  12-specialty preprint https://arxiv.org/pdf/2402.01741 . No commercial LLM prescribing checker found.
- Savana (Spain) — clinical NLP over EHR free text (EHRead), mainly real-world-evidence research;
  a 2019 NLP-based real-time CDSS in Spanish primary care; no prescribing-safety product found.
  https://cordis.europa.eu/article/id/422215-unlocking-electronic-medical-records-to-revolutionise-health-research
- Same challenge, Week 2 entry: "Parchi" by Sankalp Kotewar — local gemma3:4b prescription reader
  for an Indian pharmacy; thesis "the OCR reads, the model understands, the gate decides"; 20-line
  poisoned eval, 0/20 wrong answers reach the counter; enters Gemma, TabPFN, ElevenLabs, Render.
  https://dev.to/sankalpkotewar/i-poisoned-20-drug-names-to-find-out-whether-a-local-model-belongs-in-a-pharmacy-5ekh

### EHR landscape check (claims from the user's draft)
| Claim | Result |
|---|---|
| Andalusia — Diraya | Verified: https://www.sspa.juntadeandalucia.es/servicioandaluzdesalud/profesionales/sistemas-de-informacion/diraya |
| Valencia — Orion Clinic | Verified |
| Galicia — IANUS | Verified |
| Madrid — HCIS, Selene | Verified, but 2016 source: https://www.redaccionmedica.com/autonomias/madrid/20161220/urgencias-del-de-octubre-uci-infantil-la-paz-reforma-en/34140_0.html |
| Catalonia — ECAP, HC3 | Verified in use; ARGOS in 8 ICS hospitals (2010); "SAP-based" unconfirmed; SILICON not found |
| Quirónsalud — Casiopea | Not found |

## Market signals
### Alert fatigue (the problem)
- van der Sijs et al., JAMIA 2006 (17 papers): drug safety alerts overridden in 49–96% of cases;
  some overrides justified. https://pmc.ncbi.nlm.nih.gov/articles/PMC1447540
- JMIR Med Inform 2020 systematic review (23 articles): overrides 46.2–96.2%; appropriate
  overrides 29.4–100%. https://medinform.jmir.org/2020/7/e15653/
- Yoo et al., JMIR Med Inform 2020, single tertiary ED: 63.77% of 102,887 alerts overridden;
  ~13.75 alerts per 100 orders. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7673981/
- Verdict on the draft's "80–90%" / "85–95%": not supported as a general figure. Use "half to
  over 90%, depending on alert type and setting".

### Buyers
- No Spanish tender found combining AI CDS and innovation procurement.
- Vall d'Hebron / VHIR renewed (July 2026) an agreement with Barcelona & Madrid Health Hub to
  validate and adopt startup products — a possible pilot route.
  https://vhir.vallhebron.com/en/society/news/vall-dhebron-and-barcelona-madrid-health-hub-renew-their-collaboration-agreement
- Madrid AI cardiac-diagnosis pilot at Ramón y Cajal (2025, EU recovery funds) shows regional
  appetite for AI pilots. https://ted.europa.eu/es/notice/625237-2025/pdf
- Nothing found on Quirónsalud / Vithas / HM or pharmacy-service buying.

### Training segment (considered, not chosen)
- MIR exam prep spend €2,000–9,000 per candidate (undated).
  https://www.redaccionmedica.com/secciones/formacion/-cuanto-cuesta-preparar-el-mir--4653
- Body Interact used at UFV and UCAM; quote-only pricing. https://bodyinteract.com/?p=23125
- No evidence found of residents paying for in-residency prescribing practice.

## Technology notes
- Gemma 4: released 2026-04-02 under Apache 2.0; E2B, E4B, 26B MoE, 31B dense; 128K/256K context.
  https://the-decoder.com/googles-gemma-4-is-now-available-with-apache-2-0-licensing-for-the-first-time/
  — official docs list sizes differently: https://ai.google.dev/gemma/docs/core (verify model card).
- MedGemma: Gemma 3 based; Google says "isn't yet clinical-grade". Terms forbid uses that could make
  Google a medical-device "manufacturer" → not chosen.
  https://developers.google.com/health-ai-developer-foundations/medgemma ,
  https://developers.google.com/health-ai-developer-foundations/terms
- Cloud Run GPU: L4 (24 GB) and RTX PRO 6000; L4 in europe-west1/europe-west4; scale to zero; min
  instances billed while idle; instance-based billing; default quota 3 GPUs/region with zonal
  redundancy off (cheaper per GPU-second). https://docs.cloud.google.com/run/docs/configuring/services/gpu
- Google tutorial: Gemma 4 with Ollama on Cloud Run GPU, tag `gemma4:e4b`, concurrency 16 =
  OLLAMA_NUM_PARALLEL; 26B/31B need vLLM + Direct VPC egress + Run:ai Model Streamer.
  https://docs.cloud.google.com/run/docs/tutorials/gpu-gemma-with-ollama ,
  https://docs.cloud.google.com/run/docs/run-gemma-on-cloud-run
- vLLM on Cloud Run codelab (L4 or RTX PRO 6000).
  https://codelabs.developers.google.com/codelabs/how-to-run-inference-cloud-run-gpu-vllm
- Cold start: GPU instance ready < 5 s; Gemma 3 4B time to first token from zero ≈ 19 s incl. model
  load. https://cloud.google.com/blog/products/serverless/cloud-run-gpus-are-now-generally-available
- Vertex AI Model Garden → private endpoint via Private Service Connect (codelab, us-central1).
  https://codelabs.developers.google.com/gemini-psc-endpoint
- Not found: current Cloud Run L4 price (pricing page did not render; check
  https://cloud.google.com/run/pricing), warm Gemma 4 E4B tokens/s on L4.

## Regulatory / compliance notes
Analysis, not legal advice.
- EU MDR Rule 11 / MDCG 2019-11 Rev.1 (June 2025, non-binding): software informing therapeutic
  decisions is ≥ IIa; IIb if errors could cause serious deterioration; III if death/irreversible.
  https://openregulatory.com/mdcg/mdcg-2019-11 , https://gmpinsiders.com/mdcg-2019-11-rev1-mdr-ivdr/
- Estimate: patient-specific allow/block prescribing → IIa, plausibly IIb.
- EU AI Act: AI in a notified-body device is high-risk via Annex I; one unverified source says the
  Digital Omnibus (Reg. 2026/1744) moved Annex I obligations to 2028-08-02.
  https://www.pureglobal.com/news/eu-ai-act-omnibus-high-risk-dates-2028
- Spain: Ministry of Health CE-marking guide for medical software.
  https://www.sanidad.gob.es/areas/saludDigital/estrategiaIASNS/doc/IASNS_Guia_ProcesoMarcadoCE_Espana_PS.pdf
- A synthetic-only demo is plausibly out of scope (intended purpose), but no source confirms it;
  the demo must say "not for clinical use".

## Raw links
- DEV Hacktoberfest Week 2 "Side Hustle": https://dev.to/challenges/hf26 (due 2026-10-18 23:59 PDT;
  user's own target 2026-10-18 22:00 CEST)
