# Thinking Engine — Task Schema Specification v0.1

## Design Principles

1. **Goal-first** — every task declares what success looks like before anything else
2. **Measurable progress** — a judge LLM scores every output against explicit criteria
3. **Composable** — tasks can spawn child tasks one level deep
4. **Versionable** — same ID, incrementing version; full history preserved
5. **Self-contained** — a task file alone is enough to run, judge, and evolve the task

---

## Full Schema (annotated)

```xml
<task
  id="earnings_sentiment"          <!-- stable snake_case identifier, never changes -->
  version="3"                      <!-- incremented by evolution loop on prompt change -->
  parent_version="2"               <!-- which version this evolved from -->
  domain="trading"                 <!-- trading | research | engineering | productivity -->
  status="active"                  <!-- active | paused | deprecated | experimental -->
  created="2026-05-16"
  evolved="2026-05-20">            <!-- date of last evolution cycle change -->

  <!-- ═══════════════════════════════════════════
       1. IDENTITY
       What this task is and why it exists
  ═══════════════════════════════════════════ -->
  <identity>
    <name>Earnings Call Sentiment Analyzer</name>
    <description>
      Reads the most recent earnings call transcript for a given ticker,
      extracts sentiment, key themes, and forward guidance quality,
      and produces a structured signal for downstream use.
    </description>
    <tags>earnings, sentiment, NLP, equity-research</tags>
  </identity>

  <!-- ═══════════════════════════════════════════
       2. GOAL
       The desired outcome — what a perfect run looks like
  ═══════════════════════════════════════════ -->
  <goal>
    <statement>
      Produce a structured, accurate sentiment reading of an earnings call
      that a quantitative analyst would find actionable — capturing tone,
      management confidence, and forward guidance quality in a consistent,
      comparable format across tickers and quarters.
    </statement>
    <success_criteria>
      <!-- Each criterion has a weight that sums to 1.0 across the goal -->
      <criterion id="accuracy" weight="0.4">
        Sentiment score directionally matches the market's post-earnings
        reaction within 3 trading days (used once ground truth available;
        judge LLM proxy used until then).
      </criterion>
      <criterion id="completeness" weight="0.3">
        All required output fields are present, non-empty, and
        within specified ranges.
      </criterion>
      <criterion id="consistency" weight="0.2">
        Running the same transcript twice produces scores within ±0.1
        of each other (stability check).
      </criterion>
      <criterion id="insight_quality" weight="0.1">
        Key themes are specific and non-generic (judge LLM scores this).
      </criterion>
    </success_criteria>
  </goal>

  <!-- ═══════════════════════════════════════════
       3. PROGRESS MEASUREMENT
       How the judge LLM scores each run
  ═══════════════════════════════════════════ -->
  <measurement>
    <method>judge_llm</method>
    <judge_model>claude-haiku-4-5</judge_model>   <!-- cheap, fast, separate from executor -->

    <!-- Rubric handed to the judge on every evaluation -->
    <rubric>
      Score the following task output on each criterion below.
      Return ONLY a JSON object — no preamble, no explanation.

      Criteria:
      - accuracy (0.0–1.0): Does the sentiment score seem directionally
        consistent with the language in the transcript provided? 
        Use 0.5 if you cannot determine directional accuracy.
      - completeness (0.0–1.0): Are all fields present and within range?
        sentiment_score in [-1,1], confidence in [0,1],
        key_themes is a list of 2+, forward_guidance is non-empty.
      - consistency: skip (handled separately by runner).
      - insight_quality (0.0–1.0): Are the key_themes specific to this
        company and quarter, or are they generic boilerplate?

      Output format:
      {
        "accuracy": float,
        "completeness": float,
        "insight_quality": float,
        "composite": float,   // weighted average per criterion weights
        "flags": []           // list of strings — any issues noticed
      }
    </rubric>

    <!-- Thresholds that drive system behavior -->
    <thresholds>
      <alert_above>0.80</alert_above>        <!-- notify Chris if composite ≥ 0.80 -->
      <evolve_below>0.60</evolve_below>      <!-- trigger evolution cycle if composite < 0.60 -->
      <discard_below>0.30</discard_below>    <!-- don't store run; log error only -->
    </thresholds>

    <!-- How progress is tracked over versions -->
    <progress_tracking>
      <metric>rolling_7d_composite_avg</metric>
      <improvement_target>+0.05 per evolution cycle</improvement_target>
      <plateau_threshold>3</plateau_threshold>  <!-- stop evolving if no gain in 3 cycles -->
    </progress_tracking>
  </measurement>

  <!-- ═══════════════════════════════════════════
       4. SCHEDULE
       When and how often this task runs
  ═══════════════════════════════════════════ -->
  <schedule>
    <cron>0 8 * * 1-5</cron>               <!-- weekdays 8am -->
    <timezone>America/Chicago</timezone>
    <trigger>event:earnings_date_match</trigger>  <!-- also runs on event trigger -->
    <max_concurrent>1</max_concurrent>
    <timeout_seconds>120</timeout_seconds>
  </schedule>

  <!-- ═══════════════════════════════════════════
       5. CONTEXT
       What data gets injected before the prompt runs
  ═══════════════════════════════════════════ -->
  <context>
    <input id="transcript" required="true">
      <source>web_search</source>
      <query>{ticker} earnings call transcript Q{quarter} {year} site:seekingalpha.com OR site:fool.com</query>
      <max_chars>8000</max_chars>
      <fallback>sec_edgar:{ticker}:latest_8k</fallback>
    </input>
    <input id="prior_scores" required="false">
      <source>results_store</source>
      <job_id>earnings_sentiment</job_id>
      <filter>ticker={ticker}</filter>
      <last_n>4</last_n>
      <format>summary</format>   <!-- don't inject full prior outputs, just scores + themes -->
    </input>
    <input id="price_context" required="false">
      <source>api:polygon.io</source>
      <endpoint>/v2/aggs/ticker/{ticker}/range/1/day/-30d/today</endpoint>
      <transform>last_30d_return_pct</transform>
    </input>
  </context>

  <!-- ═══════════════════════════════════════════
       6. PROMPT
       The actual instruction sent to the executor LLM
       {placeholders} are resolved at runtime
  ═══════════════════════════════════════════ -->
  <prompt version="3">
    <system>
      You are a quantitative equity analyst specializing in earnings call analysis.
      Your output must be strictly valid JSON — no prose, no markdown, no explanation.
    </system>
    <user>
      Analyze the following earnings call transcript for {ticker} ({company_name}),
      reported on {earnings_date} for fiscal quarter {quarter} {year}.

      TRANSCRIPT:
      {transcript}

      PRIOR SENTIMENT SCORES FOR THIS TICKER:
      {prior_scores}

      30-DAY PRICE CONTEXT:
      {price_context}

      Produce a JSON object with exactly these fields:
      {{
        "ticker": string,
        "quarter": string,
        "sentiment_score": float between -1.0 and 1.0,
        "confidence": float between 0.0 and 1.0,
        "key_themes": [list of 3-5 specific strings],
        "forward_guidance": "raised" | "maintained" | "lowered" | "withdrawn" | "none",
        "guidance_confidence": float between 0.0 and 1.0,
        "management_tone": "optimistic" | "cautious" | "defensive" | "neutral",
        "notable_risks": [list of up to 3 strings, empty list if none],
        "analyst_pushback": boolean,
        "summary": string of max 100 words
      }}
    </user>
  </prompt>

  <!-- ═══════════════════════════════════════════
       7. EXECUTION
       LLM routing and cost budget
  ═══════════════════════════════════════════ -->
  <execution>
    <budget>
      <max_cost_usd>0.05</max_cost_usd>
      <max_tokens_in>6000</max_tokens_in>
      <max_tokens_out>800</max_tokens_out>
    </budget>
    <routing>
      <!-- Router tries providers in order; skips if credits exhausted -->
      <provider priority="1" model="gemini-flash-2.0">gemini</provider>
      <provider priority="2" model="claude-haiku-4-5">anthropic</provider>
      <provider priority="3" model="llama-3.1-70b">groq</provider>
      <provider priority="4" model="qwen3:30b">ollama</provider>  <!-- local fallback -->
    </routing>
    <output_format>json</output_format>
    <retry>
      <max_attempts>2</max_attempts>
      <on_parse_failure>retry_with_format_reminder</on_parse_failure>
    </retry>
  </execution>

  <!-- ═══════════════════════════════════════════
       8. CHILDREN
       Subtasks this task can spawn after a successful run
  ═══════════════════════════════════════════ -->
  <children>
    <child
      task_id="signal_aggregator"
      trigger="on_success"
      condition="composite_score >= 0.75"
      pass_fields="ticker, sentiment_score, forward_guidance, management_tone">
      <!-- signal_aggregator collects today's runs and produces a daily digest -->
    </child>
    <child
      task_id="alert_formatter"
      trigger="on_success"
      condition="composite_score >= 0.80 AND sentiment_score >= 0.6"
      pass_fields="all">
      <!-- alert_formatter sends a push notification to Chris -->
    </child>
  </children>

  <!-- ═══════════════════════════════════════════
       9. EVOLUTION
       Rules for how this task improves itself
  ═══════════════════════════════════════════ -->
  <evolution>
    <enabled>true</enabled>
    <cycle>weekly</cycle>                      <!-- how often evolution runs -->
    <trigger_condition>
      rolling_7d_composite_avg &lt; 0.70      <!-- only evolve if performance is poor -->
      OR runs_since_last_evolution &gt;= 20   <!-- or we have enough new data -->
    </trigger_condition>
    <strategy>dspy_prompt_optimization</strategy>
    <mutation_targets>
      <target>prompt/user</target>            <!-- evolve the user prompt -->
      <target>context/input[@id='transcript']/query</target>  <!-- evolve search query -->
    </mutation_targets>
    <constraints>
      <must_preserve>output JSON schema</must_preserve>  <!-- output format must not change -->
      <must_preserve>system prompt</must_preserve>
      <max_prompt_length_chars>3000</max_prompt_length_chars>
    </constraints>
    <eval_set>
      <source>results_store</source>
      <filter>composite_score IS NOT NULL</filter>
      <holdout_pct>20</holdout_pct>           <!-- 20% held out; never used for training -->
      <min_samples>10</min_samples>           <!-- don't evolve if fewer than 10 runs exist -->
    </eval_set>
  </evolution>

  <!-- ═══════════════════════════════════════════
       10. ALERTS
       What gets surfaced to you and how
  ═══════════════════════════════════════════ -->
  <alerts>
    <channel>pushover</channel>              <!-- or: email | slack | webhook | ntfy -->
    <format>
      [{ticker}] {management_tone} | Sentiment: {sentiment_score} | {forward_guidance} guidance
      {summary}
      Score: {composite_score} | Model: {model_used} | Cost: ${run_cost}
    </format>
    <digest>
      <!-- If no individual alert fires, send a daily digest at 9am anyway -->
      <enabled>true</enabled>
      <time>09:00</time>
      <min_runs>3</min_runs>
    </digest>
  </alerts>

</task>
```

