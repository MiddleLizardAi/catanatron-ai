#!/usr/bin/env python3
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


PRODUCTION_WEIGHTS = {
    6: 5,
    8: 5,
    5: 4,
    9: 4,
    4: 3,
    10: 3,
    3: 2,
    11: 2,
    2: 1,
    12: 1,
}

RESOURCE_ORDER = ["WOOD", "BRICK", "WHEAT", "ORE", "SHEEP"]
ACTION_PRIORITY = [
    "ROLL",
    "MOVE_ROBBER",
    "BUILD_CITY",
    "BUILD_SETTLEMENT",
    "BUILD_ROAD",
    "BUY_DEVELOPMENT_CARD",
    "PLAY_KNIGHT_CARD",
    "PLAY_YEAR_OF_PLENTY",
    "PLAY_ROAD_BUILDING",
    "PLAY_MONOPOLY",
    "MARITIME_TRADE",
    "END_TURN",
]


def action_type(action):
    if isinstance(action, dict):
        return action.get("type")
    return action[1]


def action_value(action):
    if isinstance(action, dict):
        return action.get("value")
    return action[2]


def action_id(action, fallback_index):
    if isinstance(action, dict):
        return action.get("id"), action.get("index", fallback_index)
    return None, fallback_index


def color_index(state, color):
    try:
        return state.get("colors", []).index(color)
    except ValueError:
        return 0


def resource_count(state, color, resource):
    index = color_index(state, color)
    return state.get("player_state", {}).get(f"P{index}_{resource}_IN_HAND", 0)


def node_score(state, node_id):
    adjacent_tiles = state.get("adjacent_tiles", {}).get(str(node_id), [])
    resources = set()
    score = 0

    for tile in adjacent_tiles:
        if tile.get("type") != "RESOURCE_TILE":
            continue
        resources.add(tile.get("resource"))
        score += PRODUCTION_WEIGHTS.get(tile.get("number"), 0)

    return score + (len(resources) * 0.6)


def choose_best_node_action(actions, state):
    return max(actions, key=lambda action: node_score(state, action_value(action)))


def choose_best_road_action(actions, state):
    def score(action):
        edge = action_value(action)
        if not isinstance(edge, list) or len(edge) != 2:
            return 0
        return max(node_score(state, edge[0]), node_score(state, edge[1]))

    return max(actions, key=score)


def choose_discard_action(actions, state, color):
    return max(
        actions,
        key=lambda action: resource_count(state, color, action_value(action)),
    )


def choose_monopoly_action(actions, state, color):
    return max(
        actions,
        key=lambda action: sum(
            resource_count(state, other_color, action_value(action))
            for other_color in state.get("colors", [])
            if other_color != color
        ),
    )


def choose_year_of_plenty_action(actions, state, color):
    def score(action):
        resources = action_value(action)
        if not isinstance(resources, list):
            resources = [resources]
        return sum(10 - resource_count(state, color, resource) for resource in resources)

    return max(actions, key=score)


def coordinate_score(state, coordinate):
    score = 0
    for item in state.get("tiles", []):
        if item.get("coordinate") != coordinate:
            continue
        tile = item.get("tile", {})
        if tile.get("type") == "RESOURCE_TILE":
            score += PRODUCTION_WEIGHTS.get(tile.get("number"), 0)
    return score


def choose_robber_action(actions, payload):
    state = payload.get("state", {})
    leader = payload.get("strategy", {}).get("public_leader", {}).get("color")

    def score(action):
        value = action_value(action)
        if not isinstance(value, list) or len(value) != 2:
            return 0
        coordinate, victim = value
        leader_bonus = 5 if victim == leader else 0
        victim_bonus = 2 if victim else 0
        return coordinate_score(state, coordinate) + leader_bonus + victim_bonus

    return max(actions, key=score)


def choose_action(payload):
    actions = payload.get("legal_actions") or payload.get("playable_actions", [])
    state = payload.get("state", {})
    color = payload.get("color")

    if not actions:
        return None, 0, "no playable actions"

    grouped = {}
    for index, action in enumerate(actions):
        grouped.setdefault(action_type(action), []).append((index, action))

    if "ROLL" in grouped:
        index, selected = grouped["ROLL"][0]
        selected_id, selected_index = action_id(selected, index)
        return selected_id, selected_index, "roll immediately"

    if "DISCARD_RESOURCE" in grouped:
        candidates = [item[1] for item in grouped["DISCARD_RESOURCE"]]
        selected = choose_discard_action(candidates, state, color)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "discard most abundant resource"

    if "MOVE_ROBBER" in grouped:
        candidates = [item[1] for item in grouped["MOVE_ROBBER"]]
        selected = choose_robber_action(candidates, payload)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "rob public leader or strongest tile"

    if "BUILD_INITIAL_SETTLEMENT" in grouped:
        candidates = [item[1] for item in grouped["BUILD_INITIAL_SETTLEMENT"]]
        selected = choose_best_node_action(candidates, state)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "best initial settlement production"

    if "BUILD_SETTLEMENT" in grouped:
        candidates = [item[1] for item in grouped["BUILD_SETTLEMENT"]]
        selected = choose_best_node_action(candidates, state)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "best settlement production"

    if "BUILD_INITIAL_ROAD" in grouped:
        candidates = [item[1] for item in grouped["BUILD_INITIAL_ROAD"]]
        selected = choose_best_road_action(candidates, state)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "road toward best adjacent node"

    if "BUILD_ROAD" in grouped:
        candidates = [item[1] for item in grouped["BUILD_ROAD"]]
        selected = choose_best_road_action(candidates, state)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "road toward best adjacent node"

    if "PLAY_MONOPOLY" in grouped:
        candidates = [item[1] for item in grouped["PLAY_MONOPOLY"]]
        selected = choose_monopoly_action(candidates, state, color)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "monopoly most visible opponent resource"

    if "PLAY_YEAR_OF_PLENTY" in grouped:
        candidates = [item[1] for item in grouped["PLAY_YEAR_OF_PLENTY"]]
        selected = choose_year_of_plenty_action(candidates, state, color)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "take scarce resources"

    for preferred_type in ACTION_PRIORITY:
        if preferred_type in grouped:
            index, selected = grouped[preferred_type][0]
            selected_id, selected_index = action_id(selected, index)
            return selected_id, selected_index, f"priority {preferred_type}"

    selected_id, selected_index = action_id(actions[0], 0)
    return selected_id, selected_index, "fallback first action"


class DecisionHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/decide":
            self.send_error(404, "Not found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
            selected_id, action_index, reason = choose_action(payload)
            response = {"action_index": action_index, "reason": reason}
            if selected_id is not None:
                response["action_id"] = selected_id
            self._send_json(response)
        except Exception as exc:
            self._send_json({"action_index": 0, "error": str(exc)}, status=200)

    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format % args))

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Local heuristic Codex Catanatron webhook adapter")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), DecisionHandler)
    print(f"Listening on http://{args.host}:{args.port}/decide")
    server.serve_forever()


if __name__ == "__main__":
    main()
