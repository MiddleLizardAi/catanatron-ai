# CatanBook

Operational notes for the `MiddleLizardAi/catanatron-ai` fork. This file is the project entry point for future Codex sessions. It complements the official Catanatron docs; it does not replace them.

## Repository

- Workspace: `/Users/dmytrolitovskyi/PhpstormProjects/catanotron`
- Main working remote: `origin = git@github.com:MiddleLizardAi/catanatron-ai.git`
- Previous fork remote: `dedli8 = git@github.com:dedli8/catanatron-ai.git`
- Upstream remote: `upstream = https://github.com/bcollazo/catanatron.git`
- Upstream push is disabled.
- Keep `.idea/` untracked unless the user explicitly asks to commit IDE files.

## Local Runtime

Use Docker Compose as the default runtime. The host Python is too old for this package in the current setup; Catanatron requires Python `>=3.11`.

```bash
docker compose up
docker compose ps
docker compose down
```

Local services:

- UI: `http://localhost:3000`
- Flask API: `http://localhost:5001`
- Postgres: `localhost:5432`

Useful checks:

```bash
curl -I http://localhost:3000
curl -I http://localhost:5001
docker compose logs --tail=80 server react-ui
```

## Verification

Prefer running frontend commands inside the `react-ui` container because host `ui/node_modules` may be missing. Prefer running Python commands inside the `server` container because the host Python in the current local setup is `3.9.6`, while this package requires Python `>=3.11`.

```bash
docker compose exec -T react-ui npm run build
docker compose exec -T react-ui npm run test -- --run
docker compose exec -T server catanatron-play --help
docker compose exec -T server python -c "import catanatron; print('catanatron import ok')"
```

The current `server` image is built with `pip install -e .[web]`, not dev extras, so `pytest` is not available in a fresh container. For backend tests, either install dev deps into the running container or adjust the image:

```bash
docker compose exec -T server python -m pip install -e '.[web,dev]'
docker compose exec -T server python -m pytest tests/web/test_api.py tests/models/test_player.py -q
```

Known current test issue as of 2026-05-21: `docker compose exec -T react-ui npm run test -- --run` passes 48 tests and fails `ui/src/App.test.tsx` because the test still expects `At most one Human player`, while the current home page supports multiple humans and no longer renders that text.

Known backend test cleanup from code inspection: `tests/web/test_api.py::test_empty_post_does_not_advance_human_turn` still creates a one-player game, but `/api/games` now requires 2 to 4 players; `tests/models/test_player.py` uses `json` in webhook tests and should import it before those tests can run.

Useful live-service smoke checks:

```bash
curl -sS -I http://localhost:3000
curl -sS http://localhost:5001/api/stress-test >/tmp/catanotron-stress.json
docker compose ps
```

## Current Custom Changes

The first customization merged to `main` is PNG board tile artwork from `Dmi3yy/catanatronui`.

Merged commit:

```bash
073c0a9 Merge PNG board tile artwork
```

Relevant files:

- `ui/src/assets/tile_brick.png`
- `ui/src/assets/tile_desert.png`
- `ui/src/assets/tile_maritime.png`
- `ui/src/assets/tile_ore.png`
- `ui/src/assets/tile_sheep.png`
- `ui/src/assets/tile_wheat.png`
- `ui/src/assets/tile_wood.png`
- `ui/src/pages/Tile.tsx`

The PNG assets are intentionally committed even though they are larger than the previous SVGs. `vite build` warns that some chunks are larger than 500 kB.

As of 2026-05-21 the active feature branch is `feature/playable-multiplayer-codex`. The working tree contains uncommitted multiplayer, webhook-strategy, and UI visual changes. Future sessions must run `git status --short --branch` first and must not revert unrelated user work.

## UI Notes

Current upstream-derived UI supports:

- Map template selection: `BASE`, `MINI`, `TOURNAMENT`
- Points to win
- Card discard limit
- Friendly robber
- 2 to 4 players
- Existing player archetypes such as `HUMAN`, `RANDOM`, `CATANATRON`, `WEIGHTED_RANDOM`

Do not replace the current UI wholesale with `Dmi3yy/catanatronui`; that fork is visually useful but behind our current `main` feature set. Cherry-pick assets/components deliberately.

