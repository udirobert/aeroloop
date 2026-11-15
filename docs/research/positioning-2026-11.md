---
title: "AeroLoop: revenue opportunity and positioning"
date: 2026-11-15
mode: deep
sources: 42
context: OpenServ SERV Hackathon Edition 02, Reppo track. Judged on creativity, user readiness and revenue potential [42].
---

# AeroLoop: revenue opportunity and positioning

## Executive Summary

Selling "London air-quality forecasts" has a weak revenue case. Selling "corrections to cheap sensors" has a crowded one: the established sensor vendors already include calibration free in their subscriptions [4][5]. The opportunity the evidence supports is narrower and better defended: **independent verification of air-quality data**. That means proving, with a tamper-evident record, that a correction to a sensor or model is valid on reference data it never saw.

Three forces make this timely. First, the revised EU Ambient Air Quality Directive applies from **12 December 2026**, 27 days from now. It sets explicit maximum uncertainties for indicative measurements, for example PM2.5 at 4 µg/m³ or 40% [11][12], and it lowers the PM2.5 limit from 25 to 10 µg/m³ by 2030 [13]. Second, the sensor industry is actively lobbying for its data to be accepted. A five-company coalition (Airly, Clarity, Kunak, Ellona, Ecomesure) launched in July 2026 calling for "greater acceptance of reliable sensor data by public authorities" [15]. Third, the UK construction market has a documented trust gap. The IAQM's September 2025 position statement says many low-cost sensors under-report PM10 near the 190 µg/m³ action level, and that certifications alone do not guarantee suitability [17][18]. Meanwhile, contractors pay £500 to £1,500 per monitoring point per month [20].

The recommended positioning is: **"AeroLoop is the independent auditor for air-quality data."** It corrects any sensor or model against reference monitors, proves every change on held-out data, has each change peer-checked through Reppo, and produces the evidence trail regulators are starting to require. The recommended first market is UK construction and demolition dust monitoring, because there the developer pays, the rules are already set, and the trust gap is on record. UK councils are the wrong first buyer: their dedicated air-quality grant fell 99.4%, to £1.5M in 2024/25 [22].

---

## Introduction

### Research question
Is there a real, substantiated revenue opportunity behind AeroLoop? If so, what is the most defensible positioning, both to win the OpenServ Reppo track (judged on creativity, user readiness and revenue potential [42]) and to build a business afterwards?

### What AeroLoop is today
AeroLoop predicts PM2.5 from CAMS model output plus weather. It saves each prediction before the ground truth exists, scores itself against LAQN reference monitors, has an LLM propose a strategy change from errors on a tune split, and keeps a change only if it beats the current strategy on a chronological holdout. Rejected strategies stay in the record. On its own data, the agent learned that CAMS systematically under-reads London's ground monitors, and it learned a correction specific to each station. That is calibration in substance.

### Scope and method
The search ran in three rounds, 48 queries in total, through Tavily (advanced depth). The most important claims were then checked by fetching their primary sources: the CIEH/FOI grant data, the tech.eu coalition report, the European Commission DG ENV FILTER summary, Clarity's 2026 pricing guide, and the Reppo Evaluation API docs. Sources cover market reports, regulation (EUR-Lex, US EPA, GOV.UK, IAQM), peer-reviewed literature (AMT, npj Climate, J. Env. Management), vendor pricing, and OpenServ/Reppo materials. Market-size reports from syndicated research firms are treated as low-confidence, directional numbers only.

### Key assumptions
"Revenue potential" is read as a credible, specific buyer with budget and a reason to pay now, not just a large market-size figure. The product is assumed to remain a software layer (no hardware).

---

## Finding 1: The market is real, but "calibration" is already bundled for free

Outdoor air-quality monitoring is a mid-single-digit-billion market growing at roughly 6–8% a year. Grand View Research puts air-quality monitoring systems at USD 5.80B in 2024 and USD 8.89B by 2030, with outdoor monitoring above 65% of revenue [1]. IMARC estimates USD 5.52B in 2025, rising to USD 9.49B by 2034 [2]. These syndicated estimates disagree in their details and should be used only to say "this is a real, growing market," never as a bottom-up market size.

