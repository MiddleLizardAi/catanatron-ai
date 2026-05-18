import random
import builtins
import json
import urllib.request

from enum import Enum

from catanatron.models.enums import Action, ActionType


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
        payload = {
            "game_id": game.id,
            "color": self.color.value,
            "name": self.name,
            "state_index": len(game.state.action_records),
            "current_prompt": game.state.current_prompt.value,
            "playable_actions": [self._action_to_json(action) for action in playable_actions],
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
    def _action_to_json(action):
        value = action.value
        if isinstance(value, tuple):
            value = list(value)
        return [action.color.value, action.action_type.value, value]

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
