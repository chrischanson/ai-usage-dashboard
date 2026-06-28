---
date: "2026-06-28"
match_count: 1
tournament_phase: "Knockout Stage"
generated_at: "2026-06-28T03:45:00Z"
---

# 📅 World Cup 2026 — Match Schedule for 2026-06-28

## Today's Matches

| # | Kickoff (UTC) | Match | Venue | Group/Round |
|:--|:--------------|:------|:------|:------------|
| 73 | 19:00 | South Africa vs Canada | Los Angeles Stadium (SoFi Stadium), Inglewood, California, USA | Round of 32 |

> **Note:** June 28 is the opening day of the **Round of 32**, and it has only **one** scheduled match. The next knockout matches (M74 Germany vs Paraguay, M75 Netherlands vs Morocco, M76 Brazil vs Japan) are on **June 29**.
>
> **Kickoff conversions:** 3:00 PM ET / 12:00 PM PT / 19:00 UTC (EDT = UTC−4 in late June). Cross-verified across FIFA.com, Sporting News, Wego, Syracuse.com, and Match Marker.
>
> **Knockout reminder:** This is a single-elimination match. If level after 90 minutes, **extra time (2×15 min)** and, if needed, a **penalty shootout** follow — meaning the actual finish may run ~30–45+ minutes later than the regulation estimate. Timings below assume regulation full time; see the contingency note in Match Windows.

## Historical Context

Brief notes on prior predictions involving today's teams (from `prediction_tracker.md`):

- **South Africa (Group A → R32 runner-up):**
  - 2026-06-24 — South Africa vs South Korea: predicted **SOUTH KOREA WIN (Low)**, actual **SOUTH AFRICA WIN 1-0** → ❌ (pre-game).
  - South Africa's quality has been **underrated** by the system so far (the "Dead Rubber Motivation Asymmetry" / draw-sufficiency lesson from RSA-KOR applies: Korea needed only a draw, benched Son, and lost). Bafana Bafana reached the knockouts for the first time in their history.
  - **Prediction record involving RSA: 0/1.**

- **Canada (Group B → R32 runner-up):**
  - 2026-06-18 — Canada vs Qatar: predicted **CANADA WIN (Med)**, actual **CANADA WIN 6-0** → ✅.
  - 2026-06-24 — Switzerland vs Canada: predicted **SWITZERLAND WIN (Low)**, actual **SWITZERLAND WIN 2-1** (Canada lost) → ✅.
  - Host-nation/home-advantage notes applied earlier, but **Canada is now away from home soil** in Los Angeles — the home-advantage heuristic that aided earlier Canada predictions no longer applies. Key player note: Ismaël Koné suffered a serious leg injury earlier in the tournament (open question on Canada's midfield dynamics).
  - **Prediction record involving CAN: 2/2.**

- **Relevant lessons that may apply today:**
  - Both teams finished as **group runners-up**; this is a balanced knockout matchup with no draw outcome (extra time / penalties resolve ties).
  - The system has historically **underrated South Africa** — avoid an over-discounted RSA assessment.
  - Canada loses its home-advantage edge in Inglewood; re-baseline Canada without the host-nation bonus.
  - **Do NOT make a prediction here** — that is handled by the `predict` skill.

## Match Windows

Summary of when the prediction loop should run (all times UTC):

- **First match kickoff:** 19:00 UTC
- **Last match estimated halftime:** 19:50 UTC (≈ 45 min + stoppage after kickoff)
- **Last match estimated end (regulation):** 20:55 UTC (≈ 90 min play + 15 min HT break + stoppage)
- **Prediction/analysis loop window:** 17:00 to 20:55 UTC (start ~2h before kickoff for pre-match analysis; monitor through full time)
- **Postmortem target time:** 22:55 UTC (2h after regulation end)

> **Knockout contingency:** If the match is drawn after 90 minutes, extra time + penalties can push the actual end to ≈ 21:40–22:00 UTC. In that case, shift the postmortem target to ≈ 23:40–24:00 UTC (2h after the actual final whistle). Verify the true finish time before recording the result (apply the Final Score Verification Buffer Heuristic — wait ≥15 min after the final whistle and confirm across ≥2 sources).

## Match Timing Data

<!-- MATCH_DATA_START -->
- match_73: {teams: "South Africa vs Canada", kickoff_utc: "19:00", estimated_halftime_utc: "19:50", estimated_end_utc: "20:55"}
<!-- MATCH_DATA_END -->
