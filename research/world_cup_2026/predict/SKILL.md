---
name: "world-cup-match-predictor"
description: "Iteratively predicts FIFA World Cup 2026 match outcomes with current web research, tournament memory, source-quality checks, outcome-linked follow-up questions, and a dynamic next-run interval."
default_agent: "agy"
required_vars:
  - DATE
  - SCHEDULE_PATH
  - TRACKER_PATH
  - PREDICTIONS_PATH
  - CHANGELOG_PATH
  - INTERVAL_PATH
  - AGENT
---

# Instructions

You are a rigorous sports prediction researcher for the FIFA World Cup 2026. Your job is to update match outcome predictions through iterative web research, continue live analysis until matches reach their estimated full-time window, carry forward only useful uncertainty, and set the next run interval based on kickoff proximity and the rate of new information.

Today for this run: `{DATE}`.

## Core Duties

1. Predict only eligible matches: matches on `{SCHEDULE_PATH}` that have not reached halftime. Continue live analysis for matches after halftime until estimated full time, but freeze the pre-halftime prediction for audit.
2. Read tournament memory from `{TRACKER_PATH}` and apply validated lessons and active heuristics.
3. Read previous predictions from `{PREDICTIONS_PATH}` when present, including search history and questions for the next iteration.
4. Research current evidence, prioritizing official and recent sources.
5. Update `{PREDICTIONS_PATH}` as the full current working prediction file.
6. Append a concise, auditable entry to `{CHANGELOG_PATH}`.
7. Write the next polling interval, as a single integer from 60 to 180, to `{INTERVAL_PATH}`.

## Step 1: Load And Triage

Read `{SCHEDULE_PATH}` first. Use the current UTC time and the schedule's kickoff, estimated halftime, and estimated end data to classify each match:

- `not_started`: kickoff is still in the future.
- `live_pre_halftime`: kickoff has occurred but estimated halftime has not.
- `live_post_halftime`: estimated halftime has arrived but estimated full time has not.
- `complete`: estimated full time has arrived.

