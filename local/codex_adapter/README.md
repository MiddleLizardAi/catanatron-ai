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

The adapter currently picks a random playable action and returns:
Both adapters return:

```json
{ "action_index": 0, "reason": "..." }
```

The Catanatron server container calls the adapter through `host.docker.internal`.

The heuristic adapter uses the webhook `state` summary to prioritize:

- best-production settlement spots;
- roads toward stronger adjacent nodes;
- rolling immediately;
- building before buying development cards;
- ending turn only after higher-priority actions are unavailable.
