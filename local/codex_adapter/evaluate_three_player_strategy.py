#!/usr/bin/env python3
import argparse
import json
import os
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def ensure_deterministic_hash_seed():
    if os.environ.get("PYTHONHASHSEED") not in (None, "", "random"):
        return
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    os.execvpe(sys.executable, [sys.executable] + sys.argv, env)


ensure_deterministic_hash_seed()

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ADAPTER_DIR = Path(__file__).resolve().parent
if str(ADAPTER_DIR) not in sys.path:
    sys.path.insert(0, str(ADAPTER_DIR))

import codex_webhook
from catanatron.game import Game
from catanatron.models.enums import DEVELOPMENT_CARDS, RESOURCES
from catanatron.models.map import build_map
from catanatron.models.player import Color, RandomPlayer, WebHookPlayer
from catanatron.players.minimax import AlphaBetaPlayer
from catanatron.players.weighted_random import WeightedRandomPlayer
from catanatron.state_functions import player_key


DEFAULT_STRATEGY_PATH = ADAPTER_DIR / "strategy.json"
DEFAULT_REPORT_DIR = ADAPTER_DIR / "reports" / "evaluations"


class DirectCodexPlayer(WebHookPlayer):
    def __init__(self, color, strategy, decision_records, context):
        super().__init__(color, "direct://codex", name="Codex")
        self.strategy = strategy
        self.decision_records = decision_records
        self.context = context
        self.player_type = "WEBHOOK_DIRECT"

    def decide(self, game, playable_actions):
        legal_actions = [
            self._legal_action_to_json(index, action)
            for index, action in enumerate(playable_actions)
        ]
        payload = {
            "game_id": game.id,
            "color": self.color.value,
            "name": self.name,
            "state_index": len(game.state.action_records),
            "current_prompt": game.state.current_prompt.value,
            "legal_actions": legal_actions,
            "playable_actions": [self._action_to_json(action) for action in playable_actions],
            "strategy": self._strategy_to_json(game, legal_actions),
            "state": self._state_to_json(game),
        }

        selected_id, action_index, reason, diagnostics = codex_webhook.choose_action_with_diagnostics(
            payload,
            self.strategy,
        )
        diagnostics.update(self.context)
        self.decision_records.append(diagnostics)

        response = {"action_index": action_index, "reason": reason}
        if selected_id is not None:
            response["action_id"] = selected_id
        return self._select_action(response, playable_actions)


def color_from_name(name):
    return Color[name.upper()]


def attach_player_metadata(player, player_type, name=None, is_bot=None):
    player.player_type = player_type
    player.name = name or player_type
    if is_bot is not None:
        player.is_bot = is_bot
    return player


def create_human_proxy(proxy_type, color):
    if proxy_type == "weighted":
        return attach_player_metadata(
            WeightedRandomPlayer(color),
            "HUMAN_PROXY_WEIGHTED",
            name="Human Proxy Weighted",
            is_bot=False,
        )
    if proxy_type == "random":
        return attach_player_metadata(
            RandomPlayer(color),
            "HUMAN_PROXY_RANDOM",
            name="Human Proxy Random",
            is_bot=False,
        )
    if proxy_type == "catanatron":
        return attach_player_metadata(
            AlphaBetaPlayer(color, 2, True),
            "HUMAN_PROXY_CATANATRON",
            name="Human Proxy Catanatron",
            is_bot=False,
        )
    raise ValueError(f"unknown human proxy: {proxy_type}")


def create_players(args, strategy, decision_records, context):
    human_color = color_from_name(args.human_color)
    codex_color = color_from_name(args.codex_color)
    catanatron_color = color_from_name(args.catanatron_color)
    if len({human_color, codex_color, catanatron_color}) != 3:
        raise ValueError("human, codex, and catanatron colors must be different")

    return [
        create_human_proxy(args.human_proxy, human_color),
        DirectCodexPlayer(codex_color, strategy, decision_records, context),
        attach_player_metadata(
            AlphaBetaPlayer(catanatron_color, 2, True),
            "CATANATRON",
            name="Catanatron",
            is_bot=True,
        ),
    ]


def action_color(action):
    return action.color.value


def action_type_name(action):
    return action.action_type.value


