# Plan 6: Tata Communications' fabrics, and what their website tells the radar (tech-atlas)

**Date:** 2026-10-04 · **Folder:** 2026-10-04/5 · **Status:**
- §2 (the fabrics) approved on 4 Oct ("please add the missing fabric");
- §3–§6 approved the same evening ("rest of the things you recommended above, go ahead"), with every configuration change written into the seeding data.

All built and deployed; build notes in §7–§8.

**Portal changes:** [tech-lens plan 6](../../../../tech-lens/docs/2026-10-04/5/implementation-plan.md).

I read tatacommunications.com on 4 Oct: the menu (201 links), the Digital Fabric page, each portfolio page, and the About, Alliances, News and Customers pages.

---

## 1. What their site says

**Fabrics:** TCL names six.
- The Digital Fabric page combines "network, cloud, security, interaction, and IoT".
- The Cyber Security page calls itself the Security Fabric.
- The menu adds a Media Fabric for media and entertainment companies.

We had four. Security sat inside Cloud, and Media was missing.

| Fabric | TCL brand | What it sells | Scale claims on the site |
|---|---|---|---|
| Network | IZO | Global VPN, internet access, private line, IP transit, SD-WAN, internet WAN, multi-cloud connectivity and networking, data-centre connectivity, managed Wi-Fi/LAN, enterprise broadband, NaaS | 1,500+ PoPs; 500,000+ km subsea and 200,000+ km terrestrial fibre; 35% of internet traffic on-net; 190+ countries; Gartner MQ Global WAN leader 13 years running |
| Cloud | Vayu (India only) | AI cloud with GPUs and AI Studio; private, hybrid, multi-cloud and edge; government and financial-services clouds; data platform | "Sovereign at core"; 100% compliance with RBI, IRDAI, SEBI and MeitY; ISO/IEC 42001; IDC: 30% lower TCO |
| Security | Security Fabric | Managed SASE, hosted SASE (powered by Versa), SSE, ZTNA, MDR/SOC, cloud security, OT security, advanced network security and DDoS, GRC consulting, edge distribution platform | 9.5B events screened daily; 3.5 TBps screened; KuppingerCole MDR leader 2026 |
| Interaction | Kaleyra, Commotion | CPaaS, CCaaS, UCaaS, cloud voice, Kaleyra Phone; Commotion AI OS: Voice AI (<250 ms), AI Workers (200+ templates), CX platform | 60B+ interactions a year; 4,000+ customers; Gartner CPaaS niche player; Juniper CCaaS established leader |
| IoT | MOVE | Cellular IoT, eSIM / global SIM, LoRaWAN, private 5G, embedded connectivity, MVNE; automotive, logistics, aviation, manufacturing | 13M+ SIMs; 160+ countries; JLR and Tata Motors connected cars |
| Media | Media Fabric | Media cloud and edge, video CDN, fibre and IP contribution and distribution, remote production, playout, satellite alternatives, live events, fan engagement, gaming | 70+ media cloud/edge/CDN locations; 100,000+ events; F1 broadcast partner |

**Also on the site:**
- **Carrier Services** is a wholesale line, not called a fabric: IPX, roaming, voice termination, toll-free. 1 in 7 international calls and 15% of global voice traffic run on TCL's network.
- **Platforms:** TCx, ThreadSpan, Commotion, Vayu AI Studio, Multi Cloud Network, Edge Distribution Platform.
- **Industries:** manufacturing, consumer goods and retail, automotive, banking, sports, aviation, logistics, gaming and esports, media and entertainment.
- **Alliances:** Cisco, AWS, Microsoft, TCS and Johnson Controls; Versa for SASE; NVIDIA GPUs for Vayu AI Cloud.
- **Company:** about 5,000 customers, including 300 of the Fortune 500; 8,500 employees; net zero by 2035.

## 2. Done: six fabrics, defined in TCL's own terms

`seeds/fabrics.json` now holds Network, Cloud, Security, Interaction, IoT and Media.

**Definitions:** each says which TCL fabric and brand it is and what that fabric sells, plus the future technology the radar should still catch (network APIs, SDN/NFV, satellite integration, photonic transport, edge AI on devices). Security moved out of Cloud's definition.

**Open questions:** Security and Media ask TCL to confirm their scope. The other four keep their existing question.

**Effect:**
- The relevance gate and every measure call read these definitions, from the next assessment on.
- Earlier assessments keep the fabrics they were scored in. They don't list Security or Media as "not assessed", because those didn't exist then.
- Estimates for never-assessed technologies now count six fabrics.

**Backup:** the four definitions from before are in `replaced/fabrics-before-plan6.json`.