Current local UI also has in-progress multi-human support:

- `ui/src/pages/HomePage.tsx` creates games with player objects: `{ type, name, color }`.
- `ui/src/components/JoinLinks.tsx` shows per-human links when a game has more than one human.
- `ui/src/utils/localPlayer.ts` reads `?player=RED|BLUE|ORANGE|WHITE` and gates local actions client-side.
- `ui/src/pages/GameScreen.tsx` polls the latest state every 1500 ms for non-replay live games.
- `ui/src/pages/ZoomableBoard.tsx` and `ui/src/pages/ActionsToolbar.tsx` only expose actions when the local URL player matches `current_color`.
- `HomePage` does not yet expose `WEBHOOK` in the player dropdown. Create webhook games through API calls or `local/codex_adapter/create_three_player_game.py`.

Important: the current client-side `?player=` check is not security. The Flask API does not yet enforce player ownership or join tokens.

## Core Architecture

The Python game engine is still the source of truth.

- `catanatron/catanatron/game.py`: `Game` wraps `State`, owns `playable_actions`, calls player decisions in `play_tick()`, and applies actions through `execute()`.
- `catanatron/catanatron/state.py`: `State` stores turn pointers, player order, board, decks, resources, action records, and prompt flags.
- `catanatron/catanatron/models/actions.py`: legal move generation. Add new legal actions here before the UI or bots can see them.
- `catanatron/catanatron/apply_action.py`: state transitions for every `ActionType`.
- `catanatron/catanatron/models/enums.py`: `ActionPrompt`, `ActionType`, resources, development cards, and action tuple shape.
- `catanatron/catanatron/models/board.py`: settlements, roads, buildable nodes/edges, ports, longest road.
- `catanatron/catanatron/models/map.py`: `BASE`, `MINI`, and static `TOURNAMENT` maps. `build_map()` is the public map entry point.
- `catanatron/catanatron/json.py`: public JSON serialization and action decoding for the web API.

Turn state is driven by `ActionPrompt`:

- `BUILD_INITIAL_SETTLEMENT`
- `BUILD_INITIAL_ROAD`
- `PLAY_TURN`
- `DISCARD`
- `MOVE_ROBBER`
- `DECIDE_TRADE`
- `DECIDE_ACCEPTEES`

`State.players` is still used even though its docstring says it is deprecated. `State.__init__` randomizes seating with `random.sample(players, len(players))`, so do not assume payload order equals turn order. Always use `gameState.colors.index(color)` / `player_key(state, color)`.

## Web API

Flask routes live in `catanatron/catanatron/web/api.py`.

Create game:

```http
POST /api/games
```

Accepted request forms:

```json
{
  "players": ["HUMAN", "CATANATRON"],
  "map_template": "BASE",
  "vps_to_win": 10,
  "discard_limit": 7,
  "friendly_robber": false
}
```

```json
{
  "players": [
    { "type": "HUMAN", "name": "Dmytro", "color": "RED" },
    { "type": "WEBHOOK", "name": "Codex", "color": "BLUE", "webhook": "http://host.docker.internal:8787/decide" },
    { "type": "CATANATRON", "name": "Catanatron", "color": "ORANGE" }
  ]
}
```

Validation currently enforced:

- `players`: list of 2 to 4 entries.
- `map_template`: `BASE`, `MINI`, or `TOURNAMENT`.
- `discard_limit`: integer 5 to 20.
- `vps_to_win`: integer 3 to 20.
- `friendly_robber`: boolean.

Supported object player types:

- `HUMAN`: stored as `ValueFunctionPlayer(color, is_bot=False)` for web play.
- `RANDOM`
- `WEIGHTED_RANDOM`
- `CATANATRON`: `AlphaBetaPlayer(color, 2, True)`.
- `WEBHOOK`: `WebHookPlayer(color, webhook_url, name=...)`.

Read state:

```http
GET /api/games/:game_id/states/:state_index
GET /api/games/:game_id/states/latest
```

Advance/submit action:

```http
POST /api/games/:game_id/actions
```

- Empty body advances one bot decision when `current_player().is_bot` is true.
- Empty body does not advance a human turn.
- Non-empty body is decoded by `action_from_json()` and executed if it matches current legal actions.
- If the game is already won, the endpoint returns the current game without advancing.