def summarize_game(game, game_number, seed, ticks, decisions, codex_color_name):
    state = game.state
    winner = game.winning_color()
    winner_name = winner.value if winner is not None else None
    stats = {}
    players_by_color = {player.color.value: player for player in state.players}

    for color in state.colors:
        color_name = color.value
        player = players_by_color[color_name]
        stats[color_name] = {
            "name": getattr(player, "name", type(player).__name__),
            "type": getattr(player, "player_type", type(player).__name__),
            "actions": 0,
            "action_type_counts": {},
            "rolls": 0,
            "roll_total": 0,
            "roll_histogram": {},
            "maritime_trades": 0,
            "dev_cards_bought": 0,
            "robber_moves": 0,
            "discards": 0,
            "end_turns": 0,
        }

    for action, result in state.action_records:
        color_name = action_color(action)
        type_name = action_type_name(action)
        stat = stats[color_name]
        stat["actions"] += 1
        stat["action_type_counts"][type_name] = stat["action_type_counts"].get(type_name, 0) + 1
        if type_name == "ROLL":
            dice = action.value if action.value else result
            total = sum(dice)
            stat["rolls"] += 1
            stat["roll_total"] += total
            stat["roll_histogram"][str(total)] = stat["roll_histogram"].get(str(total), 0) + 1
        elif type_name == "MARITIME_TRADE":
            stat["maritime_trades"] += 1
        elif type_name == "BUY_DEVELOPMENT_CARD":
            stat["dev_cards_bought"] += 1
        elif type_name == "MOVE_ROBBER":
            stat["robber_moves"] += 1
        elif type_name == "DISCARD_RESOURCE":
            stat["discards"] += 1
        elif type_name == "END_TURN":
            stat["end_turns"] += 1

    for color in state.colors:
        color_name = color.value
        key = player_key(state, color)
        ps = state.player_state
        stat = stats[color_name]
        stat["vp_public"] = ps[f"{key}_VICTORY_POINTS"]
        stat["vp_actual"] = ps[f"{key}_ACTUAL_VICTORY_POINTS"]
        stat["longest_road_length"] = ps[f"{key}_LONGEST_ROAD_LENGTH"]
        stat["has_longest_road"] = bool(ps[f"{key}_HAS_ROAD"])
        stat["has_largest_army"] = bool(ps[f"{key}_HAS_ARMY"])
        stat["roads_on_board"] = 15 - ps[f"{key}_ROADS_AVAILABLE"]
        stat["settlements_on_board"] = 5 - ps[f"{key}_SETTLEMENTS_AVAILABLE"]
        stat["cities_on_board"] = 4 - ps[f"{key}_CITIES_AVAILABLE"]
        stat["resources_in_hand"] = {
            resource: ps.get(f"{key}_{resource}_IN_HAND", 0) for resource in RESOURCES
        }
        stat["total_resources_in_hand"] = sum(stat["resources_in_hand"].values())
        stat["dev_in_hand"] = {
            card: ps.get(f"{key}_{card}_IN_HAND", 0) for card in DEVELOPMENT_CARDS
        }
        stat["avg_roll"] = round(stat["roll_total"] / stat["rolls"], 2) if stat["rolls"] else None

    reason_counts = Counter(record.get("reason") for record in decisions)
    selected_type_counts = Counter(
        (record.get("selected_action") or {}).get("type") for record in decisions
    )
    selected_type_counts.pop(None, None)
    fallback_count = sum(
        1
        for record in decisions
        if record.get("fallback") or "fallback" in (record.get("reason") or "")
    )

    return {
        "game_number": game_number,
        "seed": seed,
        "game_id": game.id,
        "winner": winner_name,
        "ticks": ticks,
        "num_turns": state.num_turns,
        "action_records": len(state.action_records),
        "colors": [color.value for color in state.colors],
        "stats": stats,
        "codex_color": codex_color_name,
        "codex_result": "WIN" if winner_name == codex_color_name else "LOSS",
        "codex_decisions": len(decisions),
        "codex_fallback_decisions": fallback_count,
        "codex_reason_counts": dict(reason_counts.most_common()),
        "codex_selected_action_type_counts": dict(selected_type_counts.most_common()),
        "last_12_actions": [
            [
                action.color.value,
                action.action_type.value,
                WebHookPlayer._json_value(action.value),
            ]
            for action, _result in state.action_records[-12:]
        ],
    }


