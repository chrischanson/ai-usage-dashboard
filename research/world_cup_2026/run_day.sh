#!/usr/bin/env bash
# World Cup 2026 — Daily Orchestrator
# Runs the full daily prediction cascade:
#   1. Fetch today's match schedule
#   2. Run prediction loop every 15 minutes
#   3. Schedule postmortem after matches end
#
# Usage:
#   bash run_day.sh              # Run for today with agy (default)
#   bash run_day.sh 2026-06-14   # Run for a specific date with agy
#   bash run_day.sh --opencode   # Run today with opencode primary agent

set -euo pipefail

# --- Configuration ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
SKILLS_RUNNER="${WORKSPACE_DIR}/skills/run_skill.py"
TRACKER_PATH="${SCRIPT_DIR}/prediction_tracker.md"
INTERVAL_PATH="${SCRIPT_DIR}/prediction_interval.txt"

# --- Parse arguments ---
AGENT="agy"
FALLBACK_AGENT="opencode"
DATE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --opencode)
            AGENT="opencode"
            FALLBACK_AGENT="agy"
            shift
            ;;
        *)
            if [ -z "${DATE}" ]; then
                DATE="$1"
            else
                echo "Error: Unknown argument '$1'" >&2
                exit 1
            fi
            shift
            ;;
    esac
done

DATE="${DATE:-$(date -u +%Y-%m-%d)}"
DAY_DIR="${SCRIPT_DIR}/runs/day_${DATE}"

SCHEDULE_PATH="${DAY_DIR}/match_schedule.md"
PREDICTIONS_PATH="${DAY_DIR}/predictions.md"
CHANGELOG_PATH="${DAY_DIR}/changelog.md"

# Validate DATE format (YYYY-MM-DD)
if ! echo "${DATE}" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'; then
    echo "Error: Invalid date format '${DATE}'. Expected YYYY-MM-DD." >&2
    exit 1
fi

echo "=========================================="
echo "⚽ World Cup 2026 — Daily Orchestrator"
echo "=========================================="
echo "Date:        ${DATE}"
echo "Agent:       ${AGENT}"
echo "Day Dir:     ${DAY_DIR}"
echo "Tracker:     ${TRACKER_PATH}"
echo "=========================================="

# --- Step 0: Create day directory ---
mkdir -p "${DAY_DIR}"
echo "[$(date -u +%H:%M:%S)] Created day directory: ${DAY_DIR}"

# --- Step 1: Fetch today's match schedule ---
echo ""
echo "--- Step 1: Fetching Match Schedule ---"

# The skills are inside this project, but run_skill.py expects them
# relative to the skills/ directory. We need to create symlinks or
# pass the skill path directly. Since our skills are in a different
# location, we invoke agy directly.

SCHEDULE_VARS="DATE=${DATE}"
SCHEDULE_VARS="${SCHEDULE_VARS},TRACKER_PATH=${TRACKER_PATH}"
SCHEDULE_VARS="${SCHEDULE_VARS},OUTPUT_DIR=${DAY_DIR}"
SCHEDULE_VARS="${SCHEDULE_VARS},AGENT=${AGENT}"

if [ -f "${SKILLS_RUNNER}" ]; then
    # Create a temporary symlink so run_skill.py can find our skills
    SKILL_LINK="${WORKSPACE_DIR}/skills/wc_daily_schedule"
    if [ ! -e "${SKILL_LINK}" ]; then
        ln -sf "${SCRIPT_DIR}/daily_schedule" "${SKILL_LINK}"
    fi
    if OUTPUT=$(python3 "${SKILLS_RUNNER}" wc_daily_schedule --agent "${AGENT}" --vars "${SCHEDULE_VARS}"); then
        echo "${OUTPUT}"
    else
        echo "Warning: ${AGENT} daily schedule failed. Trying ${FALLBACK_AGENT} fallback..." >&2
        OUTPUT=$(python3 "${SKILLS_RUNNER}" wc_daily_schedule --agent "${FALLBACK_AGENT}" --vars "${SCHEDULE_VARS}")
        echo "${OUTPUT}"
    fi
    # Extract the run directory from output
    RUN_DIR=$(echo "${OUTPUT}" | grep "Execution logs and metadata saved to:" | sed 's/Execution logs and metadata saved to: //')
    if [ -n "${RUN_DIR}" ] && [ -d "${RUN_DIR}" ]; then
        if [ -f "${RUN_DIR}/match_schedule.md" ]; then
            cp -f "${RUN_DIR}/match_schedule.md" "${DAY_DIR}/"
            echo "[$(date -u +%H:%M:%S)] Copied match_schedule.md to ${DAY_DIR}/"
        fi
    fi
    # Clean up symlink
    rm -f "${SKILL_LINK}"