The more important finding is about calibration's price. Clarity, the sensor supplier behind Breathe London, states that "calibration is included free of charge with Sensing-as-a-Service," including remote global and local calibration [4]. EarthSense sells its Zephyr monitor as one annual subscription covering hardware, modelling, platform and support. A UK council paid £2,025 per unit per year for that service in 2025/26 [5]. Kunak offers remote calibration in its own cloud [14]. Clarity's own 2026 pricing guide puts mid-tier sensors at $500–5,000 upfront, against $15,000–40,000 for regulatory monitors, which can cost more than $15,000 a year to run [3].

Calibration is genuinely necessary. Vital Strategies notes that calibration factors for low-cost PM2.5 sensors "change with time and space," because particle optical properties shift with season and humidity [6]. PurpleAir data shows bias drifting by about −0.12 µg/m³ per year, with flagged readings rising to about 4% after four years [9], and about 2% of PurpleAir sensors becoming permanently degraded [10]. Recalibration research continues to find that co-location calibration is costly and interrupts data collection [7]. But because vendors give calibration away inside their subscriptions, **a standalone "we calibrate your sensors" product would compete with free.** That rules out the most obvious version of the pitch.

What vendors do not provide is independence. Clarity calls its method "proprietary Remote Calibration" [4]. The party that sells the sensor is also the party that certifies its accuracy. Finding 3 shows why that matters now.

---

## Finding 2: The regulatory clock creates a reason to buy now

Directive (EU) 2024/2881 must be transposed into national law by 11 December 2026, and its rules apply from 12 December 2026 [12]. It cuts the PM2.5 annual limit from 25 to 10 µg/m³ and PM10 from 40 to 20 µg/m³ by 2030 [13]. For the first time, it sets numeric data-quality limits for each type of evidence. For PM2.5, fixed measurements may carry at most 3.0 µg/m³ or 30% uncertainty, indicative measurements at most 4.0 µg/m³ or 40%, and modelling and objective estimation at most 1.7 times the uncertainty of fixed measurement [11]. CEN/TS 17660 maps sensor systems onto these classes: Class 1 meets the requirements for indicative measurement and Class 2 those for objective estimation [14].

This matters directly to AeroLoop. The directive turns "is this sensor or model good enough?" into a measurable pass/fail question. AeroLoop's holdout gate is already a measure of uncertainty against reference data. Extending it to report against the directive's uncertainty limits is a small step in engineering terms and a large one in positioning.

The industry is pushing in the same direction. On 15–17 July 2026, five sensor companies launched Clean Tech for Clean Air (CT4CA) in Brussels. It calls for formal recognition of high-quality small sensors, use of existing European technical specifications, and "greater acceptance of reliable sensor data by public authorities" [15]. The European Commission's own environment news service says plainly that accuracy issues "prevent low-cost sensors from being used to support official measures like the revised EU Ambient Air Quality Directive" [16]. Reviews in npj Climate and Atmospheric Science name lack of trust, limited metadata and missing quality standards as the barriers to policy acceptance [37].

In the US, the EPA has published performance targets for PM2.5 sensors (2021) and for PM10, NO2, CO and SO2 sensors (2024) [8]. It applies its own correction equation to PurpleAir data before showing it on the AirNow Fire and Smoke Map [38]. In England, the Environment Act sets a legally binding PM2.5 target of 10 µg/m³ by 2040 and a 35% cut in population exposure from 2018 levels [36].

The combined picture: regulators are setting numeric standards for evidence, vendors want their data accepted, and **nobody in the chain is an independent party producing the proof.** That is the gap to occupy.

---

## Finding 3: UK construction dust monitoring is the sharpest first market

Construction and demolition monitoring has three things the council market lacks: a private payer, existing legal triggers, and a trust problem on public record.

**A private payer and legal triggers.** Under Section 61 of the Control of Pollution Act 1974, consents routinely require continuous PM10 monitoring at site boundaries, and planning conditions frequently require dust monitoring too [19]. IAQM guidance is non-statutory, but local planning authorities often make it a planning condition [18]. The 190 µg/m³ one-hour PM10 trigger comes from government-funded research [21] and is used in live reporting, for example in a September 2025 monthly report filed by the London Borough of Hammersmith and Fulham on GOV.UK. Consultancies price deployments at **£500–1,500 per monitoring point per month**, including equipment, telemetry, calibration and reporting [20]. The developer or contractor pays, not a cash-strapped council.