def play_one_game(args, strategy, game_number, seed):
    random.seed(seed)
    decision_records = []
    context = {"game_number": game_number, "seed": seed}
    players = create_players(args, strategy, decision_records, context)
    game = Game(
        players=players,
        seed=seed,
        discard_limit=args.discard_limit,
        friendly_robber=args.friendly_robber,
        vps_to_win=args.vps_to_win,
        catan_map=build_map(args.map_template, args.number_placement),
    )

    ticks = 0
    while (
        game.winning_color() is None
        and game.state.num_turns < args.turn_limit
        and ticks < args.max_ticks
    ):
        game.play_tick()
        ticks += 1

    codex_color_name = color_from_name(args.codex_color).value
    summary = summarize_game(
        game,
        game_number,
        seed,
        ticks,
        decision_records,
        codex_color_name,
    )
    return summary, decision_records


def mean(values):
    values = list(values)
    if not values:
        return 0
    return round(sum(values) / len(values), 3)


def aggregate_summaries(summaries, codex_color):
    codex_stats = [summary["stats"][codex_color] for summary in summaries]
    wins = sum(1 for summary in summaries if summary["winner"] == codex_color)
    reason_counts = Counter()
    selected_type_counts = Counter()
    winner_counts = Counter(summary["winner"] for summary in summaries)
    for summary in summaries:
        reason_counts.update(summary["codex_reason_counts"])
        selected_type_counts.update(summary["codex_selected_action_type_counts"])

    return {
        "games": len(summaries),
        "winner_counts": dict(winner_counts.most_common()),
        "codex_wins": wins,
        "codex_win_rate": round(wins / len(summaries), 3) if summaries else 0,
        "avg_codex_vp": mean(stat["vp_actual"] for stat in codex_stats),
        "avg_codex_roads": mean(stat["roads_on_board"] for stat in codex_stats),
        "avg_codex_settlements": mean(stat["settlements_on_board"] for stat in codex_stats),
        "avg_codex_cities": mean(stat["cities_on_board"] for stat in codex_stats),
        "avg_codex_trades": mean(stat["maritime_trades"] for stat in codex_stats),
        "avg_codex_dev_cards_bought": mean(stat["dev_cards_bought"] for stat in codex_stats),
        "avg_codex_robber_moves": mean(stat["robber_moves"] for stat in codex_stats),
        "codex_fallback_decisions": sum(summary["codex_fallback_decisions"] for summary in summaries),
        "top_codex_reasons": dict(reason_counts.most_common(12)),
        "codex_selected_action_type_counts": dict(selected_type_counts.most_common()),
    }


