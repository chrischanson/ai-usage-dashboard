from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


SYSTEM_PROMPT = """Extract marathon race dates and registration deadlines from official race page text.
Return only strict JSON with these keys:
event_date, registration_windows, confidence, notes, raw_evidence.

- event_date: The race day date (ISO 8601, e.g. "2026-10-11") or null.
- registration_windows: A list of objects representing entry/registration periods. Each object must have:
  - window_type: one of 'standard', 'lottery', 'charity', 'guaranteed-entry', 'qualification'
  - description: a short description of the entry method / who it is for
  - open_date: ISO 8601 date when registration opens, or null
  - close_date: ISO 8601 deadline date when registration closes, or null
  Ensure all distinct entry periods (like lottery windows, charity programs, time qualifier windows) are captured as separate objects.

Use ISO 8601 dates ("YYYY-MM-DD") when a full date is available. Use null when unknown.
raw_evidence must be a short list of source text snippets supporting the dates.
confidence must be high, medium, low, or unknown."""


def _parse_json_content(text: str) -> dict[str, object] | None:
    text = text.strip()
    if "```" in text:
        import re
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1)
        else:
            text = text.strip("`").removeprefix("json").strip()
            
    # Try to find JSON block in case of header/footer text (e.g. from opencode log output)
    if not (text.startswith("{") and text.endswith("}")):
        import re
        match = re.search(r"(\{.*\})", text, re.DOTALL)
        if match:
            text = match.group(1)

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError as exc:
        return {
            "confidence": "unknown",
            "notes": f"LLM returned non-JSON content: {exc}",
            "raw_evidence": [],
        }


def extract_with_llm(race_name: str, page_text: str) -> dict[str, object] | None:
    api_key = os.environ.get("LLM_API_KEY")
    if api_key:
        api_base = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1").rstrip("/")
        model = os.environ.get("LLM_MODEL", "gpt-4.1-mini")
        timeout = int(os.environ.get("LLM_TIMEOUT_SECONDS", "45"))
        content = page_text[:18000]
        body = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Race: {race_name}\n\nOfficial page text:\n{content}",
                },
            ],
        }
        request = urllib.request.Request(
            f"{api_base}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
            text = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not isinstance(text, str):
                return None
            return _parse_json_content(text)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return {
                "confidence": "unknown",
                "notes": f"LLM extraction failed: {exc}",
                "raw_evidence": [],
            }

    # If no API key, check for local CLI tools (agy, opencode)
    import shutil
    import subprocess

    content = page_text[:18000]
    prompt = f"{SYSTEM_PROMPT}\n\nRace: {race_name}\n\nOfficial page text:\n{content}"

    agy_path = shutil.which("agy")
    if agy_path:
        try:
            result = subprocess.run(
                ["agy", "--print", prompt],
                capture_output=True,
                text=True,
                timeout=90
            )
            if result.returncode == 0:
                return _parse_json_content(result.stdout)
            else:
                return {
                    "confidence": "unknown",
                    "notes": f"agy CLI execution failed: {result.stderr.strip()}",
                    "raw_evidence": [],
                }
        except (subprocess.SubprocessError, ValueError, TimeoutError) as exc:
            return {
                "confidence": "unknown",
                "notes": f"agy CLI extraction failed: {exc}",
                "raw_evidence": [],
            }

    opencode_path = shutil.which("opencode")
    if opencode_path:
        try:
            result = subprocess.run(
                ["opencode", "run", prompt],
                capture_output=True,
                text=True,
                timeout=90
            )
            if result.returncode == 0:
                return _parse_json_content(result.stdout)
            else:
                return {
                    "confidence": "unknown",
                    "notes": f"opencode CLI execution failed: {result.stderr.strip()}",
                    "raw_evidence": [],
                }
        except (subprocess.SubprocessError, ValueError, TimeoutError) as exc:
            return {
                "confidence": "unknown",
                "notes": f"opencode CLI extraction failed: {exc}",
                "raw_evidence": [],
            }

    return None


