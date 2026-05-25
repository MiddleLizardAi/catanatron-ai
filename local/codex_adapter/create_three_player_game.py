#!/usr/bin/env python3
import argparse
import json
import sys
import urllib.error
import urllib.request
import webbrowser


DEFAULT_API_URL = "http://localhost:5001"
DEFAULT_UI_URL = "http://localhost:3000"
DEFAULT_WEBHOOK_URL = "http://host.docker.internal:8787/decide"
DEFAULT_ADAPTER_HEALTH_URL = "http://127.0.0.1:8787/decide"


def check_adapter(url):
    try:
        urllib.request.urlopen(url, timeout=2)
    except urllib.error.HTTPError as error:
        if error.code == 501:
            return
        raise RuntimeError(f"adapter responded with HTTP {error.code}") from error
    except Exception as error:
        raise RuntimeError(
            "Codex adapter is not reachable. Start it with:\n"
            "python3 -u local/codex_adapter/codex_webhook.py "
            "--host 0.0.0.0 --port 8787 "
            "--strategy local/codex_adapter/strategy.json"
        ) from error


def create_game(api_url, webhook_url, options):
    payload = {
        "players": [
            {
                "type": "HUMAN",
                "name": options.human_name,
                "color": options.human_color,
            },
            {
                "type": "WEBHOOK",
                "name": options.codex_name,
                "color": options.codex_color,
                "webhook": webhook_url,
            },
            {
                "type": "CATANATRON",
                "name": options.catanatron_name,
                "color": options.catanatron_color,
            },
        ],
        "map_template": options.map_template,
        "vps_to_win": options.vps_to_win,
        "discard_limit": options.discard_limit,
        "friendly_robber": options.friendly_robber,
    }
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/api/games",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))["game_id"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create a three-player local Catanatron game: human + Codex + Catanatron."
    )
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--ui-url", default=DEFAULT_UI_URL)
    parser.add_argument("--webhook-url", default=DEFAULT_WEBHOOK_URL)
    parser.add_argument("--adapter-health-url", default=DEFAULT_ADAPTER_HEALTH_URL)
    parser.add_argument("--skip-adapter-check", action="store_true")
    parser.add_argument("--open", action="store_true", help="Open the game URL in the default browser.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--human-name", default="Dmytro")
    parser.add_argument("--codex-name", default="Codex")
    parser.add_argument("--catanatron-name", default="Catanatron")
    parser.add_argument("--human-color", default="RED")
    parser.add_argument("--codex-color", default="BLUE")
    parser.add_argument("--catanatron-color", default="ORANGE")
    parser.add_argument("--map-template", default="BASE")
    parser.add_argument("--vps-to-win", type=int, default=10)
    parser.add_argument("--discard-limit", type=int, default=7)
    parser.add_argument("--friendly-robber", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.skip_adapter_check:
        check_adapter(args.adapter_health_url)

    game_id = create_game(args.api_url, args.webhook_url, args)
    url = f"{args.ui_url.rstrip('/')}/games/{game_id}?player={args.human_color}"

    if args.open:
        webbrowser.open(url)

    output = {
        "game_id": game_id,
        "url": url,
        "players": [
            {"color": args.human_color, "name": args.human_name, "type": "HUMAN"},
            {"color": args.codex_color, "name": args.codex_name, "type": "WEBHOOK"},
            {
                "color": args.catanatron_color,
                "name": args.catanatron_name,
                "type": "CATANATRON",
            },
        ],
    }
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(url)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