else
    echo "Warning: run_skill.py not found, invoking ${AGENT} directly" >&2
    # Read and compile the skill prompt manually
    SKILL_CONTENT=$(cat "${SCRIPT_DIR}/daily_schedule/SKILL.md")
    # Replace variables
    COMPILED="${SKILL_CONTENT//\{DATE\}/${DATE}}"
    COMPILED="${COMPILED//\{TRACKER_PATH\}/${TRACKER_PATH}}"
    COMPILED="${COMPILED//\{OUTPUT_DIR\}/${DAY_DIR}}"
    if [ "${AGENT}" = "opencode" ]; then
        opencode run --dangerously-skip-permissions "${COMPILED}" || {
            echo "Warning: opencode failed. Trying agy fallback..." >&2
            agy --dangerously-skip-permissions --print "${COMPILED}"
        }
    else
        agy --dangerously-skip-permissions --print "${COMPILED}" || {
            echo "Warning: agy failed. Trying opencode fallback..." >&2
            opencode run --dangerously-skip-permissions "${COMPILED}"
        }
    fi
fi

echo "[$(date -u +%H:%M:%S)] Schedule fetched."

# --- Step 2: Check if there are matches today ---
if [ ! -f "${SCHEDULE_PATH}" ]; then
    echo "No schedule file generated — possibly no matches today."
    echo "Exiting."
    exit 0
fi

if grep -qi "no matches scheduled" "${SCHEDULE_PATH}"; then
    echo "No matches scheduled for ${DATE}. Exiting."
    exit 0
fi

echo "Matches found for today. Starting prediction loop."

# --- Step 3: Prediction Loop ---
echo ""
echo "--- Step 3: Prediction Loop (every 15 minutes) ---"

PREDICT_VARS="DATE=${DATE}"
PREDICT_VARS="${PREDICT_VARS},SCHEDULE_PATH=${SCHEDULE_PATH}"
PREDICT_VARS="${PREDICT_VARS},TRACKER_PATH=${TRACKER_PATH}"
PREDICT_VARS="${PREDICT_VARS},PREDICTIONS_PATH=${PREDICTIONS_PATH}"
PREDICT_VARS="${PREDICT_VARS},CHANGELOG_PATH=${CHANGELOG_PATH}"
PREDICT_VARS="${PREDICT_VARS},INTERVAL_PATH=${INTERVAL_PATH}"
PREDICT_VARS="${PREDICT_VARS},OUTPUT_DIR=${DAY_DIR}"
PREDICT_VARS="${PREDICT_VARS},AGENT=${AGENT}"

ITERATION=0
MAX_ITERATIONS=40  # Safety limit: ~10 hours at 15-min intervals

