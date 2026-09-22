import os
import re
import shutil
import subprocess
import time

from .base import Parser, ParserResult, ModelUsage, SourceUnavailable

# Fallback locations probed when `opencode` is not on PATH. Mirrors the
# codex pattern: a systemd unit does not normally inherit ~/.local/bin.
_BIN_FALLBACKS = ('~/.local/bin/opencode', '/usr/local/bin/opencode')

# Last successful parse, shared with the quota collector so one poll cycle
# spawns `opencode stats` once instead of twice (usage + quota). TTL is
# checked by the reader, not the writer.
_LAST_PARSE: tuple = (0.0, None)


def find_opencode_bin(configured: str = 'opencode') -> str | None:
    """Resolve the opencode executable, or None if it cannot be found.

    An explicitly configured value (USAGE_OPENCODE_BIN) is honoured as
    given; only the default name falls back to probing install locations.
    """
    configured = (configured or 'opencode').strip() or 'opencode'

    if configured != 'opencode':
        if os.path.sep in configured:
            expanded = os.path.expanduser(configured)
            if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
                return expanded
            return None
        return shutil.which(configured)

    found = shutil.which('opencode')
    if found:
        return found
    for candidate in _BIN_FALLBACKS:
        expanded = os.path.expanduser(candidate)
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            return expanded
    return None


def get_cached_parse(max_age_seconds: float = 660) -> ParserResult | None:
    """Return the most recent successful parse if fresh, else None."""
    ts, result = _LAST_PARSE
    if result is None:
        return None
    if (time.time() - ts) > max_age_seconds:
        return None
    return result


class OpenCodeParser(Parser):
    def __init__(self, timeout: int = 10, opencode_bin: str | None = None):
        self.timeout = timeout
        if opencode_bin is None:
            opencode_bin = os.getenv('USAGE_OPENCODE_BIN', 'opencode')
        self.opencode_bin = opencode_bin

    def _parse_number(self, val_str: str) -> float:
        val_str = val_str.replace(',', '').replace('$', '').strip()
        if not val_str:
            return 0
        mult = 1
        if val_str.endswith('M'):
            mult = 1000000
            val_str = val_str[:-1]
        elif val_str.endswith('K') or val_str.endswith('k'):
            mult = 1000
            val_str = val_str[:-1]
        try:
            return float(val_str) * mult
        except ValueError:
            return 0

    def _parse_content(self, content: str) -> ParserResult:
        content = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', content)
        result = ParserResult()
        models = []

        lines = content.split('\n')
        section = None
        seen_sections = set()
        current_model = None

        for line in lines:
            if 'OVERVIEW' in line:
                section = 'OVERVIEW'
                seen_sections.add(section)
                continue
            if 'COST & TOKENS' in line:
                section = 'COST_TOKENS'
                seen_sections.add(section)
                continue
            if 'MODEL USAGE' in line:
                section = 'MODEL_USAGE'
                seen_sections.add(section)
                continue
            if 'TOOL USAGE' in line:
                section = 'TOOL_USAGE'
                seen_sections.add(section)
                continue

            if section == 'OVERVIEW':
                m = re.match(r'│([A-Za-z]+)\s+([\d,]+)\s*│', line)
                if m:
                    key = m.group(1)
                    val = int(self._parse_number(m.group(2)))
                    if key == 'Sessions':
                        result.sessions = val
                    elif key == 'Messages':
                        result.messages = val

            elif section == 'COST_TOKENS':
                m = re.match(r'│([A-Za-z/ ]+?)\s+([\$0-9,\.KM]+)\s*│', line)
                if m:
                    key = m.group(1).strip()
                    val = int(self._parse_number(m.group(2)))
                    if key == 'Input':
                        result.input_tokens = val
                    elif key == 'Output':
                        result.output_tokens = val
                    elif key == 'Cache Read':
                        result.cache_read = val
                    elif key == 'Cache Write':
                        result.cache_write = val

            elif section == 'MODEL_USAGE':
                if line.startswith('│ opencode/') or line.startswith('│ '):
                    name_match = re.match(r'│\s*([^ ]+)\s*│', line)
                    if name_match and ' │' not in name_match.group(1):
                        current_model = ModelUsage(model_name=name_match.group(1).strip())
                        models.append(current_model)
                    else:
                        if current_model:
                            m = re.match(r'│\s+([A-Za-z ]+?)\s+([\$0-9,\.KM]+)\s*│', line)
                            if m:
                                prop = m.group(1).strip()
                                val = self._parse_number(m.group(2))
                                if prop == 'Messages':
                                    current_model.messages = int(val)
                                elif prop == 'Input Tokens':
                                    current_model.input_tokens = int(val)
                                elif prop == 'Output Tokens':
                                    current_model.output_tokens = int(val)
                                elif prop == 'Cache Read':
                                    current_model.cache_read = int(val)
                                elif prop == 'Cache Write':
                                    current_model.cache_write = int(val)
                                elif prop == 'Cost':
                                    current_model.cost = val

        result.models = models
        # A non-empty output with none of the known section headers means
        # the CLI changed its format — surface it as a failure rather than
        # a quiet empty result that the poller would log as 'empty result'
        # and the source would just go blank.
        if content.strip() and not seen_sections:
            raise SourceUnavailable(
                "unrecognized opencode stats format: no OVERVIEW/COST & TOKENS/MODEL USAGE headers found"
            )
        return result

    def parse(self) -> ParserResult:
        global _LAST_PARSE
        resolved = find_opencode_bin(self.opencode_bin)
        if not resolved:
            raise SourceUnavailable(
                "opencode command not found (set USAGE_OPENCODE_BIN to its full path)"
            )
        try:
            result = subprocess.run(
                [resolved, 'stats', '--models'],
                capture_output=True, text=True, timeout=self.timeout
            )
            if result.returncode != 0:
                raise SourceUnavailable(
                    f"opencode stats exited with code {result.returncode}: {result.stderr}"
                )
            parsed = self._parse_content(result.stdout)
            _LAST_PARSE = (time.time(), parsed)
            return parsed
        except FileNotFoundError:
            raise SourceUnavailable("opencode command not found")
        except subprocess.TimeoutExpired:
            raise SourceUnavailable(f"opencode stats timed out after {self.timeout}s")
        except SourceUnavailable:
            raise
        except Exception as e:
            raise SourceUnavailable(f"Failed to run opencode stats: {e}")