---

## Minimal Task (stripped down for simple jobs)

```xml
<task id="tech_news_digest" version="1" domain="research" status="active">
  <identity>
    <name>Daily Tech News Digest</name>
    <description>Summarize top 5 AI and networking developments from the last 24h.</description>
  </identity>
  <goal>
    <statement>Surface 3-5 non-obvious developments worth reading in under 2 minutes.</statement>
    <success_criteria>
      <criterion id="novelty" weight="0.5">Items are not things I already know about.</criterion>
      <criterion id="relevance" weight="0.5">Items relate to AI infrastructure, networking, or local LLMs.</criterion>
    </success_criteria>
  </goal>
  <measurement>
    <method>judge_llm</method>
    <judge_model>claude-haiku-4-5</judge_model>
    <thresholds>
      <alert_above>0.70</alert_above>
      <evolve_below>0.50</evolve_below>
    </thresholds>
  </measurement>
  <schedule>
    <cron>0 7 * * *</cron>
    <timezone>America/Chicago</timezone>
  </schedule>
  <context>
    <input id="news" required="true">
      <source>web_search</source>
      <query>AI infrastructure local LLM networking news last 24 hours</query>
      <max_chars>5000</max_chars>
    </input>
  </context>
  <prompt version="1">
    <system>You are a senior engineer who curates a daily briefing. Be terse. No fluff.</system>
    <user>
      Based on the following news, pick the 3-5 most interesting developments
      for an engineer focused on AI infrastructure and networking. Skip anything
      obvious or widely covered. Return JSON:
      {{"items": [{{"headline": str, "why_interesting": str, "source": str}}]}}

      NEWS:
      {news}
    </user>
  </prompt>
  <execution>
    <budget><max_cost_usd>0.02</max_cost_usd></budget>
    <routing>
      <provider priority="1" model="llama-3.1-70b">groq</provider>
      <provider priority="2" model="qwen3:30b">ollama</provider>
    </routing>
  </execution>
  <evolution>
    <enabled>true</enabled>
    <cycle>weekly</cycle>
    <mutation_targets>
      <target>prompt/user</target>
      <target>context/input[@id='news']/query</target>
    </mutation_targets>
  </evolution>
  <alerts>
    <channel>pushover</channel>
    <format>📰 Daily digest: {item_count} items worth reading</format>
  </alerts>
</task>
```

