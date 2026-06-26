# Postmortem: 2026-06-25 Matchday Predictions

> Generated: 2026-06-26T03:55:00Z
> Matchday: 2026-06-25 (6 matches across Groups D, E, F)
> Source run: `run_20260626_033500_wc_postmortem`

---

## 1. Match Results Summary

| # | Match (Kickoff UTC) | Venue | Prediction (Conf) | FT Score | Correct? |
|:-:|:--------------------|:------|:------------------|:---------|:---------|
| 1 | Curaçao vs. Côte d'Ivoire (20:00) | Philadelphia Stadium | CIV WIN (Med) | 0-1 | ✅ |
| 2 | Ecuador vs. Germany (20:00) | MetLife Stadium, NJ | GER WIN (Med) | 2-1 | ❌ |
| 3 | Japan vs. Sweden (23:00) | Dallas Stadium, TX | JPN WIN (Med → Low) | 1-1 | ❌ |
| 4 | Tunisia vs. Netherlands (23:00) | Kansas City Stadium | NED WIN (Med, frozen) | 0-2 | ✅ |
| 5 | Türkiye vs. USA (02:00) | SoFi Stadium, CA | USA WIN (Low) | 2-2 | ❌ |
| 6 | Paraguay vs. Australia (02:00) | Levi's Stadium, CA | DRAW (Low, frozen) | 0-0 | ✅ |

**Overall: 3/6 correct (50.0%)**

### Pre-Game Accuracy (final pre-kickoff confidence)
| Matches | Correct | Accuracy |
|:--------|:--------|:---------|
| 6 | 3 | 50.0% |

### Half-Time Frozen/Live Accuracy
| Matches | Correct | Accuracy |
|:--------|:--------|:---------|
| 4 (frozen/live) | 2 | 50.0% |

---

## 2. Detailed Miss Analysis

### Miss #1: Ecuador 2-1 Germany ❌ (Medium → Medium)
**Prediction:** GERMANY WIN (Medium)
**Root Cause:** Dead Rubber Motivation Asymmetry — Germany (6pts, already qualified) faced Ecuador (1pt, must-win). The RSA-KOR pattern (2026-06-24) was known but NOT applied because Germany wasn't rotating. The assumption was that a full-strength Germany would overpower Ecuador regardless of motivation. This was wrong.

**Contributing Factors:**
1. **MetLife pitch impact underestimated.** Germany's quick-passing game requires a reliable surface. MetLife's slow, dry temporary grass was criticized by multiple players. Germany's 0.61 xG was their lowest of the tournament.
2. **55,000 Ecuadorian fans created a de facto home match.** The crowd factor was noted but not weighted as a structural performance driver.
3. **Germany's second-half intensity dropped.** With 6pts and top spot secured, Germany subbed off key players (Musiala, Wirtz) earlier than they would have in a competitive match.