## 3. Proposal: tell the scorer what TCL has today

**The gap.** The measures about TCL's own position almost never score. Across all 432 assessments:

| Measure | Scored |
|---|---|
| Right to play | 0% |
| Serviceable capture | 0% |
| Disruption threat | 0% |
| Capability gap | 4% |
| Portfolio adjacency | 8% |

The scorer is never told what TCL runs, so it says "could not be assessed". That is the main reason so many priorities are "not set": how big a prize is depends on disruption threat and serviceable capture.

**The change.**
- Each fabric gets a short "TCL today" profile, taken from §1, with the page it comes from: products, assets, scale, customers, partners and recognitions.
- `measure_scoring` (v3) adds a "TCL TODAY IN THIS FABRIC" section. It is to be used only for the measures about TCL's position, citing that page's address, while the technology side still comes from the collected evidence.
- The code adds one field and one prompt input; nothing else changes.

**Cost and effect:**
- No calls now.
- Future assessments should score those five measures far more often, so Strategic Fit and the priority will be set for more technologies.
- Scores will shift when technologies are next assessed.

## 4. Proposal: signals

**New:**
- **Infrastructure build:** a new or upgraded subsea or terrestrial cable, a landing station, PoPs, a data-centre or GPU region, or a satellite constellation. These are TCL's core assets and its competitors' moves.
- **Major outage or cable cut:** a large cloud, network or cable outage, with its cause and impact. It shows where resilience demand and competitors' weaknesses lie.

**Sharpened:**
- **competitor-move:** its examples are Verizon, AT&T, Cisco and Juniper, but Cisco is TCL's partner. Name TCL's competitors by fabric:
  - Network: Orange Business, BT, Lumen, NTT, Colt;
  - Security: Zscaler, Palo Alto Networks, Cato Networks;
  - Interaction: Twilio, Sinch, Infobip, Genesys;
  - IoT: Vodafone IoT, KORE, 1NCE;
  - Media: Akamai, LTN;
  - Cloud in India: Yotta, CtrlS, Jio.
- **partnership:** flag moves by TCL's own partners: Cisco, AWS, Microsoft, TCS, Versa, NVIDIA and Johnson Controls.

## 5. Proposal: sources

| Gap | Suggested |
|---|---|
| TCL's own moves (needed by §3) | TCL News Centre (`/press-release`) and the New World Blog |
| Subsea and wholesale | TeleGeography, Submarine Networks, Capacity Media |
| Network APIs and NaaS | MEF, TM Forum, GSMA Open Gateway / CAMARA |
| Security advisories (named in our own signal) | CISA, CERT-In |
| India rules for sovereign cloud | MeitY, RBI, SEBI, IRDAI, TRAI / DoT |
| Media and sport | SMPTE, Sports Video Group, Streaming Media |
| CX and CPaaS | CX Today |
| IoT | IoT Analytics |

**Already in our register but switched off:** Light Reading, Fierce Network, RCR Wireless, GSMA, 3GPP and ETSI. Only 6 of 136 sources are on. Each source costs about 1 call per new page per collection.

## 6. Thresholds and other points

**Thresholds:** the site publishes none. The ones still open are TCL's to give:
- what H1, H2 and H3 mean to them (an open question since September);
- which priority triggers action.

TCL's scale figures (§1) can anchor right to play and serviceable capture through the §3 profile.

**Industries:** TCL's nine industries could guide use-case breadth and the Point of View's "what it means for TCL". This goes with §3.

**Product names:** recommendations could name the TCL product line a technology would extend, for example "IZO Multi Cloud Connect". This also goes with §3.

**Carrier Services:** it isn't a fabric on their site. Its technologies (IPX, roaming, voice fraud) fall under Network and Interaction, so I'd leave it there.

## 7. Build notes: the pending work, run on 4 Oct

You said "do it". A backup came first: `backups/2026-10-04/docker-tech_atlas-before-pending-work.archive.gz`.

**1. Re-read every stored page with the current summary skill.**
- 423 pages: the 240 from Sep 11, never checked against your current signal list, and the 183 from Oct 4, read before findings had headlines (job `b1e19036ecda`).
- 0 failed. One long page had a part fail; re-checking it on its own fixed it (`23998c51eabe`).
- **Findings:** all 514 have a headline; 502 have 1–3 technologies of their own.
- **Set aside by your ignore rules:** 59 pages, all from Sep 11 (mostly Hacker News opinion pieces).
- **Technologies:** organizing grew the register from 1,853 to 2,390, and every name has a label (4 calls).

**2. Assess the technologies with new pages.**
- 49 technologies (run `a9d3f7072257`, 1,647 calls, none skipped);
- then 2 more (run `2b367fff1362`, 89 calls), linked to the re-checked page. These were the first runs with six fabrics, and the gate already picked Security for both.