---

## Element Reference

| Element | Required | Description |
|---|---|---|
| `task@id` | ✅ | Stable identifier, never changes across versions |
| `task@version` | ✅ | Integer, incremented by evolution loop |
| `task@parent_version` | — | Which version this evolved from |
| `identity` | ✅ | Name, description, tags |
| `goal/statement` | ✅ | Plain English desired outcome |
| `goal/success_criteria` | ✅ | Weighted criteria; weights must sum to 1.0 |
| `measurement` | ✅ | Judge model, rubric, thresholds, progress tracking |
| `schedule` | ✅ | Cron, timezone, timeout |
| `context` | — | Data inputs injected into prompt at runtime |
| `prompt` | ✅ | System + user prompt with `{placeholders}` |
| `execution` | ✅ | Budget, routing priority, retry logic |
| `children` | — | Subtasks to spawn on success/failure |
| `evolution` | — | Self-improvement rules and constraints |
| `alerts` | — | Notification channel and format string |

---

## Version History Convention

```
earnings_sentiment v1  →  created manually
earnings_sentiment v2  →  evolution loop improved search query
earnings_sentiment v3  →  evolution loop tightened user prompt (current)
```

Each version stored in DB with full XML snapshot, run history, and composite scores.
Evolution never overwrites — it appends a new version and sets the old one to `deprecated`.