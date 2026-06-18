#!/usr/bin/env python3
"""
Agentic Skill Runner
Orchestrates the execution of structured agent skills/instructions stored in directories
using Antigravity CLI (agy) or OpenCode CLI (opencode).
"""

import os
import sys
import re
import argparse
import subprocess
import time
import json
from datetime import datetime

# Root paths
SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.dirname(SKILLS_DIR)
RUNS_DIR = os.path.join(SKILLS_DIR, "runs")

def get_max_log_id():
    db_path = os.path.expanduser("~/.codex/logs_2.sqlite")
    if not os.path.exists(db_path):
        return 0
    
    import shutil
    temp_dir = os.path.join(WORKSPACE_DIR, "research", "world_cup_2026", "runs", ".tmp_db")
    os.makedirs(temp_dir, exist_ok=True)
    temp_db_path = os.path.join(temp_dir, "logs_temp.sqlite")
    
    try:
        shutil.copy2(db_path, temp_db_path)
        import sqlite3
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(id) FROM logs")
        res = cursor.fetchone()
        conn.close()
        return res[0] or 0
    except Exception:
        return 0
    finally:
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
                os.rmdir(temp_dir)
            except Exception:
                pass

def get_token_usage_from_db(max_id_before):
    db_path = os.path.expanduser("~/.codex/logs_2.sqlite")
    if not os.path.exists(db_path):
        return None
        
    import shutil
    temp_dir = os.path.join(WORKSPACE_DIR, "research", "world_cup_2026", "runs", ".tmp_db")
    os.makedirs(temp_dir, exist_ok=True)
    temp_db_path = os.path.join(temp_dir, "logs_temp.sqlite")
    
    try:
        shutil.copy2(db_path, temp_db_path)
        import sqlite3
        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT feedback_log_body FROM logs WHERE id > ? AND feedback_log_body LIKE '%codex.turn.token_usage.input_tokens=%'", 
            (max_id_before,)
        )
        rows = cursor.fetchall()
        
        total_input_tokens = 0
        total_output_tokens = 0
        
        import re
        for row in rows:
            body = row[0]
            m_in = re.findall(r'codex\.turn\.token_usage\.input_tokens=(\d+)', body)
            m_out = re.findall(r'codex\.turn\.token_usage\.output_tokens=(\d+)', body)
            if m_in:
                total_input_tokens += sum(int(x) for x in m_in)
            if m_out:
                total_output_tokens += sum(int(x) for x in m_out)
                
        conn.close()
        if total_input_tokens > 0 or total_output_tokens > 0:
            return {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_input_tokens + total_output_tokens
            }
        return None
    except Exception as e:
        print(f"Warning: Failed to extract token usage from database: {e}", file=sys.stderr)
        return None
    finally:
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
                os.rmdir(temp_dir)
            except Exception:
                pass

def parse_frontmatter(content):
    """
    Parses simple YAML frontmatter delimited by --- at the top of a file.
    Does not require external pyyaml dependencies.
    """
    # Regex to capture content between three hyphens at the top of the file
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL | re.MULTILINE)
    if not match:
        return {}, content
    
    yaml_text = match.group(1)
    body = content[match.end():]
    
    metadata = {}
    current_list_key = None
    
    for line in yaml_text.splitlines():
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue
            
        # Parse list item: - value
        if line_stripped.startswith("-") and current_list_key is not None:
            val = line_stripped[1:].strip().strip('"').strip("'")
            if isinstance(metadata[current_list_key], list):
                metadata[current_list_key].append(val)
            continue
            
        # Parse key-value: key: value
        if ":" in line:
            parts = line.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip().strip('"').strip("'")
            
            # If value is empty, treat as potential list start
            if val == "":
                metadata[key] = []
                current_list_key = key
            else:
                metadata[key] = val
                current_list_key = None
                
    return metadata, body

