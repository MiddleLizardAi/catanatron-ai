# Local Codex Adapter

Minimal webhook adapter for local Catanatron testing.

Run:

```bash
python3 local/codex_adapter/random_webhook.py --port 8787
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

```json
{ "action_index": 0 }
```

The Catanatron server container calls the adapter through `host.docker.internal`.