def markdown_game_table(summaries, codex_color):
    rows = [
        "| Game | Seed | Winner | Codex VP | Roads | Settlements | Cities | Trades | Dev bought | Fallbacks |",
        "|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        codex = summary["stats"][codex_color]
        rows.append(
            f"| {summary['game_number']} | {summary['seed']} | {summary['winner']} | "
            f"{codex['vp_actual']} | {codex['roads_on_board']} | "
            f"{codex['settlements_on_board']} | {codex['cities_on_board']} | "
            f"{codex['maritime_trades']} | {codex['dev_cards_bought']} | "
            f"{summary['codex_fallback_decisions']} |"
        )
    return "\n".join(rows)


def markdown_counter_table(title, values):
    rows = [f"## {title}", "", "| Item | Count |", "|---|---:|"]
    for item, count in values.items():
        rows.append(f"| {item} | {count} |")
    return "\n".join(rows)


def write_reports(args, strategy, summaries, all_decisions):
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"three_player_eval_{timestamp}"
    summary_path = report_dir / f"{stem}_summary.json"
    decisions_path = report_dir / f"{stem}_decisions.jsonl"
    markdown_path = report_dir / f"{stem}.md"
    codex_color = color_from_name(args.codex_color).value
    aggregate = aggregate_summaries(summaries, codex_color)

    payload = {
        "config": vars(args),
        "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
        "strategy_name": strategy.get("name", "default"),
        "aggregate": aggregate,
        "games": summaries,
    }
    summary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    with decisions_path.open("w", encoding="utf-8") as decisions_file:
        for record in all_decisions:
            decisions_file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    content = [
        "# Three Player Codex Strategy Evaluation",
        "",
        f"- Strategy: `{strategy.get('name', 'default')}`",
        f"- Games: `{aggregate['games']}`",
        f"- Human proxy: `{args.human_proxy}`",
        f"- Colors: human `{args.human_color}`, Codex `{args.codex_color}`, Catanatron `{args.catanatron_color}`",
        f"- Codex wins: `{aggregate['codex_wins']}`",
        f"- Codex win rate: `{round(aggregate['codex_win_rate'] * 100, 1)}%`",
        f"- Avg Codex VP: `{aggregate['avg_codex_vp']}`",
        f"- Avg Codex cities: `{aggregate['avg_codex_cities']}`",
        f"- Avg Codex settlements: `{aggregate['avg_codex_settlements']}`",
        f"- Avg Codex roads: `{aggregate['avg_codex_roads']}`",
        f"- Codex fallback decisions: `{aggregate['codex_fallback_decisions']}`",
        "",
        "## Games",
        "",
        markdown_game_table(summaries, codex_color),
        "",
        markdown_counter_table("Winner Counts", aggregate["winner_counts"]),
        "",
        markdown_counter_table("Top Codex Reasons", aggregate["top_codex_reasons"]),
        "",
        markdown_counter_table(
            "Codex Selected Action Types",
            aggregate["codex_selected_action_type_counts"],
        ),
        "",
        "## Artifacts",
        "",
        f"- JSON summary: `{summary_path.name}`",
        f"- Decision JSONL: `{decisions_path.name}`",
        "",
    ]
    markdown_path.write_text("\n".join(content), encoding="utf-8")
    return markdown_path, summary_path, decisions_path, aggregate


def parse_args():
    parser = argparse.ArgumentParser(
        description="Evaluate Codex strategy in a 3-player human-proxy + Codex + Catanatron setup."
    )
    parser.add_argument("--games", type=int, default=20)
    parser.add_argument(
        "--seeds",
        default=None,
        help="Comma-separated explicit seed list. Overrides --games and --seed-start.",
    )
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--human-proxy", choices=("weighted", "random", "catanatron"), default="weighted")
    parser.add_argument("--human-color", default="RED")
    parser.add_argument("--codex-color", default="BLUE")
    parser.add_argument("--catanatron-color", default="ORANGE")
    parser.add_argument("--strategy", default=str(DEFAULT_STRATEGY_PATH))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--map-template", default="BASE")
    parser.add_argument("--number-placement", default="official_spiral")
    parser.add_argument("--vps-to-win", type=int, default=10)
    parser.add_argument("--discard-limit", type=int, default=7)
    parser.add_argument("--friendly-robber", action="store_true")
    parser.add_argument("--turn-limit", type=int, default=1000)
    parser.add_argument("--max-ticks", type=int, default=5000)
    parser.add_argument("--json", action="store_true", help="Print aggregate JSON instead of a short text summary.")
    return parser.parse_args()


def selected_seeds(args):
    if args.seeds:
        return [int(seed.strip()) for seed in args.seeds.split(",") if seed.strip()]
    return [args.seed_start + offset for offset in range(args.games)]


def main():
    args = parse_args()
    strategy = codex_webhook.load_strategy(args.strategy)
    summaries = []
    all_decisions = []
    seeds = selected_seeds(args)

    for offset, seed in enumerate(seeds):
        game_number = offset + 1
        summary, decisions = play_one_game(args, strategy, game_number, seed)
        summaries.append(summary)
        all_decisions.extend(decisions)
        codex = summary["stats"][color_from_name(args.codex_color).value]
        print(
            f"game {game_number}: seed={seed} winner={summary['winner']} "
            f"codex_vp={codex['vp_actual']} cities={codex['cities_on_board']} "
            f"settlements={codex['settlements_on_board']} roads={codex['roads_on_board']} "
            f"fallbacks={summary['codex_fallback_decisions']}"
        )

    markdown_path, summary_path, decisions_path, aggregate = write_reports(
        args,
        strategy,
        summaries,
        all_decisions,
    )
    if args.json:
        print(json.dumps(aggregate, indent=2, ensure_ascii=False))
    else:
        print(f"report={markdown_path}")
        print(f"summary={summary_path}")
        print(f"decisions={decisions_path}")


if __name__ == "__main__":
    main()