while [ "${ITERATION}" -lt "${MAX_ITERATIONS}" ]; do
    ITERATION=$((ITERATION + 1))
    echo ""
    echo "=== Prediction Iteration ${ITERATION} — $(date -u +%H:%M:%S) UTC ==="

    # Create symlink for run_skill.py
    SKILL_LINK="${WORKSPACE_DIR}/skills/wc_predict"
    if [ ! -e "${SKILL_LINK}" ]; then
        ln -sf "${SCRIPT_DIR}/predict" "${SKILL_LINK}"
    fi

    # Read the next model to use from predictions.md if it exists, default to Gemini 3.5 Flash (Medium)
    MODEL="Gemini 3.5 Flash (Medium)"
    if [ -f "${PREDICTIONS_PATH}" ]; then
        EXTRACTED_MODEL=$(grep -E '^next_model:' "${PREDICTIONS_PATH}" | head -n 1 | cut -d':' -f2- | tr -d '"'\'' ' || true)
        if [ "${EXTRACTED_MODEL}" = "High" ] || [ "${EXTRACTED_MODEL}" = "Gemini3.5Flash(High)" ] || [ "${EXTRACTED_MODEL}" = "Gemini 3.5 Flash (High)" ]; then
            MODEL="Gemini 3.5 Flash (High)"
        fi
    fi
    echo "[$(date -u +%H:%M:%S)] Selected model for iteration: ${MODEL}"

    # Map model name for each agent type
    EXEC_MODEL="${MODEL}"
    FALLBACK_EXEC_MODEL="${MODEL}"
    if [ "${AGENT}" = "opencode" ]; then
        EXEC_MODEL="google/gemini-3.5-flash"
    fi
    if [ "${FALLBACK_AGENT}" = "opencode" ]; then
        FALLBACK_EXEC_MODEL="google/gemini-3.5-flash"
    fi

    if [ -f "${SKILLS_RUNNER}" ]; then
        if OUTPUT=$(python3 "${SKILLS_RUNNER}" wc_predict --agent "${AGENT}" --model "${EXEC_MODEL}" --vars "${PREDICT_VARS}"); then
            echo "${OUTPUT}"
        else
            echo "Warning: ${AGENT} predict failed. Trying ${FALLBACK_AGENT} fallback..." >&2
            OUTPUT=$(python3 "${SKILLS_RUNNER}" wc_predict --agent "${FALLBACK_AGENT}" --model "${FALLBACK_EXEC_MODEL}" --vars "${PREDICT_VARS}")
            echo "${OUTPUT}"
        fi
        
        # Extract run directory and read token usage
        RUN_DIR=$(echo "${OUTPUT}" | grep "Execution logs and metadata saved to:" | sed 's/Execution logs and metadata saved to: //')
        if [ -n "${RUN_DIR}" ] && [ -d "${RUN_DIR}" ]; then
            if [ -f "${RUN_DIR}/run_metadata.json" ]; then
                TOKENS_TEXT=$(python3 -c "import json; m=json.load(open('${RUN_DIR}/run_metadata.json')); u=m.get('token_usage'); print(f\"Tokens Used: {u['input_tokens']} input, {u['output_tokens']} output (Total: {u['total_tokens']})\" if u else 'Tokens Used: Unknown')")
                echo "[$(date -u +%H:%M:%S)] ${TOKENS_TEXT}"
            fi
        fi
    else
        SKILL_CONTENT=$(cat "${SCRIPT_DIR}/predict/SKILL.md")
        COMPILED="${SKILL_CONTENT//\{DATE\}/${DATE}}"
        COMPILED="${COMPILED//\{SCHEDULE_PATH\}/${SCHEDULE_PATH}}"
        COMPILED="${COMPILED//\{TRACKER_PATH\}/${TRACKER_PATH}}"
        COMPILED="${COMPILED//\{PREDICTIONS_PATH\}/${PREDICTIONS_PATH}}"
        COMPILED="${COMPILED//\{CHANGELOG_PATH\}/${CHANGELOG_PATH}}"
        COMPILED="${COMPILED//\{INTERVAL_PATH\}/${INTERVAL_PATH}}"
        COMPILED="${COMPILED//\{OUTPUT_DIR\}/${DAY_DIR}}"
        if [ "${AGENT}" = "opencode" ]; then
            opencode run --dangerously-skip-permissions --model "${EXEC_MODEL}" "${COMPILED}" || {
                echo "Warning: opencode predict failed. Trying agy fallback..." >&2
                agy --dangerously-skip-permissions --model "${FALLBACK_EXEC_MODEL}" --print "${COMPILED}" || {
                    echo "Warning: Prediction iteration ${ITERATION} failed on both command line agents. Continuing." >&2
                }
            }
        else
            agy --dangerously-skip-permissions --model "${EXEC_MODEL}" --print "${COMPILED}" || {
                echo "Warning: agy predict failed. Trying opencode fallback..." >&2
                opencode run --dangerously-skip-permissions --model "${FALLBACK_EXEC_MODEL}" "${COMPILED}" || {
                    echo "Warning: Prediction iteration ${ITERATION} failed on both command line agents. Continuing." >&2
                }
            }
        fi
    fi

    rm -f "${SKILL_LINK}"

    # Read interval from configuration file (defaults to 5 minutes, minimum 5 minutes)
    INTERVAL_MINS=$(cat "${SCRIPT_DIR}/prediction_interval.txt" 2>/dev/null | tr -d '[:space:]' || echo "5")
    if ! echo "${INTERVAL_MINS}" | grep -qE '^[0-9]+$' || [ "${INTERVAL_MINS}" -lt 5 ]; then
        INTERVAL_MINS=5
    fi
    echo "[$(date -u +%H:%M:%S)] Iteration ${ITERATION} complete. Next run in ${INTERVAL_MINS} minutes."

    # Wait for INTERVAL_MINS minutes, checking config every 60 seconds
    ELAPSED=0
    TARGET_SECONDS=$((INTERVAL_MINS * 60))
    while [ "${ELAPSED}" -lt "${TARGET_SECONDS}" ]; do
        sleep 60
        ELAPSED=$((ELAPSED + 60))
        # Re-read configuration in case it changed mid-sleep
        NEW_MINS=$(cat "${SCRIPT_DIR}/prediction_interval.txt" 2>/dev/null | tr -d '[:space:]' || echo "${INTERVAL_MINS}")
        if ! echo "${NEW_MINS}" | grep -qE '^[0-9]+$' || [ "${NEW_MINS}" -lt 5 ]; then
            NEW_MINS=${INTERVAL_MINS}
        fi
        if [ "${NEW_MINS}" -ne "${INTERVAL_MINS}" ]; then
            echo "[$(date -u +%H:%M:%S)] Prediction interval changed from ${INTERVAL_MINS} to ${NEW_MINS} minutes."
            INTERVAL_MINS=${NEW_MINS}
            TARGET_SECONDS=$((INTERVAL_MINS * 60))
        fi
    done
done

echo "Prediction loop completed (${MAX_ITERATIONS} iterations max)."

# --- Step 4: Postmortem ---
echo ""
echo "--- Step 4: Postmortem (waiting 2 hours after last match) ---"
echo "Sleeping 2 hours for matches to conclude..."
sleep 7200

echo "Running postmortem analysis..."

POSTMORTEM_VARS="DATE=${DATE}"
POSTMORTEM_VARS="${POSTMORTEM_VARS},PREDICTIONS_PATH=${PREDICTIONS_PATH}"
POSTMORTEM_VARS="${POSTMORTEM_VARS},CHANGELOG_PATH=${CHANGELOG_PATH}"
POSTMORTEM_VARS="${POSTMORTEM_VARS},TRACKER_PATH=${TRACKER_PATH}"
POSTMORTEM_VARS="${POSTMORTEM_VARS},OUTPUT_DIR=${DAY_DIR}"
POSTMORTEM_VARS="${POSTMORTEM_VARS},AGENT=${AGENT}"

SKILL_LINK="${WORKSPACE_DIR}/skills/wc_postmortem"
if [ ! -e "${SKILL_LINK}" ]; then
    ln -sf "${SCRIPT_DIR}/postmortem" "${SKILL_LINK}"
fi

if [ -f "${SKILLS_RUNNER}" ]; then
    if OUTPUT=$(python3 "${SKILLS_RUNNER}" wc_postmortem --agent "${AGENT}" --vars "${POSTMORTEM_VARS}"); then
        echo "${OUTPUT}"
    else
        echo "Warning: ${AGENT} postmortem failed. Trying ${FALLBACK_AGENT} fallback..." >&2
        OUTPUT=$(python3 "${SKILLS_RUNNER}" wc_postmortem --agent "${FALLBACK_AGENT}" --vars "${POSTMORTEM_VARS}")
        echo "${OUTPUT}"
    fi
    # Extract the run directory from output
    RUN_DIR=$(echo "${OUTPUT}" | grep "Execution logs and metadata saved to:" | sed 's/Execution logs and metadata saved to: //')
    if [ -n "${RUN_DIR}" ] && [ -d "${RUN_DIR}" ]; then
        if [ -f "${RUN_DIR}/postmortem.md" ]; then
            cp -f "${RUN_DIR}/postmortem.md" "${DAY_DIR}/"
            echo "[$(date -u +%H:%M:%S)] Copied postmortem.md to ${DAY_DIR}/"
        fi
    fi
else
    SKILL_CONTENT=$(cat "${SCRIPT_DIR}/postmortem/SKILL.md")
    COMPILED="${SKILL_CONTENT//\{DATE\}/${DATE}}"
    COMPILED="${COMPILED//\{PREDICTIONS_PATH\}/${PREDICTIONS_PATH}}"
    COMPILED="${COMPILED//\{CHANGELOG_PATH\}/${CHANGELOG_PATH}}"
    COMPILED="${COMPILED//\{TRACKER_PATH\}/${TRACKER_PATH}}"
    COMPILED="${COMPILED//\{OUTPUT_DIR\}/${DAY_DIR}}"
    if [ "${AGENT}" = "opencode" ]; then
        opencode run --dangerously-skip-permissions "${COMPILED}" || {
            echo "Warning: opencode postmortem failed. Trying agy fallback..." >&2
            agy --dangerously-skip-permissions --print "${COMPILED}"
        }
    else
        agy --dangerously-skip-permissions --print "${COMPILED}" || {
            echo "Warning: agy postmortem failed. Trying opencode fallback..." >&2
            opencode run --dangerously-skip-permissions "${COMPILED}"
        }
    fi
fi

rm -f "${SKILL_LINK}"

echo ""
echo "=========================================="
echo "✅ Day complete: ${DATE}"
echo "Results saved to: ${DAY_DIR}"
echo "Tracker updated: ${TRACKER_PATH}"
echo "=========================================="