Other routes:

- `GET /api/stress-test`: creates and advances a four-Catanatron smoke game.
- `GET /api/games/:game_id/states/:state_index/mcts-analysis`: runs 100 MCTS simulations from the loaded state. This is useful for rough UI feedback, not a rigorous win-probability engine.

Persistence:

- `catanatron/catanatron/web/models.py` stores every persisted state in `game_states`.
- Each row includes `uuid`, `state_index`, JSON `state`, and pickled `Game`.
- There is currently no unique constraint on `(uuid, state_index)`.
- `latest` is selected by highest `state_index`.
- Webhook URL/name/player metadata live inside the pickled `Game`, not separate normalized DB columns.

## JSON Contracts

Public game JSON includes:

- `tiles`, `nodes`, `edges`, `adjacent_tiles`
- `player_state`
- `colors`
- `players`
- `bot_colors`
- `current_color`
- `current_prompt`
- `current_discard_count`
- `current_playable_actions`
- `longest_roads_by_player`
- `winning_color`
- `state_index`
- `action_records`

Action JSON uses arrays:

```json
["RED", "BUILD_SETTLEMENT", 12]
["RED", "BUILD_ROAD", [12, 17]]
["RED", "MOVE_ROBBER", [[0, 0, 0], "BLUE"]]
["RED", "PLAY_YEAR_OF_PLENTY", ["WHEAT", "ORE"]]
["RED", "MARITIME_TRADE", ["WOOD", "WOOD", "WOOD", null, "ORE"]]
["RED", "END_TURN", null]
```

Backend action decoding is in `catanatron/catanatron/json.py`. If a new action value has tuple-like structure, update both `action_from_json()` and `WebHookPlayer._action_from_json()`.

## Multiplayer Direction

Goal: allow four-party games such as:

- Dmytro as human
- Friend as human
- Dmytro Codex as bot
- Friend Codex as bot

Also support Codex-vs-Codex games.

Preferred architecture:

- Catanatron server is the game authority.
- Human players submit actions through the UI.
- Codex players connect as HTTP webhook bots.
- UI identifies the active human by join URL or token.

Current temporary join URL shape:

```text
/games/:gameId?player=RED
/games/:gameId?player=BLUE
```

Later, replace plain `player` with a tokenized link.

Current implementation status:

- Multi-human links exist with plain `?player=COLOR`.
- Local action gating exists in the UI.
- Live state polling exists.
- The API accepts 2 to 4 players and player-object payloads.
- No tokenized join links yet.
- No server-side player authorization yet.
- No stale-state precondition yet. Race handling is best-effort: the UI refreshes latest state if action submission fails.
- Domestic trade has backend state transitions but no real UI workflow. `OFFER_TRADE` is also not emitted by `generate_playable_actions()`, so webhook bots will not initiate domestic trades from `legal_actions`.
- Robber victim choice is incomplete in the UI: tile click chooses the first matching `MOVE_ROBBER` action for that coordinate, so a tile with multiple possible victims needs a victim selector.

## Webhook Bots

The backend player type already exists: `catanatron/catanatron/models/player.py::WebHookPlayer`.

`WEBHOOK` create-game payload:

```json
{
  "players": [
    { "type": "HUMAN", "name": "Dmytro", "color": "RED" },
    { "type": "HUMAN", "name": "Friend", "color": "BLUE" },
    {
      "type": "WEBHOOK",
      "name": "Dmytro Codex",
      "color": "ORANGE",
      "webhook": "https://example.com/dmytro-codex/decide"
    },
    {
      "type": "WEBHOOK",
      "name": "Friend Codex",
      "color": "WHITE",
      "webhook": "https://example.com/friend-codex/decide"
    }
  ]
}
```

Preferred local adapter command when the Catanatron server runs in Docker:

```bash
python3 -u local/codex_adapter/codex_webhook.py \
  --host 0.0.0.0 \
  --port 8787 \
  --strategy local/codex_adapter/strategy.json
```

Use `http://host.docker.internal:8787/decide` for the `WEBHOOK` player URL.

Fast local game with one human, one Codex webhook, and one Catanatron:

```bash
python3 local/codex_adapter/create_three_player_game.py
```

