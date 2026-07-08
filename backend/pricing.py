"""Claude API list pricing, for estimating dollar cost from token counts.

Only Claude models are priced here: they're the one source (claude.py) that
reads raw per-model token counts straight from Anthropic transcripts, so the
math is a direct application of Anthropic's own published rates. Other
sources report their own cost (opencode, agy) or aren't priced at all here
(codex uses OpenAI models, whose pricing isn't tracked in this project).

Rates are $ per million tokens. Cache read/write aren't separately published
per model; Anthropic's standard multipliers on the base input rate are
~0.1x for a cache read and ~1.25x for a cache write (5-minute TTL) - see
https://platform.claude.com/docs/en/build-with-claude/prompt-caching.
"""

CACHE_READ_MULTIPLIER = 0.1
CACHE_WRITE_MULTIPLIER = 1.25

# (input $/Mtok, output $/Mtok)
CLAUDE_PRICING = {
    'claude-fable-5': (10.00, 50.00),
    'claude-mythos-5': (10.00, 50.00),
    'claude-opus-4-8': (5.00, 25.00),
    'claude-opus-4-7': (5.00, 25.00),
    'claude-opus-4-6': (5.00, 25.00),
    'claude-opus-4-5': (5.00, 25.00),
    'claude-sonnet-5': (3.00, 15.00),
    'claude-sonnet-4-6': (3.00, 15.00),
    'claude-sonnet-4-5': (3.00, 15.00),
    'claude-haiku-4-5': (1.00, 5.00),
}


def estimate_claude_cost(model_name: str, input_tokens: int, output_tokens: int,
                          cache_read: int = 0, cache_write: int = 0) -> float:
    """Estimate $ cost for one model's cumulative token counts.

    Returns 0.0 for an unrecognized model (e.g. a snapshot-dated ID or a
    model released after this table was last updated) rather than guessing.
    """
    rates = CLAUDE_PRICING.get(model_name)
    if not rates:
        return 0.0
    input_rate, output_rate = rates
    cost = (input_tokens or 0) * input_rate / 1_000_000
    cost += (output_tokens or 0) * output_rate / 1_000_000
    cost += (cache_read or 0) * input_rate * CACHE_READ_MULTIPLIER / 1_000_000
    cost += (cache_write or 0) * input_rate * CACHE_WRITE_MULTIPLIER / 1_000_000
    return cost
