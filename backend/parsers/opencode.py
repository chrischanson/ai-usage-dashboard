import re
import subprocess

from .base import Parser, ParserResult, ModelUsage, SourceUnavailable


class OpenCodeParser(Parser):
    def __init__(self, timeout: int = 20):
        self.timeout = timeout

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
        current_model = None

        for line in lines:
            if 'OVERVIEW' in line:
                section = 'OVERVIEW'
                continue
            if 'COST & TOKENS' in line:
                section = 'COST_TOKENS'
                continue
            if 'MODEL USAGE' in line:
                section = 'MODEL_USAGE'
                continue
            if 'TOOL USAGE' in line:
                section = 'TOOL_USAGE'
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
        return result

    def parse(self) -> ParserResult:
        try:
            result = subprocess.run(
                ['opencode', 'stats', '--models'],
                capture_output=True, text=True, timeout=self.timeout
            )
            if result.returncode != 0:
                raise SourceUnavailable(
                    f"opencode stats exited with code {result.returncode}: {result.stderr}"
                )
            return self._parse_content(result.stdout)
        except FileNotFoundError:
            raise SourceUnavailable("opencode command not found")
        except subprocess.TimeoutExpired:
            raise SourceUnavailable(f"opencode stats timed out after {self.timeout}s")
        except SourceUnavailable:
            raise
        except Exception as e:
            raise SourceUnavailable(f"Failed to run opencode stats: {e}")
