import re
import subprocess

def parse_number(val_str):
    """Parse numbers like 8.9M, 626.2K, $0.00, 1,992 into float/int"""
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

def parse_report_content(content):
    # Strip ANSI escape sequences
    content = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', content)
    overview = {}
    cost_tokens = {}
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
                overview[m.group(1)] = parse_number(m.group(2))
                
        elif section == 'COST_TOKENS':
            m = re.match(r'│([A-Za-z/ ]+?)\s+([\$0-9,\.KM]+)\s*│', line)
            if m:
                key = m.group(1).strip()
                cost_tokens[key] = parse_number(m.group(2))
                
        elif section == 'MODEL_USAGE':
            if line.startswith('│ opencode/') or line.startswith('│ '):
                # New model
                name_match = re.match(r'│\s*([^ ]+)\s*│', line)
                if name_match and ' │' not in name_match.group(1):
                    current_model = {'name': name_match.group(1).strip()}
                    models.append(current_model)
                else:
                    # Model property
                    if current_model:
                        m = re.match(r'│\s+([A-Za-z ]+?)\s+([\$0-9,\.KM]+)\s*│', line)
                        if m:
                            current_model[m.group(1).strip()] = parse_number(m.group(2))
    
    return overview, cost_tokens, models

def fetch_and_parse():
    try:
        # Run opencode stats --models to get the report
        result = subprocess.run(['opencode', 'stats', '--models'], capture_output=True, text=True)
        return parse_report_content(result.stdout)
    except Exception as e:
        print("Failed to run opencode stats:", e)
        return {}, {}, []
