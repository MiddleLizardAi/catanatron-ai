import random
import builtins
import json
import time
import urllib.request

from enum import Enum

from catanatron.models.enums import Action, ActionType, RESOURCES, DEVELOPMENT_CARDS


class Color(Enum):
    """Enum to represent the colors in the game"""

    RED = "RED"
    BLUE = "BLUE"
    ORANGE = "ORANGE"
    WHITE = "WHITE"

    def __repr__(self):
        return f"C.{self.name}"


class Player:
    """Interface to represent a player's decision logic.

    Formulated as a class (instead of a function) so that players
    can have an initialization that can later be serialized to
    the database via pickle.
    """

    def __init__(self, color, is_bot=True, name=None):
        """Initialize the player

        Args:
            color(Color): the color of the player
            is_bot(bool): whether the player is controlled by the computer
            name(str): display name for web clients
        """
        self.color = color
        self.is_bot = is_bot
        self.name = name or type(self).__name__

    def decide(self, game, playable_actions):
        """Should return one of the playable_actions or
        an OFFER_TRADE action if its your turn and you have already rolled.

        Args:
            game (Game): complete game state. read-only.
            playable_actions (Iterable[Action]): options right now
        """
        raise NotImplementedError

    def reset_state(self):
        """Hook for resetting state between games"""
        pass

    def __repr__(self):
        return f"{type(self).__name__}({self.name}):{self.color.value}"


class SimplePlayer(Player):
    """Simple AI player that always takes the first action in the list of playable_actions"""

    def decide(self, game, playable_actions):
        return playable_actions[0]


class HumanPlayer(Player):
    """Human player that selects which action to take using standard input"""

    def __init__(self, color, is_bot=False, input_fn=builtins.input, name=None):
        super().__init__(color, is_bot, name=name or "Human")
        self.input_fn = input_fn  # this is for testing purposes

    def decide(self, game, playable_actions):
        for i, action in enumerate(playable_actions):
            print(f"{i}: {action.action_type} {action.value}")
        i = None
        while i is None or (i < 0 or i >= len(playable_actions)):
            print("Please enter a valid index:")
            try:
                x = self.input_fn(">>> ")  # Use the input_fn
                i = int(x)
            except ValueError:
                pass

        return playable_actions[i]


class RandomPlayer(Player):
    """Random AI player that selects an action randomly from the list of playable_actions"""

    def decide(self, game, playable_actions):
        return random.choice(playable_actions)