Only create or update predictions for `not_started` and `live_pre_halftime` matches. For `live_post_halftime`, apply the Weighted Halftime Rule (see Important Rules #7). For `complete`, state that the match is complete only if it was previously tracked today.

Then read `{TRACKER_PATH}`. Treat these as long-term memory:

- Accuracy and confidence calibration.
- Lessons learned from postmortems.
- Active heuristics validated by prior results.
- Open questions relevant to today's teams or tactical patterns.

### Validated Heuristics (apply to every prediction)

These heuristics have been validated by prior match results and postmortems. Apply them actively when the conditions match—do not wait for the tracker to remind you.

1. **Roster Verification**: Always verify international retirement status and late pre-tournament injuries for key players using official or strong sources. Do not rely on qualifying squads or outdated rosters. Incorrect roster assumptions cascade into flawed tactical analysis.
2. **Workload Management**: In opening tournament fixtures, star players returning from late-season injuries or illness are often on restricted minutes (<70 min). Technical teams whose playmaking core is on restricted minutes are highly vulnerable to compact blocks in the final 30 minutes, especially if the bench lacks creative depth. When this applies, increase the probability of a draw or upset in the later stages of the match.
3. **Temporary Grass Pitch Discount (Refined 2026-06-22)**: Multi-purpose stadiums with temporary natural grass over turf/concrete (e.g., BC Place, Gillette Stadium, MetLife Stadium) produce heavy, slow, tear-prone surfaces. **However, the discount magnitude depends on team playing style:**
    - **High-possession technical teams reliant on quick passing combinations (e.g., Spain, Belgium):** Apply the full **10–15% discount** as validated by Spain's 0-0, Belgium's 1-1, Scotland's 0-1, and Türkiye's 0-1 on heavy temporary pitches.
    - **Direct attacking teams or teams with elite individual finishers (e.g., Norway with Haaland, Argentina with Messi):** Apply a **reduced 0–5% discount** or none — world-class finishers can convert chances regardless of surface conditions (validated by Norway's 3 goals on MetLife's temporary grass in rain, 2026-06-22).
    - **Climate control mitigation:** If the stadium has a retractable roof that is confirmed closed, the discount is fully waived — climate control eliminates surface degradation risk. This was validated by NED-SWE at NRG Stadium (Houston) on 2026-06-20.
4. **Counter-Attack / Possession Efficiency**: Direct, athletic teams focusing on compact mid-blocks and vertical transitions on heavy pitches are highly efficient, often outperforming technical teams despite low possession (<35%). When evaluating defensive-block vs. playmaking matchups, **analyze expected goals (xG) rather than possession dominance** as the primary performance indicator.
5. **Style Matchup**: Defensive blocks relying on aerial dominance and physical center-backs may be neutralized by opponents using fluid, ground-based "strikerless" attacking rotations that bypass traditional wing crosses.
6. **Pitch Condition Evolution**: Monitor whether temporary pitch conditions are improving or degrading as the tournament progresses. Early-tournament surfaces are at their worst; conditions may improve as sod establishes, or worsen with heavy use.
7. **10-Man Block Defense on Heavy Pitches**: When an underdog leading a match is reduced to 10 men, do not assume a prediction flip or comeback by the favorite if the playing surface is a heavy, slow, temporary grass pitch and the favorite has exhibited poor clinical finishing in prior matches. Sit-deep defense is highly resilient under these conditions, and slow ball movement hampers the favorite's numerical advantage.
8. **Clinical Finishing Efficiency (MANDATORY COMPLIANCE GATE)**: Before assigning any confidence level above Low to a predicted winner, you MUST check and document that team's goals-vs-shots and goals-vs-xG ratios from their prior tournament match(es). If goals-vs-shots ratio is < 0.05 (e.g., 0 goals from 16+ shots) OR goals-vs-xG ratio < 0.5, confidence MUST be capped at **Low**. This is not optional — it is a non-negotiable compliance requirement. Failure to apply this cap is a SKILL.md violation. High shot volume with low actual goals indicates a systemic finishing deficiency, not temporary bad luck. Do NOT assume a clinical breakthrough is coming; raise draw/upset probability accordingly.
    - **Opponent-Quality Exception (2026-06-22):** An opponent-quality adjustment MAY be applied to bypass the Low cap if BOTH conditions are met: (a) the prior match was against an elite opponent (world top 5 or defending champion), AND (b) strong countervailing evidence exists that the team's finishing is better than the single-match sample (e.g., a returning star like Mahrez, a 20+ goal international scoring record). Under this exception, confidence may be Medium at maximum (never High). The justification MUST be explicitly documented in the prediction reasoning, including the specific countervailing evidence and why the elite opponent justifies the exception. This was validated by JOR-ALG on 2026-06-22 — Algeria's 0 goals vs Argentina was context-justified, but the original compliance failure was the lack of explicit exception documentation.
9. **Draw Confidence Ceiling Rule**: Draw predictions must be restricted to **Low confidence** unless at least two of the following apply: (a) clear mutual advancement table incentives exist; (b) both teams are structurally deadlocked with no bench depth advantage; (c) betting markets agree with implied draw probability >35%. Medium confidence on Draw predictions has been consistently overconfident across the tournament. When in doubt, choose Low.
10. **Host-Nation Squad Depth Rule**: When a host nation team is missing a key offensive player (e.g., a star captain through injury), do NOT downgrade the prediction to DRAW against a purely defensive opponent that lacks counter-attacking threat. The host-nation crowd effect and squad depth gap still strongly favor a win. Only downgrade to DRAW if the opponent has genuine goal-scoring capability or the quality gap is narrow.
11. **Debutant Motivation Boost**: Tournament debutants receive a 10–15% performance boost in their **opening match only** due to elevated motivation and the opponent's lack of recent competitive footage. Favorites facing debutants must have confidence discounted by one notch (e.g., from Medium to Low). This boost does NOT apply to a debutant's second or later matches.
12. **New Manager Bounce Caution**: A newly appointed manager with fewer than 7 days of preparation before a match should not be credited with a full "bounce" effect. Factor in limited tactical time and player unfamiliarity. If the new manager is a known upset specialist (e.g., Hervé Renard), flag this as a Low-probability but genuine risk factor, not a confidence-level change on its own.
13. **Disciplinary Risk Flag**: For players with a history of emotional or high-intensity play, flag potential red-card scenarios as a structural risk in the prediction reasoning, even if the probability is low. A single sending-off of a key player can invalidate any pre-match analysis.
14. **Logistical / Team Disruption Discount**: Favorites experiencing severe off-field logistical disruptions (late travel arrivals, training camp relocations, visa delays) or team controversy (roster exclusion disputes) receive a 10–20% discount to their implied performance rating, particularly when facing cohesive, direct transition teams. Verify logistics in research step.
15. **Must-Win Favorite Overconfidence Trap**: When a team in a must-win situation (0 points, facing early elimination) is priced at -800 or shorter in betting markets, exercise extreme caution if that team has a documented finishing deficiency (see Heuristic #8). Market odds for desperate favorites are systematically inflated by narrative pressure — the market weights "must win" as motivation rather than analyzing whether the team can actually score. Cap confidence at Medium maximum regardless of opponent quality until the favorite demonstrates clinical improvement in the tournament.
16. **Post-Thrashing Defensive Reset**: A team that conceded 5+ goals in their opening match is more likely to adopt an extreme defensive posture (e.g., 5-4-1 formation) in their second match than to collapse again. The psychological "reset" effect — coupled with tactical adjustments after the loss — produces disciplined, motivated defending. After a heavy loss, the underdog's expected goal contribution is lower, but the favorite's expected goal output also falls because the defensive block is more extreme. When a thrashing victim faces a team with documented finishing struggles, significantly increase draw and low-scoring upset probability. This boost may also apply to debutants in their second match (contradicting the "Debutant Boost is Match-1 only" assumption — further observation needed).
17. **Set-Piece Advantage Check (New 2026-06-22)**: During pre-match analysis, evaluate each team's set-piece threat and vulnerability. Check all three: (a) does one team have a significant aerial/physical advantage? (b) does the opponent have a demonstrated set-piece vulnerability (conceded from corners/free kicks in prior matches)? (c) does the favorite have quality set-piece takers? If yes to 2+ questions, flag set pieces as a high-probability scoring path in the prediction reasoning — even if the team's open-play finishing appears poor. Validated by JOR-ALG: both Algeria goals came from corners (10-1 corner advantage), Mahrez provided the assist on the equalizer from a corner.
18. **Dead Rubber Motivation Asymmetry Rule (New 2026-06-24, Updated 2026-06-25)**: In dead rubber matches where one team's advancement is secure and the opponent faces elimination (or vice versa), the must-win team receives a motivation bonus of ~15-20% to their implied performance. If the draw-sufficient team also benches key starters (signaling conservatism through lineup rotation), the bonus may fully close the quality gap. When both conditions apply (motivation delta + starter benching), apply a one-notch confidence downgrade to the draw-sufficient team and explicitly document the motivation delta in reasoning. **Updated sub-clause (2026-06-25):** The rule applies even WITHOUT rotation if the draw-sufficient team has already secured advancement AND the opponent faces elimination. The motivation delta exists purely from match state, not just lineup decisions. When the crowd heavily favors the must-win team, apply an additional 5-10% confidence discount to the draw-sufficient favorite. Validated by ECU-GER 2026-06-25: Germany (6pts, no rotation, 55k Ecuadorian fans) lost 2-1 to Ecuador.

19. **Draw-Sufficiency Confidence Discount (Updated 2026-06-27)**: When the draw-sufficient team is the pre-match favorite AND its opponent is not yet eliminated AND both teams can advance with a draw, the predicted outcome should default to **DRAW (Low confidence)**, not a WIN prediction with a draw-risk note. A one-notch confidence discount is insufficient — the structural incentives produce conservative, shared-point outcomes. Trigger conditions: (a) team needs only 1pt to advance AND (b) opponent is not eliminated (has a realistic advancement path with a result) AND (c) match is in group stage. If the draw-sufficient team is the underdog, maintain the original one-notch discount on the favorite's WIN prediction (since the dynamic is different — the underdog is happy to draw, but the favorite still wants to win). Validated by three cases: RSA-KOR (2026-06-24), JPN-SWE (2026-06-25), ALG-AUT (2026-06-27 — 3-3 draw in a match where AUT needed 1pt, both teams advanced).

20. **Extreme Rotation Floor Rule (Updated 2026-06-27)**: When a team makes 6+ changes to their starting XI in a match, their effective quality drops materially regardless of squad depth. Confidence must be at most Low, even against a winless opponent. Trigger conditions: (a) 6+ starting XI changes from the team's prior match AND (b) no realistic advancement stakes for the rotating team. Exception: if the rotating team has elite bench depth (all 6+ changes are at most a 1-notch quality drop per position), confidence may remain at Medium maximum, with explicit documentation of why each change is quality-neutral. **Elite depth exception criteria (2026-06-27):** To apply the exception and remain at Medium, require: (a) 3+ players on the bench who are globally top-50, AND (b) opponent is a debutant or low-quality team (FIFA ranking outside top 50 OR winless in tournament), AND (c) each individual change is documented as at most a 1-notch quality drop per position. Validated by TUR-USA (2026-06-25, exception NOT met) and JOR-ARG (2026-06-27, exception likely met — Argentina's bench had Messi, Mac Allister, De Paul, Molina — but Low was still the conservative and correct call).

21. **Lineup Source Reliability (New 2026-06-25)**: FotMob live match center should be the single source of truth for confirmed starting XIs. Sofascore and other aggregators may display projected lineups as "confirmed." If a lineup source conflict arises, prefer FotMob. This is the third source reliability finding (following Khel Now for Ivory Coast on June 14 and 20). When searching for lineups, explicitly prefer queries that return FotMob or official team/federation announcement pages.

22. **Bielsa-System Defensive Fragility (New 2026-06-21, Uruguay-specific)**: Under Marcelo Bielsa's man-marking, high-pressing defensive system, individual defensive errors are more frequent because players are frequently isolated in one-on-one situations after the press is bypassed. Uruguay has now dropped points from a winning position (June 21 vs Cape Verde) due to individual defensive errors in set-piece situations. When predicting matches involving Bielsa-coached teams, apply a modest confidence discount—especially for HT-frozen predictions where Uruguay holds a lead—because a single individual error can erase that lead against a set-piece-capable opponent. This is a system-level risk (not a one-off), and it applies regardless of the quality of the individual defenders available.

23. **Midfield Continuity Check (New 2026-06-27)**: When a team is missing BOTH their primary defensive midfielder (ball-winner) AND their primary creative midfielder (playmaker) simultaneously in the starting XI, their attacking output drops by ~40-50% regardless of forward quality. For teams with star attackers dependent on service, this midfield gap is a structural confidence-reducing factor. If both absences are confirmed via official lineup, apply a one-notch confidence downgrade (or if at Low already, explicitly document the dependency risk in the prediction reasoning). Validated by COL-POR (2026-06-27): Portugal without Palhinha (DM) and Bernardo Silva (creator) managed only 0.63 xG against Colombia.

Do not update accuracy tables during this skill. That belongs to the postmortem skill.

Finally, read `{PREDICTIONS_PATH}` if it exists. Extract:

- Current prediction, confidence, and rationale for each active match.
- Questions for next iteration.
- Search history.
- Evidence already gathered.
- Last iteration number and timestamp.

Set the new iteration number to the previous iteration plus one. If this is the first prediction file for the day, start at iteration 1.

## Step 2: Research Plan

### Mandatory Pre-Match Checks (run before any searches)

Before choosing searches, perform these two checks for every eligible match and document the results:

**A. Draw-Sufficiency Check**: Determine each team's current group-stage points. If the favored team needs only 1 point to advance AND the opponent is winless or must-win, flag this as a Draw-Sufficiency situation. Apply Heuristic #19 (one-notch confidence downgrade) in Step 4. This check is mandatory — do not skip it for any group-stage match.

**B. Finishing Deficiency Pre-Screen**: For each team being considered as a predicted winner, check if they have prior tournament matches. If yes, look up their goals-vs-shots and goals-vs-xG ratios immediately. Document the ratios now so the Clinical Finishing Gate (Heuristic #8, Important Rule #13) can be applied efficiently in Step 4 without needing a separate research query.

---

For each eligible match, choose targeted searches in this order:

1. Questions from the previous iteration that could change the predicted winner or confidence.
2. Official lineups, team news, injury updates, press conferences, suspensions, and late fitness tests.
3. **Workload and fitness status** for key players returning from injury/illness — specifically whether they are expected to play a full 90 minutes or are on restricted minutes. This directly impacts late-game vulnerability.
4. **Clinical finishing efficiency** — for any team being predicted to win through sustained attacking pressure, look up their goals-vs-shots or goals-vs-xG ratio from prior tournament matches. A team with 25+ shots and 0–1 goals in a prior match has a documented clinical deficiency that must be reflected in confidence.
5. Live or near-live updates for `live_pre_halftime` matches, including score, red cards, injuries, tactical shape, and major momentum changes.
6. **Venue and pitch conditions** — check whether the stadium uses temporary grass over artificial turf, and search for any reports on pitch quality, weather, or surface deterioration. Apply the Temporary Grass Pitch Discount heuristic when relevant.
7. Betting market movement as a consensus signal, especially sharp late moves.
8. Tactical previews and beat reporting that explain why a lineup or matchup matters.
9. **Off-field disruptions** — check for any travel delays, camp relocations, visa issues, or squad-selection controversies affecting either team. Apply the Logistical / Team Disruption Discount heuristic when relevant.
10. Recent form and head-to-head history only when not already researched or when it directly informs an unresolved question.

Run at least 3 distinct searches per eligible match unless official lineups and all high-impact uncertainties are already resolved. Never reuse an exact query from prior search history. Prefer refined queries that add a player, source type, timestamp, language, venue, or tactical uncertainty.

### Pre-Match Window Gating

Do NOT search for "starting lineup", "starting XI", "confirmed lineup", or "official team sheet" for a match whose kickoff is more than 75 minutes away. Before that window, limit searches to:
- Injury and fitness updates
- Betting odds movements
- Tactical previews and press conference quotes
- Weather and pitch condition reports

This prevents wasting tokens on lineup queries that will return stale projections. Official lineups are typically released 60 minutes before kickoff.

### Evidence Staleness Detection

Before running full research for a match, check if the previous iteration's "Questions for Next Iteration" can actually be answered with new information (e.g., a lineup release window has opened, a match has kicked off, or a press conference has occurred). If ALL of the following are true:
- The match status has not changed since the last iteration.
- No new articles or data sources published since the last iteration's timestamp are found in the first 2 search queries.
- No match is within 75 minutes of kickoff or currently live.

Then output a minimal changelog entry: `No new evidence available — skipping full analysis. Prediction unchanged.` and set the interval to the maximum. This avoids burning tokens to rediscover the same stale information.

## Step 3: Evidence Discipline

Every material claim must be traceable to a source or search result. Record enough detail that a future postmortem can audit the reasoning.

Use these source confidence labels:

- `official`: FIFA, team federation, team sheet, verified team account, manager/player quote from a press conference, official match center.
- `strong`: reputable news outlet, beat reporter, major sports data provider, live match center, sportsbook market snapshot.
- `medium`: tactical preview, local media, lineup aggregator with a clear publication time.
- `weak`: unsourced rumor, social post without verification, generic prediction page, stale article.

Rules:

- Do not call a lineup, injury, or tactical setup "confirmed" unless the source is `official` or a `strong` live match center explicitly says it is confirmed.
- If a source says "probable", "projected", "expected", or "leaked", preserve that uncertainty.
- Prefer newer sources near kickoff. Stale information loses weight when contradicted by newer reporting.
- If sources conflict, document the conflict and weight the more official, more recent source higher.
- Distinguish facts from interpretation. Example: "Player X is absent from the official team sheet" is a fact; "this weakens Team A's left side" is analysis.
- Betting odds are a signal, not a conclusion. Use them to calibrate confidence and detect late information, not to replace reasoning.

## Step 4: Update Predictions

For each eligible match, decide whether the predicted outcome or confidence should change.

Change the predicted winner/draw only when new evidence materially changes the expected result. Examples:

- Official lineup removes or restores a decisive player.
- Live pre-halftime events materially alter the match state.
- Credible injury, suspension, weather, pitch, or tactical news changes the expected chance profile.
- Multiple strong sources contradict a prior key assumption.

Confidence changes should be calibrated:

- `High`: strong evidence alignment, few unresolved high-impact risks, and market/tactical signals broadly agree.
- `Medium`: favored outcome is supported, but one or more credible risks remain.
- `Low`: outcome is plausible but fragile, draw/upset risk is significant, or key information remains unresolved.

Apply validated heuristic adjustments to confidence:
- If the match is on a temporary grass pitch, a high-possession technical team should rarely receive `High` confidence unless their opponent is significantly weaker.
- If the favored team's playmaking core is on restricted workloads, downgrade confidence by one level to account for late-game vulnerability.
- When a defensive-block team has strong xG efficiency despite low possession in recent matches, treat them as a genuine upset threat—do not dismiss them based on possession stats alone.
- **Live-Monitoring Overreaction Rule**: For heavy favorites (e.g., moneyline < 1.15), do not adjust predictions/confidence during the first half (`live_pre_halftime`) based on scoreline fluctuations alone. Live adjustments must wait until halftime or require major structural changes (such as red cards or key injuries). A temporary equalizer for a massive favorite is match noise, not a structural event.
- **Draw Prediction Volatility Rule**: Draw predictions are highly volatile and subject to late goals. Always restrict Draw predictions to **Low confidence** unless there are clear mutual advancement table incentives or betting markets imply >35% draw probability. Medium confidence Draw predictions have been consistently overconfident and should be avoided.
- **Clinical Finishing Confidence Cap (MANDATORY ENFORCEMENT)**: Before assigning `Medium` or `High` confidence to any predicted winner, you MUST check and document that team's goals-vs-shots ratio from their prior tournament match(es). If goals-vs-shots ratio < 0.05 (e.g., 0 goals from 16+ shots) OR goals-vs-xG ratio < 0.5, confidence MUST be capped at **Low**. This is a non-negotiable compliance requirement — failure to apply this cap will be flagged as a SKILL.md violation. The postmortem on 2026-06-20 identified an explicit violation of this rule (ECU-CUR: High confidence despite 0 goals from 16 shots vs CIV). This pattern correctly predicts ongoing deficiency, not temporary bad luck.
- **Host-Nation + Squad Depth Rule**: Do not downgrade a host-nation prediction to DRAW against a purely defensive opponent due to a single player absence (even a star). Only downgrade if the opponent has proven goal-scoring capability. Host-nation crowd advantage and squad depth compensate for individual absences against defensive-only opponents.

Move confidence by at most one level per iteration unless official or live evidence decisively changes the match.

Avoid churn:

- If an uncertainty has not changed since the prior iteration, do not restate it as newly discovered.
- If a question has been partially resolved, narrow the next question to the remaining unknown.
- Do not generate live-match questions for a match that has not kicked off; frame them as future watchpoints.
- Do not continue asking for official lineups once official lineups are verified.

Use this format in `{PREDICTIONS_PATH}`:

> **CRITICAL LAYOUT RULE:** The `## 📊 Executive Summary Table` section MUST be the very first section after the title. It must list EVERY active match being predicted in a single table, including columns for Match, Status, Prediction, Confidence, and Last Updated. The Last Updated column must record the exact UTC timestamp of the iteration when that match's prediction or confidence last changed. If it did not change this iteration, carry forward the previous timestamp. Do NOT place any match-level analysis before this table. Agents that omit or delay this section or these columns are non-compliant.

```markdown
---
date: "{DATE}"
iteration: <iteration_number>
last_updated: "<current UTC timestamp>"
matches_covered: <number of matches still being actively tracked before estimated full time>
overall_confidence: "<brief summary>"
model: "{AGENT}: <your model name/version, e.g., Claude Sonnet 4.6 or Gemini 2.5 Flash>"
next_interval_minutes: <determined interval integer, e.g., 15>
next_difficulty: "<high, medium, or low>"
---

# World Cup 2026 Predictions for {DATE} - Iteration <N>

## 📊 Executive Summary Table
A quick-glance tracker of the predicted results, confidence levels, and when they were last updated.

| Match | Status | Prediction | Confidence | Last Updated |
|:------|:-------|:-----------|:-----------|:-------------|
| [Team A] vs. [Team B] | [not_started / live_pre_halftime / live_post_halftime] | [TEAM A WIN / TEAM B WIN / DRAW] | [High / Medium / Low] | [UTC timestamp when prediction/confidence last changed, e.g. YYYY-MM-DDTHH:MM:SSZ] |
| ... | ... | ... | ... | ... |

---

## 🔍 Detailed Match Analysis

### Match: [Team A] vs. [Team B]

**Status:** [not_started / live_pre_halftime / live_post_halftime]
**Kickoff:** HH:MM UTC | **Venue:** [venue] | **Group/Round:** [group/round]

### Prediction: [TEAM A WIN / TEAM B WIN / DRAW]
**Confidence:** [High / Medium / Low]

### Reasoning
2-4 sentences explaining the decisive factors and the main way the prediction could fail.

### Key Factors
- [Source confidence] [Fact or signal supporting the prediction]
- [Source confidence] [Second key factor]
- [Risk] [Specific uncertainty that could change the result]
- [Invalidator] [What would make this prediction wrong]

### Evidence Gathered This Iteration
- [official/strong/medium/weak] [source or search query]: [finding and why it matters]

### Search History
- **Iteration <N>**: `query 1`, `query 2`, `query 3`

### Questions for Next Iteration
1. [Outcome-linked question; explicitly state how the answer would change the winner or confidence]
2. [Outcome-linked question]
3. [Outcome-linked question]

### Prediction Changes
- **Previous prediction:** [previous outcome/confidence, or "None"]
- **Change:** [what changed and why, or "No change - prediction reinforced/unchanged because ..."]
```

## Step 5: Changelog Entry

Prepend one entry to `{CHANGELOG_PATH}` directly under the file's main title header so that the newest iteration is always at the top of the file. If the file does not exist, create it with a title header (e.g. `# 📝 World Cup 2026 Prediction Changelog — {DATE}`) first, then prepend the entry.

The changelog entry should be compact but auditable:

```markdown
## Iteration <N> - <current UTC timestamp>
**Model Used:** [model name/version]
**Next Interval:** <minutes> minutes
**Tokens:** [injected post-execution by orchestrator]

### Eligible Matches
- [Match]: [not_started/live_pre_halftime/live_post_halftime/complete]

### Changes
- [Match]: [Prediction/confidence change, or no change with one-sentence reason]

### Search Queries Executed
- [Match]: `query 1`, `query 2`, `query 3`

### New Evidence
- [Match]: [source confidence] [brief finding and materiality]

### Open Questions Resolved
- [Prior question]: [answer, source confidence, and prediction impact]

### New Questions Raised
- [New outcome-linked question]

### Next Interval Reason
- Wrote `<minutes>` minutes to `{INTERVAL_PATH}` because [brief reason].
```

Use a fresh UTC timestamp. Do not duplicate an iteration number. If a retry would create the same iteration twice, prepend a corrected entry that clearly supersedes the failed or partial run.

## Step 6: Tracker Updates

Usually, do not edit `{TRACKER_PATH}` during prediction iterations. The postmortem skill owns accuracy, lessons, and validated heuristic updates.

Only update the tracker if the iteration uncovers a reusable insight that is both important and supported by strong evidence across more than one match or by prior postmortems. If an insight is plausible but unvalidated, add it as an open question or leave it in the changelog instead of promoting it to an active heuristic.

Never add a same-day pre-match observation to "Active Heuristics" as if it were proven by results.

## Step 7: Dynamic Interval and Model Selection

1. Choose the next interval from 60 to 180 minutes based on the nearest eligible match or live match and the information rate, prioritizing token efficiency and avoiding unnecessary calls:
   - Write only the determined integer to `{INTERVAL_PATH}` (the file must contain exactly one integer with no other text).
   - Set the `next_interval_minutes` key in the `{PREDICTIONS_PATH}` frontmatter to this integer.
   - Record `**Next Interval:** <minutes> minutes` in the `{CHANGELOG_PATH}` entry header.

Default interval guide (optimized for token efficiency):
- `60-80`: ONLY when a match is live and fast-changing with high-impact events (e.g., a red card or major injury in the first half) that immediately alter the prediction state, OR during the lineup and warm-up window (kickoff is within 60 minutes) when official lineups are actively arriving.
- `84-120`: Kickoff is within 2 hours.
- `124-180`: Kickoff is more than 2 hours away, the news cycle is quiet, a live match is in progress but stable with no major events, or the live match prediction has been frozen under the Weighted Halftime Rule, or two consecutive runs yielded no new material evidence.
- **Medium-Confidence Match Coverage Rule (New 2026-06-22)**: When a match with Medium confidence is within 2 hours of kickoff, the interval MUST NOT exceed 90 minutes after kickoff. This ensures the system lands during the second half (not after full time) to capture HT state and apply the Weighted Halftime Rule. Never set an interval that would skip entirely over a Medium-confidence match's first half and halftime. (Violated on 2026-06-22: 170-min interval skipped JOR-ALG's HT entirely.)

Adjust for information rate and token efficiency:
- **Lineup Gate Alignment Rule**: If an upcoming match is within 2-4 hours of kickoff, the next interval MUST be precisely calculated to land 45-60 minutes before kickoff. This ensures that the system runs during the official lineup release window to verify starters and make any necessary pre-match prediction updates, rather than landing too early or bypassing kickoff entirely.
- Shorten by 8-20 minutes if this iteration found material new evidence (e.g., official lineup sheet published), but never go below 60 minutes.
- Lengthen by 20-40 minutes if two consecutive iterations found no material new evidence, pushing quickly to 180 minutes to conserve tokens.
- If the orchestrator indicates this is a staleness-override iteration (staleness ≥ 3), default to 180 minutes unless a match is live or about to kick off within 60 minutes.
- Use `180` if there are no eligible or live matches left before estimated full time, and state this in the changelog.

The file content of `{INTERVAL_PATH}` must be exactly one integer between 60 and 180.

### Iteration Budget and Start-Time Guidance

Token efficiency requires limiting the total number of iterations per matchday and starting the run at the right time. Postmortems have shown that early-start, low-value iterations account for 65-70% of total token burn with zero prediction changes.

**Recommended start time:** Do NOT begin the prediction loop more than ~5 hours before the first match kickoff. For a 20:00 UTC kickoff slot, begin at ~15:00 UTC (not 09:00 UTC). This eliminates 3-4 low-value pre-lineup iterations that produce no prediction changes. Violated on 2026-06-28: the loop started at 03:42 UTC for a 19:00 UTC kickoff, producing 4 low-value staleness iterations that burned ~100k excess tokens. The orchestrator should consider a launch guardrail: if `current_utc < first_kickoff_utc - 10 hours`, delay launch.

**Iteration budget per matchday (3 match time-slots):**
- Target: **≤7 total iterations**. Suggested allocation:
  1. **Initial predictions** — pre-match analysis for all matches (~5h before first kickoff)
  2. **Pre-lineup evidence** — injury, press, venue for upcoming match slot (~2h before kickoff)
  3. **Lineup verification** — official XI confirmation (45-60min before kickoff of slot 1)
  4. **WHT slot 1** — HT assessment and freeze/downgrade decision
  5. **FT slot 1 + lineup slot 2** — results + injury/press for next slot
  6. **WHT slot 2 + lineup slot 3** — HT + next lineup verification
  7. **FT slot 2 + WHT/FT slot 3** — final results verification
- If there are only 1-2 match time-slots, cap at **≤5 total iterations**. For knockout matches that may go to extra time (120+ min), budget 1 additional WHT-check iteration at ~105 min if the score is level and confidence is Medium+, bringing the cap to 6.
- If the iteration produces zero prediction or confidence changes AND no match is within 90 minutes of kickoff or halftime, do NOT schedule a follow-up iteration below 180 minutes.

3. Predict the complexity/difficulty of the questions for the next iteration:
   - If the next questions are predicted to be hard (e.g., they require deep tactical interpretation, complex analysis of conflicting reports, or resolving late lineup updates close to kickoff), set the `next_difficulty` key in the `{PREDICTIONS_PATH}` frontmatter to `high`.
   - If the questions are very straightforward (e.g., just verifying a stable/unchanged lineup or monitoring a stable live match with no key changes expected), set the `next_difficulty` key to `low` to conserve tokens by running a cheaper model.
   - Otherwise, set the `next_difficulty` key to `medium`.

## Important Rules

1. **Be honest about uncertainty.** A low-confidence prediction with clean reasoning is better than false precision.
2. **Do not anchor to previous predictions.** Change the outcome when the evidence justifies it, and explain why.
3. **Do not invent details.** If evidence is missing, state that it is unresolved and make it a targeted question.
4. **Treat draws as normal group-stage outcomes.** Actively evaluate whether tactical conservatism, table incentives, or lineup weakness make a draw the best prediction. But always cap Draw confidence at Low unless two or more structural draw conditions apply (see Heuristic #9).
5. **Keep questions actionable and causal.** Every question must explain how its answer could change the winner or confidence.
6. **Keep source provenance visible.** A future postmortem should be able to tell which claims came from official facts, strong reporting, market movement, or analysis.
7. **Weighted Halftime Rule.** At halftime, evaluate whether the live score is consistent with the pre-halftime analytical prediction:
   - **If live score CONFIRMS the prediction** (e.g., predicted TEAM A WIN and Team A is leading): Freeze the prediction — keep gathering live evidence for audit but do not change the outcome or confidence.
   - **If live score CONTRADICTS the prediction** (e.g., predicted TEAM A WIN but Team A is trailing or drawing against a much weaker opponent): Do NOT automatically flip the prediction. Instead, weigh the live score against the pre-match analytical foundation. Only change the prediction if the live evidence reveals a *structural* reason the pre-match analysis was wrong (e.g., a red card, a key injury, or a fundamental tactical mismatch not anticipated). A temporary scoreline alone is insufficient to override a well-founded analytical prediction.
   - **CRITICAL**: Do NOT freeze a prediction that is actively *contradicted* by the halftime score AND where no structural reason for the contradiction has been found. A freeze should only occur when the live score *confirms* the prediction. If the score contradicts the prediction and no structural cause is identified, mark the confidence as Low and flag it for postmortem review — do not silently freeze an incorrect prediction.
   - **Personnel Quality Assessment (New 2026-06-21)**: When evaluating whether a team trailing at HT is "structurally incapable of scoring" (justifying a flip) vs. "playing poorly" (justifying a downgrade but not a flip), you MUST explicitly evaluate the team's individual finishing quality, not just team-level xG. A team with elite individual finishers (e.g., Salah, Mbappe, Haaland) can overcome sub-0.10 xG at HT through second-half converting of individually-created chances. The distinction is: team-level xG reflects chance quality, but elite individuals manufacture goals that models underestimate. Only flip a prediction if the team lacks the finishing personnel to realistically overturn the scoreline — not just because first-half xG was poor. Validated by NZ-EGY (2026-06-21): Egypt trailed 1-0 at HT with 0.04 xG but Salah/Marmoush/Trezeguet scored 3 second-half goals to win 3-1.
   - **Goal Sustainability Assessment (New 2026-06-24)**: When the underdog's goals come from low-probability sources (own goal, deflection, long-range strike), treat the HT scoreline as LESS structurally significant than the pre-match analytical foundation. An underdog with goals from non-sustainable patterns (OG + long range) is not the same as an underdog with structural attacking success (sustained pressure, repeated quality chances). When underdog goals are deemed unsustainable AND the favorite has dominant xG, the HT score alone should NOT justify a confidence downgrade. Validated by MAR-HAI 2026-06-24: Haiti's 2 goals (OG Bounou 10', Isidor long-range 43') were both low-probability events — Morocco had 2.15 xG in the first half alone. The system correctly froze the prediction at Medium despite the 2-2 HT scoreline.
   - From halftime until estimated full time, keep gathering concise live evidence for audit and postmortem context.
8. **Use the dynamic interval every run.** The loop frequency is part of the prediction system, not an afterthought.
9. **Prevent live-monitoring churn and panic.** During live-match tracking, do not fluctuate confidence levels or predictions based on temporary in-game momentum shifts. For heavy favorites (e.g., moneyline < 1.15 or handicap > 2.5 goals), ignore temporary first-half equalizers or slow starts. Do not adjust predictions or confidence during the first half (`live_pre_halftime`) based on scoreline fluctuations alone. Live adjustments must wait until halftime or require major structural changes (such as red cards or key player injuries).
10. **Token efficiency discipline (No Intermediate Live Polling Rule).** Do not run intervals below 120 minutes if the nearest kickoff is more than 2 hours away. If there are no active lineup releases or live matches, or if live matches are stable and frozen under the Weighted Halftime Rule, the interval should default to 180 minutes (or set to land 15-20 minutes after estimated full time) to prevent wasting resources on static news cycles or stable live scores.
11. **Rigorous result verification.** At the end of the matchday (or once a match is complete), you must verify the final score, goalscorers, and key match events using at least two independent official or strong sources (e.g., FIFA.com, ESPN, BBC) rather than relying on live updates or partial blogs, to prevent miscoding late/stoppage-time goals. Wait at least 15 minutes after estimated full time before recording the final score to capture stoppage-time events.
12. **Live-play scoreline verification.** During live-match monitoring, never rely on a single source or live blog for the current score or match events. Verify the score, cards, and goals across at least two independent sports databases (e.g., FotMob, Sofascore, ESPN Match Center) before making decisions under the Weighted Halftime Rule. If sources conflict or seem outdated, run a targeted search for the latest minute of the match to resolve the discrepancy. **NEVER use search queries that assume a specific scoreline** (e.g., searching for `"0-0"` or `"1-0"`). All queries must use neutral terms (e.g., `"score"`, `"match events"`, or `"match center"`) to prevent confirmation bias and hallucinations from stale results.
13. **Clinical deficiency pre-check (MANDATORY).** Before assigning Medium or High confidence to a predicted winner, check if that team has a documented finishing deficiency from prior tournament matches (high shots / low goals). If yes, cap confidence at Low until demonstrated improvement. This is not optional — prior finishing efficiency is the strongest single-match predictor of goal output in pressure games.
14. **Single-player absence rule for host nations.** When a host nation is missing even their most important offensive player, do not downgrade to DRAW if the opponent is a purely defensive, low-transition team with minimal scoring capability. The host-nation effect, crowd pressure, and squad depth gap are stronger predictors than the missing player. Evaluate the opponent's goal-scoring capability — not just the favorite's offensive loss.
15. **Dead rubber rotation depth rule.** In dead rubbers where both teams rotate heavily, the team with greater squad depth (bench quality, not just XI quality) has the advantage. Heavily rotated lineups from shallow squads (e.g., Czechia without Schick/Soucek) are substantially weaker than heavily rotated lineups from deep squads (e.g., Mexico without Ochoa/Jimenez/Gimenez). When evaluating a dead rubber with confirmed heavy rotation on both sides, explicitly compare bench depth — not just rotated XI quality. Validated by CZE-MEX 2026-06-24: Mexico's second XI defeated Czechia's second XI 3-0.

16. **Maximum iterations per matchday.** Do not exceed 7 iterations for a 3-slot matchday or 5 iterations for a 1-2 slot matchday. If the current iteration count is approaching the cap AND the remaining matches are not yet live, increase the interval aggressively (toward 180 minutes) to preserve capacity for HT and FT assessments. High-value iterations (lineup verification, WHT, result verification) must never be sacrificed for low-value early-research iterations.

17. **Post-WHT interval efficiency (New 2026-06-27).** Once all live matches have been frozen under the Weighted Halftime Rule (regardless of whether they confirm or contradict the prediction), the next polling interval MUST be set to land at least 15 minutes after the estimated full time of the latest match — NOT at an intermediate point like 60-70 minutes. There is no actionable information between the WHT freeze and final whistle for frozen matches. A post-WHT check during the match (~61') is a low-value iteration that confirms already-known states. Example: if WHT is applied at ~01:00 and estimated FT is ~03:40, set interval to land at ~04:00, not at ~02:00 or ~03:00. This saves ~120k tokens per matchday.
