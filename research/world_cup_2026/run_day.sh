#!/usr/bin/env bash
# World Cup 2026 — Daily Orchestrator
# Runs the full daily prediction cascade:
#   1. Fetch today's match schedule
#   2. Run the prediction/analysis loop on the configured dynamic interval
#   3. Keep running until every scheduled match reaches its estimated end
#   4. Run postmortem 2 hours after the final estimated match end
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
DEFAULT_INTERVAL_MINS=60
MIN_INTERVAL_MINS=60
MAX_INTERVAL_MINS=180
POSTMORTEM_DELAY_SECONDS=$((2 * 60 * 60))
CLEANUP_LINKS=()
POSTMORTEM_EPOCH=0
OPENCODE_SESSION_FILE=""
AGY_CONVERSATION_FILE=""

log() {
    echo "[$(date -u +%H:%M:%S)] $*"
}

cleanup() {
    local link
    for link in "${CLEANUP_LINKS[@]:-}"; do
        rm -f "${link}"
    done
}
trap cleanup EXIT

ensure_skill_link() {
    local name="$1"
    local target="$2"

    SKILL_LINK="${WORKSPACE_DIR}/skills/${name}"
    ln -sfn "${target}" "${SKILL_LINK}"
    CLEANUP_LINKS+=("${SKILL_LINK}")
}

read_interval_mins() {
    local raw min_mins max_mins default_mins config_path
    config_path="${SCRIPT_DIR}/model_config.json"
    
    if [ -f "${config_path}" ]; then
        min_mins=$(python3 -c "import json; c=json.load(open('${config_path}')); print(c.get('min_interval_minutes', 15))")
        max_mins=$(python3 -c "import json; c=json.load(open('${config_path}')); print(c.get('max_interval_minutes', 45))")
        default_mins=$(python3 -c "import json; c=json.load(open('${config_path}')); print(c.get('default_interval_minutes', 15))")
    else
        min_mins="${MIN_INTERVAL_MINS:-15}"
        max_mins="${MAX_INTERVAL_MINS:-45}"
        default_mins="${DEFAULT_INTERVAL_MINS:-15}"
    fi

    raw=$(cat "${INTERVAL_PATH}" 2>/dev/null | tr -d '[:space:]' || true)
    if ! echo "${raw}" | grep -qE '^[0-9]+$'; then
        raw="${default_mins}"
    fi
    if [ "${raw}" -lt "${min_mins}" ]; then
        raw="${min_mins}"
    fi
    if [ "${raw}" -gt "${max_mins}" ]; then
        raw="${max_mins}"
    fi
    echo "${raw}"
}

utc_epoch() {
    date -u -d "$1" +%s
}

format_utc_epoch() {
    date -u -d "@$1" "+%Y-%m-%d %H:%M:%S UTC"
}

derive_match_windows() {
    local in_data=0
    local prev_kickoff_epoch=0
    local max_halftime_epoch=0
    local max_end_epoch=0
    local line kickoff halftime end match_date kickoff_epoch halftime_epoch end_epoch

    while IFS= read -r line; do
        case "${line}" in
            *"<!-- MATCH_DATA_START -->"*) in_data=1; continue ;;
            *"<!-- MATCH_DATA_END -->"*) in_data=0; continue ;;
        esac
        [ "${in_data}" -eq 1 ] || continue

        kickoff=$(echo "${line}" | sed -n 's/.*kickoff_utc: "\([0-9][0-9]:[0-9][0-9]\)".*/\1/p')
        halftime=$(echo "${line}" | sed -n 's/.*estimated_halftime_utc: "\([0-9][0-9]:[0-9][0-9]\)".*/\1/p')
        end=$(echo "${line}" | sed -n 's/.*estimated_end_utc: "\([0-9][0-9]:[0-9][0-9]\)".*/\1/p')
        [ -n "${kickoff}" ] && [ -n "${halftime}" ] && [ -n "${end}" ] || continue

        match_date="${DATE}"
        kickoff_epoch=$(utc_epoch "${match_date} ${kickoff}")
        if [ "${prev_kickoff_epoch}" -gt 0 ] && [ "${kickoff_epoch}" -lt "${prev_kickoff_epoch}" ]; then
            match_date=$(date -u -d "${match_date} +1 day" +%Y-%m-%d)
            kickoff_epoch=$(utc_epoch "${match_date} ${kickoff}")
        fi
        prev_kickoff_epoch="${kickoff_epoch}"

        halftime_epoch=$(utc_epoch "${match_date} ${halftime}")
        end_epoch=$(utc_epoch "${match_date} ${end}")
        if [ "${halftime_epoch}" -lt "${kickoff_epoch}" ]; then
            halftime_epoch=$((halftime_epoch + 86400))
        fi
        if [ "${end_epoch}" -lt "${kickoff_epoch}" ]; then
            end_epoch=$((end_epoch + 86400))
        fi

        if [ "${halftime_epoch}" -gt "${max_halftime_epoch}" ]; then
            max_halftime_epoch="${halftime_epoch}"
        fi
        if [ "${end_epoch}" -gt "${max_end_epoch}" ]; then
            max_end_epoch="${end_epoch}"
        fi
    done < "${SCHEDULE_PATH}"

    if [ "${max_end_epoch}" -eq 0 ]; then
        echo "Error: Could not parse match timing data from ${SCHEDULE_PATH}" >&2
        return 1
    fi

    LAST_HALFTIME_EPOCH="${max_halftime_epoch}"
    LAST_END_EPOCH="${max_end_epoch}"
    POSTMORTEM_EPOCH=$((LAST_END_EPOCH + POSTMORTEM_DELAY_SECONDS))
}