**A documented trust gap.** In September 2025, the IAQM published a position statement on low-cost PM10 sensors near construction sites. It says that many such devices **under-report PM10 at concentrations near or above the 190 µg/m³ action level**, "risking undetected dust events," and that certifications such as MCERTS or PAS 4023:2023 alone do not guarantee suitability [17][18]. In other words, the professional body is saying that the very thing these sensors exist to catch, exceedances, is where they are least reliable, and that existing certificates are not enough.

**Why AeroLoop fits.** AeroLoop's core mechanism is: lock the prediction before the truth arrives, then score it on reference data it never tuned on. That is exactly the evidence a planning officer or IAQM-minded consultant needs to answer "was this sensor fit for purpose near the action level, at this site, this month?" The rejected-strategy record also matters here. It shows the corrections were not tuned after the fact to make a site look compliant, which protects the contractor, the consultant and the local authority.

**Pricing hypothesis (needs testing).** A verification layer sold to monitoring consultancies at roughly £50–150 per point per month would be about 10% of what is already spent per point [20], below the £2,025 per unit per year that councils pay for a full EarthSense subscription [5]. No source was found giving the number of UK sites under active dust monitoring. That count is the first thing to confirm in customer interviews.

---

## Finding 4: Councils, the obvious buyer, are the wrong first buyer

It is tempting to pitch local authorities, since they own the duty to manage local air quality. The evidence argues against leading with them. Freedom of Information data reported by CIEH in December 2025 shows the dedicated air-quality grant for English councils fell to **£1.5M in 2024/25, a 99.4% drop** from a peak of £225M in 2020/21, against an average of £71.8M a year from 2016/17 to 2023/24 [22]. Defra says it has provided £575M since 2018 [22]. Emeritus Professor James Longhurst is quoted saying councils' "capacity and capability… to discharge their air quality duties… has been severely diminished" [22].

Councils still buy. UK tender trackers list more than a hundred air-quality monitoring contract awards, and Luton awarded a sensor-network supply contract to Ricardo-AEA (UK procurement listings; low-confidence). But these are slow, procurement-heavy sales, and councils mostly buy hardware bundles from incumbents. A better route to councils is indirect: council planning officers read the construction dust reports, so if AeroLoop's verification appears in those reports, councils become users before they are buyers.

The health stakes are why this matters at all. Air pollution is linked to 28,000–34,000 UK deaths a year and £27B in healthcare and productivity costs [22]. The World Bank puts global health damages from air pollution at $8.1 trillion, or 6.1% of global GDP (World Bank).

---

## Finding 5: Hyperlocal data shows exits exist, but it is the wrong place to start

There is evidence that verified hyperlocal air-quality data is valued at acquisition scale. Google bought BreezoMeter in September 2022 for over $200M [26]. AccuWeather bought Plume Labs in January 2022 [27]. Google's Air Quality API now charges $5 per 1,000 calls beyond a free 10,000 a month [25]. PurpleAir moved its API to paid, points-based pricing [28]. Ambee has raised about $33M (Caplight). On the hardware side, Clarity has raised a $9.6M Series A+ [39] and Airly about $8.8M [40], which shows modest venture scale for sensor companies.

Competing head-on with Google on map-level data needs global coverage and distribution that a hackathon project cannot reach. The sensible use of this evidence is as an **exit path and a long-term data channel**: a corpus of verified corrections, each with a held-out score, is the kind of asset data platforms buy or license. It is not a first product.

---

## Finding 6: Reppo and SERV fit this positioning unusually well

