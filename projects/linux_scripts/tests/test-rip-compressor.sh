#!/usr/bin/env bash
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${TEST_DIR}/../rip-compressor.sh"
FAKES_DIR="${TEST_DIR}/fakes"

fail() {
  printf 'not ok - %s\n' "$*" >&2
  exit 1
}

pass() {
  printf 'ok - %s\n' "$*"
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  local message="$3"
  [[ "$haystack" == *"$needle"* ]] || fail "${message}: missing '${needle}'"
}

assert_not_contains() {
  local haystack="$1"
  local needle="$2"
  local message="$3"
  [[ "$haystack" != *"$needle"* ]] || fail "${message}: unexpectedly found '${needle}'"
}

run_script() {
  XDG_DATA_HOME="${TMPDIR}/xdg" "$SCRIPT" --ffmpeg-dir "$FAKES_DIR" "$@"
}

setup_media_tree() {
  mkdir -p "${TMPDIR}/dvd/VIDEO_TS" "${TMPDIR}/bluray"
  touch \
    "${TMPDIR}/dvd/VIDEO_TS/VTS_02_0.VOB" \
    "${TMPDIR}/dvd/VIDEO_TS/VTS_02_0.IFO" \
    "${TMPDIR}/dvd/VIDEO_TS/VTS_02_1.VOB" \
    "${TMPDIR}/dvd/VIDEO_TS/VTS_02_2.VOB" \
    "${TMPDIR}/bluray/1 Part I.ts"
}

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT
setup_media_tree

bash -n "$SCRIPT"
pass "rip-compressor.sh parses as Bash"

dvd_try_dry="$(run_script --try --dry-run "${TMPDIR}/dvd")"
assert_contains "$dvd_try_dry" "Ready: 1 file(s), dry-run" "DVD dry-run summary"
assert_contains "$dvd_try_dry" "DVD VOB groups: 1 merged title set(s)" "DVD VOB chunks are grouped"
assert_contains "$dvd_try_dry" "DVD menu VOBs skipped: 1" "DVD menu VOB is skipped"
assert_contains "$dvd_try_dry" "concat:${TMPDIR}/dvd/VIDEO_TS/VTS_02_1.VOB\\|${TMPDIR}/dvd/VIDEO_TS/VTS_02_2.VOB" "DVD concat input is built"
assert_not_contains "$dvd_try_dry" "VTS_02_0.VOB\\|" "DVD concat excludes menu VOB"
assert_contains "$dvd_try_dry" "-map 0:v:0" "only primary video is mapped"
assert_not_contains "$dvd_try_dry" "-map 0 " "legacy map-all is not used"
assert_not_contains "$dvd_try_dry" "-c:d copy" "DVD nav/data streams are not copied"
assert_contains "$dvd_try_dry" "subtitles  dvd" "DVD subtitles are summarized"
assert_not_contains "$dvd_try_dry" "┌" "box drawing output is removed"
assert_not_contains "$dvd_try_dry" "│" "box drawing output is removed"
pass "DVD grouping, stream mapping, subtitles, and concise output are stable"

try_wet="$(run_script --try "${TMPDIR}/dvd")"
assert_contains "$try_wet" "Ready: 1 file(s), wet-run" "--try defaults to wet-run"
assert_contains "$try_wet" "running:" "--try runs by default"
assert_contains "$try_wet" "FAKE_FFMPEG_RUN" "fake ffmpeg was executed in try mode"
pass "try mode defaults to wet-run"

full_dry="$(run_script "${TMPDIR}/bluray/1 Part I.ts")"
assert_contains "$full_dry" "Ready: 1 file(s), dry-run" "full encode defaults to dry-run"
assert_contains "$full_dry" "dry-run command:" "full encode prints dry-run command"
assert_not_contains "$full_dry" "FAKE_FFMPEG_RUN" "full dry-run does not execute ffmpeg"
pass "full mode defaults to dry-run"

ts_try_dry="$(run_script --try --dry-run "${TMPDIR}/bluray/1 Part I.ts")"
assert_contains "$ts_try_dry" "audio      ac3  5.1(side)" "TS summary shows 5.1(side) layout"
assert_contains "$ts_try_dry" "-filter:a:0 pan=5.1\\|FL=FL\\|FR=FR\\|FC=FC\\|LFE=LFE\\|BL=SL\\|BR=SR" "5.1(side) audio is normalized for Opus"
assert_contains "$ts_try_dry" "-mapping_family:a:0 1" "Opus surround mapping family is set"
assert_contains "$ts_try_dry" "subtitles  dvb  2 track(s)" "TS subtitle summary is retained"
pass "Blu-ray TS 5.1(side) Opus handling is stable"

printf 'All rip-compressor tests passed.\n'
