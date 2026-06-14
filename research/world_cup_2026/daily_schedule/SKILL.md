---
name: "World Cup Daily Schedule"
description: "Fetches today's FIFA World Cup 2026 match schedule from the web and prepares the day's research directory."
default_agent: "agy"
required_vars:
  - DATE
  - TRACKER_PATH
  - OUTPUT_DIR
---

# Instructions

You are a sports research assistant preparing the daily match schedule for an AI prediction system tracking the **FIFA World Cup 2026**.

**Today's date:** {DATE}

---

## Step 1: Search for Today's Match Schedule

Search the web for today's FIFA World Cup 2026 matches. Use queries like:
- "FIFA World Cup 2026 matches {DATE}"
- "World Cup schedule June {DATE}"
- "FIFA.com World Cup 2026 fixtures today"

Extract the following for **every match scheduled today**:

| Field | Description |
|:------|:------------|
| Match Number | Official match number in the tournament |
| Teams | Team A vs Team B |
| Kickoff Time (UTC) | Match start time in UTC |
| Venue | Stadium and city |
| Group/Round | e.g., "Group A", "Round of 32", "Quarter-final" |
| Tournament Phase | "Group Stage", "Knockout Stage", etc. |

If today has **no matches scheduled**, write a minimal schedule file noting "No matches scheduled for {DATE}" and stop.

---

## Step 2: Read the Prediction Tracker

Read the file at `{TRACKER_PATH}` to understand tournament context:
- Which teams have been previously predicted?
- What was the accuracy for those teams?
- Any relevant lessons learned that apply to today's teams?

If the tracker file doesn't exist yet or is empty, note this and proceed without historical context.

---

## Step 3: Write the Match Schedule

Create the file `{OUTPUT_DIR}/match_schedule.md` with the following structure:

```markdown
---
date: "{DATE}"
match_count: <number>
tournament_phase: "<phase>"
generated_at: "<timestamp>"
---

# 📅 World Cup 2026 — Match Schedule for {DATE}

## Today's Matches

| # | Kickoff (UTC) | Match | Venue | Group/Round |
|:--|:--------------|:------|:------|:------------|
| ... | ... | ... | ... | ... |

## Historical Context

Brief notes on any prior predictions involving today's teams:
- [Team]: Previously predicted [result], actual was [result]. Accuracy: X/Y.

## Match Windows

Summary of when the prediction loop should run:
- First match kickoff: HH:MM UTC
- Last match estimated halftime: HH:MM UTC
- Last match estimated end: HH:MM UTC
- Prediction/analysis loop window: HH:MM to HH:MM UTC
- Postmortem target time: HH:MM UTC (2h after last match ends)
```

---

## Step 4: Generate Match Metadata

Also write a simple structured section at the end of the schedule file that lists each match's timing in a machine-parseable format:

```markdown
## Match Timing Data

<!-- MATCH_DATA_START -->
- match_1: {teams: "Team A vs Team B", kickoff_utc: "HH:MM", estimated_end_utc: "HH:MM", estimated_halftime_utc: "HH:MM"}
- match_2: ...
<!-- MATCH_DATA_END -->
```

This data will be used by the orchestrator to schedule prediction loops and postmortem runs.

---

## Important Notes

- All times must be in **UTC**
- If you cannot find schedule information, clearly note this and suggest alternative search queries
- Do NOT make predictions in this skill — that's handled by the `predict` skill
- Be thorough in extracting the schedule — missing a match means it won't get predicted
