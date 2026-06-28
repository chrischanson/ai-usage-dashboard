"""
Thin wrapper for backward compatibility.
Delegates to parsers.codex.CodexParser and returns the old tuple format.
"""
from parsers.codex import CodexParser
from parsers.base import ParserResult


def _result_to_tuple(result: ParserResult) -> tuple:
    overview = {
        'Sessions': result.sessions,
        'Messages': result.messages,
    }
    cost_tokens = {
        'Total Cost': 0.0,
        'Avg Cost/Day': 0.0,
        'Input': result.input_tokens,
        'Output': result.output_tokens,
        'Cache Read': result.cache_read,
        'Cache Write': result.cache_write,
    }
    models = [
        {
            'name': m.model_name,
            'Messages': m.messages,
            'Input Tokens': m.input_tokens,
            'Output Tokens': m.output_tokens,
            'Cache Read': m.cache_read,
            'Cache Write': m.cache_write,
            'Cost': m.cost,
        }
        for m in result.models
    ]
    return overview, cost_tokens, models


def fetch_codex_usage():
    result = CodexParser().parse()
    return _result_to_tuple(result)
