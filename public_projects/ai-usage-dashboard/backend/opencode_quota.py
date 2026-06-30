from parser import fetch_and_parse

def fetch_opencode_cost():
    try:
        overview, cost_tokens, models = fetch_and_parse()
        cost_by_model = {}
        total_cost = 0.0
        for m in models:
            c = m.get('Cost', 0) or 0
            if c:
                cost_by_model[m['name']] = c
                total_cost += c
        return {
            'total_cost': total_cost,
            'cost_by_model': cost_by_model,
        }
    except Exception as e:
        return {'error': str(e)}
