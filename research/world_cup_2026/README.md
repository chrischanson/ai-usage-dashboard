# ⚽ World Cup 2026 — AI Prediction Research

An automated, self-improving research system that predicts FIFA World Cup 2026 match outcomes, iteratively refines predictions through live web research, and learns from post-match analysis to improve future accuracy.

---

## 🏗️ Architecture

The system runs three skills in a daily cascade:

```
Morning          During Matches         After Matches
  │                    │                      │
  ▼                    ▼                      ▼
┌──────────┐    ┌────────────┐         ┌────────────┐
│  daily   │───▶│  predict   │────────▶│ postmortem │
│ schedule │    │ (5 min ×)  │         │ (2h after) │
└──────────┘    └────────────┘         └────────────┘
       │               │                      │
       └───────────────┼──────────────────────┘
                       ▼
              prediction_tracker.md
              (persistent memory)
```

| Skill | Trigger | Frequency | Purpose |
|:------|:--------|:----------|:--------|
| `daily_schedule` | Morning cron | Once/day | Fetch today's match schedule from the web |
| `predict` | After schedule is fetched | Every 5 min until halftime | Iteratively refine Win/Lose/Draw predictions with web research |
| `postmortem` | ~2h after each match ends | Once per match | Evaluate accuracy, extract lessons, update tracker |

---

## 📂 File Structure

```
research/world_cup_2026/
├── README.md                      # This file
├── prediction_tracker.md          # Shared persistent memory (entire tournament)
├── prediction_interval.txt        # Dynamic configuration of prediction loop interval (in minutes)
├── run_day.sh                     # Orchestrator script
├── daily_schedule/
│   └── SKILL.md                   # Skill: fetch today's match schedule
├── predict/
│   └── SKILL.md                   # Skill: iterative prediction refinement
├── postmortem/
│   └── SKILL.md                   # Skill: post-match analysis
└── runs/
    ├── day_2026-06-13/
    │   ├── match_schedule.md      # Today's matches
    │   ├── predictions.md         # Working doc (overwritten each iteration)
    │   ├── changelog.md           # Append-only log of prediction changes
    │   └── postmortem.md          # Post-match analysis
    ├── day_2026-06-14/
    │   └── ...
    └── ...
```

---

## 🚀 Running

### Manual (Single Day)

```bash
# From workspace root
cd research/world_cup_2026

# Run the daily schedule skill
python3 ../../skills/run_skill.py daily_schedule --vars "DATE=$(date +%Y-%m-%d)"

# Run a single prediction iteration
python3 ../../skills/run_skill.py predict --vars "DATE=$(date +%Y-%m-%d)"

# Run postmortem after matches
python3 ../../skills/run_skill.py postmortem --vars "DATE=$(date +%Y-%m-%d)"
```

### Automated (Full Tournament)

Use the `/schedule` command in Antigravity IDE to set up recurring cron jobs, or run:

```bash
bash run_day.sh
```

The orchestrator handles the full daily cascade automatically.

---

## 🧠 How It Self-Improves

1. **Each prediction iteration** reads the shared `prediction_tracker.md` for lessons learned from past matches
2. **The postmortem** analyzes prediction accuracy and extracts concrete insights (e.g., "Underestimated Group B teams consistently")
3. **Future predictions** incorporate these heuristics, leading to improved accuracy over the tournament
4. **Open questions** from each iteration carry forward, ensuring the system digs deeper on unresolved topics

---

## 📊 Key Outputs

- **Win/Lose/Draw predictions** with confidence levels (High/Medium/Low)
- **Reasoning** grounded in web-researched evidence
- **Prediction evolution** tracked via changelogs showing how predictions refined over time
- **Accuracy statistics** broken down by confidence level and tournament phase
- **Lessons learned** accumulating throughout the tournament