sleep_until_or_interval_change() {
    local target_epoch="$1"
    local interval_mins="$2"
    local target_interval_epoch=$(( $(date -u +%s) + interval_mins * 60 ))
    local wake_epoch="${target_interval_epoch}"
    local now remaining sleep_for new_mins new_interval_epoch

    if [ "${target_epoch}" -lt "${wake_epoch}" ]; then
        wake_epoch="${target_epoch}"
    fi

    while true; do
        now=$(date -u +%s)
        [ "${now}" -lt "${wake_epoch}" ] || break

        remaining=$((wake_epoch - now))
        sleep_for="${remaining}"
        if [ "${sleep_for}" -gt 60 ]; then
            sleep_for=60
        fi
        sleep "${sleep_for}"

        new_mins=$(read_interval_mins)
        if [ "${new_mins}" -ne "${interval_mins}" ]; then
            log "Prediction interval changed from ${interval_mins} to ${new_mins} minutes."
            interval_mins="${new_mins}"
            new_interval_epoch=$(( $(date -u +%s) + interval_mins * 60 ))
            if [ "${new_interval_epoch}" -lt "${target_epoch}" ]; then
                wake_epoch="${new_interval_epoch}"
            else
                wake_epoch="${target_epoch}"
            fi
        fi
    done
}

# --- Session Helpers ---
get_session_id() {
    local agent="$1"
    local file
    file="$(session_file_for_agent "${agent}")"
    if [ -n "${file}" ] && [ -f "${file}" ]; then
        cat "${file}"
    fi
}

save_session_id() {
    local agent="$1"
    local id="$2"
    local file
    file="$(session_file_for_agent "${agent}")"
    if [ -n "${id}" ]; then
        echo "${id}" > "${file}"
        log "Saved ${agent} session ID: ${id}"
    fi
}

save_session_ids_from_output() {
    local output="$1"
    local sid

    sid=$(echo "${output}" | grep -E "OPENCODE_SESSION_ID:" | head -1 | sed 's/.*: //' || true)
    save_session_id "opencode" "${sid}"

    sid=$(echo "${output}" | grep -E "AGY_CONVERSATION_ID:" | head -1 | sed 's/.*: //' || true)
    save_session_id "agy" "${sid}"
}

clear_session_id() {
    rm -f "${OPENCODE_SESSION_FILE}" "${AGY_CONVERSATION_FILE}"
}

session_file_for_agent() {
    local agent="$1"
    case "${agent}" in
        opencode) echo "${OPENCODE_SESSION_FILE}" ;;
        agy) echo "${AGY_CONVERSATION_FILE}" ;;
        *) echo "" ;;
    esac
}

session_args() {
    local agent="$1"
    local id
    id=$(get_session_id "${agent}")
    if [ -n "${id}" ]; then
        echo "--session ${id}"
    fi
}

cli_session_args() {
    local agent="$1"
    local id
    id=$(get_session_id "${agent}")
    if [ -z "${id}" ]; then
        return 0
    fi
    case "${agent}" in
        opencode) echo "-s ${id}" ;;
        agy) echo "--conversation ${id}" ;;
    esac
}

