from parsers.opencode import OpenCodeParser


def fetch_opencode_cost():
    try:
        result = OpenCodeParser(timeout=3).parse()
        cost_by_model = {m.model_name: m.cost for m in result.models if m.cost}
        return {
            'total_cost': sum(cost_by_model.values()),
            'cost_by_model': cost_by_model,
        }
    except Exception as e:
        return {'error': str(e)}