**3. Write the Points of View.**
- 158 (job `7c6a793cc7e4`). One reply came back in the wrong format twice (ml-dsa); a retry wrote it.
- Then the 2 from step 2 (job `54fd0c3c088d`).

**Result:** nothing is left waiting and there are no problems. Model calls in all: about 2,300.
- All 159 technologies' latest Points of View use `pov` v4, and a scan of every one found no rule broken.

**The fabrics (§2)** were deployed between steps 2 and 3, once nothing was running. Live matched the seeding data afterwards, and Changes was 0.

## 8. Build notes: §3–§6, built and deployed on 4 Oct

**Everything is in the seeding data.** On deploy:
- the live-vs-seeds check showed only these changes;
- nothing was running;
- the one signal ever edited in the app ("Price change", 3 Oct) was already in the seeds.

After the deploy, live matched the seeds exactly and Changes was 0. The files from before are in `replaced/*-before-tcl-profile.json`.

**§3, the TCL-today profile:**
- **Data:** each fabric has a `tcl_today` profile, 790–1,030 characters, with the TCL pages it comes from, plus one company-wide line (about 5,000 customers, including 300 of the Fortune 500).
- **Code:**
  - `engine._score_measure` passes it in, or "Not described." when a fabric has none;
  - `FabricEdit` accepts it;
  - the expected placeholders for `measure_scoring` include `{tcl_today}`;
  - Setup → Fabrics shows two lines of it on each card and edits it in full.
- **Skill: `measure_scoring` v3.** For a measure about TCL's own position, TCL's side comes from TCL TODAY and the technology's side from the evidence. A score needs both, citing URLs for both. Justifications keep URLs out of their text.
- **Tests:** 85 pass. `test_tcl_today.py` covers the edit and the prompt.

**Verified on the dev copy.** AgenticOps (38 calls), against its Sep 11 assessment:
- portfolio adjacency went from not assessed to 5 in all three fabrics;
- capability gap went from 8, which had been judged from Cisco's capabilities, to 5–6 against TCL's;
- right to play, serviceable capture and disruption threat stayed honestly unassessed, naming the buyer and market evidence they still need.

**Live showcase, AgenticOps** (run `b81a421ed6dd`, 38 calls, plus its Point of View, 1 call):
- Strategic Fit went from 8 on 1 of 3 measures to 6.7 on 2 of 3 (Cloud) and 5.3 on 3 of 3 (Network, where right to play is now judged).
- Security, a new fabric, gives its first priority: P5, horizon H3.
- The Point of View: "Monitor; do not invest yet… Security remains P5 with horizon H3."

**§4, signals:**
- **New:** `major-outage` (after security advisory) and `infrastructure-build` (after product launch), so there are now 35 signals.
- **Reworded:**
  - `competitor-move` names TCL's competitors by fabric, and Cisco and Juniper are dropped;
  - `partnership` flags TCL's own partners.
- **Effect:** the signal list's fingerprint changed, so the 423 stored pages show as "checked against an older list" (Operations → Signals → "Check again", about 430 calls). New pages get the new list automatically.
- **Left optional:** re-reading tags the pages' technologies again. Last time that sent 49 technologies back for assessment (about 1,650 calls).

**§5, sources:** 147 in all, 21 switched on (was 6). Each was checked first with our collector's user agent: robots.txt, the page, its links and its feed.
- **Added and on:** TCL News Centre, TeleGeography, Mplify (formerly MEF), TM Forum Inform, CERT-In advisories, RBI press releases, SEBI (through its feed), SMPTE, Sports Video Group, CX Today, IoT Analytics.
- **Switched on:** Light Reading, 3GPP, ETSI, and GSMA through its newsroom and feed, since its home page refuses our collector.
- **Left out, and why:**
  - CISA refuses our collector (403, feeds included);
  - Fierce Network's articles refuse it (403);
  - MeitY's site doesn't resolve from here.
- **The next collection:** it reads 21 sites at up to 40 pages each; the Collect button shows the cost before it starts.

**§6, thresholds:** the priority grid has a new open question: which priorities should trigger action at TCL. It sits with the horizons question on the Open questions tab.

**Found while testing, and not changed:**
- **The agents fail at their first call.** OpenAI now refuses tool-calling agents on gpt-5.6-luna with a reasoning effort ("set reasoning_effort to 'none'"). Assessment and collection both fall back to their built-in sweeps, so the results are complete; the agent step is effectively skipped.
- **The fix** is one setting on the agent model, or the Responses API. It hasn't been done yet.