# Determine if this is the first invocation (no session file yet)
is_first_session() {
    local agent="$1"
    local file
    file="$(session_file_for_agent "${agent}")"
    [ -z "${file}" ] || [ ! -f "${file}" ]
}

# --- Parse arguments ---
AGENT="agy"
FALLBACK_AGENT="opencode"
DATE=""
POSTMORTEM_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --opencode)
            AGENT="opencode"
            FALLBACK_AGENT="agy"
            shift
            ;;
        --postmortem)
            POSTMORTEM_ONLY=1
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
OPENCODE_SESSION_FILE="${DAY_DIR}/.opencode_session_id"
AGY_CONVERSATION_FILE="${DAY_DIR}/.agy_conversation_id"

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
log "Created day directory: ${DAY_DIR}"

if [ "${POSTMORTEM_ONLY}" -eq 0 ]; then

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
    # Create a temporary symlink so run_skill.py can find this project's skills.
    ensure_skill_link "wc_daily_schedule" "${SCRIPT_DIR}/daily_schedule"

    SCHEDULE_SESSION_ARGS=""
    if [ "${AGENT}" = "opencode" ] && is_first_session "${AGENT}"; then
        SCHEDULE_SESSION_ARGS='--title "world cup prediction"'
    else
        SCHEDULE_SESSION_ARGS="$(session_args "${AGENT}")"
    fi

    if OUTPUT=$(python3 "${SKILLS_RUNNER}" wc_daily_schedule --agent "${AGENT}" ${SCHEDULE_SESSION_ARGS} --vars "${SCHEDULE_VARS}"); then
        echo "${OUTPUT}"
    else
        echo "Warning: ${AGENT} daily schedule failed. Trying ${FALLBACK_AGENT} fallback..." >&2
        # Fallback starts fresh — no session reuse
        OUTPUT=$(python3 "${SKILLS_RUNNER}" wc_daily_schedule --agent "${FALLBACK_AGENT}" --vars "${SCHEDULE_VARS}")
        echo "${OUTPUT}"
    fi
    save_session_ids_from_output "${OUTPUT}"
    # Extract the run directory from output
    RUN_DIR=$(echo "${OUTPUT}" | grep "Execution logs and metadata saved to:" | sed 's/Execution logs and metadata saved to: //')
    if [ -n "${RUN_DIR}" ] && [ -d "${RUN_DIR}" ]; then
        if [ -f "${RUN_DIR}/match_schedule.md" ]; then
            cp -f "${RUN_DIR}/match_schedule.md" "${DAY_DIR}/"
            log "Copied match_schedule.md to ${DAY_DIR}/"
        fi
    fi
