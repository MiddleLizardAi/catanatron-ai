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

Prefer running frontend commands inside the `react-ui` container because host `ui/node_modules` may be missing.

```bash
docker compose exec -T react-ui npm run build
docker compose exec -T react-ui npm run test -- --run
docker compose exec -T server catanatron-play --help
docker compose exec -T server python -c "import catanatron; print('catanatron import ok')"
```

Known current test issue: `ui/src/App.test.tsx` expects `At most one Human player`, but that text is not present on the current home page. This is unrelated to PNG tile artwork.

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

## UI Notes

Current upstream-derived UI supports:

- Map template selection: `BASE`, `MINI`, `TOURNAMENT`
- Points to win
- Card discard limit
- Friendly robber
- 2 to 4 players
- Existing player archetypes such as `HUMAN`, `RANDOM`, `CATANATRON`, `WEIGHTED_RANDOM`

Do not replace the current UI wholesale with `Dmi3yy/catanatronui`; that fork is visually useful but behind our current `main` feature set. Cherry-pick assets/components deliberately.

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

Planned join URL shape:

```text
/games/:gameId?player=RED
/games/:gameId?player=BLUE
```

Later, replace plain `player` with a tokenized link.

## Webhook Bot Plan

Add a backend player type that calls an external URL when it is that player's turn.

Target create-game payload shape:

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

Target webhook request:

```json
{
  "game_id": "...",
  "color": "ORANGE",
  "state": {},
  "playable_actions": []
}
```

Target webhook response:

```json
{
  "action": ["ORANGE", "BUILD_ROAD", [12, 18]]
}
```

Start with a simple local/test webhook bot before connecting any OpenAI/Codex logic.

## Work Plan

1. Keep Git flow clean: one feature branch per task, push to `origin`.
2. Finish UI visual improvements from the friend's repo only where they fit the current codebase.
3. Add multi-human game support in UI and API.
4. Add player identity/join links.
5. Add `WEBHOOK` player support.
6. Add a minimal bot adapter service.
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
