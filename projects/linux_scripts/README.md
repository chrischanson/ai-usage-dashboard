# Linux Scripts Collection

A collection of robust, fail-safe Bash scripts for media management, file organization, and system auditing.

## 🚀 Overview

These scripts are designed for reliability, featuring:
- **Strict Mode**: Uses `set -euo pipefail` to catch errors early.
- **Fail-Safety**: Inode checks, backup creation, and careful file operations.
- **Dry-Run Support**: Most scripts support a dry-run mode to preview changes.
- **Rich Feedback**: Colored logging and detailed summaries.

## 🛠 Scripts

### [dng-cleanup.sh](./dng-cleanup.sh)
**Post-processor for Adobe DNG Converter.**
Restores file timestamps from EXIF data, deletes redundant originals, and standardizes filenames to uppercase `.DNG`.
- **Usage**: `./dng-cleanup.sh [-y] [-r] [directory]`

### [cue-to-utf8.sh](./cue-to-utf8.sh)
**Character encoding fixer for music metadata.**
Batch converts `.cue` sheet files to UTF-8 encoding. Includes automatic backup and encoding detection.
- **Usage**: `./cue-to-utf8.sh [directory]`

### [organize-by-date.sh](./organize-by-date.sh)
**Automated file sorter.**
Moves files into a `YYYY/MM/DD` directory structure based on EXIF 'DateTimeOriginal' or file modification time.
- **Usage**: `./organize-by-date.sh <destination_root> [--wet-run]`

### [media-report.sh](./media-report.sh)
**Media inventory and optimization tool.**
Generates reports on media file types (RAW, DNG, JPEG, Video) and sizes. Includes a workflow for lossless DNG compression via `tinydng-cli`.
- **Usage**: `./media-report.sh [OPTIONS] [DIRECTORY]`

### [verify-exif-timestamps.sh](./verify-exif-timestamps.sh)
**Metadata integrity auditor.**
Scans for discrepancies between file system timestamps and embedded EXIF data. Can optionally "fix" the file system time to match the EXIF capture time.
- **Usage**: `./verify-exif-timestamps.sh [directory] [options]`

### [rip-compressor.sh](./rip-compressor.sh)
**High-efficiency DVD/Blu-ray rip compressor.**
Encodes video to AV1 (SVT-AV1), preserves audio (FLAC for 1-2ch, Opus for surround), and copies all other streams. Supports auto-merging of DVD VOB chunks and automatic toolchain bootstrapping.
- **Usage**: `./rip-compressor.sh [OPTIONS] <file-or-directory>`

### [large-dir-audit.sh](./large-dir-audit.sh)
**Storage analysis tool.**
Identifies directories containing a large volume of direct files (non-recursive) exceeding a specified GB threshold.
- **Usage**: `./large-dir-audit.sh [directory] [threshold_gb]`

## 📋 Requirements

Most scripts require the following tools:
- `bash` (v4+)
- `exiftool` (for metadata operations)
- `uchardet` & `iconv` (for `cue-to-utf8.sh`)
- `bc` (for `large-dir-audit.sh`)
- `tinydng-cli` (optional, for `media-report.sh` compression)

## ⚠️ Safety First

Most scripts run in **Dry-Run mode by default**. Always review the output before applying changes with `--wet-run` or `-y`.
