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


## Workflow totals in 0.2.0

A configured workflow links all its runs and snapshots turn, wall-time and optional USD-estimate limits. Resuming uses the remaining total rather than resetting it; individual requests also retain the limits in Connections. Workflow review permits an explicit, noted change to the total budget. SDK limits can be exceeded by the final model step and do not cap or reveal Max allowance. If a previous result has incomplete usage, the total shown is a lower bound. Starting with 0.2.4, Workflow review provides an acknowledgement action that permits continuation while retaining this gap. Clara does not invent a dollar cost for a crashed request.


## Turn limits and resuming in 0.2.3

Connections & settings accepts any positive whole-number turn limit, including 500, or an explicit No turn limit selection. Workflow review exposes the same choice for total model turns across all runs in that conversation. Both settings must be unlimited to remove both caps. A finite applicable cap still applies, and already-used workflow turns are subtracted from a finite total. Changing the request default does not silently rewrite existing workflows.

The stored/API representation of No turn limit is `max_turns: null`; zero is invalid. With no applicable turn cap, the SDK receives `max_turns=None` and its CLI transport omits `--max-turns`. Clara continues recording actual turns, tokens, cost estimates and checkpoints. Request/workflow time and cost limits, unknown-usage checks, cancellation and provider/account restrictions are independent and remain enforced.

## Interrupted usage review in 0.2.4

In the paused conversation, select **Workflow review → Allow continuation with incomplete usage**. The review records the exact interrupted-job usage reports and a note in the local event history. It does not edit those reports or zero missing values. A different interruption or a changed report needs another review; stale browser submissions are rejected. The action requires an authenticated, idle dashboard and is not exposed as a model tool.

After review, known usage still counts against workflow limits. Because unknown usage cannot be subtracted accurately, aggregate turn and cost limits cannot guarantee a true total for this workflow; the displayed totals are lower bounds. Per-request limits and all known exhausted budgets still apply. Review does not increase a budget, mark any output verified or waive uncertain external-operation checks. Continue in the same conversation so the saved session and checkpoints remain available.


## Waiting time and reasoning effort in 0.2.5

New task cards/CSV split elapsed time into user-input waiting and remaining working time. Questions/approvals count as waiting until answered or execution ends, with overlapping waits counted once. Working time includes inference, tools, network and other processing. Older reports without these fields show their original elapsed time. Existing task/workflow time limits continue to use wall time.

Reasoning effort is configurable independently of the model. Balanced is medium and the default for an unset preference. Compare both speed and verified outcomes when changing effort; lower effort is not a guarantee of lower total cost if it introduces retries.

## Estimating Max capacity

As checked on 12 September 2026, the [Max 20x plan](https://support.claude.com/en/articles/11049762-choose-a-claude-plan) costs $200/month and is described relative to Pro capacity, not as a fixed published token balance. [Usage depends on model, conversation size, complexity and features](https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work). [The current SDK update](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) says the announced separate SDK-credit change is paused; its old credit table is not an active $200 API allowance. Do not divide the subscription fee by Clara's API estimate to predict closeouts.

For a practical estimate, record the provider's actual remaining-usage indicators before and after several comparable, reviewed test runs, with the same model/effort and no unrelated account activity. For each displayed limit window, divide remaining percentage points by typical percentage points consumed per run. Treat the lowest remaining-run estimate as the constraint, and account for resets. This is an empirical estimate, not a guaranteed quota; rounding, cache state, retries, other account activity and provider changes affect it. [Claude Code /usage](https://code.claude.com/docs/en/costs) reports plan usage; API dollar estimates answer a different question.