**Reppo.** The Reppo Evaluation API returns a score (0–100), a decision (accept/revise/reject), a confidence level and a written critique for each dimension. Reppo's own documentation is inconsistent on price and latency: the docs site lists 1¢ per evaluation with a settlement window of 10 minutes or more [29], while its agent integration guide (eval.reppo.xyz/agents.md, checked 2026-11-15) lists 440 credits per text evaluation (about $0.22 when bought over x402), results in 30–90 seconds, and keyless x402 payment. A live call on 2026-11-15 confirmed the agent guide's API is the current one: 440 credits per text evaluation, verdict in about 90 seconds. Either way the cost per check is cents. Reppo explicitly pitches its verdict records as audit evidence for the EU AI Act [29]. Evaluations are currently public [29]. That rules out confidential use cases but is harmless for air-quality data, which is public anyway. At the protocol level, Reppo is a prediction-market network: Datanets in which contributors submit data and domain experts stake REPPO tokens on its quality [30]. AeroLoop's predict-before-truth records are naturally verifiable prediction data, so a later "air-quality calibration Datanet" is a plausible second revenue line. Treat that as speculative.

In AeroLoop, the split of duties is clean. The holdout error judges whether a correction is accurate. Reppo's peer verdict judges whether the correction is a sound explanation: physically plausible, not overfitted, not quoting a test value. A change ships only if both pass. That is precisely the "independent auditor" story, and it uses Reppo for what Reppo does best.

**SERV.** OpenServ says SERV compiles prompts into a bounded reasoning graph so that smaller, cheaper models can match frontier models, for example SERV Nano at roughly 20x lower cost than GPT-5.4 [31]. Its vision document cites government production work through Neol and a compliance test with zero false approvals [32]. Independent coverage notes these are **project-reported benchmarks** [31]. AeroLoop can test that claim on hidden data in a domain where the answer cannot be faked. If SERV-driven strategy changes beat the baseline model's changes on the holdout, that is independent evidence for OpenServ's central claim. If they don't, the honest record is still credible. Either way, it aligns with the organiser's own story, and their positioning toward government buyers matches AeroLoop's regulatory angle.

**Distribution.** OpenServ runs an x402 pay-per-use marketplace for agent services (OpenServ x402 Agent Market), and Coinbase's Agentic.market reports more than 165M x402 transactions and roughly $50M in volume [33]. A pay-per-call "verify this sensor series" endpoint is a credible, cheap channel to developers in the agent economy, once the core product works.

---

## Synthesis & Insights

**1. The product is the proof, not the prediction.** Forecasts are commoditised (Google, Tomorrow.io, Ambee), and calibration is bundled for free [4][5][25]. What nobody sells is independent, tamper-evident proof that a correction is valid on data it never tuned on. AeroLoop's distinctive habits (saving predictions before truth, a chronological holdout, and keeping rejected ideas in the record) are exactly what makes such proof credible. *This is the core analytical claim of the report; it is inferred from the sources rather than stated by any of them.*

**2. Independence is the moat.** A vendor cannot credibly audit its own sensors. An independent verifier that works across vendors (Clarity, EarthSense, Kunak, PurpleAir, and also models such as CAMS) sits where incumbents cannot. That also makes the sensor coalition a potential **partner rather than a competitor**: verified data is what CT4CA says it needs authorities to accept [15].

**3. Timing beats market size.** The directive's numeric uncertainty limits take effect on 12 December 2026 [11][12]. IAQM's statement already questions sensor fitness near action levels [17]. These are buying triggers with dates, which judges reading "revenue potential" will value above a large market-size number.

**4. The general version is the long-term upside, not the pitch.** "Verified self-correction for any forecast whose truth arrives later" sits beside AI evaluation and observability, where Arize raised a $70M Series C [34] and eval-focused startups have raised tens of millions each [35]. Use this as one sentence about the long-term vision, not as the headline.

### Locked positioning

> **AeroLoop: the independent auditor for air-quality data.**
> It corrects any sensor or model against reference monitors, proves every correction on held-out data it never tuned on, has each change peer-verified through Reppo, and keeps an audit trail of what changed and why, including the rejected ideas.

**For:** environmental consultancies running construction and demolition dust monitoring in the UK (first market). Then EU sensor operators and integrators who need independent evidence of indicative-measurement quality under 2024/2881.
**Against:** vendor self-calibration (proprietary, not independent) and black-box hyperlocal APIs (no verifiable error record).
**Because:** regulators now set numeric uncertainty limits [11], the professional body says certificates are not enough [17], and the evidence trail is what is missing.

