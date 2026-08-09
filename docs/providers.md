# Provider System Reference

The provider system in the AI Usage Dashboard allows you to easily plug in new AI agents, APIs, and tools to track their usage and quota without modifying the core codebase. 

Instead of writing new parser classes and registering them manually, you can simply define a declarative YAML file that instructs the dashboard how to fetch and map your data.

## Adding a New Source

1. Create a new file ending in `.yaml` inside the `backend/providers/` directory. The filename (without `.yaml`) becomes the internal ID of the source.
2. Define how the dashboard should fetch the data using one of the built-in adapters.
3. Restart the dashboard server to pick up the new provider.

## Security Guarantees

The provider system is designed with security in mind, allowing you to define custom data sources without exposing the host system to unnecessary risks:
- **No Arbitrary Code Execution:** YAML files are parsed strictly using `yaml.safe_load()`.
- **Command Injection Prevention:** The `subprocess` adapter requires arguments as a list and strictly enforces `shell=False`.
- **Secure Network Calls:** The `http_json` adapter enforces `https://` URLs (except for `localhost`/`127.0.0.1` during testing).
- **Read-Only SQLite:** The `sqlite_query` adapter opens databases with `mode=ro`.
- **Path Traversal Prevention:** Script modules and SQLite database paths are checked to prevent `../` attacks outside the expected boundaries.

## YAML Schema Reference

A complete provider configuration looks like this:

```yaml
# Human-readable name shown in dashboard tabs
display_name: "My Custom Agent"

# Chart color in oklch() format
color: "oklch(0.6 0.15 250)"

# Defines how to fetch and parse usage data
usage:
  type: http_json # Adapter type
  url: "https://api.example.com/v1/usage"
  headers:
    Authorization: "Bearer ${MY_API_KEY}"
  
  # How to map the returned data to the dashboard's internal format
  mapping:
    input_tokens: ".data.total_input"
    output_tokens: ".data.total_output"
    sessions: ".data.sessions"
    messages: ".data.messages"

# Defines how to fetch and parse quota/limit data (optional)
quota:
  type: python_script
  module: "providers.scripts.my_quota_script"
```

### The `color` Field
The `color` field uses the `oklch()` CSS color function format (e.g., `oklch(0.667 0.183 310)`). This is used to paint the source's area in the main dashboard chart and to style its specific UI elements.

## Adapters

Adapters do the heavy lifting of fetching data. You specify an adapter using the `type` field in the `usage` or `quota` block.

### 1. `http_json`

Issues a GET request to a URL and parses the response as JSON. Useful for pulling data from vendor APIs.

```yaml
usage:
  type: http_json
  url: "https://api.anthropic.com/v1/usage"
  headers:
    # Environment variables in headers are interpolated automatically
    x-api-key: "${ANTHROPIC_API_KEY}"
```

### 2. `subprocess`

Runs a local command and parses its output. By default, it expects JSON output.

```yaml
usage:
  type: subprocess
  # Must be a list of strings (no shell=True)
  command: ["my-cli", "stats", "--format=json"]
  format: "json" # 'json' or 'text'
```

If your CLI tool only outputs raw text, you can use `format: text` and specify a Python `preprocessor` function to convert the text output into a Python dictionary:

```yaml
usage:
  type: subprocess
  command: ["my-cli", "stats"]
  format: "text"
  preprocessor: "my_module.parse_cli_output"
```

### 3. `sqlite_query`

Executes a read-only query against a local SQLite database.

```yaml
usage:
  type: sqlite_query
  db_path: "/home/user/.my-agent/state.db"
  overview_query: "SELECT sum(input_tokens) as input_tokens, sum(output_tokens) as output_tokens FROM usage"
  # Optional: Query to fetch per-model breakdowns
  models_query: "SELECT model_name, sum(input_tokens) as input_tokens FROM usage GROUP BY model_name"
```

### 4. `python_script`

For complex scenarios where simple mapping isn't enough, you can point to a custom Python script.

```yaml
usage:
  type: python_script
  module: "providers.scripts.my_agent_usage"
```

The script must define a `create_parser()` function that returns a `Parser` subclass instance:

```python
# providers/scripts/my_agent_usage.py
from parsers.base import Parser, ParserResult

class MyAgentParser(Parser):
    def parse(self) -> ParserResult:
        # Complex parsing logic...
        result = ParserResult()
        result.input_tokens = 500
        return result

def create_parser(**kwargs):
    return MyAgentParser()
```

## Field Mapping

When using generic adapters (`http_json`, `subprocess`, `sqlite_query`), the adapter returns raw JSON, dictionary, or SQLite Row objects. You must define a `mapping` block to extract the required fields using dot-notation paths.

```yaml
mapping:
  # Starts with a dot, indicating the root of the data object
  input_tokens: ".data.metrics.input"
  output_tokens: ".data.metrics.output"
  sessions: ".data.session_count"
```

**Supported Mapping Fields (Global):**
- `sessions`
- `messages`
- `input_tokens`
- `output_tokens`
- `cache_read`
- `cache_write`

**Model-Specific Breakdown:**
If the data contains a list of models, you can map the list and its fields:

```yaml
models_path: ".data.models"
model_mapping:
  model_name: ".name"
  input_tokens: ".stats.in"
  output_tokens: ".stats.out"
  cost: ".cost_usd"
```

## How Quota Works

Quotas define the progress bars and limits shown in the dashboard. Similar to `usage`, you define a `quota` block with an adapter type.

Unlike `usage` which uses generic dot-mapping, quotas usually have deeply nested structures (e.g. grouped by plan type and model limit). You handle this in two ways:

1. **Fully Custom Python Script (`type: python_script`):**
   The script must define both `collect()` (fetches data) and `normalize()` (transforms it to the dashboard format).

   ```python
   # providers/scripts/my_quota.py
   def collect():
       return {"used": 50, "limit": 100}

   def normalize(raw):
       return {
           "_plan": "Pro Plan",
           "group_name": {
               "limit_name": {
                   "used": raw["used"],
                   "total": raw["limit"],
                   "remaining_pct": 50.0,
                   "refreshes_in_seconds": 3600
               }
           }
       }
   ```

2. **Generic Adapter + Normalizer Function:**
   You can use `http_json` or `subprocess` to fetch the raw quota, and then specify a Python normalizer function to process the dictionary into the required nested format.

   ```yaml
   quota:
     type: http_json
     url: "https://api.example.com/quota"
     normalizer: "providers.scripts.my_quota.normalize"
   ```