The script checks the adapter and prints a playable URL like:

```text
http://localhost:3000/games/<game-id>?player=RED
```

Webhook request shape:

```json
{
  "game_id": "...",
  "color": "ORANGE",
  "name": "Local Codex",
  "state_index": 0,
  "current_prompt": "BUILD_INITIAL_SETTLEMENT",
  "legal_actions": [
    {
      "id": "0:ROLL:null",
      "index": 0,
      "type": "ROLL",
      "value": null,
      "action": ["ORANGE", "ROLL", null]
    }
  ],
  "playable_actions": [["ORANGE", "ROLL", null]],
  "strategy": {
    "objective": "Choose exactly one id from legal_actions. Do not invent actions.",
    "response_schema": {
      "action_id": "string from legal_actions[].id",
      "reason": "short strategy reason"
    },
    "public_leader": {},
    "self": {},
    "players": []
  },
  "state": {}
}
```

Preferred webhook response:

```json
{
  "action_id": "0:ROLL:null",
  "action_index": 0,
  "reason": "best settlement production"
}
```

`action_index` is kept for backward compatibility. `action_id` is safer because it includes index, action type, and canonical value.

Local test adapter:

```bash
python3 local/codex_adapter/random_webhook.py --host 0.0.0.0 --port 8787
```

Local heuristic Codex adapter:

```bash
python3 local/codex_adapter/codex_webhook.py --host 0.0.0.0 --port 8787
```

Webhook failure behavior:

- `WebHookPlayer.decide()` uses `urllib.request` with a default 30 second timeout.
- Any exception prints a warning and falls back to `playable_actions[0]`.
- This is good for not blocking games, but bad for training quality. Capture failures in logs when evaluating strategies.

Privacy warning:

- `strategy.players` hides opponent actual VP/resources/dev-card details.
- `state.player_state` currently contains the full raw player state for every player, including hidden resources and development cards.
- Therefore webhook play is currently an open-information/training mode. For fair human-vs-Codex games, add server-side private-state filtering before sending webhook payloads or public API responses.

Payload size warning:

- `WebHookPlayer._state_to_json()` currently sends all `action_records`.
- Long games can make webhook payloads large. If latency becomes an issue, add a compact public replay summary plus a bounded recent-action window.

## Codex Strategy Adapter

Local adapter files:

- `local/codex_adapter/random_webhook.py`: smoke-test bot.
- `local/codex_adapter/codex_webhook.py`: heuristic strategy adapter.
- `local/codex_adapter/strategy.json`: tunable scoring profile.
- `local/codex_adapter/create_three_player_game.py`: quick local game creator.
- `local/codex_adapter/run_strategy_tournament.py`: experimental self-play/training loop that mutates `strategy.json` and writes reports.

`codex_webhook.py` currently prioritizes:

- Roll immediately.
- Discard excess while preserving city materials.
- Move robber to target leader/strong production while avoiding self-blocking.
- Score settlement/city nodes by dice production, resource coverage, ports, and human pressure.
- Build roads only when they point toward near-term settlement/port targets or endgame Longest Road.
- Penalize expansion roads whose target settlement node is contested by an opponent that can reach/build it sooner.
- Use maritime trades to complete settlement/city/development plans, especially under discard pressure.
- Buy development cards under caps so it does not spam unplayed tactical cards.
- Treat 8+ actual VP as endgame and bias toward shortest path to 10 VP.
- Use Catanatron's own depth-2 `AlphaBetaPlayer` as the primary decision source. `WebHookPlayer._strategy_to_json()` sends `strategy.catanatron_search.recommended_action` plus scored candidates; the adapter chooses that action first when `catanatron_search.enabled` is true. Local heuristic scores are now diagnostics/fallback/optional guardrails, not the main live policy.
- Use Catanatron's one-ply `base_fn` teacher only as a fallback correction when full search is unavailable.

Current checked strategies:

