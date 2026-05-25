#!/usr/bin/env python3
import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path


API_URL = "http://localhost:5001"
WEBHOOK_URL = "http://host.docker.internal:8787/decide"
ROOT = Path(__file__).resolve().parents[2]
STRATEGY_PATH = ROOT / "local" / "codex_adapter" / "strategy.json"
REPORTS_DIR = ROOT / "local" / "codex_adapter" / "reports"
RESOURCES = ["WOOD", "BRICK", "SHEEP", "WHEAT", "ORE"]
DEVS = ["KNIGHT", "YEAR_OF_PLENTY", "MONOPOLY", "ROAD_BUILDING", "VICTORY_POINT"]


def request_json(method, path, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{API_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def load_strategy():
    return json.loads(STRATEGY_PATH.read_text(encoding="utf-8"))


def save_strategy(strategy):
    STRATEGY_PATH.write_text(
        json.dumps(strategy, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def start_adapter():
    return subprocess.Popen(
        [
            "python3",
            str(ROOT / "local" / "codex_adapter" / "codex_webhook.py"),
            "--host",
            "0.0.0.0",
            "--port",
            "8787",
            "--strategy",
            str(STRATEGY_PATH),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_adapter(process):
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def create_game():
    return request_json(
        "POST",
        "/api/games",
        {
            "players": [
                {
                    "type": "WEBHOOK",
                    "name": "Codex",
                    "color": "RED",
                    "webhook": WEBHOOK_URL,
                },
                {"type": "CATANATRON", "name": "Catanatron Blue", "color": "BLUE"},
                {
                    "type": "CATANATRON",
                    "name": "Catanatron Orange",
                    "color": "ORANGE",
                },
            ],
            "map_template": "BASE",
            "vps_to_win": 10,
            "discard_limit": 7,
            "friendly_robber": False,
        },
    )["game_id"]


def play_game(game_id, max_ticks=2400):
    state = request_json("GET", f"/api/games/{game_id}/states/latest")
    ticks = 0
    while not state.get("winning_color") and ticks < max_ticks:
        state = request_json("POST", f"/api/games/{game_id}/actions", {})
        ticks += 1
    if not state.get("winning_color"):
        raise RuntimeError(f"game {game_id} did not finish after {ticks} ticks")
    return state, ticks


def player_key_by_color(state):
    return {color: f"P{index}" for index, color in enumerate(state["colors"])}


def summarize_state(game_id, state, ticks):
    key_by_color = player_key_by_color(state)
    player_by_color = {player["color"]: player for player in state["players"]}
    stats = {}
    global_roll_histogram = {}

    for color in state["colors"]:
        stats[color] = {
            "name": player_by_color[color]["name"],
            "type": player_by_color[color]["type"],
            "actions": 0,
            "rolls": 0,
            "roll_total": 0,
            "roll_histogram": {},
            "builds": {"roads": 0, "settlements": 0, "cities": 0},
            "dev_cards_bought": 0,
            "dev_played": {
                "knight": 0,
                "monopoly": 0,
                "year_of_plenty": 0,
                "road_building": 0,
            },
            "maritime_trades": 0,
            "robber_moves": 0,
            "discards": 0,
            "end_turns": 0,
        }

    for action, result in state["action_records"]:
        color, action_type, value = action
        stat = stats[color]
        stat["actions"] += 1
        if action_type == "ROLL":
            dice = value if value else result
            total = sum(dice)
            stat["rolls"] += 1
            stat["roll_total"] += total
            stat["roll_histogram"][str(total)] = stat["roll_histogram"].get(str(total), 0) + 1
            global_roll_histogram[str(total)] = global_roll_histogram.get(str(total), 0) + 1
        elif action_type in {"BUILD_ROAD", "BUILD_INITIAL_ROAD"}:
            stat["builds"]["roads"] += 1
        elif action_type in {"BUILD_SETTLEMENT", "BUILD_INITIAL_SETTLEMENT"}:
            stat["builds"]["settlements"] += 1
        elif action_type == "BUILD_CITY":
            stat["builds"]["cities"] += 1
        elif action_type == "BUY_DEVELOPMENT_CARD":
            stat["dev_cards_bought"] += 1
        elif action_type == "PLAY_KNIGHT_CARD":
            stat["dev_played"]["knight"] += 1
        elif action_type == "PLAY_MONOPOLY":
            stat["dev_played"]["monopoly"] += 1
        elif action_type == "PLAY_YEAR_OF_PLENTY":
            stat["dev_played"]["year_of_plenty"] += 1
        elif action_type == "PLAY_ROAD_BUILDING":
            stat["dev_played"]["road_building"] += 1
        elif action_type == "MARITIME_TRADE":
            stat["maritime_trades"] += 1
        elif action_type == "MOVE_ROBBER":
            stat["robber_moves"] += 1
        elif action_type == "DISCARD_RESOURCE":
            stat["discards"] += 1
        elif action_type == "END_TURN":
            stat["end_turns"] += 1

    for color, key in key_by_color.items():
        ps = state["player_state"]
        stat = stats[color]
        stat["vp_public"] = ps[f"{key}_VICTORY_POINTS"]
        stat["vp_actual"] = ps[f"{key}_ACTUAL_VICTORY_POINTS"]
        stat["longest_road_length"] = ps[f"{key}_LONGEST_ROAD_LENGTH"]
        stat["has_longest_road"] = ps[f"{key}_HAS_ROAD"]
        stat["has_largest_army"] = ps[f"{key}_HAS_ARMY"]
        stat["roads_on_board"] = 15 - ps[f"{key}_ROADS_AVAILABLE"]
        stat["settlements_on_board"] = 5 - ps[f"{key}_SETTLEMENTS_AVAILABLE"]
        stat["cities_on_board"] = 4 - ps[f"{key}_CITIES_AVAILABLE"]
        stat["resources_in_hand"] = {
            resource: ps.get(f"{key}_{resource}_IN_HAND", 0) for resource in RESOURCES
        }
        stat["total_resources_in_hand"] = sum(stat["resources_in_hand"].values())
        stat["dev_in_hand"] = {dev: ps.get(f"{key}_{dev}_IN_HAND", 0) for dev in DEVS}
        stat["avg_roll"] = (
            round(stat["roll_total"] / stat["rolls"], 2) if stat["rolls"] else None
        )

    return {
        "game_id": game_id,
        "url": f"http://localhost:3000/games/{game_id}?player=RED",
        "winner": state["winning_color"],
        "ticks": ticks,
        "state_index": state["state_index"],
        "action_records": len(state["action_records"]),
        "players": state["players"],
        "stats": stats,
        "global_roll_histogram": dict(
            sorted(global_roll_histogram.items(), key=lambda item: int(item[0]))
        ),
        "last_10_actions": state["action_records"][-10:],
    }


def analyze_and_mutate_strategy(summary, strategy):
    updated = deepcopy(strategy)
    scoring = updated.setdefault("scoring", {})
    resource_priority = updated.setdefault("resource_priority", {})
    notes = []
    red = summary["stats"]["RED"]
    winner = summary["winner"]

    if winner == "RED":
        notes.append("Codex won; kept strategy mostly stable.")
        scoring["maritime_min_score"] = min(3.4, scoring.get("maritime_min_score", 2.6) + 0.05)
        return updated, notes

    if red["cities_on_board"] < 1:
        resource_priority["ORE"] = round(resource_priority.get("ORE", 1.5) + 0.08, 2)
        resource_priority["WHEAT"] = round(resource_priority.get("WHEAT", 1.55) + 0.06, 2)
        scoring["ore_wheat_sheep_combo_bonus"] = round(
            scoring.get("ore_wheat_sheep_combo_bonus", 2.35) + 0.2, 2
        )
        notes.append("Codex still underbuilt cities; increased ORE/WHEAT and ore-wheat-sheep setup bonus.")

    if red["maritime_trades"] > max(2, red["cities_on_board"] + red["settlements_on_board"]):
        scoring["maritime_min_score"] = round(scoring.get("maritime_min_score", 2.6) + 0.25, 2)
        scoring["maritime_offer_priority_penalty"] = round(
            scoring.get("maritime_offer_priority_penalty", 1.05) + 0.08, 2
        )
        notes.append("Codex overused maritime trades; raised minimum trade score and offered-resource penalty.")

    if red["roads_on_board"] > red["settlements_on_board"] * 2 + 2 and not red["has_longest_road"]:
        scoring["road_target_node_weight"] = round(
            max(0.35, scoring.get("road_target_node_weight", 0.72) - 0.08),
            2,
        )
        notes.append("Codex built roads without longest-road payoff; reduced road target weight.")

    if red["dev_cards_bought"] == 0 and red["vp_actual"] <= 5:
        scoring["year_of_plenty_priority_weight"] = round(
            scoring.get("year_of_plenty_priority_weight", 1.65) + 0.05,
            2,
        )
        notes.append("Codex lacked dev-card leverage; nudged development-card support via Year of Plenty value.")

    if not notes:
        notes.append("Loss did not match a hard rule; kept strategy stable to avoid overfitting.")

    return updated, notes


def markdown_table(summary):
    rows = [
        "| Гравець | Тип | VP | Доріг | Поселень | Міст | Longest road | Trades | Dev bought | Ресурсів |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for color in summary["players"]:
        stat = summary["stats"][color["color"]]
        rows.append(
            f"| {color['color']} | {stat['type']} | {stat['vp_actual']} | "
            f"{stat['roads_on_board']} | {stat['settlements_on_board']} | "
            f"{stat['cities_on_board']} | {stat['longest_road_length']} | "
            f"{stat['maritime_trades']} | {stat['dev_cards_bought']} | "
            f"{stat['total_resources_in_hand']} |"
        )
    return "\n".join(rows)


def write_game_report(index, summary, notes, strategy_before, strategy_after):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"game_{index:02d}.md"
    red = summary["stats"]["RED"]
    content = [
        f"# Strategy Training Game {index}",
        "",
        f"- Game: [{summary['game_id']}]({summary['url']})",
        f"- Winner: **{summary['winner']}**",
        f"- Codex result: **{'WIN' if summary['winner'] == 'RED' else 'LOSS'}**",
        f"- Actions: `{summary['action_records']}`",
        "",
        markdown_table(summary),
        "",
        "## Codex Details",
        "",
        f"- VP: `{red['vp_actual']}`",
        f"- Builds: roads `{red['roads_on_board']}`, settlements `{red['settlements_on_board']}`, cities `{red['cities_on_board']}`",
        f"- Maritime trades: `{red['maritime_trades']}`",
        f"- Dev cards bought: `{red['dev_cards_bought']}`",
        f"- Robber moves: `{red['robber_moves']}`",
        f"- Discards: `{red['discards']}`",
        f"- Avg roll: `{red['avg_roll']}`",
        "",
        "## Analysis And Strategy Update",
        "",
    ]
    content.extend(f"- {note}" for note in notes)
    content.extend(
        [
            "",
            "## Roll Histogram",
            "",
            "```json",
            json.dumps(summary["global_roll_histogram"], indent=2),
            "```",
            "",
            "## Strategy Snapshot",
            "",
            f"- Before: `{strategy_before['name']}`",
            f"- After: `{strategy_after['name']}`",
        ]
    )
    path.write_text("\n".join(content) + "\n", encoding="utf-8")
    return path


def write_summary_report(summaries, strategy_start, strategy_end, report_paths):
    wins = sum(1 for summary in summaries if summary["winner"] == "RED")
    avg_vp = round(sum(summary["stats"]["RED"]["vp_actual"] for summary in summaries) / len(summaries), 2)
    avg_cities = round(
        sum(summary["stats"]["RED"]["cities_on_board"] for summary in summaries) / len(summaries),
        2,
    )
    avg_trades = round(
        sum(summary["stats"]["RED"]["maritime_trades"] for summary in summaries) / len(summaries),
        2,
    )

    rows = [
        "| Game | Winner | Codex VP | Codex roads | Codex settlements | Codex cities | Codex trades | Report |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for index, summary in enumerate(summaries, start=1):
        red = summary["stats"]["RED"]
        rows.append(
            f"| {index} | {summary['winner']} | {red['vp_actual']} | "
            f"{red['roads_on_board']} | {red['settlements_on_board']} | "
            f"{red['cities_on_board']} | {red['maritime_trades']} | "
            f"[game_{index:02d}.md]({report_paths[index - 1].name}) |"
        )

    path = REPORTS_DIR / "summary.md"
    content = [
        "# Codex Strategy Training Summary",
        "",
        f"- Games: `{len(summaries)}`",
        f"- Codex wins: `{wins}`",
        f"- Codex win rate: `{round(wins / len(summaries) * 100, 1)}%`",
        f"- Avg Codex VP: `{avg_vp}`",
        f"- Avg Codex cities: `{avg_cities}`",
        f"- Avg Codex maritime trades: `{avg_trades}`",
        "",
        "\n".join(rows),
        "",
        "## What Was Wrong",
        "",
        "- The first observed loss showed no city upgrades, so the old profile overvalued expansion/trading relative to ore/wheat city tempo.",
        "- Maritime trades were previously accepted whenever legal, causing loops and resource churn.",
        "- Road building could consume tempo without securing either settlements or Longest Road.",
        "",
        "## Strategy Changes",
        "",
        f"- Start strategy: `{strategy_start['name']}`",
        f"- End strategy: `{strategy_end['name']}`",
        f"- Final resource priority: `{json.dumps(strategy_end.get('resource_priority', {}), sort_keys=True)}`",
        f"- Final scoring knobs: `{json.dumps(strategy_end.get('scoring', {}), sort_keys=True)}`",
        "",
    ]
    path.write_text("\n".join(content) + "\n", encoding="utf-8")
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=10)
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    strategy_start = load_strategy()
    summaries = []
    report_paths = []

    for index in range(1, args.games + 1):
        strategy_before = load_strategy()
        adapter = start_adapter()
        time.sleep(0.8)
        try:
            game_id = create_game()
            state, ticks = play_game(game_id)
        finally:
            stop_adapter(adapter)

        summary = summarize_state(game_id, state, ticks)
        strategy_after, notes = analyze_and_mutate_strategy(summary, strategy_before)
        strategy_after["name"] = f"city_first_ore_wheat_v2_g{index:02d}"
        save_strategy(strategy_after)
        report_path = write_game_report(index, summary, notes, strategy_before, strategy_after)
        summaries.append(summary)
        report_paths.append(report_path)
        print(
            f"game {index}: winner={summary['winner']} "
            f"codex_vp={summary['stats']['RED']['vp_actual']} "
            f"cities={summary['stats']['RED']['cities_on_board']} "
            f"trades={summary['stats']['RED']['maritime_trades']} "
            f"report={report_path}"
        )

    summary_path = write_summary_report(summaries, strategy_start, load_strategy(), report_paths)
    print(f"summary={summary_path}")


if __name__ == "__main__":
    main()
