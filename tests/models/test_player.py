from catanatron.models.enums import Action, ActionType
from catanatron.state import State
from catanatron.state_functions import (
    player_clean_turn,
    player_can_play_dev,
    player_deck_replenish,
)
from catanatron.game import Game
from catanatron.models.player import Color, SimplePlayer, HumanPlayer, RandomPlayer, WebHookPlayer


def test_playable_cards():
    player = SimplePlayer(Color.RED)

    state = State([player])
    player_deck_replenish(state, Color.RED, "KNIGHT")
    player_clean_turn(state, Color.RED)

    assert player_can_play_dev(state, Color.RED, "KNIGHT")


def test_human_player_asks_for_input():
    # Arrange
    # Create a mock input provider function
    def mock_input_function(prompt):
        return "1"

    player = HumanPlayer(Color.BLUE, input_fn=mock_input_function)

    # Create mock actions
    playable_actions = [
        Action(Color.BLUE, ActionType.BUY_DEVELOPMENT_CARD, None),
        Action(Color.BLUE, ActionType.END_TURN, None),
    ]

    # Act
    chosen_action = player.decide(None, playable_actions)

    # Assert
    assert chosen_action == playable_actions[1]  # Should select the END_TURN action


def test_webhook_player_sends_structured_legal_actions_and_selects_action_id(monkeypatch):
    player = WebHookPlayer(Color.RED, "http://example.test/decide", name="Codex")
    game = Game([player, RandomPlayer(Color.BLUE)], seed=1)
    selected = game.playable_actions[1]
    selected_id = WebHookPlayer._action_id(1, selected)
    captured_payload = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return json.dumps(
                {"action_id": selected_id, "reason": "test legal id"}
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured_payload.update(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    action = player.decide(game, game.playable_actions)

    assert action == selected
    assert captured_payload["legal_actions"][1] == {
        "id": selected_id,
        "index": 1,
        "type": selected.action_type.value,
        "value": WebHookPlayer._json_value(selected.value),
        "action": WebHookPlayer._action_to_json(selected),
    }
    assert captured_payload["strategy"]["response_schema"]["action_id"] == (
        "string from legal_actions[].id"
    )
    assert captured_payload["strategy"]["self"]["color"] == "RED"


def test_webhook_strategy_does_not_reveal_opponent_hidden_victory_points():
    player = WebHookPlayer(Color.RED, "http://example.test/decide", name="Codex")
    game = Game([player, RandomPlayer(Color.BLUE)], seed=1)
    game.state.player_state["P1_VICTORY_POINT_IN_HAND"] = 1
    game.state.player_state["P1_ACTUAL_VICTORY_POINTS"] += 1

    legal_actions = [
        WebHookPlayer._legal_action_to_json(index, action)
        for index, action in enumerate(game.playable_actions)
    ]
    strategy = player._strategy_to_json(game, legal_actions)
    opponent = next(item for item in strategy["players"] if item["color"] == "BLUE")

    assert "actual_victory_points" not in opponent
    assert "resources" not in opponent
    assert "development_cards" not in opponent
    assert opponent["development_card_count"] == 1