- Previous high-win strategy, `balanced_base_catan_v5_catanatron_teacher`: 50-game three-player eval against weighted human proxy and Catanatron, Codex `26/50` wins, `52%`, avg VP `8.04`, avg roads `9.08`, fallback decisions `0`. Report: `local/codex_adapter/reports/evaluations/three_player_eval_20260521_163315.md`.
- Guardrailed heuristic strategy, `balanced_base_catan_v6_contested_expansion`: 50-game three-player eval against weighted human proxy and Catanatron, Codex `20/50` wins, `40%`, avg VP `7.8`, avg roads `5.4`, avg settlements `1.28`, avg cities `2.86`, fallback decisions `0`. Report: `local/codex_adapter/reports/evaluations/three_player_eval_20260522_052208.md`.
- Previous search baseline, `search_first_catan_v7_alpha_beta_baseline`: 50-game three-player eval against weighted human proxy and Catanatron, Codex `20/50` wins, `40%`, avg VP `7.28`, avg roads `10.36`, avg settlements `2.68`, avg cities `1.84`, fallback decisions `0`, all `4246` Codex decisions from `catanatron search primary`. Report: `local/codex_adapter/reports/evaluations/three_player_eval_20260522_072112.md`.
- Interpretation: v7 proves the webhook/action-id path is correct and can exactly use Catanatron's search recommendation, but Catanatron's default value/search still overbuilds roads in this BLUE-vs-ORANGE seated format and does not beat the ORANGE Catanatron baseline. Next tuning should modify the value/search policy itself under fixed-seed evaluation, not add broad post-search road bans that block useful tempo.
- Previous live experiment, `search_first_catan_v8_committed_road_override`: starts from v7 and adds a narrow road override when AlphaBeta abandons a committed route and Codex road scoring sees a much stronger continuation to a 3-hex settlement target. Regression checked on live game `fafd1e2a-28f9-41aa-b5b3-103ee31433b5`: state `113` still keeps AlphaBeta road `[1,6]`; state `140` overrides AlphaBeta road `[7,24]` to `[0,1]`.
- Previous live patch, `search_first_catan_v9_safe_robber`: keeps v8 road behavior and prevents AlphaBeta from overriding local robber scoring. Robber selection filters out self-blocking tiles when an opponent-only alternative exists. Regression checked on live game `462985ea-458b-4315-a376-4c9ad7978293`: state `20` changes from AlphaBeta `MOVE_ROBBER [[-1,0,1], "ORANGE"]` on a `6 ORE` tile containing `ORANGE+BLUE` to safe local `MOVE_ROBBER [[1,-2,1], "RED"]`.
- High-win but road-heavy patch, `search_first_catan_v10_tempo_defense`: added opening-road, city-target, anti-stall maritime trade, army-defense, and leader-threat robber overrides. 50-game eval against weighted human proxy and Catanatron: Codex `32/50` wins, `64%`, avg VP `8.54`, avg roads `10.6`, avg settlements `2.54`, avg cities `2.3`, avg dev cards bought `0.62`, fallback decisions `0`. Report: `local/codex_adapter/reports/evaluations/three_player_eval_20260522_125955.md`. Interpretation: strong win-rate, but still too road-heavy for live human review; 18/50 games reached 12+ Codex roads.
- Current live profile, `search_first_catan_v12_guarded_expansion`: keeps the v10 tempo/defense overrides and enables search guardrails. Expansion roads are allowed, but dead roads and road-debt roads are vetoed when they do not leave Codex close to a settlement. 50-game eval against weighted human proxy and Catanatron: Codex `27/50` wins, `54%`, avg VP `8.68`, avg roads `6.6`, avg settlements `1.86`, avg cities `2.84`, avg dev cards bought `1.82`, fallback decisions `0`. Report: `local/codex_adapter/reports/evaluations/three_player_eval_20260522_135109.md`. Interpretation: lower raw win-rate than v10, but much closer to the desired live style; only `1/50` games reached 12+ Codex roads and no loss had 12+ Codex roads.

Training/report workflow:

```bash
python3 local/codex_adapter/run_strategy_tournament.py --games 10
```

Important: the tournament script mutates `local/codex_adapter/strategy.json`. Review the diff before committing. Reports go to `local/codex_adapter/reports/`.

`local/codex_adapter/evaluate_three_player_strategy.py` relaunches itself with `PYTHONHASHSEED=0` when the hash seed is unset, so fixed seed lists are reproducible across Python processes. Keep that behavior for strategy A/B tests.

Missing for real Codex learning:

