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

The heuristic adapter uses the webhook `state` summary to prioritize:

- best-production settlement spots;
- roads toward stronger adjacent nodes;
- robber moves against the public leader or strongest production tile;
- rolling immediately;
- building before buying development cards;
- ending turn only after higher-priority actions are unavailable.
