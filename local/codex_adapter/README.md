# Local Codex Adapter

Webhook adapters for local Catanatron testing.

Random smoke-test adapter:

```bash
python3 local/codex_adapter/random_webhook.py --port 8787
```

Heuristic Codex adapter:

```bash
python3 local/codex_adapter/codex_webhook.py --port 8787
```

With an explicit strategy profile:

```bash
python3 local/codex_adapter/codex_webhook.py \
  --port 8787 \
  --strategy local/codex_adapter/strategy.json
```

With decision diagnostics:

```bash
python3 -u local/codex_adapter/codex_webhook.py \
  --host 0.0.0.0 \
  --port 8787 \
  --strategy local/codex_adapter/strategy.json \
  --decision-log local/codex_adapter/reports/live_decisions.jsonl
```

The decision log is JSONL: one record per Codex decision. Each record includes
the prompt, legal action counts, selected action, reason, public player summary,
self hand/pieces, and top scored candidates by action type.

Use this player payload when creating a game:

```json
{
  "type": "WEBHOOK",
  "name": "Local Codex",
  "color": "ORANGE",
  "webhook": "http://host.docker.internal:8787/decide"
}
```

The server sends both the legacy `playable_actions` list and the preferred
structured `legal_actions` list:

```json
{
  "legal_actions": [
    {
      "id": "0:ROLL:null",
      "index": 0,
      "type": "ROLL",
      "value": null,
      "action": ["ORANGE", "ROLL", null]
    }
  ],
  "strategy": {
    "objective": "Choose exactly one id from legal_actions. Do not invent actions.",
    "self": {},
    "players": []
  }
}
```

Both adapters return an `action_id` from `legal_actions`. `action_index` remains
in the response for backward compatibility:

```json
{ "action_id": "0:ROLL:null", "action_index": 0, "reason": "..." }
```

The Catanatron server container calls the adapter through `host.docker.internal`.

Fast local three-player game creation:

```bash
python3 local/codex_adapter/create_three_player_game.py
```

Default players:

- `RED`: `Dmytro` human
- `BLUE`: `Codex` webhook bot
- `ORANGE`: `Catanatron`

The script prints a ready-to-open URL like:

```text
http://localhost:3000/games/<game-id>?player=RED
```

The heuristic adapter uses the webhook `state` summary to prioritize:

- best-production settlement spots;
- roads toward stronger adjacent nodes only when the route has a near-term settlement or endgame Longest Road plan;
- contested expansion checks, so a road target is penalized when an opponent can claim the same settlement node first;
- robber moves against the public leader or strongest production tile;
- rolling immediately;
- building before buying development cards;
- ending turn only after higher-priority actions are unavailable.

Tune `strategy.json` while testing games. Useful knobs:

- `production_weights`: value of dice numbers, usually 6/8 highest.
- `resource_priority`: resource bias; baseline favors wheat, ore, then sheep.
- `scoring.resource_diversity_bonus`: how much to value mixed production.
- `scoring.ore_wheat_sheep_combo_bonus`: extra startup/city-engine bonus.
- `road.*`: route lookahead, road debt, and minimum score gates for expansion roads.
- `settlement_race.*`: penalties for road targets that opponents can reach or build sooner.
- `catanatron_search.enabled`: use Catanatron depth-2 AlphaBeta as the primary policy.
- `catanatron_search.respect_guardrails`: post-search gates that reject weak roads/trades before accepting AlphaBeta; disable only for pure search baselines.
- `catanatron_teacher.respect_strategy_gates`: keep teacher road/trade overrides behind local strategy gates.
- `robber.public_leader_bonus`: how aggressively to target the visible leader.
- `action_priority`: broad fallback ordering when no specialized scorer applies.

Latest checked profiles:

- `search_first_catan_v7_alpha_beta_baseline`
- 50-game three-player eval: Codex `20/50` wins, avg VP `7.28`, avg roads `10.36`, fallback decisions `0`; all `4246` decisions used `catanatron search primary`.
- Report: `local/codex_adapter/reports/evaluations/three_player_eval_20260522_072112.md`
- Interpretation: pure Catanatron AlphaBeta fixes webhook correctness but not strength. The next improvement should change the search/value policy directly instead of relying on broad post-search road bans.
- `search_first_catan_v10_tempo_defense`: added opening-road, city-target, anti-stall maritime trade, army-defense, and leader-threat robber overrides. 50-game eval: Codex `32/50` wins, avg VP `8.54`, avg roads `10.6`, avg dev cards bought `0.62`, fallback decisions `0`. Report: `local/codex_adapter/reports/evaluations/three_player_eval_20260522_125955.md`. Stronger raw win-rate, but too road-heavy for live play review.
- Current live patch, `search_first_catan_v12_guarded_expansion`: keeps v10 overrides, enables post-search guardrails, allows roads toward real expansion, and vetoes dead/road-debt roads. 50-game eval: Codex `27/50` wins, avg VP `8.68`, avg roads `6.6`, avg cities `2.84`, avg dev cards bought `1.82`, fallback decisions `0`. Report: `local/codex_adapter/reports/evaluations/three_player_eval_20260522_135109.md`. This is the preferred live profile because it removes most road spam while staying above the v7/v6 win-rate baselines.

Three-player strategy evaluation:

```bash
docker compose exec -T server python \
  local/codex_adapter/evaluate_three_player_strategy.py \
  --games 20 \
  --human-proxy weighted
```

The evaluator relaunches itself with `PYTHONHASHSEED=0` when unset, so repeated fixed-seed runs are comparable across Python processes.

Default evaluation players:

- `RED`: human proxy (`weighted`, `random`, or `catanatron`)
- `BLUE`: direct Codex strategy using `strategy.json`
- `ORANGE`: Catanatron

The evaluator writes a markdown report, JSON summary, and full decision JSONL
under `local/codex_adapter/reports/evaluations/` by default.