- Decision traces are not persisted. The webhook `reason` is ignored by the server after choosing the action.
- There is no prompt/model-output log for later supervised fine-tuning or strategy review.
- Games are not reproducible from API payload alone because `/api/games` does not expose `seed` or `number_placement`.
- Public/private observation modes are not separated.
- No evaluation harness compares Codex against baselines over fixed seeds with confidence intervals.

Recommended next learning infrastructure:

1. Add optional `decision_log` persistence for webhook turns: game id, state index, color, prompt, legal actions, selected action id, reason, latency, adapter/model name, and error if any.
2. Add API support for `seed` and `number_placement`.
3. Add a fair-observation serializer that hides opponent hands/dev-card identities while preserving public counts.
4. Add fixed-seed evaluation scripts: Codex vs Random, Weighted Random, Catanatron, and Codex mirrors.
5. Keep strategy changes data-backed: report win rate, average VP, average game length, cities/settlements/roads, dev-card usage, maritime trades, and discard losses.

## Extension Guide

When adding Catan expansions or custom rules, touch the smallest complete slice.

New action or rule phase:

1. Add enum/value shape in `catanatron/catanatron/models/enums.py`.
2. Generate legal actions in `catanatron/catanatron/models/actions.py`.
3. Apply state changes in `catanatron/catanatron/apply_action.py`.
4. Store any durable fields in `catanatron/catanatron/state.py` and `State.copy()`.
5. Serialize/decode in `catanatron/catanatron/json.py`.
6. Add frontend types in `ui/src/utils/api.types.ts`.
7. Add UI controls in `ActionsToolbar`, `ZoomableBoard`, `Board`, or a focused component.
8. Teach webhook adapters to score/ignore the action safely.
9. Add tests in `tests/models`, `tests/web`, and focused UI utility/component tests.

New board/map content:

1. Add map/template data in `catanatron/catanatron/models/map.py` or a dedicated module if it grows.
2. Verify node/edge ids, port nodes, adjacent tile caches, and robber initial coordinate.
3. Update `build_map()` and API validation.
4. Update UI tile rendering/assets if new tile/resource types exist.
5. Update gym action space if topology or action targets change.

New resource/development card:

1. Update constants in `enums.py` and deck/cost logic in `models/decks.py`.
2. Update `PLAYER_INITIAL_STATE` in `state.py`.
3. Update action generation/apply logic.
4. Update `ResourceCards`, TypeScript card unions, prompt text, and adapter scoring.

Private information rule:

- Do not rely on the UI to hide secrets. Filter on the server before returning state to humans or webhook bots.
- Current `player_state` is convenient for debugging but not a fair multiplayer contract.

## Known Gaps / Next Milestones

Highest-impact product gaps:

1. Server-side join tokens and action authorization.
2. Stale-action protection: require client to submit the state index it acted on.
3. Fair public/private state serializers.
4. WEBHOOK option in the new-game UI, including URL/name fields.
5. Domestic trade UI and webhook initiation support.
6. Robber victim selector when multiple victims touch the selected tile.
7. Decision logging for Codex training.
8. API support for game seed and number placement.
9. Backend dev/test dependencies in Docker or a dedicated test image.
10. Fix `ui/src/App.test.tsx` to match the new multi-human home page.

## Work Plan

1. Keep Git flow clean: one feature branch per task, push to `origin`.
2. Stabilize the current multi-human and webhook branch.
3. Add server-side join identity and stale-state checks.
4. Add fair state filtering for humans and Codex bots.
5. Add decision logging and fixed-seed evaluation.
6. Finish UI visual improvements from the friend's repo only where they fit the current codebase.
7. Deploy or expose the central server for the friend to join.

## Git Commands

Create a feature branch:

```bash
git checkout main
git pull --ff-only origin main
git checkout -b feature/name
```

Push a feature branch:

```bash
git push -u origin feature/name
```

Merge to main when the user asks for direct merge:

```bash
git checkout main
git merge --no-ff feature/name -m "Merge feature name"
git push origin main
```

## External References

- Official docs: `https://docs.catanatron.com/`
- Upstream repo: `https://github.com/bcollazo/catanatron`
- Friend UI repo: `https://github.com/Dmi3yy/catanatronui`
- Friend backend fork: `https://github.com/Dmi3yy/catanatron/tree/caprover`