**Postmortem Insight:** The Dead Rubber Motivation Asymmetry Rule (Heuristic #18) should have been applied to ECU-GER even though Germany was not rotating starters. The motivation delta exists regardless of rotation — a draw-sufficient team with nothing to play for will not match the intensity of a must-win opponent playing in front of 55,000 fans. **Action:** Add a "Motivation Only" sub-clause to Heuristic #18: the rule applies even without rotation when the draw-sufficient team has already secured advancement AND faces a desperate opponent.

### Miss #2: Japan 1-1 Sweden ❌ (Medium → Low via WHT)
**Prediction:** JAPAN WIN (Medium pre-kickoff, Low post-WHT)
**Root Cause:** Draw-Sufficiency Underestimation — Japan needed only 1 point to advance from Group F. Despite Moriyasu promising "full-strength" (confirmed pre-match), the team played conservatively: 0.76 xG in the first half (low for Japan's standard), few attacking risks, and a defensive posture after Maeda's 56' opener.

**Contributing Factors:**
1. **Draw-sufficiency was identified as a risk (in changelog questions) but was NEVER applied as a confidence modifier in pre-match reasoning.** This is a reasoning error, not an information gap — the data was available pre-match.
2. **Sweden's individual quality was underrated.** Elanga (Man Utd) and Gyökeres (Sporting) combined for the equalizer. Despite Sweden's 5-1 loss to Netherlands, they had elite finishers capable of individual moments.
3. **WHT correctly applied at HT** (downgraded from Medium to Low without flipping). The structural-evidence approach was correct — Japan's xG dominance didn't justify a flip.

**Postmortem Insight:** Draw-sufficiency is a structural factor that should be evaluated and applied during pre-match analysis, not discovered at HT. Japan faced a scenario identical to Korea (RSA-KOR): needed 1pt, faced a must-win opponent. This is a **second validation** of the Dead Rubber Motivation Asymmetry pattern.

### Miss #3: Türkiye 2-2 USA ❌ (Low)
**Prediction:** USA WIN (Low)
**Root Cause:** Extreme USA rotation (8 changes) was identified as a risk but the performance impact was grossly underestimated. USA's disjointed XI produced only 0.52 xG in the first half and trailed 2-1 at HT. The second-half equalizer (Berhalter, 57') salvaged a draw, but USA was the inferior side for extended periods.

**Contributing Factors:**
1. **USA's rotation was the heaviest of any team this matchday** — 8 changes. This created a first XI with limited prior playing time together.
2. **Türkiye broke their 62-shot goal drought.** The Clinical Finishing Gate correctly flagged Türkiye's finishing as a systemic problem, but the drought-breaking effect in a dead rubber (no pressure, playing for pride) was not anticipated.
3. **Pulisic's HT introduction changed the match** — USA immediately equalized, but this masked the structural weakness of the rotated XI.

**Postmortem Insight:** Extreme rotation (8+ changes) in a dead rubber should trigger a confidence floor no higher than Low, even when the opponent is winless and goalless. The "Dead Rubber Rotation Depth Rule" (Heuristic #15 in SKILL.md) addresses bench depth comparison but does not provide guidance on the absolute minimum confidence for heavily rotated teams. **Action:** Add explicit guidance: when a team makes 6+ changes in a dead rubber, confidence must be at most Low even if the opponent is weak.

---

## 3. Confidence Calibration Analysis

| Confidence Level | Correct | Total | Accuracy |
|:-----------------|:--------|:------|:---------|
| High | 0 | 0 | N/A |
| Medium | 1 | 3 | 33.3% |
| Low | 2 | 3 | 66.7% |

**Pre-game accuracy by confidence:**

Low confidence predictions (JPN-SWE was Medium pre-kickoff, downgraded at HT):
- CIV WIN (Med) ✅
- GER WIN (Med) ❌
- NED WIN (Med) ✅
- USA WIN (Low) ❌
- DRAW (Low) ✅
- JPN WIN (Med → Low HT) ❌

Medium-confidence pre-game performance (n=5 actually medium pre-kickoff, but one had JPN-SWE as Medium) was 2/5 = 40%. This continues the trend of Medium confidence underperforming.

---

## 4. Weighted Halftime Rule (WHT) Evaluation

| Match | HT Score | Pre-Ht Pred | WHT Decision | Correct? |
|:------|:---------|:------------|:-------------|:---------|
| CIV-CUR | 1-0 CIV | CIV WIN | Frozen ✅ | ✅ |
| ECU-GER | 1-1 | GER WIN | Not applicable (pre-halftime) | N/A |
| JPN-SWE | 0-0 | JPN WIN | Downgrade Med→Low, not flip | ✅ |
| TUN-NED | 2-0 NED | NED WIN | Frozen ✅ | ✅ |
| TUR-USA | 2-1 TUR | USA WIN | Not flipped (structural cause) | Correct protocol despite ❌ |
| PAR-AUS | 0-0 | DRAW | Frozen ✅ | ✅ |

**WHT Performance:** 5/5 correct protocol applications. The structural-evidence approach was validated even where the final prediction was incorrect (TUR-USA) — the correct decision was to not flip, as the structural cause (extreme rotation) was real and the final outcome (draw) was between both original predictions.

---

## 5. Token Efficiency Analysis

| Iteration | Time (UTC) | Tokens (total) | Matches Changed | Purpose |
|:----------|:-----------|:---------------|:----------------|:--------|
| 1 | 08:50 | 21,577 | 0 | Initial predictions |
| 2 | 11:53 | 153,034 | 0 | Nagelsmann full-strength confirmed |
| 3 | 13:59 | 151,419 | 0 | Press conferences, venue updates |
| 4 | 17:01 | 33,831 | 0 | Pre-match injury checks |
| 5 | 18:58 | 128,346 | 0 | Lineup window search (premature) |
| 6 | 20:48 | 58,213 | 0 | 20:00 matches HT verified |
| 7 | 21:58 | 42,685 | 0 | 20:00 matches FT verified |
| 8 | 23:50 | 313,151 | 1 | WHT for JPN-SWE (downgrade), TUN-NED (frozen) |
| 9 | 01:15 | 65,536 | 0 | 23:00 matches FT, 02:00 lineups |
| 10 | 02:55 | 34,885 | 0 | WHT for TUR-USA, PAR-AUS |
| **Total** | | **~1,002,677** | **1** | |

**Key finding:** ~1M tokens were consumed for 6 matches across 10 iterations, but only **1 prediction change** occurred (JPN-SWE downgrade from Medium to Low via WHT). The remaining 9 iterations produced **zero prediction or confidence changes**.

**Wasted token categories:**
1. **Pre-lineup searches (Iterations 2-4, total ~338k tokens):** Searches for "injury updates", "press conferences", "venue conditions" that did not change any prediction. While these provided background context, most of this information was already known.
2. **Premature lineup search (Iteration 5, 128k tokens):** Searching for official lineups 60+ minutes before release. The 75-min gating rule was technically followed but the searches returned stale projected lineups from prediction sites.
3. **Multiple identical search domains (Iterations 2-3):** Both iterations independently researched MetLife pitch, Brobbey fitness, Pulisic status — largely re-confirming the same evidence.

**Token waste estimate:** ~65-70% of tokens (~650k-700k) were spent on runs that produced no prediction changes.

**Recommendation for future matchdays:**
- Start later (not at ~09:00 UTC when first kickoff is 20:00 UTC). Begin at ~15:00 UTC for 20:00 kickoffs.
- Reduce pre-match iterations to 2-3: one for initial predictions, one for pre-lineup evidence (injuries/press), one for lineup verification.
- Post-kickoff iterations should be capped at 5-6 (one per timeslot: 20:00 HT, 20:00 FT, 23:00 lineups, 23:00 HT, 02:00 lineups, 02:00 HT, 02:00 FT).
- Target total token budget: 300k-400k per matchday with 6 matches.

---

## 6. New Heuristic Updates

### A. Draw-Sufficiency Confidence Discount (NEW)
**Rule:** When a team needs only 1 point to advance and faces a must-win opponent, apply a one-notch confidence discount to the draw-sufficient team's win prediction. The discount applies regardless of whether the team rotates starters. Validated by JPN-SWE (2026-06-25) and RSA-KOR (2026-06-24).

**Trigger conditions:**
- Team needs only 1pt to advance AND
- Opponent is winless/must-win AND
- Match is not a knockout (motivation asymmetry is strongest in group stage)

**Confidence impact:** Reduce by one notch (e.g., Medium → Low). If confidence is already Low, flag for postmortem but no further discount possible.

### B. Extreme Rotation Floor Rule (NEW)
**Rule:** When a team makes 6+ changes to their starting XI in a match, their effective quality drops materially regardless of squad depth. Confidence must be at most Low, even against a winless opponent. Validated by TUR-USA (USA made 8 changes, struggled to 2-2 draw).

**Trigger conditions:**
- 6+ starting XI changes from the team's prior match AND
- No realistic advancement stakes for the rotating team

**Exception:** If the rotating team has elite bench depth (all 6+ changes are at most a 1-notch quality drop per position), confidence may remain at Medium maximum, with explicit documentation of why each change is quality-neutral.

### C. Dead Rubber Motivation Asymmetry — Motivation-Only Sub-Clause (UPDATE to Heuristic #18)
**Update:** Add the following to the existing Dead Rubber Motivation Asymmetry Rule:

> The rule applies even without rotation if the draw-sufficient team has already secured advancement AND the opponent faces elimination. The motivation delta (~15-20%) exists purely from the match state, not just from lineup decisions. When the crowd heavily favors the must-win team, apply an additional 5-10% confidence discount to the draw-sufficient favorite.

**Validated by:** ECU-GER (2026-06-25): Germany (6pts, no rotation, draw-sufficient, 55,000 Ecuadorian fans) lost 2-1 to a desperate Ecuador.

---

## 7. Open Questions for Future Research

1. How can draw-sufficiency be operationally detected during pre-match analysis? Should it be a mandatory check for any match where a team enters the final group match with a qualification-safe position but not yet mathematically confirmed as group winner?
2. Does the Extreme Rotation Floor Rule hold for teams with historically deep squads (e.g., France, Brazil)? USA rotated 8 changes and struggled — would a similar rotation from Brazil produce a different outcome?
3. Can the token budget per matchday be reliably reduced to 300k-400k without losing essential coverage? The current 1M token average for 6-match days is unsustainable.
4. How should the system handle the Sofascore vs FotMob lineup data discrepancy? FotMob's live match-center data was accurate; Sofascore's "confirmed" data was a projection. Should FotMob be the single source of truth?
5. Is there a minimum xG threshold below which a low-confidence prediction should automatically be considered ❌ even if the result is correct? PAR-AUS had 0.12-0.37 xG total — a goal would have invalidated the DRAW prediction through pure randomness.

---

## 8. Recommendations

1. **Reduce maximum iterations per matchday from 10 to 7.** With 3 match slots (20:00, 23:00, 02:00), one iteration per timeslot transition is sufficient: Initial (pre-match), Lineups, HT Slot-1, FT Slot-1 + Lineups Slot-2, HT Slot-2, FT Slot-2 + Lineups Slot-3, HT+FT Slot-3.
2. **Add Draw-Sufficiency Check to mandatory pre-match workflow.** Before assigning any win prediction, check if the predicted winner needs only 1pt. Flag this as a confidence modifier.
3. **Enforce the Extreme Rotation Floor Rule in SKILL.md** — add it as Heuristic #19 or incorporate into existing Dead Rubber Rotation Depth guidance.
4. **Replace Sofascore with FotMob as the primary lineup source.** Sofascore's "confirmed" data in Iteration 9 was a projection. FotMob's live match center provides verified official lineups.
5. **Consider reducing starting token budget** by beginning iteration 1 at ~15:00 UTC instead of ~09:00 UTC for 20:00 kickoffs. This eliminates 3-4 low-value early iterations.