def load_skill(skill_name):
    """Loads a skill's MD file and parses metadata."""
    skill_file_path = os.path.join(SKILLS_DIR, skill_name, "SKILL.md")
    if not os.path.exists(skill_file_path):
        print(f"Error: Skill '{skill_name}' not found at {skill_file_path}", file=sys.stderr)
        sys.exit(1)
        
    with open(skill_file_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    metadata, instructions = parse_frontmatter(content)
    return metadata, instructions

def parse_vars_arg(vars_str):
    """Parses var1=val1,var2=val2 string into a dictionary."""
    variables = {}
    if not vars_str:
        return variables
    
    # Split by comma but handle cases where values might have commas protected by quotes or escapes
    # Simpler split is by comma if no quotes are present
    pairs = vars_str.split(",")
    for pair in pairs:
        if "=" in pair:
            k, v = pair.split("=", 1)
            variables[k.strip()] = v.strip()
    return variables

def compile_prompt(instructions, variables):
    """Replaces placeholders in the format {VARIABLE_NAME} with actual values."""
    compiled = instructions
    for key, val in variables.items():
        placeholder = "{" + key + "}"
        compiled = compiled.replace(placeholder, val)
        
    # Check if there are any unreplaced placeholders
    unreplaced = re.findall(r"\{([A-Z0-9_]+)\}", compiled)
    if unreplaced:
        print(f"Warning: The following placeholders were not resolved: {', '.join(set(unreplaced))}", file=sys.stderr)
        
    return compiled

def execute_agent(agent_type, model, prompt, dry_run=False, continue_session=False, session_id=None, title=None):
    """Executes the agent CLI tool and captures output."""
    if agent_type == "agy":
        cmd = [
            "agy",
            "--dangerously-skip-permissions",
        ]
        if model:
            cmd.extend(["--model", model])
        if continue_session:
            cmd.append("--continue")
        elif session_id:
            cmd.extend(["--conversation", session_id])
        cmd.extend([
            "--print",
            prompt
        ])
    elif agent_type == "opencode":
        cmd = [
            "opencode",
            "run",
            "--dangerously-skip-permissions"
        ]
        if model:
            cmd.extend(["--model", model])
        if continue_session:
            cmd.append("--continue")
        if session_id:
            cmd.extend(["-s", session_id])
        if title:
            cmd.extend(["--title", title])
        cmd.append(prompt)
    else:
        print(f"Error: Unsupported agent type '{agent_type}'", file=sys.stderr)
        sys.exit(1)
        
    print(f"\n--- [Executing Agent: {agent_type}] ---")
    print(f"Command: {' '.join(cmd[:3])} ... [Prompt details hidden]")
    
    if dry_run:
        print("\n[Dry Run] Prompt to be sent:")
        print("=" * 60)
        print(prompt)
        print("=" * 60)
        return 0, "[Dry Run Mode - No execution output]", ""
        
    # Start execution
    start_time = time.time()
    
    # Run process and stream logs to both console and buffer
    process = subprocess.Popen(
        cmd,
        cwd=WORKSPACE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    output_lines = []
    for line in process.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        output_lines.append(line)
        
    process.wait()
    duration = time.time() - start_time
    return_code = process.returncode
    full_output = "".join(output_lines)
    
    print(f"\n--- [Execution Finished with code {return_code} in {duration:.2f}s] ---")
    return return_code, full_output, duration

def main():
    parser = argparse.ArgumentParser(description="Run an agentic skill from a structured definition.")
    parser.add_argument("skill", help="The name of the skill directory containing SKILL.md")
    parser.add_argument("--agent", choices=["agy", "opencode"], help="Override default agent CLI (default: agy)")
    parser.add_argument("--model", help="Override default agent model")
    parser.add_argument("--vars", help="Comma-separated variables, e.g. COMPONENT_NAME=UserCard,SPEC='A simple card'")
    parser.add_argument("--dry-run", action="store_true", help="Print the compiled prompt without executing the agent")
    parser.add_argument("--continue", action="store_true", dest="continue_session", help="Continue the last session")
    parser.add_argument("--session", help="Session ID to continue")
    parser.add_argument("--title", help="Title for the session")
    
    args = parser.parse_args()
    
    # Load skill
    metadata, instructions = load_skill(args.skill)
    
    # Extract settings
    skill_name = metadata.get("name", args.skill)
    agent = args.agent or metadata.get("default_agent", "agy")
    model = args.model or metadata.get("default_model", "")
    required_vars = metadata.get("required_vars", [])
    
    # Parse passed variables
    variables = parse_vars_arg(args.vars)
    
    # Collect missing variables
    missing_vars = [v for v in required_vars if v not in variables]
    if missing_vars:
        if args.dry_run:
            # For dry-run, inject placeholders
            for mv in missing_vars:
                variables[mv] = f"<{mv}>"
        else:
            print(f"Resolving required variables for skill '{skill_name}':")
            for mv in missing_vars:
                # Prompt user for value
                val = input(f"Enter value for {mv}: ").strip()
                variables[mv] = val
                
    # Create runs directory if it doesn't exist
    os.makedirs(RUNS_DIR, exist_ok=True)
    
    # Generate run ID and path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = f"run_{timestamp}_{args.skill}"
    run_dir = os.path.join(RUNS_DIR, run_name)
    
    if not args.dry_run:
        os.makedirs(run_dir, exist_ok=True)
    
    # Inject OUTPUT_DIR so skill instructions can place output in the run folder
    variables["OUTPUT_DIR"] = run_dir if not args.dry_run else f"<{run_dir}>"
    
    # Compile prompt
    compiled_prompt = compile_prompt(instructions, variables)
    
    max_id_before = 0
    if not args.dry_run:
        # Write prompt before execution
        with open(os.path.join(run_dir, "input_prompt.md"), "w", encoding="utf-8") as f:
            f.write(compiled_prompt)
        max_id_before = get_max_log_id()
            
    # Execute
    return_code, full_output, duration = execute_agent(
        agent, model, compiled_prompt, args.dry_run,
        continue_session=args.continue_session,
        session_id=args.session,
        title=args.title
    )
    
    if not args.dry_run:
        # Write logs
        with open(os.path.join(run_dir, "output.log"), "w", encoding="utf-8") as f:
            f.write(full_output)
            
        # Token accounting is agent-specific. The old implementation read
        # Codex's sqlite logs, which misattributes usage for agy/opencode runs.
        token_usage = None
            
        # Write execution metadata
        metadata_summary = {
            "skill": args.skill,
            "agent": agent,
            "model": model,
            "variables": variables,
            "timestamp": timestamp,
            "duration_seconds": duration,
            "return_code": return_code,
            "status": "success" if return_code == 0 else "failed"
        }
        if token_usage:
            metadata_summary["token_usage"] = token_usage
        
        with open(os.path.join(run_dir, "run_metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata_summary, f, indent=2)
            
        # Resolve and print session/conversation ID for the caller to reuse
        current_session_id = args.session
        if agent == "opencode" and not current_session_id:
            try:
                result = subprocess.run(
                    ["opencode", "session", "list", "--format", "json", "-n", "10"],
                    capture_output=True, text=True, timeout=10
                )
                sessions = json.loads(result.stdout)
                if args.title:
                    for s in sessions:
                        if s.get("title") == args.title:
                            current_session_id = s["id"]
                            break
                if not current_session_id and sessions:
                    current_session_id = sessions[0]["id"]
            except Exception:
                pass
        if agent == "agy" and not current_session_id:
            match = re.search(
                r"Print mode: conversation=([0-9a-fA-F-]{36})",
                full_output,
            )
            if match:
                current_session_id = match.group(1)
            else:
                try:
                    log_path = os.path.expanduser("~/.gemini/antigravity-cli/cli.log")
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        log_tail = f.read()[-20000:]
                    matches = re.findall(
                        r"Print mode: conversation=([0-9a-fA-F-]{36})",
                        log_tail,
                    )
                    if matches:
                        current_session_id = matches[-1]
                except Exception:
                    pass
        if current_session_id and agent == "opencode":
            print(f"OPENCODE_SESSION_ID: {current_session_id}")
        elif current_session_id and agent == "agy":
            print(f"AGY_CONVERSATION_ID: {current_session_id}")

        print(f"Execution logs and metadata saved to: {run_dir}")
        sys.exit(return_code)

if __name__ == "__main__":
    main()
