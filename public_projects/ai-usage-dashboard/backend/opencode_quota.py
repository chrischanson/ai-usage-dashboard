from parser import fetch_and_parse

def fetch_opencode_cost():
    try:
        overview, cost_tokens, models = fetch_and_parse()
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