class WebHookPlayer(Player):
    """Bot player that chooses actions through an HTTP webhook."""

    def __init__(self, color, webhook_url, name=None, timeout=30):
        super().__init__(color, is_bot=True, name=name or "Webhook")
        self.webhook_url = webhook_url
        self.timeout = timeout
        self.player_type = "WEBHOOK"

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
            "strategy": self._strategy_to_json(game, legal_actions, playable_actions),
            "state": self._state_to_json(game),
        }

        request = urllib.request.Request(
            self.webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            return self._select_action(data, playable_actions)
        except Exception as exc:
            print(
                f"WebHookPlayer({self.name}) failed for {self.color.value}: {exc}. "
                "Falling back to first playable action."
            )
            return playable_actions[0]

    def _select_action(self, data, playable_actions):
        if "action_id" in data:
            action_id = str(data["action_id"])
            for index, action in enumerate(playable_actions):
                if self._action_id(index, action) == action_id:
                    return action

        if "action_index" in data:
            index = int(data["action_index"])
            if 0 <= index < len(playable_actions):
                return playable_actions[index]

        if "action" in data:
            requested_action = self._action_from_json(data["action"])
            for action in playable_actions:
                if action == requested_action:
                    return action

        return playable_actions[0]

    @staticmethod
    def _action_id(index, action):
        value = WebHookPlayer._json_value(action.value)
        value_json = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return f"{index}:{action.action_type.value}:{value_json}"

    @staticmethod
    def _legal_action_to_json(index, action):
        return {
            "id": WebHookPlayer._action_id(index, action),
            "index": index,
            "type": action.action_type.value,
            "value": WebHookPlayer._json_value(action.value),
            "action": WebHookPlayer._action_to_json(action),
        }

    @staticmethod
    def _action_to_json(action):
        return [
            action.color.value,
            action.action_type.value,
            WebHookPlayer._json_value(action.value),
        ]

    def _strategy_to_json(self, game, legal_actions, playable_actions=None):
        from catanatron.state_functions import (
            get_actual_victory_points,
            get_visible_victory_points,
            player_key,
            player_num_resource_cards,
        )

        state = game.state
        current_key = player_key(state, self.color)
        visible_players = []

        for color in state.colors:
            key = player_key(state, color)
            player = next(player for player in state.players if player.color == color)
            player_summary = {
                "color": color.value,
                "name": getattr(player, "name", type(player).__name__),
                "type": getattr(
                    player,
                    "player_type",
                    "HUMAN"
                    if not player.is_bot
                    else type(player).__name__.replace("Player", "").upper(),
                ),
                "is_self": color == self.color,
                "public_victory_points": get_visible_victory_points(state, color),
                "resource_card_count": player_num_resource_cards(state, color),
                "development_card_count": sum(
                    state.player_state[f"{key}_{card}_IN_HAND"]
                    for card in DEVELOPMENT_CARDS
                ),
                "played_knights": state.player_state[f"{key}_PLAYED_KNIGHT"],
                "roads": state.player_state[f"{key}_ROADS_AVAILABLE"],
                "settlements": state.player_state[f"{key}_SETTLEMENTS_AVAILABLE"],
                "cities": state.player_state[f"{key}_CITIES_AVAILABLE"],
            }
            if color == self.color:
                player_summary["actual_victory_points"] = get_actual_victory_points(
                    state, color
                )
                player_summary["resources"] = {
                    resource: state.player_state[f"{current_key}_{resource}_IN_HAND"]
                    for resource in RESOURCES
                }
                player_summary["development_cards"] = {
                    card: state.player_state[f"{current_key}_{card}_IN_HAND"]
                    for card in DEVELOPMENT_CARDS
                }
            visible_players.append(player_summary)

        public_leader = max(
            visible_players,
            key=lambda player: player["public_victory_points"],
        )

        action_type_counts = {}
        for action in legal_actions:
            action_type_counts[action["type"]] = action_type_counts.get(action["type"], 0) + 1

        return {
            "objective": "Choose exactly one id from legal_actions. Do not invent actions.",
            "response_schema": {
                "action_id": "string from legal_actions[].id",
                "reason": "short strategy reason",
            },
            "priorities": [
                "Roll immediately when ROLL is legal.",
                "During setup, evaluate both starting settlements as one engine: seek strong dice numbers plus at least four resource types, with a concrete plan for any missing resource.",
                "Choose an opening archetype from the board: expansion/road when wood+brick are strong, city/development when ore+wheat+sheep are strong, hybrid when both are available.",
                "Do not overvalue a single high-production resource pile. A hand full of one resource is weak unless a matching port or trade plan is already reachable.",
                "Prefer settlements early when legal because more production and resource coverage beat waiting passively for a perfect city.",
                "Prefer cities when affordable on strong production, especially wheat/ore/sheep, but do not ignore expansion tempo.",
                "Use the robber against the public leader or the strongest production tile.",
                "Buy development cards when city/settlement progress is unavailable and the hand supports ore+wheat+sheep.",
                "Use maritime trades to convert surplus into missing build resources, especially before ending with more than seven cards.",
                "Build roads only when they unlock a reachable settlement, port, or real longest-road plan.",
                "After the opening two roads, do not build another road unless it directly opens a legal settlement spot and the settlement is already buildable or one resource away. Otherwise prefer settlement, city, targeted trade, development card, or end turn.",
                "Do not chase Longest Road before 8+ actual victory points unless the road also creates a near-term settlement. Roads without new buildings are usually lost tempo.",
                "At 8+ actual victory points, switch to endgame mode: choose the shortest route to 10 VP instead of general production. Prefer direct city/settlement, then Longest Road if it can flip, then development cards for hidden VP.",
                "If settlement/city pieces are exhausted, do not trade for those plans; convert surplus toward development cards or Longest Road only.",
                "End the turn when no useful build, targeted trade, or development action is legal.",
            ],
            "public_leader": public_leader,
            "self": next(player for player in visible_players if player["is_self"]),
            "players": visible_players,
            "legal_action_count": len(legal_actions),
            "legal_action_type_counts": action_type_counts,
            "catanatron_search": self._catanatron_search_to_json(
                game,
                legal_actions,
                playable_actions or game.playable_actions,
            ),
            "catanatron_teacher": self._catanatron_teacher_to_json(
                game,
                legal_actions,
                playable_actions or game.playable_actions,
            ),
        }

    def _catanatron_search_to_json(self, game, legal_actions, playable_actions):
        """Expose Catanatron's own AlphaBeta recommendation to webhook strategies."""
        try:
            from catanatron.players.minimax import (
                AlphaBetaPlayer,
                DebugStateNode,
                MAX_SEARCH_TIME_SECS,
            )
            from catanatron.players.value import DEFAULT_WEIGHTS

            depth = 2
            prunning = True
            search_player = AlphaBetaPlayer(
                self.color,
                depth=depth,
                prunning=prunning,
                value_fn_builder_name="base_fn",
                params=DEFAULT_WEIGHTS,
            )
            start = time.time()
            node = DebugStateNode(
                str(len(game.state.action_records)),
                self.color,
            )
            action, value = search_player.alphabeta(
                game.copy(),
                depth,
                float("-inf"),
                float("inf"),
                start + MAX_SEARCH_TIME_SECS,
                node,
            )

            action_scores = []
            for child in node.children:
                row = self._action_json_row_for_action(
                    child.action,
                    legal_actions,
                    playable_actions,
                )
                if row is None:
                    continue
                row["score"] = self._finite_float(child.expected_value)
                row["alpha_beta_scored"] = True
                action_scores.append(row)

            scored_ids = {row["id"] for row in action_scores if row.get("id") is not None}
            for index, _action in enumerate(playable_actions):
                row = {
                    key: legal_actions[index][key]
                    for key in ("id", "index", "type", "value")
                }
                if row["id"] in scored_ids:
                    continue
                row["score"] = None
                row["alpha_beta_scored"] = False
                action_scores.append(row)

            recommended = self._action_json_row_for_action(
                action,
                legal_actions,
                playable_actions,
            )
            if recommended is not None:
                recommended["score"] = self._finite_float(value)
                recommended["alpha_beta_scored"] = True

            return {
                "source": "catanatron.players.minimax.AlphaBetaPlayer",
                "depth": depth,
                "prunning": prunning,
                "value_fn": "base_fn",
                "timeout_seconds": MAX_SEARCH_TIME_SECS,
                "elapsed_ms": round((time.time() - start) * 1000, 3),
                "leaf_weights": DEFAULT_WEIGHTS,
                "recommended_action": recommended,
                "action_scores": action_scores,
            }
        except Exception as exc:
            return {"source": "catanatron search unavailable", "error": str(exc)}

    def _catanatron_teacher_to_json(self, game, legal_actions, playable_actions):
        """Expose Catanatron's cheap value-function opinion to webhook strategies.

        AlphaBetaPlayer uses the same value function at search leaves. Running full
        depth-2 AlphaBeta inside every webhook payload would make live games feel
        sluggish, so this exports one-ply expected value scores instead.
        """
        try:
            from catanatron.players.tree_search_utils import (
                execute_spectrum,
                list_prunned_actions,
            )
            from catanatron.players.value import DEFAULT_WEIGHTS, get_value_fn

            value_fn = get_value_fn("base_fn", DEFAULT_WEIGHTS)
            pruned_actions = set(list_prunned_actions(game))
            action_scores = []

            for index, action in enumerate(playable_actions):
                row = {
                    key: legal_actions[index][key]
                    for key in ("id", "index", "type", "value")
                }
                row["pruned"] = action not in pruned_actions
                try:
                    outcomes = execute_spectrum(game, action)
                    score = sum(
                        probability * value_fn(outcome, self.color)
                        for outcome, probability in outcomes
                    )
                    row["score"] = self._finite_float(score)
                except Exception as exc:
                    row["score"] = None
                    row["error"] = str(exc)
                action_scores.append(row)

            ranked = sorted(
                [
                    row
                    for row in action_scores
                    if row.get("score") is not None
                    and (not row.get("pruned") or len(pruned_actions) == 0)
                ],
                key=lambda row: row["score"],
                reverse=True,
            )
            return {
                "source": "catanatron.players.value.base_fn one-ply expected value",
                "alpha_beta_leaf_weights": DEFAULT_WEIGHTS,
                "recommended_action": ranked[0] if ranked else None,
                "action_scores": action_scores,
            }
        except Exception as exc:
            return {"source": "catanatron teacher unavailable", "error": str(exc)}

    @staticmethod
    def _action_json_row_for_action(action, legal_actions, playable_actions):
        if action is None:
            return None
        for index, candidate in enumerate(playable_actions):
            if candidate != action:
                continue
            return {
                key: legal_actions[index][key]
                for key in ("id", "index", "type", "value")
            }
        return None

    @staticmethod
    def _finite_float(value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        if value == float("inf") or value == float("-inf") or value != value:
            return None
        return round(value, 6)

    def _state_to_json(self, game):
        state = game.state
        nodes = {}
        edges = {}

        for coordinate, tile in state.board.map.tiles.items():
            for direction, node_id in tile.nodes.items():
                building = state.board.buildings.get(node_id, None)
                color = None if building is None else building[0]
                building_type = None if building is None else building[1]
                nodes[node_id] = {
                    "id": node_id,
                    "tile_coordinate": self._json_value(coordinate),
                    "direction": self._json_value(direction),
                    "building": self._json_value(building_type),
                    "color": self._json_value(color),
                }

            for direction, edge in tile.edges.items():
                edge_id = tuple(sorted(edge))
                edges[edge_id] = {
                    "id": self._json_value(edge_id),
                    "tile_coordinate": self._json_value(coordinate),
                    "direction": self._json_value(direction),
                    "color": self._json_value(state.board.roads.get(edge, None)),
                }

        return {
            "tiles": [
                {
                    "coordinate": self._json_value(coordinate),
                    "tile": self._tile_to_json(tile),
                }
                for coordinate, tile in state.board.map.tiles.items()
            ],
            "adjacent_tiles": {
                str(node_id): [self._tile_to_json(tile) for tile in tiles]
                for node_id, tiles in state.board.map.adjacent_tiles.items()
            },
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
            "player_state": self._json_value(state.player_state),
            "colors": self._json_value(state.colors),
            "bot_colors": [
                player.color.value for player in state.players if player.is_bot
            ],
            "players": [
                {
                    "color": player.color.value,
                    "name": getattr(player, "name", type(player).__name__),
                    "type": getattr(
                        player,
                        "player_type",
                        "HUMAN"
                        if not player.is_bot
                        else type(player).__name__.replace("Player", "").upper(),
                    ),
                    "is_bot": player.is_bot,
                }
                for player in state.players
            ],
            "robber_coordinate": self._json_value(state.board.robber_coordinate),
            "action_records": [
                [self._action_to_json(action), self._json_value(result)]
                for action, result in state.action_records
            ],
        }

    def _tile_to_json(self, tile):
        if not hasattr(tile, "id"):
            return {"type": "WATER"}

        base = {
            "id": tile.id,
            "nodes": self._json_value(tile.nodes),
            "edges": self._json_value(tile.edges),
        }
        if hasattr(tile, "direction"):
            return {
                **base,
                "type": "PORT",
                "direction": self._json_value(tile.direction),
                "resource": self._json_value(tile.resource),
            }

        if hasattr(tile, "resource"):
            resource = self._json_value(tile.resource)
            if resource is None:
                return {**base, "type": "DESERT"}
            return {
                **base,
                "type": "RESOURCE_TILE",
                "resource": resource,
                "number": tile.number,
            }

        return {"type": "WATER"}

    @staticmethod
    def _json_value(value):
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, tuple):
            return [WebHookPlayer._json_value(item) for item in value]
        if isinstance(value, list):
            return [WebHookPlayer._json_value(item) for item in value]
        if isinstance(value, dict):
            return {
                WebHookPlayer._json_value(key): WebHookPlayer._json_value(item)
                for key, item in value.items()
            }
        return value

    @staticmethod
    def _action_from_json(data):
        value = data[2]
        if isinstance(value, list):
            if data[1] in {"BUILD_ROAD", "PLAY_YEAR_OF_PLENTY", "MARITIME_TRADE"}:
                value = tuple(value)
            elif data[1] == "MOVE_ROBBER":
                coordinate, victim = value
                value = (tuple(coordinate), Color[victim] if victim else None)
        return Action(Color[data[0]], ActionType[data[1]], value)
