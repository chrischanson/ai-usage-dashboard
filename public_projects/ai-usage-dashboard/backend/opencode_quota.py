import subprocess
from .parser import parse_report_content

def fetch_opencode_cost():
    try:
        result = subprocess.run(['opencode', 'stats', '--models'], capture_output=True, text=True, timeout=10)
        overview, cost_tokens, models = parse_report_content(result.stdout)
        total_cost = cost_tokens.get('Total Cost', 0.0)
        cost_by_model = {}
        for m in models:
            c = m.get('Cost', 0)
            if c:
                cost_by_model[m['name']] = c
        return {
            'total_cost': total_cost,
            'cost_by_model': cost_by_model,
        }
    except Exception as e:
        return {'error': str(e)}