### How this maps to the three judging criteria [42]
- **Creativity:** an agent that audits its own learning. It cannot keep a change it can't prove on hidden data, and its reasoning is peer-reviewed. It also tests OpenServ's own claim about small models.
- **User readiness:** a working dashboard, real LAQN reference data, a one-click demo, and a report expressed in units a buyer already uses (the 190 µg/m³ PM10 trigger, the directive's uncertainty limits, EPA sensor targets [8]).
- **Revenue potential:** a named first buyer that pays £500–1,500 per point per month today [20], a dated regulatory trigger [12], and a clear pricing hypothesis (about 10% of existing spend per point).

---

## Limitations & Caveats

**Counterevidence and risks.** First, open and academic correction methods exist. The University of Cambridge network calibration used by Breathe London [24] and the European FILTER framework (13.2B observations; corrected values for 52.5% of measurements) [16] show that correction itself is not proprietary. The defensible part is independent verification and the audit trail, not the correction algorithm. Second, the IAQM statement cuts both ways. If the hardware cannot read correctly near 190 µg/m³, software correction may be unable to rescue it in that range. AeroLoop must be willing to say a sensor is *not fit* for a site; that honesty is a feature, but it limits what can be promised. Third, AeroLoop's current validation is on PM2.5 from CAMS model output at four London stations. Construction monitoring is about PM10 near sources, so the first customer needs new data (sensor series co-located with reference monitors) and a PM10 evaluation. Fourth, Reppo evaluations are public [29], which rules out confidential use, and its documented latency ranges from 30–90 seconds to 10+ minutes depending on which of its two APIs is used; a live call on 2026-11-15 confirmed the agent guide's API (verdict in about 90 seconds).

**Evidence gaps.** No source gives the number of UK sites under active dust monitoring, so the market size for the first market is unverified. The verification pricing is a hypothesis, not a validated number. OpenServ's SERV benchmarks are reported by the project itself [31]. Market-size reports [1][2] are low-confidence. The EU AI Act timeline citation [41] comes from a secondary blog; it is not used for any load-bearing claim.

**Next validation steps.** Run five to ten interviews with UK construction-monitoring consultancies (for example firms that publish IAQM-aligned dust services) to test willingness to pay and the per-point price. Ask one council environmental health officer whether an independent verification appendix would change how they review Section 61 monitoring reports.

---

## Recommendations

**For the hackathon submission (positioning only; implementation to be agreed separately):**
1. Re-title and re-pitch around "the independent auditor for air-quality data," and drop the Hacktoberfest "ghost" framing from the opening, keeping it as visual flavour only.
2. Integrate SERV Reasoning as the engine that proposes strategy changes, and report holdout results for SERV against the baseline model. This tests OpenServ's small-model claim honestly.
3. Gate each strategy change on **both** the holdout improvement and a Reppo `accept` verdict, and store the verdict, confidence and critique in the run report.
4. Add a verification summary in buyer units: holdout error against the EU 2024/2881 indicative-measurement limits [11], EPA sensor targets [8], and, where PM10 data exists, behaviour near 190 µg/m³ [21].
5. Make the write-up's revenue section: named first buyer → existing spend per point → dated regulatory trigger → pricing hypothesis → longer-term data and x402 channels.

**After the hackathon:**
1. Run the customer interviews above before building more.
2. Add an ingestion path for sensor series (PurpleAir, sensor.community, vendor APIs) co-located with LAQN/AURN reference sites, and a PM10 evaluation.
3. Explore partnership rather than competition with CT4CA members, offering independent verification for their tender bids.

---

## Bibliography

[1] Grand View Research. "Air Quality Monitoring System Market Size Report, 2030." https://www.grandviewresearch.com/industry-analysis/air-quality-monitoring-system-market
[2] IMARC Group. "Air Quality Monitoring Market Size, Share & Forecast 2034." https://www.imarcgroup.com/air-quality-monitoring-market
[3] Clarity Movement Co. (2026). "Cost of air quality monitoring: A pricing guide for cities & agencies." https://www.clarity.io/blog/cost-of-air-quality-monitoring-a-pricing-guide-for-cities-agencies
[4] Clarity Movement Co. "Air Quality Sensors Calibration." https://www.clarity.io/air-quality-monitoring-solution/project-support/calibration
[5] Charnwood Borough Council. "DD253 – Purchase of Air Quality Monitoring Equipment." https://www.charnwood.gov.uk/files/documents/dd253_purchase_of_air_quality_monitoring_equipment/DD253%20-%20Purchase%20of%20Air%20Quality%20Monitoring%20Equipment.pdf
[6] Vital Strategies. "Integrated Use of Low-Cost Sensors to Strengthen Air Quality Management." https://www.vitalstrategies.org/wp-content/uploads/Integrated-Use-of-Low-Cost-Sensors-to-Strengthen-Air-Quality-Management.pdf
[7] Gäbel, P. & Hertig, E. (2026). "Recalibration of low-cost O3 and PM2.5 sensors." Atmos. Meas. Tech. 19, 1293–1321. https://opus.bibliothek.uni-augsburg.de/opus4/files/128274/128274.pdf
[8] US EPA. "Air Sensor Performance Targets and Testing Protocols." https://www.epa.gov/air-sensor-toolbox/air-sensor-performance-targets-and-testing-protocols
[9] PurpleAir. "Scientific Papers" (sensor degradation summary). https://www.purpleair.com/papers
[10] "An analysis of degradation in low-cost particulate matter sensors." PMC10208317. https://pmc.ncbi.nlm.nih.gov/articles/PMC10208317
[11] EUR-Lex. Directive (EU) 2024/2881, Annex on data quality objectives. https://eur-lex.europa.eu/eli/dir/2024/2881/oj/eng
[12] EUR-Lex. "Cleaner air for Europe" (summary). https://eur-lex.europa.eu/EN/legal-content/summary/cleaner-air-for-europe.html
[13] Envira. "Summary of the new provisions of European Directive 2024/2881." https://envira.global/new-european-air-quality-directive-2024-2881
[14] Kunak. "How to choose an air quality sensor for your project" (CEN/TS 17660 classes). https://kunakair.com/how-to-choose-air-quality-sensor
[15] Lawrence, C. (2026, July 17). "Five startups spearhead coalition to put small air quality sensors at the heart of EU clean air policy." Tech.eu. https://tech.eu/2026/07/17/five-startups-spearhead-european-push-for-smarter-air-quality-monitoring
[16] European Commission DG ENV (2025, Nov 6). "Air pollution data from citizen-operated sensors improved by novel quality control system" (Hassani et al. 2025, J. Env. Mgmt 380:125100, https://doi.org/10.1016/j.jenvman.2025.125100). https://environment.ec.europa.eu/news/air-pollution-data-citizen-operated-sensors-improved-novel-quality-control-system-2025-11-06_en
[17] IAQM (2025, Sept). Position Statement on low-cost PM10 sensors near construction sites (announcement). https://www.linkedin.com/posts/institute-of-air-quality-management-iaqm_iaqm-publishes-position-statement-on-the-activity-7374004281806331904-rvaI
[18] Clarity Movement Co. "UK construction dust monitoring: Rules and best practices." https://www.clarity.io/blog/construction-demolition-dust-monitoring-in-the-uk-regulations-requirements-and-best-practices
[19] Sensorbee. "Dust Monitoring: IAQM Construction Guide." https://www.sensorbee.com/guides/dust-monitoring-construction-industrial
[20] Alkali Consultants. "Construction Dust Monitoring UK | Real-Time PM10 Alerts." https://alkaliconsultants.com/air-quality-services/construction-dust-monitoring-pm10
[21] GOV.UK. "Testing PM10 trigger values at construction sites." https://assets.publishing.service.gov.uk/media/5a750e9640f0b6360e473009/construction_site_dust_monitoring_report.pdf
[22] Smethurst, S. (2025, Dec 4). "Councils' air pollution grant 'drastically reduced'." CIEH Environmental Health News. https://www.cieh.org/ehn/environmental-protection/2025/december/councils-air-pollution-grant-drastically-reduced
[23] Clarity Movement Co. "Breathe London Case Study." https://www.clarity.io/customer-stories/breathe-london
[24] Environmental Defense Fund. "Breathe London network-based calibration method." https://www.edf.org/sites/default/files/documents/Breathe%20London-Network%20calibration%20methodology.pdf
[25] Google for Developers. "Google Maps Platform core services pricing list" (Air Quality SKU). https://developers.google.com/maps/billing-and-pricing/pricing
[26] Vidal, E. (2022, Sept 20). "Google acquires Israeli climatech startup BreezoMeter for over $200 million." Ctech. https://www.calcalistech.com/ctechnews/article/sycbrdpbi
[27] TechCrunch (2022, Jan 24). "AccuWeather acquires air pollution startup Plume Labs." https://techcrunch.com/2022/01/24/accuweather-acquires-air-pollution-startup-plume-labs
[28] PurpleAir Community. "API Pricing." https://community.purpleair.com/t/api-pricing/4523
[29] Reppo. "What is the Reppo Evaluation API?" https://docs.reppo.ai/concepts/evaluation-api
[30] Kraken Blog. "REPPO is available for trading!" (Datanets overview). https://blog.kraken.com/product/asset-listings/reppo-is-available-for-trading
[31] OpenServ. "SERV Reasoning Public API is Now Live." https://www.openserv.ai/blog/serv-reasoning-public-api-is-now-live ; see also CryptoSlate, "Crypto AI project OpenServ says it can beat OpenAI, but the real test starts now." https://cryptoslate.com/openserv-openai-benchmark-claims-proof-threshold
[32] OpenServ (@openservai). "The SERV Vision and Roadmap." https://x.com/openservai/article/2065790589329690851
[33] Coinbase Developer Platform. "Introducing Agentic.Market." https://www.coinbase.com/developer-platform/discover/launches/agentic-market
[34] PR Newswire (2025, Feb 20). "Arize AI Secures $70M Series C." https://www.prnewswire.com/news-releases/arize-ai-secures-70m-series-c-to-fix-ais-biggest-problem-making-llms-and-ai-agents-work-in-the-real-world-302381601.html
[35] Presenc AI (2026, May). "AI Agent Evaluation and RLHF Startups Landscape." https://presenc.ai/research/ai-agent-evaluation-startups-2026
[36] GOV.UK. "Air quality Environment Act target delivery plan." https://www.gov.uk/government/publications/air-quality-environment-act-target-delivery-plan/air-quality-environment-act-target-delivery-plan
[37] npj Climate and Atmospheric Science (2025). "Evolving trends in application of low-cost air quality sensor networks: challenges and future directions." https://www.nature.com/articles/s41612-025-01216-4
[38] US EPA. "EPA Research Improves Air Quality Information for the Public on the AirNow Fire and Smoke Map." https://www.epa.gov/sciencematters/epa-research-improves-air-quality-information-public-airnow-fire-and-smoke-map
[39] Clarity Movement Co. "Clarity raises $9.6M in Series A+ funding." https://www.clarity.io/blog/clarity-movement-co-raises-us-9-6m-series-a-co-led-by-amasia-and-active-fund
[40] LeadIQ. "Airly Company Overview" (funding history). https://leadiq.com/c/airly/5a1dc9c02300005400cea2ba
[41] Synapt. "EU AI Act Article 12 Explained." https://www.synapt.ai/layered-by-synapt/eu-ai-act-article-12-decoded
[42] OpenServ. "SERV Hackathon — Edition 02." https://www.openserv.ai/hackathon-2

Additional sources referenced inline: World Bank, "The Global Health Cost of PM2.5 Air Pollution" (https://openknowledge.worldbank.org/entities/publication/c96ee144-4a4b-5164-ad79-74c051179eee); Caplight, "Ambee Valuation & Funding History" (https://www.caplight.com/company/getambee); OpenServ x402 Agent Market (https://platform.openserv.ai/x402-services); UK procurement listings (https://bidskim.com/contracts/air-quality-monitoring, https://www.govmarket.uk/contract/supply-and-maintenance-of-air-pollution-sensor-network-for-luton-council-277057).
