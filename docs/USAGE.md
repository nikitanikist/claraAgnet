# Task usage and closeout estimates

Each submitted chat task produces a **Task usage** card beneath its response and files. It shows total reported tokens, SDK API cost estimate in USD, elapsed time and model turns. Expand **Token breakdown & models** for uncached input, output, cache-read and cache-write tokens. A blended estimate per 1,000 tokens is an average for that particular run, including any request fees, not a fixed token price.

For a closeout, start a new conversation and keep that closeout's follow-ups there. **Conversation totals** sum its finished tasks; **Download usage CSV** exports individual task rows for analysis. An unrelated test in that conversation also contributes to the total. Run a complete representative closeout before describing its cost; earlier file and messaging tests do not establish closeout usage.

Old conversations show the usage already recorded, without another model call. No missing historical data is reconstructed or invented. Each new task uses a fresh SDK client and one query; its result is recorded once. Per-model totals are preferred so helper-model usage is included when the SDK supplies it. Older records may cover only the main loop. Cache counts include context reused across steps; the total is not the number of unique words/files the user supplied.

## Estimates, missing data and Max

The SDK reports estimated dollar costs using its price table, and different token categories have different prices. These estimates can differ from billing. Clara does not calculate your actual subscription charge or remaining Max allowance. See Anthropic's [cost-tracking documentation](https://code.claude.com/docs/en/agent-sdk/cost-tracking), checked 11 September 2026.

Anthropic's [current subscription update](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) says the proposed usage changes are paused and SDK usage continues drawing from subscription limits. Account usage-credit settings remain with the provider. Sharing this report gives the client an operational estimate, not an invoice.

Stopped or failed runs can consume tokens. If a final SDK report is missing or zeroed after a crash, Clara preserves available deduplicated input/cache counts and labels the report incomplete. Output and cost remain unreported. Conversation totals identify how many tasks have known totals; an unreported value is not zero. CSV cells for unavailable numbers are blank.

## Limit a task

In **Connections & settings**, set **Task estimate limit (USD)** to a positive value, or leave it blank. Clara passes that value to the SDK's `max_budget_usd` option. Existing turn and time limits remain active. The SDK may stop after a model step crosses the estimate limit, so it is not an exact spending ceiling. It cannot guarantee that the account's Max limit will not be reached.

The default remains no estimate limit, preserving existing settings. A budget-limited task may be incomplete; inspect its result and completed actions before retrying. See the official [SDK option reference](https://code.claude.com/docs/en/agent-sdk/python#claudeagentoptions).

## Validation

Tests cover all-model counts without double counting, independent follow-up totals, duplicate assistant messages, missing and zero usage, partial/crash reports, budget-crossing results, unknown model prices, authenticated CSV export and budget validation. A real Chrome/API test checks saved and live usage cards, conversation totals, CSV downloads, settings and narrow-screen layout using synthetic data. These tests do not submit model requests or measure a real closeout.
