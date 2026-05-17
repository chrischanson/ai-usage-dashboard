"""Evaluator — scores job outputs using rubric-based fitness functions."""

import json
import logging
import re
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


def _is_float_in_range(value: Any, min_val: float, max_val: float) -> bool:
    """Check if value is a float within [min_val, max_val]."""
    try:
        f = float(value)
        return min_val <= f <= max_val
    except (TypeError, ValueError):
        return False


def _is_list_min_length(value: Any, min_len: int) -> bool:
    """Check if value is a list with at least min_len items."""
    return isinstance(value, list) and len(value) >= min_len


def _is_not_empty(value: Any) -> bool:
    """Check if value is truthy / non-empty."""
    if value is None:
        return False
    if isinstance(value, str):
        return len(value.strip()) > 0
    if isinstance(value, list):
        return len(value) > 0
    return bool(value)


def _has_field(value: Any) -> bool:
    """Check if the value exists (is not None)."""
    return value is not None


# Registry of check functions
CHECK_REGISTRY = {
    "is_float_in_range": _is_float_in_range,
    "is_list_min_length": _is_list_min_length,
    "is_not_empty": _is_not_empty,
    "has_field": _has_field,
}


def _parse_check(check_str: str) -> tuple[str, list]:
    """
    Parse a check string like 'is_float_in_range(-1, 1)' into
    (function_name, [arg1, arg2]).
    """
    match = re.match(r"(\w+)\(([^)]*)\)", check_str)
    if not match:
        return check_str, []

    func_name = match.group(1)
    args_str = match.group(2).strip()
    if not args_str:
        return func_name, []

    args = []
    for arg in args_str.split(","):
        arg = arg.strip()
        try:
            args.append(int(arg))
        except ValueError:
            try:
                args.append(float(arg))
            except ValueError:
                args.append(arg)

    return func_name, args


def parse_output(raw_output: str) -> dict | None:
    """
    Attempt to extract JSON from the raw LLM output.
    Handles cases where JSON is wrapped in markdown code blocks.
    """
    if not raw_output:
        return None

    # Try direct JSON parse
    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code blocks
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_output)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } block
    brace_match = re.search(r"\{[\s\S]*\}", raw_output)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def score_rubric(parsed_output: dict | None, fitness_config: dict) -> tuple[Decimal, dict]:
    """
    Score output against rubric rules.

    Returns:
        (composite_score, details_dict)
        where composite_score is 0.0-1.0 and details_dict has per-rule results.
    """
    if parsed_output is None:
        return Decimal("0"), {"error": "output_not_parseable", "rules": {}}

    rules = fitness_config.get("rules", [])
    if not rules:
        return Decimal("1"), {"rules": {}, "note": "no_rules_defined"}

    results = {}
    passed = 0
    total = len(rules)

    for rule in rules:
        field = rule.get("field", "")
        check_str = rule.get("check", "has_field")

        value = parsed_output.get(field)
        func_name, args = _parse_check(check_str)

        check_fn = CHECK_REGISTRY.get(func_name)
        if not check_fn:
            results[field] = {"check": check_str, "passed": False, "error": f"unknown_check: {func_name}"}
            continue

        try:
            result = check_fn(value, *args)
        except Exception as e:
            results[field] = {"check": check_str, "passed": False, "error": str(e)}
            continue

        results[field] = {"check": check_str, "passed": result, "value": str(value)[:200]}
        if result:
            passed += 1

    composite = Decimal(str(round(passed / total, 4))) if total > 0 else Decimal("0")

    logger.info("Rubric score: %s/%s rules passed (%.4f)", passed, total, composite)
    return composite, {"rules": results, "passed": passed, "total": total}


async def score(
    raw_output: str,
    parsed_output: dict | None,
    fitness_config: dict,
) -> tuple[Decimal, dict]:
    """
    Main scoring entry point. Routes to the appropriate evaluator mode.
    Currently supports: rubric.
    Future: llm_judge, signal_correlation.
    """
    eval_type = fitness_config.get("type", "rubric")

    if eval_type == "rubric":
        return score_rubric(parsed_output, fitness_config)
    else:
        logger.warning("Unknown evaluator type: %s, defaulting to rubric", eval_type)
        return score_rubric(parsed_output, fitness_config)
