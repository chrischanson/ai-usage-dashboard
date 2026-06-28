# 🏆 World Cup 2026 Prediction Tracker

> This file is the persistent memory of the AI prediction system. It is read by every skill and updated by the `predict` and `postmortem` skills. **Do not edit manually** unless correcting data errors.

---

## Tournament Overview

- **Tournament:** FIFA World Cup 2026 (USA / Canada / Mexico)
- **Dates:** June 11 – July 19, 2026
- **Current Phase:** Group Stage
- **Tracking Started:** 2026-06-13
- **Total Matches Tracked:** 48
- **Pre-Game Accuracy (Final Pre-Kickoff):** 64.3% (27/42)
- **Half-Time Accuracy (Frozen/Live):** 62.2% (23/37)

---

## Accuracy by Confidence Level

### Pre-Game (Pre-Kickoff)
| Confidence | Correct | Total | Accuracy |
|:-----------|:--------|:------|:---------|
| High       | 4       | 5     | 80.0%    |
| Medium     | 15      | 23    | 65.2%    |
| Low        | 8       | 14    | 57.1%    |

*(Note: Germany vs. Curaçao was predicted as GERMANY WIN with High confidence pre-game, and USA vs. Australia was predicted as DRAW with Low confidence pre-game. This table shows pre-kickoff lineup-verified prediction performance. On 2026-06-20, Ecuador vs. Curaçao was the first High-confidence prediction failure — Ecuador's clinical finishing deficiency was identified but not properly enforced as a confidence cap. On 2026-06-21, SPAIN WIN (High) was correct, DRAW (Low) was correct, URUGUAY WIN (Medium) was incorrect (frozen at HT, lost 2-2 on set-piece goals), and EGYPT WIN (Medium) was correct (trailed 1-0 at HT but won 3-1, WHT downgraded to Low). On 2026-06-22, JOR-ALG (ALGERIA WIN Medium) was correct but the Clinical Finishing Gate was not properly enforced — a compliance violation documented in the postmortem.)*

### Half-Time (Frozen / Live-Monitoring)
| Confidence | Correct | Total | Accuracy |
|:-----------|:--------|:------|:---------|
| High       | 2       | 3     | 66.7%    |
| Medium     | 12      | 17    | 70.6%    |
| Low        | 9       | 17    | 52.9%    |

*(Note: Under the Weighted Halftime Rule, in-play monitoring downgraded Germany vs. Curaçao to Low-confidence DRAW, and downgraded Saudi Arabia vs. Uruguay to Low-confidence URUGUAY WIN. On 2026-06-20, GER-CIV was correctly NOT frozen at HT, confidence was downgraded to Low (structural evidence approach), and the final outcome was correct. On 2026-06-21, WHT was applied to two matches: Uruguay-Cape Verde (correctly frozen at 2-1 Uruguay, final was 2-2 — prediction incorrect but protocol correctly applied) and NZ-Egypt (correctly downgraded to Low and NOT frozen, Egypt trailed 1-0 at HT but won 3-1 — prediction correct).)*

---

## Accuracy by Tournament Phase

| Phase | Pre-Game Correct | Half-Time Correct | Total | Pre-Game Acc | Half-Time Acc |
|:------|:-----------------|:------------------|:------|:-------------|:--------------|
| Group Stage | 27 | 23 | 42 | 64.3% | 62.2% |
| Round of 32 | 0 | 0 | 0 | N/A | N/A |
| Round of 16 | 0 | 0 | 0 | N/A | N/A |
| Quarter-finals | 0 | 0 | 0 | N/A | N/A |
| Semi-finals | 0 | 0 | 0 | N/A | N/A |
| Third Place | 0 | 0 | 0 | N/A | N/A |
| Final | 0 | 0 | 0 | N/A | N/A |

---

## Match Results Log

| Date | Match | Pre-Game Pred (Conf) | Half-Time Pred (Conf) | Actual | Correct? (Pre / HT) |
|:-----|:------|:---------------------|:---------------------|:-------|:--------------------|
| 2026-06-14 | Haiti vs. Scotland | SCOTLAND WIN (Med) | SCOTLAND WIN (Med) | SCOTLAND WIN | ✅ / ✅ |
| 2026-06-14 | Australia vs. Türkiye | TÜRKİYE WIN (Low) | TÜRKİYE WIN (Low) | AUSTRALIA WIN | ❌ / ❌ |
| 2026-06-14 | Germany vs. Curaçao | GERMANY WIN (High) | DRAW (Low) | GERMANY WIN | ✅ / ❌ |
| 2026-06-14 | Netherlands vs. Japan | NETHERLANDS WIN (Med) | NETHERLANDS WIN (Med) | DRAW | ❌ / ❌ |
| 2026-06-14 | Côte d'Ivoire vs. Ecuador | DRAW (Med) | DRAW (Med) | CÔTE D'IVOIRE WIN | ❌ / ❌ |
| 2026-06-14 | Sweden vs. Tunisia | SWEDEN WIN (Med) | SWEDEN WIN (Med) | SWEDEN WIN | ✅ / ✅ |
| 2026-06-15 | Spain vs. Cape Verde | SPAIN WIN (Med) | SPAIN WIN (Med) | DRAW | ❌ / ❌ |
| 2026-06-15 | Belgium vs. Egypt | DRAW (Low) | DRAW (Low) | DRAW | ✅ / ✅ |
| 2026-06-15 | Saudi Arabia vs. Uruguay | URUGUAY WIN (Med) | URUGUAY WIN (Low) | DRAW | ❌ / ❌ |
| 2026-06-15 | Iran vs. New Zealand | IRAN WIN (Low) | IRAN WIN (Low) | DRAW | ❌ / ❌ |
| 2026-06-16 | Iraq vs. Norway | NORWAY WIN (Med) | NORWAY WIN (Med) | NORWAY WIN | ✅ / ✅ |
| 2026-06-16 | Argentina vs. Algeria | ARGENTINA WIN (High) | ARGENTINA WIN (High) | ARGENTINA WIN | ✅ / ✅ |
| 2026-06-16 | Austria vs. Jordan | AUSTRIA WIN (Med) | AUSTRIA WIN (Med) | AUSTRIA WIN | ✅ / ✅ |
| 2026-06-18 | Switzerland vs. Bosnia and Herzegovina | SWITZERLAND WIN (Med) | SWITZERLAND WIN (Med) | SWITZERLAND WIN | ✅ / ✅ |
| 2026-06-18 | Canada vs. Qatar | CANADA WIN (Med) | CANADA WIN (Med) | CANADA WIN | ✅ / ✅ |
| 2026-06-18 | Mexico vs. South Korea | MEXICO WIN (Low) | MEXICO WIN (Low) | MEXICO WIN | ✅ / ✅ |
| 2026-06-19 | USA vs. Australia | DRAW (Low) | DRAW (Low) | USA WIN | ❌ / ❌ |
| 2026-06-19 | Scotland vs. Morocco | DRAW (Low) | DRAW (Low) | MOROCCO WIN | ❌ / ❌ |
| 2026-06-19 | Brazil vs. Haiti | BRAZIL WIN (High) | BRAZIL WIN (High) | BRAZIL WIN | ✅ / ✅ |
| 2026-06-19 | Türkiye vs. Paraguay | TÜRKİYE WIN (Med) | TÜRKİYE WIN (Med) | PARAGUAY WIN | ❌ / ❌ |
| 2026-06-20 | Netherlands vs. Sweden | NETHERLANDS WIN (Med) | NETHERLANDS WIN (Med) (FROZEN) | NETHERLANDS WIN | ✅ / ✅ |
| 2026-06-20 | Germany vs. Côte d'Ivoire | GERMANY WIN (Med) | GERMANY WIN (Low) (NOT FROZEN) | GERMANY WIN | ✅ / ✅ |
| 2026-06-20 | Ecuador vs. Curaçao | ECUADOR WIN (High) | ECUADOR WIN (High) (no live adjustment) | DRAW | ❌ / ❌ |
| 2026-06-20 | Tunisia vs. Japan | JAPAN WIN (Med) | JAPAN WIN (Med) (no live adjustment) | JAPAN WIN | ✅ / ✅ |
| 2026-06-21 | Spain vs. Saudi Arabia | SPAIN WIN (High) | N/A (complete by Iter 1) | SPAIN WIN 4-0 | ✅ / N/A |
| 2026-06-21 | Belgium vs. Iran | DRAW (Low) | N/A (complete by Iter 1) | DRAW 0-0 | ✅ / N/A |
| 2026-06-21 | Uruguay vs. Cape Verde | URUGUAY WIN (Med) | URUGUAY WIN (Med) (FROZEN) | DRAW 2-2 | ❌ / ❌ |
| 2026-06-21 | New Zealand vs. Egypt | EGYPT WIN (Med) | EGYPT WIN (Low) (NOT FROZEN) | EGYPT WIN 3-1 | ✅ / ✅ |
| 2026-06-22 | Norway vs. Senegal | NORWAY WIN (Low) | NORWAY WIN (Low) (FROZEN at HT 1-0) | NORWAY WIN 3-2 | ✅ / ✅ |
| 2026-06-22 | Jordan vs. Algeria | ALGERIA WIN (Med) | N/A (not tracked at HT) | ALGERIA WIN 2-1 | ✅ / N/A |
| 2026-06-23 | Portugal vs. Uzbekistan | N/A (system missed) | N/A (system missed) | PORTUGAL WIN 5-0 | N/A |
| 2026-06-23 | England vs. Ghana | N/A (system missed) | N/A (system missed) | DRAW 0-0 | N/A |
| 2026-06-23 | Panama vs. Croatia | N/A (system missed) | N/A (system missed) | CROATIA WIN 1-0 | N/A |
| 2026-06-23 | Colombia vs. DR Congo | N/A (system missed) | N/A (system missed) | COLOMBIA WIN 1-0 | N/A |
| 2026-06-24 | Switzerland vs. Canada | SWITZERLAND WIN (Low) | SWITZERLAND WIN (Low) | SWITZERLAND WIN 2-1 | ✅ / ✅ |
| 2026-06-24 | Bosnia and Herzegovina vs. Qatar | BOSNIA WIN (Low) | BOSNIA WIN (Low) | BOSNIA WIN 3-1 | ✅ / ✅ |
| 2026-06-24 | Scotland vs. Brazil | BRAZIL WIN (Med) | BRAZIL WIN (Med) | BRAZIL WIN 3-0 | ✅ / ✅ |
| 2026-06-24 | Morocco vs. Haiti | MOROCCO WIN (Med) | MOROCCO WIN (Med) | MOROCCO WIN 4-2 | ✅ / ✅ |
| 2026-06-24 | Czechia vs. Mexico | MEXICO WIN (Low) | N/A | MEXICO WIN 3-0 | ✅ / N/A |
| 2026-06-24 | South Africa vs. South Korea | SOUTH KOREA WIN (Low) | N/A | SOUTH AFRICA WIN 1-0 | ❌ / N/A |
| 2026-06-25 | Curaçao vs. Côte d'Ivoire | CÔTE D'IVOIRE WIN (Med) | CÔTE D'IVOIRE WIN (Med) (FROZEN) | CÔTE D'IVOIRE WIN | ✅ / ✅ |
| 2026-06-25 | Ecuador vs. Germany | GERMANY WIN (Med) | N/A (missed HT window) | ECUADOR WIN | ❌ / N/A |
| 2026-06-25 | Japan vs. Sweden | JAPAN WIN (Med) | JAPAN WIN (Low) (NOT FROZEN, downgraded) | DRAW | ❌ / ❌ |
| 2026-06-25 | Tunisia vs. Netherlands | NETHERLANDS WIN (Med) | NETHERLANDS WIN (Med) (FROZEN) | NETHERLANDS WIN | ✅ / ✅ |
| 2026-06-25 | Türkiye vs. USA | USA WIN (Low) | USA WIN (Low) (NOT FROZEN, contradicted) | DRAW | ❌ / ❌ |
| 2026-06-25 | Paraguay vs. Australia | DRAW (Low) | DRAW (Low) (FROZEN) | DRAW | ✅ / ✅ |
| 2026-06-26 | France vs. Norway | N/A (complete) | N/A (complete) | FRANCE WIN 4-1 | N/A |
| 2026-06-26 | Senegal vs. Iraq | N/A (complete) | N/A (complete) | SENEGAL WIN 5-0 | N/A |
| 2026-06-26 | Cape Verde vs. Saudi Arabia | N/A (complete) | N/A (complete) | DRAW 0-0 | N/A |
| 2026-06-26 | Uruguay vs. Spain | N/A (complete) | N/A (complete) | SPAIN WIN 1-0 | N/A |
| 2026-06-26 | Egypt vs. Iran | N/A (complete) | N/A (complete) | DRAW 1-1 | N/A |
| 2026-06-26 | New Zealand vs. Belgium | N/A (complete) | N/A (complete) | BELGIUM WIN 5-1 | N/A |

*(Note: Germany vs. Curaçao pre-match prediction was GERMANY WIN with High confidence, which was correct. However, live-monitoring in-play adjusted the prediction to DRAW with Low confidence, which was frozen at halftime and recorded as incorrect for the Half-Time category. On 2026-06-20, GER-CIV HT was correctly NOT frozen — the prediction was downgraded to Low but kept as GERMANY WIN using the structural-evidence approach, and the final outcome validated this decision. On 2026-06-21, Uruguay-Cape Verde was correctly frozen at HT under WHT (2-1 Uruguay confirmed URUGUAY WIN), but set-piece defensive errors in the second half produced a 2-2 draw — the WHT protocol was correctly applied despite the incorrect outcome. NZ-Egypt was correctly NOT frozen (Egypt trailed 1-0 at HT), downgraded to Low, and validated by the final 3-1 win. On 2026-06-23, the system missed all 4 matches — prediction loop started after the matchday ended. On 2026-06-25, the system achieved 3/6 (50%) accuracy. Three misses: ECU-GER (Dead Rubber Motivation Asymmetry — Germany draw-sufficient, Ecuador must-win, 55k fans), JPN-SWE (Draw-Sufficiency — Japan needed 1pt, played conservatively), TUR-USA (Extreme Rotation — USA made 8 changes, struggled to 2-2 draw with winless Türkiye).)*

---

## Lessons Learned

- [2026-06-14] On heavy temporary grass turf, possession-heavy teams with high technical requirements suffer a significant drop in passing speed and chance-creation efficiency, making direct, athletic counter-attacking teams highly dangerous even with low possession.
- [2026-06-14] Running stars or playmakers returning from illness/injury (e.g., Güler, Çalhanoğlu) on restricted workloads makes a team vulnerable to compact blocks in the later stages of matches, especially on fatiguing pitches.
- [2026-06-14] During live-match monitoring, early first-half score fluctuations (e.g., a temporary 1-1 equalizer) represent normal noise and should not trigger prediction adjustments for heavy favorites; live-monitoring adjustments should be restricted to major structural events like red cards or key player injuries.
- [2026-06-14] When predicting draws in highly compact, defensive matchups (e.g., Ivory Coast vs. Ecuador), confidence should remain Low due to extreme late-game volatility, such as 90th-minute winners by substitutes.
- [2026-06-14] At the end of the matchday, result tracking must verify final scores using multiple official sources rather than relying on live blogs, to prevent miscoding stoppage-time goals.
- [2026-06-15] Favorites playing against highly organized defensive low blocks (e.g., Cape Verde) can easily be frustrated if the opponent’s goalkeeper is in inspired form, especially when the favorite lacks a physical, clinical center-forward to penetrate the block.
- [2026-06-15] When a favorite playing in extreme heat/humidity has a makeshift center-back partnership, their pressing intensity drops significantly, making them highly vulnerable to set-pieces and counter-attacks from well-drilled defensive blocks.
- [2026-06-15] Off-field logistical disruptions (e.g., training camp relocations, travel delays) and key starter roster absences severely impact team focus and structural organization, making favorites highly susceptible to cohesive transition-focused teams.
- [2026-06-15] Live-monitoring during matches must employ rigorous multi-source scoreline verification to prevent data discrepancies (such as misreporting a 2-2 scoreline as 1-1) that blind the prediction system from true match events.
- [2026-06-18] Favorites facing deep defensive blocks benefit significantly from tactical substitutes and second-half opponent fatigue. Avoid premature downgrades at halftime if structural metrics remain dominant.
- [2026-06-18] Host-nation favorites playing on home soil with high motivation (e.g., Canada at BC Place, Mexico at Guadalajara Stadium) exhibit strong home-advantage resilience. High-quality transition-heavy teams can run up the score against weaker defensive opponents.
- [2026-06-18] When a key defender is suspended (e.g., Cesar Montes for Mexico), the team tends to adopt a more conservative defensive structure rather than collapsing, particularly when playing at home under favorable conditions, resulting in tight, low-scoring clean sheets.
- [2026-06-16] Final score verification must include a 15-minute buffer after estimated full time to capture stoppage-time goals. The Iraq-Norway match had a 90+6' own goal that was missed because verification ran too early.
- [2026-06-16] Tournament debutants (e.g., Jordan) consistently overperform expected quality in their opening match due to elevated motivation and the opponent's lack of scouting data against them. Favorites facing debutants should receive a modest confidence discount.
- [2026-06-16] When star players face potential disciplinary incidents (e.g., Messi's red-card-worthy challenge on Mandi), this represents a genuine structural risk that pre-match analysis should proactively flag, even if no card is ultimately given.
- [2026-06-19] Host-nation favorites playing on home soil with major quality advantages should not be downgraded to a DRAW against defensive block opponents solely due to individual player injuries (e.g., Pulisic) if the opponent lacks transition threat.
- [2026-06-19] During live-match monitoring, never use search queries that assume a specific scoreline (e.g., "0-0 halftime"), as confirmation bias from outdated reports can lead the system to hallucinate scorelines and incorrectly freeze predictions.
- [2026-06-19] A 10-man defensive block under a disciplined manager (e.g., Gustavo Alfaro) is highly resilient when defending a lead on a heavy temporary grass pitch. Under these conditions, the slow playing surface negates the favorite's numerical advantage and ball circulation speed.
- [2026-06-19] Assess team finishing efficiency metrics (goals vs shots/xG) before predicting comebacks or heavy wins. High shot volume (e.g., Türkiye's 30+ shots) without actual goals indicates a systemic clinical deficiency rather than temporary bad luck.
- [2026-06-20] The Clinical Finishing Efficiency heuristic must be enforced as a MANDATORY confidence cap, not an optional check. Ecuador's 0 goals from 16 shots vs CIV (3 woodwork hits) was correctly identified as a risk but was fatally underweighted — High confidence was assigned despite clearly triggering the cap rule. This is a compliance failure, not an analytical gap.
- [2026-06-20] When a retractable-roof stadium is confirmed closed, the Temporary Grass Pitch Heuristic discount should be fully waived. Climate control eliminates the surface degradation risk. This was properly handled for NED-SWE at NRG Stadium.
- [2026-06-20] A team that concedes 5+ goals in their opening match is more likely to adopt an extreme defensive posture in their second match (5-4-1) than to collapse again. The "Post-Thrashing Defensive Reset" effect produces disciplined, motivated defending against opponents who struggled to score in their own opening match.
- [2026-06-20] Betting market odds below 1.15 should NOT automatically imply High confidence when the favorite has a documented finishing deficiency. Market odds for must-win favorites are systematically inflated by narrative pressure and do not account for finishing efficiency.
- [2026-06-20] The Weighted Halftime Rule structural-evidence approach was validated for GER-CIV. The prediction was correctly NOT frozen at HT despite a 1-0 deficit, because the pre-match analytical foundation (Germany bench depth) identified a credible path back. Confidence was appropriately downgraded to Low.
- [2026-06-20] New managers appointed with fewer than 7 days preparation should not receive credit beyond a low-probability risk flag. TUN-JPN confirmed this — Renard had only 4 days and Tunisia were dismantled 4-0.
- [2026-06-20] Khel Now was unreliable for Ivory Coast lineups for two consecutive matches (June 14 and June 20). Future lineup sources should prioritize ESPN match centre displays, FotMob, and official team accounts over Khel Now.
- [2026-06-21] Set-piece vulnerability persists against heavy favorites even when the favorite has their preferred CB pairing. Uruguay's 2-0 HT lead was erased by two set-piece/cross-derived goals (Andrade 10', Costa 85'). Set-piece organization on dead balls is a distinct defensive skill that not all teams possess equally. For teams with known set-piece weaknesses (e.g., Bielsa's man-marking system), this should be a confidence-reducing factor even when leading comfortably.
- [2026-06-21] The Weighted Halftime Rule's "downgrade but don't flip" approach was validated for NZ-Egypt. Despite trailing 1-0 at HT with 0.04 xG, Egypt's pre-match finishing analysis (Salah, Marmoush, Trezeguet as elite finishers) provided structural evidence that prevented a flip. Egypt scored 3 second-half goals and won 3-1. This confirms the structural-evidence approach is superior to a naive scoreline-based flip.
- [2026-06-21] Elite individual finishing quality can overcome poor team xG. Egypt's 0.04 xG at HT was predominantly low-quality chances, but Salah, Marmoush, and Trezeguet converted 3 second-half opportunities that the xG model rated as low-probability. The WHT must evaluate finishing personnel quality — not just team-level xG — when assessing comeback likelihood.
- [2026-06-22] The Temporary Grass Pitch Heuristic should be refined: elite individual finishers (e.g., Haaland-level) can overcome surface disadvantages. Norway scored 3 goals on MetLife's temporary grass in rainy conditions. The 10-15% discount should apply primarily to possession-heavy passing teams (Spain-style), not to direct attacking teams or teams with world-class finishers.
- [2026-06-22] The Clinical Finishing Compliance Gate was violated for JOR-ALG. Algeria had 0 goals from 1 SOT vs Argentina. The reasoning used an opponent-quality exception ("scoring vs Argentina is fundamentally different") that is not in the SKILL.md text. The rule needs an explicit opponent-quality exception clause with documentation requirements.
- [2026-06-22] Set-piece vulnerability was a blind spot in JOR-ALG analysis. Both Algeria goals came from corners (they had 10 corners to Jordan's 1). Pre-match analysis focused entirely on open-play quality. A "Set-Piece Advantage Check" should be added to the pre-match analysis workflow.
- [2026-06-22] The 170-minute post-kickoff interval was too long for JOR-ALG. It skipped the entire first half and HT, preventing WHT application. For Medium-confidence matches within 2 hours of kickoff, the interval should land during the second half (60-90 min), not after full time.
- [2026-06-22] Jordan became the first debutant to score in both of their first two World Cup matches since Ivory Coast 2006. The Debutant Motivation Boost (Match 1 only) was accurate in formulation — Jordan scored in Match 2 but was still eliminated.
- [2026-06-23] System timing is critical: The prediction loop must launch before the first match kickoff. 4 matches on this matchday received no predictions because the system ran after all matches had completed. Total tokens burned: 37,508 across 2 iterations with zero prediction value.
- [2026-06-23] Gillette Stadium temporary grass validated: England (79% possession, 1.36 xG, 19 shots) failed to score against Ghana. Matches the Temporary Grass Pitch Heuristic pattern — possession-heavy technical teams struggle on heavy temporary surfaces regardless of quality advantage. This is the fifth validation of this heuristic.
- [2026-06-23] England's clinical finishing deficiency is persistent: 19 shots, 3 on target (16%), 1.36 xG, 0 goals. Despite dominant possession and territory, England could not break a deep block on temporary grass. This reinforces the Clinical Finishing Compliance Gate — finishing efficiency from prior matches is predictive across matchdays.
- [2026-06-24] WHT structural-evidence approach validated for SUI-CAN (0-0 HT, downgrade but not flip). The distinction between "not finishing" (structure correct, execution missing) and "structurally incapable" (fundamental flaw) is operationally sound. Switzerland created chances in the first half — the HT score was execution noise, not structural failure.
- [2026-06-24] xG dominance combined with opponent goals from low-probability sources (own goal, long-range strike) is strong evidence that an ambiguous HT scoreline is noise, not structural. MAR-HAI: Morocco had 2.15 xG in the first half alone while both Haiti goals came from non-sustainable scenarios. The WHT should include a "Goal Sustainability Assessment" — when the underdog's goals come from OG/deflections/long-range, the HT score carries less weight against a structurally dominant favorite.
- [2026-06-24] Dead rubber motivation asymmetry can overcome significant quality differences. RSA-KOR: Korea needed a draw (play not to lose), RSA needed a win (play desperately). When the draw-sufficient team also benches its star player (Son), the conservatism signal is even stronger. Future dead rubber predictions must weigh the motivation delta explicitly — the must-win team's implied performance increases by ~15-20%, and the draw-sufficient team's effective quality decreases when signaling conservatism through lineup decisions.
- [2026-06-24] Heavy rotation in dead rubbers favors the team with greater squad depth, not better starters. CZE-MEX: Mexico's second XI (no Ochoa/Jimenez/Gimenez) beat Czechia's second XI (no Schick/Soucek) 3-0. The depth gap (bench quality, not XI quality) was the decisive factor.
- [2026-06-25] Dead Rubber Motivation Asymmetry applies even without rotation. ECU-GER: Germany fielded full-strength XI but was draw-sufficient (6pts). Ecuador was must-win (1pt) with 55,000 supporters. The motivation delta (~15-20%) exists purely from match state, not just lineup decisions. Update to Heuristic #18: the rule applies even when the draw-sufficient team does not rotate.
- [2026-06-25] Draw-sufficiency is a structural pre-match factor that must be evaluated before kickoff. JPN-SWE: Japan needed only 1pt to advance and played conservatively despite Moriyasu's "full-strength" promise. This is the second validation (after RSA-KOR) that a 1pt requirement produces conservative play. A new Draw-Sufficiency Confidence Discount should be added: when a predicted winner needs only 1pt, apply a one-notch confidence discount.
- [2026-06-25] Extreme rotation (6+ changes) in dead rubbers should cap confidence at Low regardless of opponent quality. TUR-USA: USA made 8 changes and struggled to a 2-2 draw against a winless, goalless opponent. The rotated XI's lack of cohesion (0.52 xG in first half) outweighed the quality gap. Squad depth matters for rotation quality, but 6+ changes always introduces significant cohesion risk.
- [2026-06-25] Türkiye's 62-shot goal drought confirms the Clinical Finishing Gate's predictive value. They broke the drought against a rotated USA defense, scoring from 4 shots (2 SOT, 2 goals). The Gate correctly flagged Türkiye's finishing as a systemic problem — the drought-breaking against a weakened opponent was the expected "regression to the mean" event, not a contradiction of the heuristic.
- [2026-06-25] Sofascore's "confirmed" lineup data was a projection, not verified official data, for Türkiye-USA. FotMob's live match center had the correct lineup. FotMob should replace Sofascore as the primary lineup source for future matchdays. This issue also occurred with Khel Now for Ivory Coast lineups on June 14 and 20 — suggesting multiple sources besides FotMob are unreliable for "confirmed" lineups.
- [2026-06-25] The 10-iteration cycle for 6 matches consumed ~1M tokens with only 1 prediction change. This is highly inefficient. Recommendation: start later (15:00 UTC vs 09:00 UTC), reduce to 5-7 iterations, and target 300k-400k tokens per matchday.
- [2026-06-26] The timing failure recurred for a second consecutive matchday (June 26 matches missed). Root cause is now clearly orchestrator-level: the prediction loop did not launch before the first match kickoff. A guardrail should be added: if current time exceeds the last match's estimated end by >6 hours, skip the prediction loop entirely and proceed directly to postmortem.
- [2026-06-26] Norway's 10 changes vs France (already qualified) produced a 4-1 blowout. This validates the Extreme Rotation Floor Rule (#20) with the important nuance: rotation by a weaker draw-sufficient team against an elite opponent produces an even larger blowout than normal. When the rotating team is the underdog AND eliminates its star player(s) (Haaland benched), apply an additional confidence boost to the elite opponent.
- [2026-06-26] Cape Verde went unbeaten in all 3 group matches (0-0 vs Saudi Arabia, 0-0 vs Spain, 2-2 vs Uruguay). The Debutant Motivation Boost's "Match 1 only" assumption may need revision — Cape Verde's disciplined defensive organization persisted across all three matches, not just the opener. This may be a genuine structural quality (well-drilled low block) rather than motivation-driven.
- [2026-06-26] Bielsa-System Defensive Fragility (#22) was validated for a third consecutive Uruguay match. Uruguay finished Group H with 0 wins (2 draws, 1 loss) — the worst performance of any Bielsa-coached side in a major tournament. Individual defensive errors occurred in every match. The heuristic's confidence discount should be strengthened from "modest" to "significant" for Uruguay specifically.
- [2026-06-26] Spain's Setien-era tactical discipline (1-0 win over Uruguay) suggests possession-based systems can overcome temporary grass if they adapt their style. Spain's passing tempo was deliberately slow, avoiding the high-tempo combinations that fail on heavy surfaces.
- [2026-06-26] BC Place temporary grass did not impair Belgium (5 goals vs New Zealand). Combined with Norway's 3 goals at MetLife (June 22), the evidence grows that elite individual finishers and direct attacking teams are not meaningfully affected by temporary grass. The heuristic's distinction between possession-heavy technical teams and direct/elite-finisher teams is well-supported.
- [2026-06-26] The system has now missed two full matchdays (June 23 and June 26) due to orchestrator timing. Total matches with no predictions: 10. Total tokens consumed without prediction value across both missed matchdays: ~60k. This is an orchestration failure, not a skill failure.

---

## Active Heuristics

- **Roster Verification Heuristic**: Always double-check and verify international retirement status and late-stage pre-tournament injuries (from warm-up friendly matches, club playoff finals, etc.) for key players rather than relying on historical qualifying squads or outdated tournament rosters. Outdated roster tracking can lead to incorrect tactical assumptions (e.g. projecting retired/injured players to start).
- **Workload Management Heuristic**: In opening tournament fixtures, teams returning star players from late-season injuries or illness (e.g., muscle tears) often restrict their minutes (rarely playing a full 90+ minutes). Technical teams whose playmaking core is on restricted minutes are highly vulnerable to compact blocks in the final 30 minutes, particularly if the bench lacks creative depth.
- **Style Matchup Heuristic**: Defensive blocks relying heavily on aerial dominance and physical center-backs to defend the penalty box may find this strength neutralized when facing opponents that employ fluid, ground-based "strikerless" attacking rotations that bypass traditional wing crosses and aerial duels.
- **Temporary Grass Pitch Heuristic (Refined 2026-06-22)**: Multi-purpose stadiums that normally feature artificial turf (e.g., BC Place in Vancouver, Gillette Stadium in Boston, MetLife Stadium in NY/NJ, Dallas Stadium, Houston Stadium) have temporary natural grass pitches installed over turf/concrete bases for the World Cup. These surfaces are often slower, heavier, and prone to tearing up compared to established natural pitches. **However, the discount magnitude depends on team playing style:**
  - High-possession technical teams reliant on quick passing combinations (e.g., Spain, Belgium): Apply the full **10-15% discount** as validated by Spain's 0-0 draw on Atlanta's temporary grass, Belgium's 1-1 draw on Seattle's slow turf, Scotland's 0-1 loss to Morocco on Boston's slow grass, and Türkiye's 0-1 loss to Paraguay on Santa Clara's slow grass.
  - Direct attacking teams or teams with elite individual finishers (e.g., Norway with Haaland, Argentina with Messi): Apply a **reduced 0-5% discount** or none — world-class finishers can convert chances regardless of surface (validated by Norway's 3 goals on MetLife's temporary grass in rainy conditions, 2026-06-22).
  - The heavy pitch environment enables deep defensive blocks to sit compact and absorb pressure with less fatigue, even when down to 10 men — this part of the heuristic remains regardless of team style.
  - **Climate control mitigation:** If retractable-roof stadium is confirmed closed, the discount is fully waived (validated by NED-SWE at NRG Stadium).*
- **Counter-Attack / Possession Efficiency Heuristic**: Direct, athletic teams focusing on compact mid-blocks and vertical transitions on heavy pitches are highly efficient, often outperforming technical teams despite low possession percentages (<35%) and low shot volume. Analyze expected goals (xG) rather than possession dominance when evaluating defensive block vs. playmaking matchups.
- **Live-Monitoring Overreaction Heuristic (New)**: For heavy favorites (e.g., moneyline < 1.15), ignore temporary first-half equalizers or slow starts. Do not adjust predictions or confidence during the first half (`live_pre_halftime`) based on scoreline fluctuations alone. Live adjustments must wait until halftime or require major structural changes (such as red cards or key player injuries).
- **Draw Prediction Volatility Heuristic (New)**: Draw predictions are highly fragile and subject to late-game volatility. Always restrict Draw predictions to Low confidence unless there are clear tournament table incentives (e.g., mutual progression) or both teams are structurally deadlocked with no bench depth.
- **Makeshift Defense / Extreme Weather Heuristic (New)**: When a favorite plays with a makeshift center-back partnership (due to late injuries/workload management) under extreme heat or humidity conditions (e.g. Miami, feels-like >100°F), their structural defensive organization and pressing intensity drop significantly. This increases the probability of defensive errors, set-piece vulnerabilities, and low-scoring draws or upsets.
- **Makeshift Defense Heuristic**: A makeshift defensive lineup (e.g., due to suspension or injury) does not automatically result in defensive failure. If the team enjoys a strong home-field or altitude advantage (e.g., Mexico in Guadalajara), they tend to compensate by playing a more conservative, defensively cautious style. This reduces overall match expected goal margins while maintaining defensive solidity. Under these conditions, adjust predicted goal margins downward rather than automatically downgrading the favorite to a draw or loss.
- **Squad Depth & Substitution Impact Heuristic**: Teams with deep squads and high-quality attacking substitutes are highly effective at breaking down disciplined defensive blocks in the final 30 minutes of matches, especially as underdogs experience fatigue. When predicting matchups where a favorite has deep squad rotation and the opponent has thin bench depth, increase confidence in a late-game breakthrough for the favorite.
- **Logistical / Team Disruption Heuristic (New)**: Favorites experiencing severe off-field logistical disruptions (such as late travel arrivals, training base camp relocations, visa delays) or team controversy (roster exclusion disputes) are prone to organizational collapse and lack of focus. Apply a 10-20% discount to their implied performance rating, particularly when facing cohesive, direct transition teams.
- **Live-Monitoring Score Verification Heuristic (New)**: Live monitoring updates must verify match scorelines and events across at least two independent live match centers (e.g., FotMob and ESPN) to prevent data discrepancies from blinding the model to the true state of the game.
- **Final Score Verification Buffer Heuristic (New)**: After estimated full time, wait at least 15 minutes before recording the final score, and confirm across at least two independent official or strong match centers. Stoppage-time goals (including 90+6' own goals) are routinely missed if verification runs too early.
- **Debutant Motivation Boost Heuristic (New)**: Tournament debutants receive a 10-15% performance boost in their opening match due to elevated motivation and the opponent's lack of recent competitive footage. Favorites facing debutants should have confidence discounted by one notch.
- **Disciplinary Risk Flag Heuristic (New)**: For players with a history of emotional or high-intensity play that could result in a red-card incident, flag this as a structural risk in the prediction reasoning, even if the probability is low. A single sending-off can invalidate any pre-match analysis.
- **10-Man Block Defense on Heavy Pitches Heuristic (New)**: Underdogs defending a lead on a heavy temporary grass pitch can neutralize a 10-man disadvantage. If the favorite has shown poor clinical finishing efficiency, do not assume a comeback or flip predictions to them, as the slow surface slows ball movement and fatigue sets in quickly.
- **Neutral Query Live Monitoring Heuristic (New)**: Never use search queries with specific scorelines (e.g. "0-0", "1-0") during active live tracking or score verification. All queries must use neutral terms (e.g. "score", "match events") to avoid confirmation bias and hallucinations from stale web results.
- **Clinical Finishing Compliance Gate (New, Strengthened)**: BEFORE assigning Medium or High confidence to any predicted winner, the system MUST check and document that team's goals-vs-shots ratio from their prior tournament match(es). If goals-vs-shots ratio is < 0.05 (e.g., 0 goals from 16+ shots) OR goals-vs-xG ratio is < 0.5, confidence MUST be capped at Low. This is a non-negotiable compliance requirement — failure to apply this cap will be flagged as a SKILL.md violation in postmortems.
- **Post-Thrashing Defensive Reset Heuristic (New)**: A team that concedes 5+ goals in their opening match is more likely to adopt an extreme defensive posture (e.g., 5-4-1 formation) in their second match than to collapse again. The psychological "reset" effect produces disciplined, motivated defending against volume-shooting opponents. When a thrashing victim faces a team with documented finishing struggles, significantly increase draw/upset probability.
- **Must-Win Favorite Overconfidence Trap (New)**: When a team in a must-win situation (0 points, facing elimination) is priced at -800 or shorter, exercise extreme caution if that team has a documented finishing deficiency from prior matches. Market odds for desperate favorites are systematically inflated by narrative pressure. Cap confidence at Medium maximum, regardless of opponent quality, until the favorite demonstrates clinical improvement.
- **Stadium Climate Control Mitigation (Strengthened)**: The Temporary Grass Pitch Heuristic discount is fully waived for retractable-roof stadiums confirmed as closed. Verified roof closures eliminate surface degradation risk. This was validated by NED-SWE at NRG Stadium (roof closed, no pitch impact).

- **Bielsa-System Defensive Fragility (New)**: Under Marcelo Bielsa's man-marking, high-pressing defensive system, individual defensive errors are more frequent because players are often isolated in one-on-one situations after the press is bypassed. Uruguay has now dropped points from a winning position (June 21 vs Cape Verde) due to individual defensive errors. When predicting matches involving Bielsa-coached teams, apply a modest confidence discount (especially for HT frozen predictions) because a single individual error can erase a lead against a set-piece-capable opponent.
- **WHT Structural-Evidence Finishing Quality Sub-Rule (Strengthened)**: When deciding whether to flip a pre-match prediction at HT (score contradicts prediction), the key distinction is between "playing poorly" (downgrade confidence) and "structurally incapable of scoring" (justify a flip). A team with elite individual finishers (e.g., Salah-level) should rarely be considered "structurally incapable" even with very low xG at HT. The WHT must explicitly evaluate finishing personnel quality — not just team-level xG — as a structural factor against flipping.
- **Set-Piece Advantage Check (New 2026-06-22)**: During pre-match analysis, evaluate each team's set-piece threat and vulnerability. Check: (1) does one team have a significant aerial/physical advantage? (2) does the opponent have a demonstrated set-piece vulnerability from prior matches? (3) does the favorite have quality set-piece takers? If yes to 2+ questions, flag set pieces as a high-probability scoring path — even if the team's open-play finishing is poor. Validated by JOR-ALG (both Algeria goals from corners, 10-1 corner advantage).
- **Clinical Finishing Compliance Gate — Opponent-Quality Exception (New 2026-06-22)**: An opponent-quality adjustment MAY be applied to bypass the Low confidence cap if BOTH: (a) the prior match was against an elite opponent (world top 5 or defending champion), AND (b) strong countervailing evidence exists that the team's finishing is better than the single-match sample (e.g., a returning star, 20+ goal international record). Confidence may be Medium at maximum (never High) under this exception. The justification MUST be explicitly documented in the reasoning. Validated by JOR-ALG — Algeria's 0 goals vs Argentina was context-justified by Mahrez return and the elite opponent quality.

- **Dead Rubber Motivation Asymmetry Rule (Updated 2026-06-25)**: In dead rubber matches where advancement scenarios differ (one team must-win, opponent needs only a draw), the must-win team receives a motivation bonus of ~15-20% to their implied performance. If the draw-sufficient team also benches key starters (signaling conservatism through lineup rotation), the bonus may fully close the quality gap. When both conditions apply (motivation delta + starter benching), apply a one-notch confidence downgrade to the draw-sufficient team and explicitly document the motivation delta in reasoning. **Updated sub-clause (2026-06-25):** The rule applies even without rotation if the draw-sufficient team has already secured advancement AND the opponent faces elimination. The motivation delta exists purely from match state, not just lineup decisions. When the crowd heavily favors the must-win team, apply an additional 5-10% confidence discount to the draw-sufficient favorite. Validated by ECU-GER (2026-06-25): Germany (6pts, no rotation) lost 2-1 to Ecuador (1pt, must-win, 55k fans).

- **Draw-Sufficiency Confidence Discount (New 2026-06-25)**: When a team needs only 1 point to advance and faces a must-win opponent, apply a one-notch confidence discount to the draw-sufficient team's win prediction. The discount applies regardless of whether the team rotates starters. Trigger conditions: (a) team needs only 1pt to advance AND (b) opponent is winless/must-win AND (c) match is not a knockout (motivation asymmetry is strongest in group stage). Validated by JPN-SWE (2026-06-25): Japan needed 1pt, played conservatively, drew 1-1 despite 1.31 xG dominance. This parallels RSA-KOR (2026-06-24): Korea needed 1pt (Son benched), lost 1-0.

- **Extreme Rotation Floor Rule (New 2026-06-25)**: When a team makes 6+ changes to their starting XI in a match, their effective quality drops materially regardless of squad depth. Confidence must be at most Low, even against a winless opponent. Trigger conditions: (a) 6+ starting XI changes from the team's prior match AND (b) no realistic advancement stakes for the rotating team. Exception: if the rotating team has elite bench depth (all 6+ changes are at most a 1-notch quality drop per position), confidence may remain at Medium maximum, with explicit documentation of why each change is quality-neutral. Validated by TUR-USA (2026-06-25): USA made 8 changes, produced 0.52 xG in first half, and could only draw 2-2 against winless, goalless Türkiye.

- **Lineup Source Reliability (New 2026-06-25)**: FotMob live match center should be the single source of truth for confirmed starting XIs. Sofascore and other aggregators may display projected lineups as "confirmed." If a lineup source conflict arises, prefer FotMob. This is the third source reliability finding (following Khel Now for Ivory Coast on June 14 and 20).

### Initial Assumptions
- Home advantage matters in World Cup group stages (host nations USA, Canada, Mexico)
- Teams with longer rest between matches tend to perform better in knockout stages
- Historical head-to-head records have limited predictive value in World Cup contexts
- Betting market odds provide a useful baseline but should be adjusted for narrative bias

---

## Open Questions for Future Research

- Do teams from the same confederation consistently over/under-perform relative to expectations?
- How does squad depth correlate with outcomes in the expanded 48-team format?
- Does the new tournament structure (groups of 4, top 2 + 8 best 3rd-place advance to Round of 32) change group-stage dynamics?
- How do temporary grass pitch conditions evolve over the course of the tournament as the sod establishes or wears out?
- Will Germany's reliance on young playmakers (Musiala, Wirtz) hold up when they face physical defensive blocks on temporary grass pitches later in the tournament?
- Can Japan maintain their high tactical discipline and resilience against transition-heavy opponents in Group F after their dominant 4-0 win over Tunisia?
- Can Cape Verde sustain their defensive low-block discipline against more direct opponents in Group H, or will they struggle when forced to play more offensively?
- Will Uruguay's defensive organization stabilize once Ronald Araújo or José Giménez return, or are their structural defensive issues deeper under Bielsa's system?
- Does Belgium's reliance on Romelu Lukaku's physical presence mean they are unable to break down organized blocks when he is benched or on restricted workloads?
- How severely does player injury (e.g., Ismaël Koné's serious leg injury) affect Canada's midfield dynamics in subsequent matches?
- Will Qatar's disciplinary collapse (two red cards) lead to a systemic team morale breakdown in their final group match?
- Do tournament debutants maintain their elevated performance in subsequent group matches, or is the "debutant boost" limited to the opening match? (Curaçao got their first point in Match 2 after a 7-1 loss — suggesting the boost may persist for motivated debutants after a thrashing.)
- Can Argentina maintain their defensive solidity (clean sheet vs Algeria) against stronger attacking opponents like Austria?
- Will the USA's reliance on home crowd support in Seattle and other venues carry them deep into the knockout stage despite captain Christian Pulisic's injury duration?
- Can Paraguay's highly disciplined defense under Gustavo Alfaro continue to hold out against elite teams in Group D, even with Almirón serving a suspension?
- Will Brazil's rotated players (like Matheus Cunha) maintain their starting roles once Rodrygo's injury impact is fully absorbed?
- [2026-06-20] Do betting markets systematically overprice must-win favorites in the group stage? The ECU-CUR miss (-900 favorite, 0-0 draw) adds to evidence that market odds for desperate teams are inflated by narrative pressure. Cross-reference with other tournament mismatches.
- [2026-06-20] Does the "Debutant Motivation Boost" extend to a team's second match when they suffered a heavy opening loss? Curaçao lost 7-1 to Germany but played disciplined, motivated defense vs Ecuador. This suggests the boost may persist into Match 2 if the debutant is not demoralized by Match 1.
- [2026-06-20] Can a team's finishing efficiency be reliably predicted from a single prior tournament match? Ecuador had only one match (0 goals, 16 shots vs CIV). Was this variance or a systemic pattern? Their historical trend (Under in 12 of 14) suggests the latter.
- [2026-06-21] Does the Weighted Halftime Rule need a specific set-piece vulnerability sub-check? Uruguay's frozen prediction was invalidated by two set-piece goals. Should pre-match set-piece defensive analysis be integrated into WHT freeze decisions (i.e., a frozen prediction could still be downgraded if the opponent has a demonstrated set-piece threat)?
- [2026-06-21] How should a team with sub-0.10 xG at HT be evaluated for comeback potential? Egypt (0.04 xG at HT, 3 goals second half) shows elite quality can overcome poor first-half performance. What xG threshold or personnel quality assessment justifies maintaining vs. flipping?
- [2026-06-21] Is Bielsa's high-risk system inherently more vulnerable to frozen-prediction invalidation? Uruguay has now conceded 2 goals from winning positions in this tournament. Is this system-specific or opponent-specific?
- [2026-06-22] Should the system ever set an interval that skips entirely over a Medium-confidence match's HT? The 170-min interval skipped JOR-ALG's HT, preventing WHT application. What interval rule prevents this?
- [2026-06-22] How should the Clinical Finishing Gate opponent-quality exception be practically enforced? Should it require explicit pre-approval in SKILL.md or is runtime documentation sufficient?
- [2026-06-22] Is Jordan's scoring record (goals in both debut matches) indicative of genuine attacking quality or a quirk of debutant motivation?
- [2026-06-22] Does the Temporary Grass Pitch discount refinement (elite-finisher exception) replicate across other venues and teams, or is Norway's performance an outlier?
- [2026-06-23] How can the prediction loop be guaranteed to start before the first match kickoff, rather than after the matchday ends? Current orchestration allowed a complete matchday to pass without any predictions.
- [2026-06-24] Does the Dead Rubber Motivation Asymmetry Rule generalize across tournament phases? Is the ~15-20% motivation bonus consistent in knockout rounds, where elimination is absolute regardless of seeding?
- [2026-06-24] When a draw-sufficient team benches a star player (e.g., Son for Korea), is this always a conservatism signal, or could it be workload management for a potential knockout round? Does the answer depend on whether the team has already secured advancement?
- [2026-06-24] How does the "third-place qualification" possibility affect dead rubber dynamics? Korea was eliminated after losing (3rd place, not enough points as a best 3rd-place team). Would the motivation gap narrow if the draw-sufficient team was already guaranteed advancement vs. needing a result to be sure?
- [2026-06-24] Can the WHT be improved by adding a specific "Goal Sustainability Assessment" sub-check? When an underdog's goals come from low-probability sources (OG, deflections, long-range), should the WHT apply a lower weight to the HT scoreline when deciding freeze vs downgrade?

- [2026-06-25] Can draw-sufficiency be reliably detected during pre-match analysis as a mandatory check? Japan's draw-sufficiency was documented in changelog questions but never applied as a pre-match confidence modifier. What operational check ensures this is caught before kickoff?
- [2026-06-25] Does the Extreme Rotation Floor Rule (6+ changes → Low cap) hold for teams with historically elite squad depth like France or Brazil? USA's 8 changes produced a significant quality drop — would the same apply to deeper squads?
- [2026-06-25] Can the per-matchday token budget be reliably reduced from ~1M to 300k-400k without losing essential coverage? What is the minimum viable iteration count for a 3-slot matchday?
- [2026-06-25] When should the Sofascore vs FotMob lineup discrepancy be considered resolved? Should SKILL.md be updated to specify FotMob as the preferred source?
- [2026-06-25] Is there a minimum total xG threshold below which a DRAW prediction should be considered "lucky" even when correct? PAR-AUS had 0.49 total xG — a single goal from any source would have invalidated the prediction. Should very-low-xG draws receive a confidence discount in future predictions?
- [2026-06-26] How can the orchestrator be guaranteed to launch the prediction loop before the first match kickoff? Two consecutive matchdays (June 23, June 26) were missed. Should the orchestrator check if current time < first_match_estimated_start before attempting predictions, and if not, skip to postmortem?
- [2026-06-26] Does the Debutant Motivation Boost extend beyond Match 1 when the debutant's style is defensive organization rather than motivation-driven? Cape Verde went unbeaten in all 3 group matches (0.94 xG against per match). Is this a "Cape Verde-specific" outlier or should the heuristic be generalized?
- [2026-06-26] How should the system handle "elite opponent resting starters" scenarios differently from "mediocre opponent resting starters"? Norway's 10 changes (resting Haaland, Ødegaard) vs France produced a 4-1 blowout, while USA's 8 changes (resting Pulisic, McKennie) vs Türkiye produced a 2-2 draw. The Elite Depth Exception to the Extreme Rotation Floor Rule needs definition.
- [2026-06-26] Does BC Place's temporary grass actually improve over the tournament duration as the sod establishes? Belgium scored 5 goals there on June 26 — the highest single-match goal total at that venue. Compare with Canada's 2 goals there on June 18.
- [2026-06-26] Is Uruguay's Bielsa-era collapse (0 wins in group stage) a system-specific failure or a personnel/adaptation issue? With 0 wins from 3 matches, this is the worst tournament performance of Bielsa's career. Should Uruguay be considered a permanently damaged team for future Bielsa-coached predictions?