else
    echo "Warning: run_skill.py not found, invoking ${AGENT} directly" >&2
    # Read and compile the skill prompt manually
    SKILL_CONTENT=$(cat "${SCRIPT_DIR}/daily_schedule/SKILL.md")
    # Replace variables
    COMPILED="${SKILL_CONTENT//\{DATE\}/${DATE}}"
    COMPILED="${COMPILED//\{TRACKER_PATH\}/${TRACKER_PATH}}"
    COMPILED="${COMPILED//\{OUTPUT_DIR\}/${DAY_DIR}}"
    if [ "${AGENT}" = "opencode" ]; then
        SESSION_ARGS=""
        if is_first_session "${AGENT}"; then
            SESSION_ARGS='--title "world cup prediction"'
        else
            SID=$(get_session_id "${AGENT}")
            if [ -n "${SID}" ]; then
                SESSION_ARGS="-s ${SID}"
            fi
        fi
        # shellcheck disable=SC2086
        opencode run --dangerously-skip-permissions ${SESSION_ARGS} "${COMPILED}" || {
            echo "Warning: opencode failed. Trying agy fallback..." >&2
            agy --dangerously-skip-permissions --print "${COMPILED}"
        }
        # Capture session ID from most recent session if first invocation
        if is_first_session "${AGENT}"; then
            SID=$(opencode session list --format json -n 5 2>/dev/null | python3 -c "
import json, sys
sessions = json.load(sys.stdin)
for s in sessions:
    if s.get('title') == 'world cup prediction':
        print(s['id'])
        break
" 2>/dev/null)
            save_session_id "${AGENT}" "${SID}"
        fi
    else
        AGY_SESSION_ARGS="$(cli_session_args "${AGENT}")"
        # shellcheck disable=SC2086
        agy --dangerously-skip-permissions ${AGY_SESSION_ARGS} --print "${COMPILED}" || {
            echo "Warning: agy failed. Trying opencode fallback..." >&2
            SESSION_ARGS=""
            if is_first_session "opencode"; then
                SESSION_ARGS='--title "world cup prediction"'
            else
                SID=$(get_session_id "opencode")
                if [ -n "${SID}" ]; then
                    SESSION_ARGS="-s ${SID}"
                fi
            fi
            # shellcheck disable=SC2086
            opencode run --dangerously-skip-permissions ${SESSION_ARGS} "${COMPILED}"
            if is_first_session "opencode"; then
                SID=$(opencode session list --format json -n 5 2>/dev/null | python3 -c "
import json, sys
sessions = json.load(sys.stdin)
for s in sessions:
    if s.get('title') == 'world cup prediction':
        print(s['id'])
        break
" 2>/dev/null)
                save_session_id "opencode" "${SID}"
            fi
        }
    fi
fi

log "Schedule fetched."

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

derive_match_windows
echo "Last estimated halftime: $(format_utc_epoch "${LAST_HALFTIME_EPOCH}")"
echo "Last estimated match end: $(format_utc_epoch "${LAST_END_EPOCH}")"
echo "Postmortem target:        $(format_utc_epoch "${POSTMORTEM_EPOCH}")"

# --- Step 3: Prediction Loop ---
echo ""
echo "--- Step 3: Prediction Loop (dynamic interval until all games end) ---"

PREDICT_VARS_BASE="DATE=${DATE}"
PREDICT_VARS_BASE="${PREDICT_VARS_BASE},SCHEDULE_PATH=${SCHEDULE_PATH}"
PREDICT_VARS_BASE="${PREDICT_VARS_BASE},TRACKER_PATH=${TRACKER_PATH}"
PREDICT_VARS_BASE="${PREDICT_VARS_BASE},PREDICTIONS_PATH=${PREDICTIONS_PATH}"
PREDICT_VARS_BASE="${PREDICT_VARS_BASE},CHANGELOG_PATH=${CHANGELOG_PATH}"
PREDICT_VARS_BASE="${PREDICT_VARS_BASE},INTERVAL_PATH=${INTERVAL_PATH}"
PREDICT_VARS_BASE="${PREDICT_VARS_BASE},OUTPUT_DIR=${DAY_DIR}"

ITERATION=0
STALENESS_COUNT=0
PREV_PREDICTIONS_HASH=""

# Compute md5 hash of predictions file for change detection
predictions_hash() {
    if [ -f "${PREDICTIONS_PATH}" ]; then
        md5sum "${PREDICTIONS_PATH}" | cut -d' ' -f1
    else
        echo "empty"
    fi
}

while [ "$(date -u +%s)" -lt "${LAST_END_EPOCH}" ]; do
    ITERATION=$((ITERATION + 1))
    echo ""
    echo "=== Prediction Iteration ${ITERATION} — $(date -u +%H:%M:%S) UTC (staleness: ${STALENESS_COUNT}) ==="

    # Snapshot the predictions hash before this iteration
    PREV_PREDICTIONS_HASH=$(predictions_hash)

    ensure_skill_link "wc_predict" "${SCRIPT_DIR}/predict"

    # Extract the next difficulty level from predictions.md if it exists, default to 'medium'
    DIFFICULTY="medium"
    if [ -f "${PREDICTIONS_PATH}" ]; then
        EXTRACTED_DIFF=$(grep -E '^next_difficulty:' "${PREDICTIONS_PATH}" | head -n 1 | cut -d':' -f2- | tr -d '"'\'' ' || true)
        if [ "${EXTRACTED_DIFF}" = "high" ] || [ "${EXTRACTED_DIFF}" = "medium" ] || [ "${EXTRACTED_DIFF}" = "low" ]; then
            DIFFICULTY="${EXTRACTED_DIFF}"
        fi
    fi

    # Staleness override: if 3+ consecutive iterations had no changes, force low difficulty
    if [ "${STALENESS_COUNT}" -ge 3 ]; then
        log "Staleness override: ${STALENESS_COUNT} consecutive unchanged iterations. Forcing difficulty=low."
        DIFFICULTY="low"
    fi

    # Read agent and model from model_config.json
    CONFIG_PATH="${SCRIPT_DIR}/model_config.json"
    if [ -f "${CONFIG_PATH}" ]; then
        EXEC_AGENT=$(python3 -c "import json; c=json.load(open('${CONFIG_PATH}')); tier=c.get('${DIFFICULTY}', {}); print(tier.get('agent', 'agy'))")
        EXEC_MODEL=$(python3 -c "import json; c=json.load(open('${CONFIG_PATH}')); tier=c.get('${DIFFICULTY}', {}); print(tier.get('model', ''))")
    else
        # Fallback if config is missing
        EXEC_AGENT="agy"
        if [ "${DIFFICULTY}" = "high" ]; then
            EXEC_MODEL="Gemini 3.5 Flash (Medium)"
        else
            EXEC_MODEL="Gemini 3.5 Flash (Low)"
        fi
    fi

    # Determine fallback agent and model
    if [ "${EXEC_AGENT}" = "opencode" ]; then
        FALLBACK_EXEC_AGENT="agy"
        FALLBACK_EXEC_MODEL="Gemini 3.5 Flash (Low)"
    else
        FALLBACK_EXEC_AGENT="opencode"
        FALLBACK_EXEC_MODEL="google/gemini-3.5-flash"
    fi

    log "Difficulty: ${DIFFICULTY} | Agent: ${EXEC_AGENT} | Model: ${EXEC_MODEL:-[default]}"

    PREDICT_VARS_PRIMARY="${PREDICT_VARS_BASE},AGENT=${EXEC_AGENT}"
    PREDICT_VARS_FALLBACK="${PREDICT_VARS_BASE},AGENT=${FALLBACK_EXEC_AGENT}"

    if [ -f "${SKILLS_RUNNER}" ]; then
        PREDICT_SESSION_ARGS="$(session_args "${EXEC_AGENT}")"

        if OUTPUT=$(python3 "${SKILLS_RUNNER}" wc_predict --agent "${EXEC_AGENT}" --model "${EXEC_MODEL}" ${PREDICT_SESSION_ARGS} --vars "${PREDICT_VARS_PRIMARY}"); then
            echo "${OUTPUT}"
        else
            echo "Warning: ${EXEC_AGENT} predict failed. Trying ${FALLBACK_EXEC_AGENT} fallback..." >&2
            OUTPUT=$(python3 "${SKILLS_RUNNER}" wc_predict --agent "${FALLBACK_EXEC_AGENT}" --model "${FALLBACK_EXEC_MODEL}" --vars "${PREDICT_VARS_FALLBACK}")
            echo "${OUTPUT}"
        fi
        save_session_ids_from_output "${OUTPUT}"
        
        # Extract run directory, read token usage, and inject into changelog
        RUN_DIR=$(echo "${OUTPUT}" | grep "Execution logs and metadata saved to:" | sed 's/Execution logs and metadata saved to: //')
        if [ -n "${RUN_DIR}" ] && [ -d "${RUN_DIR}" ] && [ -f "${RUN_DIR}/run_metadata.json" ]; then
            python3 -c "
import json, sys, os
m = json.load(open('${RUN_DIR}/run_metadata.json'))
u = m.get('token_usage')
if u:
    line = f\"**Tokens:** {u['input_tokens']} input + {u['output_tokens']} output = {u['total_tokens']} total\n\"
    cl = '${CHANGELOG_PATH}'
    if os.path.exists(cl):
        with open(cl) as f:
            content = f.read()
        # Insert after the first blank line following '## Iteration'
        idx = content.find('## Iteration')
        if idx >= 0:
            nl = content.find('\n\n', idx)
            if nl >= 0:
                content = content[:nl+2] + line + content[nl+2:]
                with open(cl, 'w') as f:
                    f.write(content)
                print(f'Tokens: {u[\"input_tokens\"]}i + {u[\"output_tokens\"]}o = {u[\"total_tokens\"]}t')
            else:
                print('Tokens: Unknown (no gap after header)')
        else:
            print('Tokens: Unknown (no iteration header)')
    else:
        print('Tokens: Unknown (no changelog yet)')
else:
    print('Tokens: Unknown (no token data)')
" | while read -r line; do log "${line}"; done
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
        PREDICT_SESSION_ARGS="$(cli_session_args "${EXEC_AGENT}")"
        if [ "${EXEC_AGENT}" = "opencode" ]; then
            # shellcheck disable=SC2086
            opencode run --dangerously-skip-permissions --model "${EXEC_MODEL}" ${PREDICT_SESSION_ARGS} "${COMPILED}" || {
                echo "Warning: opencode predict failed. Trying agy fallback..." >&2
                agy --dangerously-skip-permissions --model "${FALLBACK_EXEC_MODEL}" --print "${COMPILED}" || {
                    echo "Warning: Prediction iteration ${ITERATION} failed on both command line agents. Continuing." >&2
                }
            }
        else
            # shellcheck disable=SC2086
            agy --dangerously-skip-permissions --model "${EXEC_MODEL}" ${PREDICT_SESSION_ARGS} --print "${COMPILED}" || {
                echo "Warning: agy predict failed. Trying opencode fallback..." >&2
                PREDICT_FALLBACK_SESSION_ARGS="$(cli_session_args "opencode")"
                # shellcheck disable=SC2086
                opencode run --dangerously-skip-permissions --model "${FALLBACK_EXEC_MODEL}" ${PREDICT_FALLBACK_SESSION_ARGS} "${COMPILED}" || {
                    echo "Warning: Prediction iteration ${ITERATION} failed on both command line agents. Continuing." >&2
                }
            }
        fi
    fi

    # If the skill reports no matches left to cover, skip future invocations
    # and just wait out the remaining time until the final whistle window.
    # This avoids burning tokens on runs that would produce no useful output.
    if [ -f "${PREDICTIONS_PATH}" ]; then
        COVERED=$(grep -E '^matches_covered:' "${PREDICTIONS_PATH}" | head -n 1 | cut -d':' -f2 | tr -d ' ' || echo "1")
        if [ "${COVERED}" = "0" ]; then
            log "Prediction skill reports no matches left to cover; skipping further invocations and waiting until all games end at $(format_utc_epoch "${LAST_END_EPOCH}")."
            local max_interval
            max_interval=$(python3 -c "import json; c=json.load(open('${SCRIPT_DIR}/model_config.json')); print(c.get('max_interval_minutes', 45))" 2>/dev/null || echo "${MAX_INTERVAL_MINS}")
            sleep_until_or_interval_change "${LAST_END_EPOCH}" "${max_interval}"
            break
        fi
    fi

    # Detect whether predictions actually changed this iteration
    CURRENT_HASH=$(predictions_hash)
    if [ "${CURRENT_HASH}" = "${PREV_PREDICTIONS_HASH}" ]; then
        STALENESS_COUNT=$((STALENESS_COUNT + 1))
        log "Predictions unchanged (staleness: ${STALENESS_COUNT})."
    else
        if [ "${STALENESS_COUNT}" -gt 0 ]; then
            log "Predictions changed — resetting staleness counter (was ${STALENESS_COUNT})."
        fi
        STALENESS_COUNT=0
    fi

    INTERVAL_MINS=$(read_interval_mins)

    # Staleness override: if 3+ consecutive unchanged, force max interval
    if [ "${STALENESS_COUNT}" -ge 3 ]; then
        MAX_INT=$(python3 -c "import json; c=json.load(open('${SCRIPT_DIR}/model_config.json')); print(c.get('max_interval_minutes', 45))" 2>/dev/null || echo "${MAX_INTERVAL_MINS}")
        if [ "${INTERVAL_MINS}" -lt "${MAX_INT}" ]; then
            log "Staleness override: forcing interval from ${INTERVAL_MINS} to ${MAX_INT} minutes."
            INTERVAL_MINS="${MAX_INT}"
        fi
    fi

    log "Iteration ${ITERATION} complete. Next run in ${INTERVAL_MINS} minutes, unless all games end first."
    sleep_until_or_interval_change "${LAST_END_EPOCH}" "${INTERVAL_MINS}"
done

log "Prediction loop completed after ${ITERATION} iterations; all scheduled games have reached the estimated end window."

fi # end if [ "${POSTMORTEM_ONLY}" -eq 0 ]

# --- Step 4: Postmortem ---
echo ""
echo "--- Step 4: Postmortem (2 hours after last match end) ---"
NOW_EPOCH=$(date -u +%s)
if [ "${POSTMORTEM_ONLY}" -eq 0 ] && [ "${NOW_EPOCH}" -lt "${POSTMORTEM_EPOCH}" ]; then
    WAIT_SECONDS=$((POSTMORTEM_EPOCH - NOW_EPOCH))
    log "Waiting until $(format_utc_epoch "${POSTMORTEM_EPOCH}") for final results to settle (${WAIT_SECONDS}s)."
    sleep "${WAIT_SECONDS}"
fi

echo "Running postmortem analysis..."

POSTMORTEM_VARS="DATE=${DATE}"
POSTMORTEM_VARS="${POSTMORTEM_VARS},PREDICTIONS_PATH=${PREDICTIONS_PATH}"
POSTMORTEM_VARS="${POSTMORTEM_VARS},CHANGELOG_PATH=${CHANGELOG_PATH}"
POSTMORTEM_VARS="${POSTMORTEM_VARS},TRACKER_PATH=${TRACKER_PATH}"
POSTMORTEM_VARS="${POSTMORTEM_VARS},OUTPUT_DIR=${DAY_DIR}"
POSTMORTEM_VARS="${POSTMORTEM_VARS},AGENT=${AGENT}"
POSTMORTEM_VARS="${POSTMORTEM_VARS},PREDICT_SKILL_PATH=${SCRIPT_DIR}/predict/SKILL.md"

ensure_skill_link "wc_postmortem" "${SCRIPT_DIR}/postmortem"

if [ -f "${SKILLS_RUNNER}" ]; then
    POSTMORTEM_SESSION_ARGS="$(session_args "${AGENT}")"
    if OUTPUT=$(python3 "${SKILLS_RUNNER}" wc_postmortem --agent "${AGENT}" ${POSTMORTEM_SESSION_ARGS} --vars "${POSTMORTEM_VARS}"); then
        echo "${OUTPUT}"
    else
        echo "Warning: ${AGENT} postmortem failed. Trying ${FALLBACK_AGENT} fallback..." >&2
        OUTPUT=$(python3 "${SKILLS_RUNNER}" wc_postmortem --agent "${FALLBACK_AGENT}" --vars "${POSTMORTEM_VARS}")
        echo "${OUTPUT}"
    fi
    save_session_ids_from_output "${OUTPUT}"
    # Extract the run directory from output
    RUN_DIR=$(echo "${OUTPUT}" | grep "Execution logs and metadata saved to:" | sed 's/Execution logs and metadata saved to: //')
    if [ -n "${RUN_DIR}" ] && [ -d "${RUN_DIR}" ]; then
        if [ -f "${RUN_DIR}/postmortem.md" ]; then
            cp -f "${RUN_DIR}/postmortem.md" "${DAY_DIR}/"
            log "Copied postmortem.md to ${DAY_DIR}/"
        fi
    fi
else
    SKILL_CONTENT=$(cat "${SCRIPT_DIR}/postmortem/SKILL.md")
    COMPILED="${SKILL_CONTENT//\{DATE\}/${DATE}}"
    COMPILED="${COMPILED//\{PREDICTIONS_PATH\}/${PREDICTIONS_PATH}}"
    COMPILED="${COMPILED//\{CHANGELOG_PATH\}/${CHANGELOG_PATH}}"
    COMPILED="${COMPILED//\{TRACKER_PATH\}/${TRACKER_PATH}}"
    COMPILED="${COMPILED//\{OUTPUT_DIR\}/${DAY_DIR}}"
    COMPILED="${COMPILED//\{PREDICT_SKILL_PATH\}/${SCRIPT_DIR}/predict/SKILL.md}"
    POSTMORTEM_SESSION_ARGS="$(cli_session_args "${AGENT}")"
    if [ "${AGENT}" = "opencode" ]; then
        # shellcheck disable=SC2086
        opencode run --dangerously-skip-permissions ${POSTMORTEM_SESSION_ARGS} "${COMPILED}" || {
            echo "Warning: opencode postmortem failed. Trying agy fallback..." >&2
            agy --dangerously-skip-permissions --print "${COMPILED}"
        }
    else
        # shellcheck disable=SC2086
        agy --dangerously-skip-permissions ${POSTMORTEM_SESSION_ARGS} --print "${COMPILED}" || {
            echo "Warning: agy postmortem failed. Trying opencode fallback..." >&2
            POSTMORTEM_FALLBACK_SESSION_ARGS="$(cli_session_args "opencode")"
            # shellcheck disable=SC2086
            opencode run --dangerously-skip-permissions ${POSTMORTEM_FALLBACK_SESSION_ARGS} "${COMPILED}"
        }
    fi
fi

echo ""
echo "=========================================="
echo "✅ Day complete: ${DATE}"
echo "Results saved to: ${DAY_DIR}"
echo "Tracker updated: ${TRACKER_PATH}"
echo "=========================================="
