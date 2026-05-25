#!/usr/bin/env python3
import argparse
import copy
import json
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from heapq import heappop, heappush


DEFAULT_STRATEGY = {
    "production_weights": {
        "6": 5,
        "8": 5,
        "5": 4,
        "9": 4,
        "4": 3,
        "10": 3,
        "3": 2,
        "11": 2,
        "2": 1,
        "12": 1,
    },
    "resource_priority": {
        "WHEAT": 1.35,
        "ORE": 1.3,
        "SHEEP": 1.15,
        "WOOD": 1,
        "BRICK": 1,
    },
    "scoring": {
        "production_weight": 1,
        "resource_diversity_bonus": 0.75,
        "ore_wheat_sheep_combo_bonus": 1.6,
        "road_target_node_weight": 1,
        "discard_count_weight": 10,
        "discard_keep_priority_weight": 1.6,
        "year_of_plenty_scarcity_target": 3,
        "year_of_plenty_priority_weight": 1.4,
    },
    "robber": {
        "public_leader_bonus": 5,
        "victim_bonus": 2,
        "tile_production_weight": 1,
        "avoid_self_blocking_penalty": 4,
    },
    "action_priority": [
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
    ],
}

STRATEGY = copy.deepcopy(DEFAULT_STRATEGY)
DECISION_LOG_PATH = None
MARITIME_TRADE_COUNTS = {}
RESOURCE_COSTS = {
    "CITY": {"ORE": 3, "WHEAT": 2},
    "SETTLEMENT": {"WOOD": 1, "BRICK": 1, "SHEEP": 1, "WHEAT": 1},
    "DEVELOPMENT_CARD": {"ORE": 1, "SHEEP": 1, "WHEAT": 1},
    "ROAD": {"WOOD": 1, "BRICK": 1},
}
RESOURCE_TYPES = ("WOOD", "BRICK", "SHEEP", "WHEAT", "ORE")
TACTICAL_DEVELOPMENT_TYPES = (
    "KNIGHT",
    "YEAR_OF_PLENTY",
    "MONOPOLY",
    "ROAD_BUILDING",
)


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


def deep_merge(base, override):
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_strategy(path):
    if path is None:
        return copy.deepcopy(DEFAULT_STRATEGY)

    with open(path, "r", encoding="utf-8") as strategy_file:
        loaded = json.load(strategy_file)
    return deep_merge(DEFAULT_STRATEGY, loaded)


def production_weight(strategy, number):
    return strategy.get("production_weights", {}).get(str(number), 0)


def resource_priority(strategy, resource):
    return strategy.get("resource_priority", {}).get(resource, 1)


def color_index(state, color):
    try:
        return state.get("colors", []).index(color)
    except ValueError:
        return 0


def resource_count(state, color, resource):
    index = color_index(state, color)
    return state.get("player_state", {}).get(f"P{index}_{resource}_IN_HAND", 0)


def player_state_value(state, color, name, default=0):
    index = color_index(state, color)
    return state.get("player_state", {}).get(f"P{index}_{name}", default)


def actual_victory_points(state, color):
    return player_state_value(state, color, "ACTUAL_VICTORY_POINTS", 0)


def is_endgame(state, color, strategy):
    return actual_victory_points(state, color) >= strategy.get("endgame", {}).get(
        "threshold_vp", 8
    )


def player_resource_total(state, color):
    return sum(resource_count(state, color, resource) for resource in RESOURCE_TYPES)


def resource_counts(state, color):
    return {resource: resource_count(state, color, resource) for resource in RESOURCE_TYPES}


def development_count(state, color, card_type):
    return player_state_value(state, color, f"{card_type}_IN_HAND", 0)


def tactical_development_cards_in_hand(state, color):
    return sum(
        development_count(state, color, card_type)
        for card_type in TACTICAL_DEVELOPMENT_TYPES
    )


def blocking_tactical_development_cards_in_hand(state, color, strategy):
    card_types = list(TACTICAL_DEVELOPMENT_TYPES)
    if not strategy.get("road", {}).get("road_building_enabled", False):
        card_types.remove("ROAD_BUILDING")
    return sum(development_count(state, color, card_type) for card_type in card_types)


def is_discard_risk(state, color, strategy):
    return player_resource_total(state, color) > strategy.get("hand_management", {}).get(
        "discard_risk_threshold", 7
    )


def production_resources_for_color(state, color):
    resources = set()
    for node in nodes_by_id(state).values():
        if node.get("color") != color:
            continue
        for tile in state.get("adjacent_tiles", {}).get(str(node.get("id")), []):
            if tile.get("type") == "RESOURCE_TILE":
                resources.add(tile.get("resource"))
    return resources


def production_pips_for_color(state, color, strategy):
    pips = {resource: 0 for resource in RESOURCE_TYPES}
    for node in nodes_by_id(state).values():
        if node.get("color") != color:
            continue
        multiplier = 2 if node.get("building") == "CITY" else 1
        for tile in state.get("adjacent_tiles", {}).get(str(node.get("id")), []):
            if tile.get("type") == "RESOURCE_TILE":
                resource = tile.get("resource")
                pips[resource] = pips.get(resource, 0) + (
                    production_weight(strategy, tile.get("number")) * multiplier
                )
    return pips


def building_count_for_color(state, color):
    return sum(1 for node in nodes_by_id(state).values() if node.get("color") == color)


def board_piece_counts(state, color):
    nodes = nodes_by_id(state).values()
    settlements = sum(
        1
        for node in nodes
        if node.get("color") == color and node.get("building") == "SETTLEMENT"
    )
    cities = sum(
        1
        for node in nodes_by_id(state).values()
        if node.get("color") == color and node.get("building") == "CITY"
    )
    roads = sum(1 for edge in state.get("edges", []) if edge.get("color") == color)
    return {"settlements": settlements, "cities": cities, "roads": roads}


def road_debt_for_state(state, color, strategy):
    pieces = board_piece_counts(state, color)
    road_strategy = strategy.get("road", {})
    road_allowance = road_strategy.get("roads_per_building_allowance", 1.35)
    free_road_buffer = road_strategy.get("free_road_buffer", 1)
    return max(
        0,
        pieces["roads"]
        - int((pieces["settlements"] + pieces["cities"]) * road_allowance)
        - free_road_buffer,
    )


def needs_expansion_pressure(state, color, strategy):
    pieces = board_piece_counts(state, color)
    if player_state_value(state, color, "SETTLEMENTS_AVAILABLE", 0) <= 0:
        return False

    road_strategy = strategy.get("road", {})
    building_target = road_strategy.get("expansion_pressure_building_target", 4)
    city_trigger = road_strategy.get("expansion_pressure_city_trigger", 2)
    return (
        pieces["settlements"] + pieces["cities"] < building_target
        or (
            pieces["settlements"] == 0
            and pieces["cities"] >= city_trigger
        )
    )


def settlement_missing_after_road(state, color):
    return settlement_missing_after_roads(state, color, 1)


def settlement_missing_after_roads(state, color, roads_to_add):
    counts = resource_counts(state, color)
    counts["WOOD"] = max(0, counts["WOOD"] - RESOURCE_COSTS["ROAD"]["WOOD"] * roads_to_add)
    counts["BRICK"] = max(0, counts["BRICK"] - RESOURCE_COSTS["ROAD"]["BRICK"] * roads_to_add)
    return sum(
        max(0, required - counts.get(resource, 0))
        for resource, required in RESOURCE_COSTS["SETTLEMENT"].items()
    )


def direct_settlement_target_after_road(action, state, color, strategy):
    edge = action_value(action)
    if not isinstance(edge, list) or len(edge) != 2:
        return None

    min_target_score = strategy.get("road", {}).get("settlement_target_min_score", 0)
    candidates = []
    for node_id in edge:
        if is_settlement_candidate_node(state, node_id):
            target_score = settlement_target_score(
                state,
                node_id,
                strategy,
                color,
                extra_edge=edge,
                distance=0,
                spent_roads=1,
            )
            if target_score >= min_target_score:
                candidates.append((target_score, node_id))
    if not candidates:
        return None
    return max(candidates)


def road_has_near_settlement_plan(action, state, color, strategy):
    road_strategy = strategy.get("road", {})
    if direct_settlement_target_after_road(action, state, color, strategy) is None:
        if not needs_expansion_pressure(state, color, strategy):
            return False
        if road_debt_for_state(state, color, strategy) > road_strategy.get(
            "max_road_debt_for_indirect_route",
            1,
        ):
            return False

        current_route_score = best_route_target_score(state, color, strategy)
        next_route_score = best_route_target_score(
            state, color, strategy, extra_edge=action_value(action)
        )
        if next_route_score is None:
            return False
        if current_route_score is not None and next_route_score <= current_route_score:
            return False
        return settlement_missing_after_road(state, color) <= road_strategy.get(
            "expansion_pressure_max_settlement_missing_after_road", 2
        )

    return settlement_missing_after_road(state, color) <= road_strategy.get(
        "max_settlement_missing_after_road", 1
    )


def should_require_near_settlement_for_road(state, color, strategy):
    if should_chase_longest_road(state, color, strategy):
        return False
    road_strategy = strategy.get("road", {})
    if not road_strategy.get("require_near_settlement_after_opening", True):
        return False
    pieces = board_piece_counts(state, color)
    opening_buildings = road_strategy.get("opening_building_count", 2)
    opening_roads = road_strategy.get("opening_road_count", 2)
    return (
        pieces["settlements"] + pieces["cities"] >= opening_buildings
        and pieces["roads"] >= opening_roads
    )


def nodes_by_id(state):
    nodes = state.get("nodes", {})
    if isinstance(nodes, dict):
        return {int(node_id): node for node_id, node in nodes.items()}
    return {node.get("id"): node for node in nodes if isinstance(node, dict)}


def node_record(state, node_id):
    return nodes_by_id(state).get(node_id) or nodes_by_id(state).get(str(node_id))


def edge_touches_node(edge, node_id):
    edge_id = edge.get("id")
    return isinstance(edge_id, list) and node_id in edge_id


def normalized_edge_id(edge_id):
    if not isinstance(edge_id, (list, tuple)) or len(edge_id) != 2:
        return None
    try:
        return tuple(sorted((int(edge_id[0]), int(edge_id[1]))))
    except (TypeError, ValueError):
        return tuple(sorted(edge_id))


def neighboring_node_ids(state, node_id):
    neighbors = set()
    for edge in state.get("edges", []):
        if not edge_touches_node(edge, node_id):
            continue
        edge_id = edge.get("id", [])
        if len(edge_id) != 2:
            continue
        neighbors.add(edge_id[0] if edge_id[1] == node_id else edge_id[1])
    return neighbors


def is_settlement_candidate_node(state, node_id):
    nodes = nodes_by_id(state)
    node = nodes.get(node_id)
    if not node or node.get("color") is not None:
        return False
    return all(
        not nodes.get(neighbor_id) or nodes[neighbor_id].get("color") is None
        for neighbor_id in neighboring_node_ids(state, node_id)
    )


def own_network_nodes(state, color, extra_edge=None):
    nodes = {
        node_id
        for node_id, node in nodes_by_id(state).items()
        if node.get("color") == color
    }
    extra_key = normalized_edge_id(extra_edge)
    for edge in state.get("edges", []):
        edge_id = edge.get("id")
        if not isinstance(edge_id, list) or len(edge_id) != 2:
            continue
        if edge.get("color") == color or normalized_edge_id(edge_id) == extra_key:
            nodes.update(edge_id)
    if isinstance(extra_edge, list) and len(extra_edge) == 2:
        nodes.update(extra_edge)
    return nodes


def traversable_road_neighbors(state, node_id, color, extra_edge=None):
    nodes = nodes_by_id(state)
    extra_key = normalized_edge_id(extra_edge)
    current_node = nodes.get(node_id)
    if current_node and current_node.get("color") not in (None, color):
        return

    for edge in state.get("edges", []):
        if not edge_touches_node(edge, node_id):
            continue
        edge_id = edge.get("id", [])
        if len(edge_id) != 2:
            continue
        edge_key = normalized_edge_id(edge_id)
        edge_color = edge.get("color")
        if edge_key == extra_key or edge_color == color:
            cost = 0
        elif edge_color is None:
            cost = 1
        else:
            continue

        other_node_id = edge_id[0] if edge_id[1] == node_id else edge_id[1]
        other_node = nodes.get(other_node_id)
        if other_node and other_node.get("color") not in (None, color):
            continue
        yield other_node_id, cost


def road_distance_to_node(state, color, target_node_id, strategy, extra_edge=None, max_depth=None):
    road_strategy = strategy.get("road", {})
    if max_depth is None:
        max_depth = road_strategy.get("route_lookahead_depth", 3)

    starts = own_network_nodes(state, color, extra_edge=extra_edge)
    if not starts:
        return None
    if target_node_id in starts:
        return 0

    distances = {}
    queue = []
    for node_id in starts:
        distances[node_id] = 0
        heappush(queue, (0, node_id))

    while queue:
        distance, node_id = heappop(queue)
        if distance != distances.get(node_id):
            continue
        if distance >= max_depth:
            continue

        for neighbor_id, cost in traversable_road_neighbors(
            state,
            node_id,
            color,
            extra_edge=extra_edge,
        ):
            next_distance = distance + cost
            if next_distance > max_depth:
                continue
            if neighbor_id == target_node_id:
                return next_distance
            if next_distance < distances.get(neighbor_id, max_depth + 1):
                distances[neighbor_id] = next_distance
                heappush(queue, (next_distance, neighbor_id))

    return None


def opponent_colors(state, color):
    return [candidate for candidate in state.get("colors", []) if candidate != color]


def settlement_target_contest_penalty(
    state,
    node_id,
    color,
    strategy,
    our_distance,
    our_missing,
):
    race = strategy.get("settlement_race", {})
    if not race.get("enabled", True):
        return 0
    if our_distance is None:
        return 0
    if our_distance == 0 and our_missing <= race.get("secure_if_missing_at_most", 0):
        return 0

    distance_margin = race.get("distance_margin", 1)
    resource_margin = race.get("resource_missing_margin", 0)
    search_depth = max(
        race.get("min_search_depth", 2),
        our_distance + distance_margin,
    )
    penalty = 0
    for opponent in opponent_colors(state, color):
        opponent_distance = road_distance_to_node(
            state,
            opponent,
            node_id,
            strategy,
            max_depth=search_depth,
        )
        if opponent_distance is None:
            continue

        opponent_missing = settlement_missing_after_roads(
            state,
            opponent,
            opponent_distance,
        )
        if opponent_distance == 0 and opponent_missing == 0 and our_missing > 0:
            penalty = max(penalty, race.get("opponent_can_build_now_penalty", 16))
        elif opponent_distance < our_distance:
            penalty = max(penalty, race.get("opponent_closer_penalty", 10))
        elif opponent_distance == our_distance and opponent_missing <= our_missing + resource_margin:
            penalty = max(penalty, race.get("opponent_tie_penalty", 6))
        elif (
            opponent_distance <= our_distance + distance_margin
            and opponent_missing <= our_missing + resource_margin
        ):
            penalty = max(penalty, race.get("opponent_nearby_penalty", 3))

    return penalty


def settlement_target_score(
    state,
    node_id,
    strategy,
    color=None,
    extra_edge=None,
    distance=None,
    spent_roads=0,
):
    score = node_score(state, node_id, strategy, color)
    if color is None:
        return score

    if distance is None:
        distance = road_distance_to_node(
            state,
            color,
            node_id,
            strategy,
            extra_edge=extra_edge,
        )
    if distance is None:
        return score

    our_missing = settlement_missing_after_roads(state, color, spent_roads + distance)
    return score - settlement_target_contest_penalty(
        state,
        node_id,
        color,
        strategy,
        distance,
        our_missing,
    )


def best_route_target_score(state, color, strategy, extra_edge=None):
    road_strategy = strategy.get("road", {})
    max_depth = road_strategy.get("route_lookahead_depth", 3)
    step_penalty = road_strategy.get("route_step_penalty", 1.2)
    min_target_score = road_strategy.get("settlement_target_min_score", 0)
    starts = own_network_nodes(state, color, extra_edge=extra_edge)
    if not starts:
        return None

    distances = {}
    queue = []
    for node_id in starts:
        distances[node_id] = 0
        heappush(queue, (0, node_id))

    best = None
    while queue:
        distance, node_id = heappop(queue)
        if distance != distances.get(node_id):
            continue

        if is_settlement_candidate_node(state, node_id):
            target_score = settlement_target_score(
                state,
                node_id,
                strategy,
                color,
                extra_edge=extra_edge,
                distance=distance,
                spent_roads=1 if extra_edge is not None else 0,
            )
            if target_score >= min_target_score:
                adjusted_score = target_score - distance * step_penalty
                best = adjusted_score if best is None else max(best, adjusted_score)

        if distance >= max_depth:
            continue

        for neighbor_id, cost in traversable_road_neighbors(
            state, node_id, color, extra_edge=extra_edge
        ):
            next_distance = distance + cost
            if next_distance > max_depth:
                continue
            if next_distance < distances.get(neighbor_id, max_depth + 1):
                distances[neighbor_id] = next_distance
                heappush(queue, (next_distance, neighbor_id))

    return best


def adjacent_human_pressure(state, node_id, color):
    pressure = 0
    human_colors = {
        player.get("color")
        for player in state.get("players", [])
        if not player.get("is_bot") and player.get("color") != color
    }
    if not human_colors:
        return 0

    nodes = nodes_by_id(state)
    for edge in state.get("edges", []):
        if not edge_touches_node(edge, node_id):
            continue
        edge_id = edge.get("id", [])
        other_node_id = edge_id[0] if edge_id[1] == node_id else edge_id[1]
        other_node = nodes.get(other_node_id)
        if other_node and other_node.get("color") in human_colors:
            pressure += 1
        if edge.get("color") in human_colors:
            pressure += 1
    return pressure


def tile_record_at_coordinate(state, coordinate):
    coordinate = list(coordinate)
    for item in state.get("tiles", []):
        if item.get("coordinate") == coordinate:
            return item.get("tile", {})
    return {}


def tile_nodes_for_coordinate(state, coordinate):
    tile = tile_record_at_coordinate(state, coordinate)
    nodes = tile.get("nodes") or {}
    return set(nodes.values())


def node_port_resources(state, node_id):
    resources = set()
    for item in state.get("tiles", []):
        tile = item.get("tile", {})
        if tile.get("type") != "PORT":
            continue
        if node_id in (tile.get("nodes") or {}).values():
            resources.add(tile.get("resource"))
    return resources


def port_bonus(state, node_id, resources, strategy):
    port_strategy = strategy.get("ports", {})
    bonus = 0
    for port_resource in node_port_resources(state, node_id):
        if port_resource == "ORE":
            bonus += port_strategy.get("ore_port_bonus", 0)
        elif port_resource in resources:
            bonus += port_strategy.get("matching_resource_port_bonus", 0)
        elif port_resource is None:
            bonus += port_strategy.get("generic_port_bonus", 0)
        else:
            bonus += port_strategy.get("other_port_bonus", 0)
    return bonus


def node_score(state, node_id, strategy, color=None):
    adjacent_tiles = state.get("adjacent_tiles", {}).get(str(node_id), [])
    resources = set()
    resource_pips = {}
    score = 0
    scoring = strategy.get("scoring", {})
    coverage = strategy.get("resource_coverage", {})
    existing_resources = (
        production_resources_for_color(state, color) if color is not None else set()
    )
    combined_resources = resources | existing_resources

    for tile in adjacent_tiles:
        if tile.get("type") != "RESOURCE_TILE":
            continue
        resource = tile.get("resource")
        resources.add(resource)
        combined_resources.add(resource)
        resource_pips[resource] = resource_pips.get(resource, 0) + production_weight(
            strategy, tile.get("number")
        )
        score += (
            production_weight(strategy, tile.get("number"))
            * resource_priority(strategy, resource)
            * scoring.get("production_weight", 1)
        )

    if {"ORE", "WHEAT", "SHEEP"}.issubset(resources):
        score += scoring.get("ore_wheat_sheep_combo_bonus", 0)

    if {"ORE", "WHEAT"}.issubset(resources):
        score += coverage.get("ore_wheat_pair_bonus", 0)
    if "ORE" in resources and "WHEAT" not in resources:
        score -= coverage.get("ore_without_wheat_penalty", 0)

    building_count = building_count_for_color(state, color) if color is not None else 0
    apply_opening_coverage = color is None or building_count < 2
    if apply_opening_coverage:
        min_unique = coverage.get("min_unique_resources", 0)
        resources_for_coverage = (
            combined_resources if color is not None and building_count > 0 else resources
        )
        target_unique = min_unique if building_count > 0 else min(min_unique, 3)
        if len(resources_for_coverage) < target_unique:
            score -= (target_unique - len(resources_for_coverage)) * coverage.get("under_min_unique_penalty", 0)

        for resource in coverage.get("must_cover_for_expansion", []):
            if resource not in combined_resources:
                score -= coverage.get("missing_expansion_resource_penalty", 0)

        if color is not None and building_count > 0:
            concentration = strategy.get("resource_concentration", {})
            missing_expansion_resources = [
                resource
                for resource in coverage.get("must_cover_for_expansion", [])
                if resource not in combined_resources
            ]
            if missing_expansion_resources:
                existing_pips = production_pips_for_color(state, color, strategy)
                ports = node_port_resources(state, node_id)
                has_generic_port = None in ports
                for resource, pips in resource_pips.items():
                    if existing_pips.get(resource, 0) <= 0:
                        continue
                    penalty = pips * concentration.get("opening_duplicate_pip_penalty", 0)
                    if resource not in ports and not has_generic_port:
                        penalty += pips * concentration.get(
                            "opening_surplus_without_port_pip_penalty",
                            0,
                        )
                    if resource == "SHEEP":
                        penalty *= concentration.get(
                            "sheep_surplus_without_port_multiplier",
                            1,
                        )
                    score -= penalty

    if color is not None:
        for resource in resources:
            if resource not in existing_resources:
                score += coverage.get("missing_current_resource_bonus", 0)

    score += len(resources) * scoring.get("resource_diversity_bonus", 0.75)
    score += port_bonus(state, node_id, resources, strategy)

    if color is not None:
        score -= adjacent_human_pressure(state, node_id, color) * strategy.get(
            "human_conflict", {}
        ).get("adjacent_human_penalty", 0)

    return score


def choose_best_node_action(actions, state, strategy, color=None):
    return max(actions, key=lambda action: node_score(state, action_value(action), strategy, color))


def choose_best_city_action(actions, state, strategy, color=None):
    return max(actions, key=lambda action: node_score(state, action_value(action), strategy, color))


def score_road_action(action, state, color, strategy):
    road_strategy = strategy.get("road", {})
    road_weight = strategy.get("scoring", {}).get("road_target_node_weight", 1)
    route_weight = road_strategy.get("route_improvement_weight", 1.6)
    edge = action_value(action)
    if not isinstance(edge, list) or len(edge) != 2:
        return 0

    nodes = nodes_by_id(state)
    endpoint_scores = []
    for node_id in edge:
        if is_settlement_candidate_node(state, node_id):
            target_score = settlement_target_score(
                state,
                node_id,
                strategy,
                color,
                extra_edge=edge,
                distance=0,
                spent_roads=1,
            )
        else:
            target_score = -road_strategy.get("non_settlement_endpoint_penalty", 0)
        node = nodes.get(node_id)
        if node and node.get("color") is not None:
            if node.get("color") == color:
                target_score -= road_strategy.get("own_building_endpoint_penalty", 0)
            else:
                target_score -= road_strategy.get("occupied_endpoint_penalty", 0)
        endpoint_scores.append(target_score)

    direct_target_score = max(endpoint_scores)
    current_route_score = best_route_target_score(state, color, strategy)
    next_route_score = best_route_target_score(state, color, strategy, extra_edge=edge)
    route_improvement = 0
    if next_route_score is not None:
        route_improvement = next_route_score
        if current_route_score is not None:
            route_improvement = max(0, next_route_score - current_route_score)

    score = road_weight * direct_target_score + route_weight * route_improvement

    piece_counts = board_piece_counts(state, color)
    road_debt = road_debt_for_state(state, color, strategy)
    missing_after_road = settlement_missing_after_road(state, color)
    chasing_longest = should_chase_longest_road(state, color, strategy)
    if road_debt > 0 and not chasing_longest:
        score -= road_debt * road_strategy.get("road_debt_penalty", 2.4)
        if missing_after_road > road_strategy.get("max_settlement_missing_after_road", 1):
            score -= road_strategy.get("far_from_settlement_penalty", 4.0)

    if (
        piece_counts["settlements"] + piece_counts["cities"]
        >= road_strategy.get("city_transition_building_count", 3)
        and piece_counts["cities"] < road_strategy.get("city_transition_min_cities", 2)
        and missing_after_road > road_strategy.get("max_settlement_missing_after_road", 1)
        and not chasing_longest
    ):
        score -= road_strategy.get("city_transition_road_penalty", 3.0)

    score -= adjacent_human_pressure(state, edge[0], color) * strategy.get(
        "human_conflict", {}
    ).get("road_race_penalty", 0)
    score -= adjacent_human_pressure(state, edge[1], color) * strategy.get(
        "human_conflict", {}
    ).get("road_race_penalty", 0)

    if direct_target_score < road_strategy.get("settlement_target_min_score", 0) and (
        next_route_score is None
        or next_route_score < road_strategy.get("settlement_target_min_score", 0)
    ):
        score -= road_strategy.get("no_settlement_target_penalty", 0)

    return score


def choose_best_road_action(actions, state, color, strategy):
    return max(actions, key=lambda action: score_road_action(action, state, color, strategy))


def own_road_degree_by_node(state, color):
    degrees = {}
    for edge in state.get("edges", []):
        if edge.get("color") != color:
            continue
        edge_id = edge.get("id")
        if not isinstance(edge_id, list) or len(edge_id) != 2:
            continue
        degrees[edge_id[0]] = degrees.get(edge_id[0], 0) + 1
        degrees[edge_id[1]] = degrees.get(edge_id[1], 0) + 1
    return degrees


def resource_tiles_for_node(state, node_id):
    return [
        tile
        for tile in state.get("adjacent_tiles", {}).get(str(node_id), [])
        if tile.get("type") == "RESOURCE_TILE"
    ]


def road_committed_route_profile(action, state, color, strategy):
    edge = action_value(action)
    if not isinstance(edge, list) or len(edge) != 2:
        return None

    nodes = nodes_by_id(state)
    own_degrees = own_road_degree_by_node(state, color)
    profiles = []
    for target_node_id, anchor_node_id in (
        (edge[0], edge[1]),
        (edge[1], edge[0]),
    ):
        if own_degrees.get(anchor_node_id, 0) <= 0:
            continue
        anchor = nodes.get(anchor_node_id)
        if anchor and anchor.get("color") not in (None, color):
            continue
        if not is_settlement_candidate_node(state, target_node_id):
            continue

        resource_tiles = resource_tiles_for_node(state, target_node_id)
        target_score = settlement_target_score(
            state,
            target_node_id,
            strategy,
            color,
            extra_edge=edge,
            distance=0,
            spent_roads=1,
        )
        profiles.append(
            {
                "target_node": target_node_id,
                "anchor_node": anchor_node_id,
                "resource_hexes": len(resource_tiles),
                "target_pips": sum(
                    production_weight(strategy, tile.get("number"))
                    for tile in resource_tiles
                ),
                "target_score": target_score,
                "anchor_road_degree": own_degrees.get(anchor_node_id, 0),
            }
        )

    if not profiles:
        return None
    return max(
        profiles,
        key=lambda profile: (
            profile["resource_hexes"],
            profile["target_pips"],
            profile["target_score"],
        ),
    )


def catanatron_search_road_override(payload, strategy, recommended_action):
    search_strategy = strategy.get("catanatron_search", {})
    if not search_strategy.get("road_override_enabled", False):
        return None
    if payload.get("current_prompt") != "PLAY_TURN":
        return None
    if action_type(recommended_action) != "BUILD_ROAD":
        return None

    state = payload.get("state", {})
    color = payload.get("color")
    actions = payload.get("legal_actions") or payload.get("playable_actions", [])
    road_candidates = [
        (index, action)
        for index, action in enumerate(actions)
        if action_type(action) == "BUILD_ROAD"
    ]
    if len(road_candidates) < 2:
        return None

    recommended_score = score_road_action(recommended_action, state, color, strategy)
    best_index, best_action = max(
        road_candidates,
        key=lambda item: score_road_action(item[1], state, color, strategy),
    )
    if same_action(best_action, recommended_action):
        return None

    best_score = score_road_action(best_action, state, color, strategy)
    profile = road_committed_route_profile(best_action, state, color, strategy)
    if profile is None:
        return None
    if best_score < search_strategy.get("road_override_min_score", 7):
        return None
    if best_score - recommended_score < search_strategy.get("road_override_min_margin", 4):
        return None
    if profile["resource_hexes"] < search_strategy.get("road_override_min_target_resource_hexes", 3):
        return None
    if profile["target_pips"] < search_strategy.get("road_override_min_target_pips", 8):
        return None

    selected_id, selected_index = action_id(best_action, best_index)
    return (
        selected_id,
        selected_index,
        (
            "catanatron search road override: committed route to "
            f"{profile['resource_hexes']}-hex target"
        ),
    )


def catanatron_search_initial_road_override(payload, strategy, recommended_action):
    search_strategy = strategy.get("catanatron_search", {})
    if not search_strategy.get("initial_road_override_enabled", False):
        return None
    if payload.get("current_prompt") != "BUILD_INITIAL_ROAD":
        return None
    if action_type(recommended_action) != "BUILD_ROAD":
        return None

    state = payload.get("state", {})
    color = payload.get("color")
    actions = payload.get("legal_actions") or payload.get("playable_actions", [])
    road_candidates = [
        (index, action)
        for index, action in enumerate(actions)
        if action_type(action) == "BUILD_ROAD"
    ]
    if len(road_candidates) < 2:
        return None

    recommended_score = initial_road_score(recommended_action, state, color, strategy)
    best_index, best_action = max(
        road_candidates,
        key=lambda item: initial_road_score(item[1], state, color, strategy),
    )
    if same_action(best_action, recommended_action):
        return None

    best_score = initial_road_score(best_action, state, color, strategy)
    if best_score < search_strategy.get("initial_road_override_min_score", 4):
        return None
    if best_score - recommended_score < search_strategy.get(
        "initial_road_override_min_margin",
        2.5,
    ):
        return None

    selected_id, selected_index = action_id(best_action, best_index)
    return (
        selected_id,
        selected_index,
        "catanatron search initial road override: stronger opening route",
    )


def catanatron_search_city_override(payload, strategy, recommended_action):
    search_strategy = strategy.get("catanatron_search", {})
    if not search_strategy.get("city_override_enabled", False):
        return None
    if payload.get("current_prompt") != "PLAY_TURN":
        return None
    if action_type(recommended_action) != "BUILD_CITY":
        return None

    state = payload.get("state", {})
    color = payload.get("color")
    actions = payload.get("legal_actions") or payload.get("playable_actions", [])
    city_candidates = [
        (index, action)
        for index, action in enumerate(actions)
        if action_type(action) == "BUILD_CITY"
    ]
    if len(city_candidates) < 2:
        return None

    recommended_score = node_score(state, action_value(recommended_action), strategy, color)
    best_index, best_action = max(
        city_candidates,
        key=lambda item: node_score(state, action_value(item[1]), strategy, color),
    )
    if same_action(best_action, recommended_action):
        return None

    best_score = node_score(state, action_value(best_action), strategy, color)
    if best_score < search_strategy.get("city_override_min_score", 0):
        return None
    if best_score - recommended_score < search_strategy.get(
        "city_override_min_margin",
        2.5,
    ):
        return None

    selected_id, selected_index = action_id(best_action, best_index)
    return (
        selected_id,
        selected_index,
        "catanatron search city override: upgrade stronger production node",
    )


def road_action_min_score(state, color, strategy, hand_pressure=False):
    min_score = strategy.get("road", {}).get("min_score", 0)
    if hand_pressure:
        return strategy.get("hand_management", {}).get(
            "discard_risk_road_min_score",
            min_score,
        )
    return min_score


def road_action_is_strategy_approved(action, state, color, strategy, hand_pressure=False):
    if not endgame_road_action_is_strictly_approved(action, state, color, strategy):
        return False
    score = score_road_action(action, state, color, strategy)
    if should_chase_longest_road(state, color, strategy):
        return score >= strategy.get("road", {}).get("longest_road_min_score", -999)

    if (
        should_require_near_settlement_for_road(state, color, strategy)
        and not road_has_near_settlement_plan(action, state, color, strategy)
    ):
        return False

    return score >= road_action_min_score(state, color, strategy, hand_pressure)


def initial_road_score(action, state, color, strategy):
    edge = action_value(action)
    if not isinstance(edge, list) or len(edge) != 2:
        return -999

    route_score = best_route_target_score(state, color, strategy, extra_edge=edge)
    if route_score is not None:
        return route_score

    nodes = nodes_by_id(state)
    endpoint_scores = []
    for node_id in edge:
        node = nodes.get(node_id)
        if node and node.get("color") == color:
            continue
        if node and node.get("color") is not None:
            endpoint_scores.append(-10)
            continue
        endpoint_scores.append(node_score(state, node_id, strategy, color))
    return max(endpoint_scores or [-999])


def choose_initial_road_action(actions, state, color, strategy):
    return max(actions, key=lambda action: initial_road_score(action, state, color, strategy))


def longest_road_gap(state, color):
    own = player_state_value(state, color, "LONGEST_ROAD_LENGTH", 0)
    opponents = [
        player_state_value(state, other_color, "LONGEST_ROAD_LENGTH", 0)
        for other_color in state.get("colors", [])
        if other_color != color
    ]
    return own - max(opponents or [0])


def road_can_flip_longest_road(state, color, roads_to_add=1):
    own = player_state_value(state, color, "LONGEST_ROAD_LENGTH", 0)
    opponents = [
        player_state_value(state, other_color, "LONGEST_ROAD_LENGTH", 0)
        for other_color in state.get("colors", [])
        if other_color != color
    ]
    opponent_best = max(opponents or [0])
    return own + roads_to_add >= max(5, opponent_best + 1)


def should_chase_longest_road(state, color, strategy, roads_to_add=1):
    threshold = strategy.get("road", {}).get("longest_road_chase_min_vp", 8)
    return actual_victory_points(state, color) >= threshold and road_can_flip_longest_road(
        state, color, roads_to_add=roads_to_add
    )


def should_play_road_building(state, color, strategy):
    road_strategy = strategy.get("road", {})
    if not road_strategy.get("road_building_enabled", False):
        return False

    return should_chase_longest_road(state, color, strategy, roads_to_add=2)


def choose_discard_action(actions, state, color, strategy):
    scoring = strategy.get("scoring", {})
    hand = strategy.get("hand_management", {})
    keep_targets = hand.get("discard_keep_targets", {})

    return max(
        actions,
        key=lambda action: discard_score(action, state, color, strategy, scoring, keep_targets),
    )


def discard_score(action, state, color, strategy, scoring, keep_targets):
    resource = action_value(action)
    count = resource_count(state, color, resource)
    above_keep_target = max(0, count - keep_targets.get(resource, 0))
    city_material_penalty = 0
    if resource in RESOURCE_COSTS["CITY"] and count <= RESOURCE_COSTS["CITY"][resource]:
        city_material_penalty = scoring.get("discard_city_material_penalty", 0)
    city_reserve_penalty = city_reserve_shortfall_after(
        state,
        color,
        resource,
        max(0, count - 1),
        strategy,
    ) * scoring.get("discard_city_reserve_penalty", 0)
    return (
        count * scoring.get("discard_count_weight", 10)
        + above_keep_target * scoring.get("discard_above_keep_target_weight", 0)
        - resource_priority(strategy, resource) * scoring.get("discard_keep_priority_weight", 1.6)
        - city_material_penalty
        - city_reserve_penalty
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


def score_year_of_plenty_action(action, state, color, strategy):
    scoring = strategy.get("scoring", {})
    scarcity_target = scoring.get("year_of_plenty_scarcity_target", 3)
    priority_weight = scoring.get("year_of_plenty_priority_weight", 1.4)
    resources = action_value(action)
    if not isinstance(resources, list):
        resources = [resources]
    return sum(
        max(0, scarcity_target - resource_count(state, color, resource))
        + resource_priority(strategy, resource) * priority_weight
        for resource in resources
    )


def choose_year_of_plenty_action(actions, state, color, strategy):
    return max(actions, key=lambda action: score_year_of_plenty_action(action, state, color, strategy))


def can_afford_with_extra(state, color, plan, extra_resources):
    counts = resource_counts(state, color)
    for resource in extra_resources:
        if resource in counts:
            counts[resource] += 1
    return all(
        counts.get(resource, 0) >= amount
        for resource, amount in RESOURCE_COSTS[plan].items()
    )


def year_of_plenty_completes_plan(action, state, color, strategy):
    resources = action_value(action)
    if not isinstance(resources, list):
        resources = [resources]

    for plan in ("CITY", "SETTLEMENT", "DEVELOPMENT_CARD"):
        if plan_is_available(state, color, plan, strategy) and can_afford_with_extra(
            state, color, plan, resources
        ):
            return True
    return False


def current_turn_action_count(state, color, action_type_name):
    count = 0
    for record in reversed(state.get("action_records", [])):
        action = record[0] if isinstance(record, list) and record else None
        if not isinstance(action, list) or len(action) < 2:
            continue
        action_color, action_type_name_seen = action[0], action[1]
        if action_color != color:
            break
        if action_type_name_seen == action_type_name:
            count += 1
    return count


def current_game_action_count(state, color, action_type_name):
    count = 0
    for record in state.get("action_records", []):
        action = record[0] if isinstance(record, list) and record else None
        if (
            isinstance(action, list)
            and len(action) >= 2
            and action[0] == color
            and action[1] == action_type_name
        ):
            count += 1
    return count


def resource_deficit_score(state, color, resource, plan):
    costs = RESOURCE_COSTS[plan]
    current = resource_count(state, color, resource)
    return max(0, costs.get(resource, 0) - current)


def city_plan_is_available(state, color):
    return (
        player_state_value(state, color, "CITIES_AVAILABLE", 0) > 0
        and board_piece_counts(state, color)["settlements"] > 0
    )


def city_deficit_from_counts(counts):
    return sum(
        max(0, required - counts.get(resource, 0))
        for resource, required in RESOURCE_COSTS["CITY"].items()
    )


def city_deficit_score(state, color):
    return city_deficit_from_counts(resource_counts(state, color))


def settlement_deficit_from_counts(counts):
    return sum(
        max(0, required - counts.get(resource, 0))
        for resource, required in RESOURCE_COSTS["SETTLEMENT"].items()
    )


def endgame_settlement_mode(state, color, strategy):
    endgame = strategy.get("endgame", {})
    if not endgame.get("settlement_mode_enabled", False):
        return False
    pieces = board_piece_counts(state, color)
    return (
        actual_victory_points(state, color) >= endgame.get("settlement_mode_min_vp", 9)
        and player_state_value(state, color, "SETTLEMENTS_AVAILABLE", 0) > 0
        and (
            pieces["settlements"] > 0
            or endgame.get("settlement_mode_when_no_settlements", True)
        )
    )


def city_reserve_target(state, color, resource, strategy):
    if resource not in RESOURCE_COSTS["CITY"] or not city_plan_is_available(state, color):
        return 0

    pieces = board_piece_counts(state, color)
    dev_strategy = strategy.get("development", {})
    endgame_city_deficit_limit = strategy.get("endgame", {}).get(
        "city_reserve_max_deficit",
        4,
    )
    if pieces["cities"] < dev_strategy.get("min_cities_before_extra_dev", 1):
        return RESOURCE_COSTS["CITY"][resource]
    if is_endgame(state, color, strategy) and city_deficit_score(state, color) <= endgame_city_deficit_limit:
        return RESOURCE_COSTS["CITY"][resource]
    return 0


def city_reserve_shortfall_after(state, color, resource, after_count, strategy):
    reserve = city_reserve_target(state, color, resource, strategy)
    return max(0, reserve - after_count)


def city_materials_should_block_dev_card(state, color, strategy):
    if not city_plan_is_available(state, color):
        return False
    pieces = board_piece_counts(state, color)
    dev_strategy = strategy.get("development", {})
    if pieces["cities"] >= dev_strategy.get("min_cities_before_extra_dev", 1):
        return False
    max_missing = dev_strategy.get("city_reserve_dev_card_max_missing", 3)
    return city_deficit_score(state, color) <= max_missing


def plan_is_available(state, color, plan, strategy):
    if plan == "CITY":
        return city_plan_is_available(state, color)
    if plan == "SETTLEMENT":
        return player_state_value(state, color, "SETTLEMENTS_AVAILABLE", 0) > 0
    if plan == "ROAD":
        return player_state_value(state, color, "ROADS_AVAILABLE", 0) > 0
    if plan == "DEVELOPMENT_CARD":
        return should_buy_development_card(state, color, strategy, ignore_caps=is_endgame(state, color, strategy))
    return True


def maritime_trade_limits_reached(state, color, strategy, hand_pressure=False, endgame=False):
    status = maritime_trade_limit_status(
        state,
        color,
        strategy,
        hand_pressure=hand_pressure,
        endgame=endgame,
    )
    return status["game_limit_reached"] or status["turn_limit_reached"]


def maritime_trade_limit_status(state, color, strategy, hand_pressure=False, endgame=False):
    scoring = strategy.get("scoring", {})
    if endgame:
        max_per_game = scoring.get(
            "max_maritime_trades_per_game_endgame",
            scoring.get("max_maritime_trades_per_game_hand_pressure", scoring.get("max_maritime_trades_per_game", 3)),
        )
    else:
        max_per_game = (
            scoring.get("max_maritime_trades_per_game_hand_pressure", scoring.get("max_maritime_trades_per_game", 3))
            if hand_pressure
            else scoring.get("max_maritime_trades_per_game", 3)
        )
    game_count = current_game_action_count(state, color, "MARITIME_TRADE")

    if endgame:
        max_per_turn = scoring.get(
            "max_maritime_trades_per_turn_endgame",
            scoring.get("max_maritime_trades_per_turn_hand_pressure", scoring.get("max_maritime_trades_per_turn", 1)),
        )
    else:
        max_per_turn = (
            scoring.get("max_maritime_trades_per_turn_hand_pressure", scoring.get("max_maritime_trades_per_turn", 1))
            if hand_pressure
            else scoring.get("max_maritime_trades_per_turn", 1)
        )
    turn_count = current_turn_action_count(state, color, "MARITIME_TRADE")
    return {
        "game_count": game_count,
        "game_limit": max_per_game,
        "game_limit_reached": game_count >= max_per_game,
        "turn_count": turn_count,
        "turn_limit": max_per_turn,
        "turn_limit_reached": turn_count >= max_per_turn,
    }


def maritime_cap_override_allowed(score, state, color, strategy, hand_pressure=False, endgame=False):
    if not (hand_pressure or endgame):
        return False
    scoring = strategy.get("scoring", {})
    min_score = scoring.get("maritime_cap_override_min_score")
    if min_score is None or score < min_score:
        return False

    max_per_turn = scoring.get(
        "max_maritime_trades_per_turn_cap_override",
        scoring.get("max_maritime_trades_per_turn_endgame", 2),
    )
    max_per_game = scoring.get(
        "max_maritime_trades_per_game_cap_override",
        scoring.get("max_maritime_trades_per_game_endgame", 12),
    )
    return (
        current_turn_action_count(state, color, "MARITIME_TRADE") < max_per_turn
        and current_game_action_count(state, color, "MARITIME_TRADE") < max_per_game
    )


def maritime_trade_minimum_score(strategy, hand_pressure=False, endgame=False):
    scoring = strategy.get("scoring", {})
    if endgame:
        return scoring.get(
            "maritime_endgame_min_score",
            scoring.get("maritime_hand_pressure_min_score", scoring.get("maritime_min_score", 2.4)),
        )
    return (
        scoring.get("maritime_hand_pressure_min_score", scoring.get("maritime_min_score", 2.4))
        if hand_pressure
        else scoring.get("maritime_min_score", 2.4)
    )


def maritime_plan_weights(state, color, strategy):
    scoring = strategy.get("scoring", {})
    plan_weights = scoring.get(
        "maritime_plan_weights",
        {"CITY": 4, "SETTLEMENT": 2.2, "DEVELOPMENT_CARD": 1.4, "ROAD": 0.35},
    ).copy()
    if needs_expansion_pressure(state, color, strategy):
        plan_weights.update(scoring.get("maritime_expansion_pressure_plan_weights", {}))
    return plan_weights


def score_maritime_trade_action(action, state, color, strategy, hand_pressure=False, endgame=False):
    scoring = strategy.get("scoring", {})
    value = action_value(action)
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return -999
    offered = list(value[:-1])
    offered_resources = [resource for resource in offered if resource]
    received = value[-1]
    if not received:
        return -999

    active_plans = [
        plan
        for plan in ("CITY", "SETTLEMENT", "DEVELOPMENT_CARD", "ROAD")
        if plan_is_available(state, color, plan, strategy)
    ]
    if not active_plans:
        return -999

    if all(resource_deficit_score(state, color, received, plan) <= 0 for plan in active_plans):
        return -999

    received_score = 0
    for plan, weight in maritime_plan_weights(state, color, strategy).items():
        if plan not in active_plans:
            continue
        deficit = resource_deficit_score(state, color, received, plan)
        if deficit > 0:
            received_score += weight * deficit

    counts_before = resource_counts(state, color)
    counts_after = counts_before.copy()
    for resource in offered_resources:
        counts_after[resource] = max(0, counts_after.get(resource, 0) - 1)
    counts_after[received] = counts_after.get(received, 0) + 1

    city_material_penalty = 0
    offered_counts = {resource: offered_resources.count(resource) for resource in set(offered_resources)}
    for resource, offered_count in offered_counts.items():
        after_count = counts_before.get(resource, 0) - offered_count
        if (
            resource in RESOURCE_COSTS["CITY"]
            and after_count < RESOURCE_COSTS["CITY"][resource]
        ):
            city_material_penalty += scoring.get("maritime_city_material_penalty", 2.2)
        city_material_penalty += city_reserve_shortfall_after(
            state,
            color,
            resource,
            after_count,
            strategy,
        ) * scoring.get("maritime_city_reserve_penalty", 0)

    if city_plan_is_available(state, color):
        before_city_deficit = city_deficit_from_counts(counts_before)
        after_city_deficit = city_deficit_from_counts(counts_after)
        city_deficit_delta = before_city_deficit - after_city_deficit
        if city_deficit_delta > 0:
            received_score += city_deficit_delta * scoring.get(
                "maritime_city_deficit_improvement_bonus",
                0,
            )
        elif city_deficit_delta < 0:
            city_material_penalty += abs(city_deficit_delta) * scoring.get(
                "maritime_city_deficit_damage_penalty",
                0,
            )
    if endgame_settlement_mode(state, color, strategy):
        before_settlement_deficit = settlement_deficit_from_counts(counts_before)
        after_settlement_deficit = settlement_deficit_from_counts(counts_after)
        settlement_deficit_delta = before_settlement_deficit - after_settlement_deficit
        if settlement_deficit_delta > 0:
            received_score += settlement_deficit_delta * scoring.get(
                "maritime_endgame_settlement_deficit_improvement_bonus",
                0,
            )
        elif settlement_deficit_delta < 0:
            city_material_penalty += abs(settlement_deficit_delta) * scoring.get(
                "maritime_endgame_settlement_deficit_damage_penalty",
                0,
            )

    keep_targets = strategy.get("hand_management", {}).get("discard_keep_targets", {})
    offered_penalty = 0
    for resource in offered_resources:
        surplus_after_trade = (
            resource_count(state, color, resource)
            - offered_counts.get(resource, 0)
            - keep_targets.get(resource, 0)
        )
        surplus_discount = (
            scoring.get("maritime_surplus_offer_discount", 0)
            if surplus_after_trade >= 0
            else 0
        )
        offered_penalty += resource_priority(strategy, resource) * max(
            0,
            scoring.get("maritime_offer_priority_penalty", 0.95) - surplus_discount,
        )
    hand_count_penalty = max(0, len(offered) - 3) * scoring.get(
        "maritime_ratio_penalty", 0.4
    )
    discard_risk_bonus = 0
    if is_discard_risk(state, color, strategy):
        discard_risk_bonus = scoring.get("maritime_discard_risk_bonus", 0)
    endgame_bonus = (
        scoring.get("maritime_endgame_bonus", 0)
        if (endgame or is_endgame(state, color, strategy)) and "DEVELOPMENT_CARD" in active_plans
        else 0
    )
    return (
        received_score
        + resource_priority(strategy, received)
        * scoring.get("maritime_received_priority_weight", 1.3)
        + discard_risk_bonus
        + endgame_bonus
        - offered_penalty
        - hand_count_penalty
        - city_material_penalty
    )


def choose_maritime_trade_action(actions, state, color, strategy, hand_pressure=False, endgame=False):
    selected = max(
        actions,
        key=lambda action: score_maritime_trade_action(
            action,
            state,
            color,
            strategy,
            hand_pressure=hand_pressure,
            endgame=endgame,
        ),
    )
    score = score_maritime_trade_action(
        selected,
        state,
        color,
        strategy,
        hand_pressure=hand_pressure,
        endgame=endgame,
    )
    if score < maritime_trade_minimum_score(
        strategy,
        hand_pressure=hand_pressure,
        endgame=endgame,
    ):
        return None

    if maritime_trade_limits_reached(
        state,
        color,
        strategy,
        hand_pressure=hand_pressure,
        endgame=endgame,
    ) and not maritime_cap_override_allowed(
        score,
        state,
        color,
        strategy,
        hand_pressure=hand_pressure,
        endgame=endgame,
    ):
        return None

    return selected


def resource_deficit_from_counts(counts, plan, resource):
    return max(0, RESOURCE_COSTS[plan].get(resource, 0) - counts.get(resource, 0))


def plan_deficit_from_counts(counts, plan):
    return sum(
        max(0, required - counts.get(resource, 0))
        for resource, required in RESOURCE_COSTS[plan].items()
    )


def counts_after_maritime_trade(action, state, color):
    value = action_value(action)
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    offered = [resource for resource in value[:-1] if resource]
    received = value[-1]
    if not received:
        return None

    counts = resource_counts(state, color)
    for resource in offered:
        counts[resource] = max(0, counts.get(resource, 0) - 1)
    counts[received] = counts.get(received, 0) + 1
    return counts


def anti_stall_active_plans(state, color, strategy):
    plans = []
    if plan_is_available(state, color, "SETTLEMENT", strategy):
        plans.append("SETTLEMENT")
    if plan_is_available(state, color, "CITY", strategy):
        plans.append("CITY")
    if should_buy_development_card(
        state,
        color,
        strategy,
        ignore_caps=army_defense_threat(state, color, strategy)["active"],
    ):
        plans.append("DEVELOPMENT_CARD")
    if plan_is_available(state, color, "ROAD", strategy):
        plans.append("ROAD")
    return plans


def score_anti_stall_trade_action(action, state, color, strategy):
    search_strategy = strategy.get("catanatron_search", {})
    value = action_value(action)
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return -999
    offered = [resource for resource in value[:-1] if resource]
    received = value[-1]
    if not offered or not received:
        return -999

    counts_before = resource_counts(state, color)
    counts_after = counts_after_maritime_trade(action, state, color)
    if counts_after is None:
        return -999

    active_plans = anti_stall_active_plans(state, color, strategy)
    if not active_plans:
        return -999

    plan_weights = {
        "SETTLEMENT": 7,
        "CITY": 5,
        "DEVELOPMENT_CARD": 3,
        "ROAD": 0.5,
    }
    plan_weights.update(search_strategy.get("anti_stall_trade_plan_weights", {}))

    improvement_score = 0
    best_delta = 0
    completed_plan = False
    for plan in active_plans:
        before_deficit = plan_deficit_from_counts(counts_before, plan)
        after_deficit = plan_deficit_from_counts(counts_after, plan)
        delta = before_deficit - after_deficit
        best_delta = max(best_delta, delta)
        if delta > 0:
            improvement_score += delta * plan_weights.get(plan, 1)
        if before_deficit > 0 and after_deficit == 0:
            completed_plan = True

    if best_delta <= 0:
        return -999

    offered_counts = {resource: offered.count(resource) for resource in set(offered)}
    keep_targets = strategy.get("hand_management", {}).get("discard_keep_targets", {})
    surplus_relief = 0
    reserve_damage = 0
    for resource, offered_count in offered_counts.items():
        surplus_before = counts_before.get(resource, 0) - keep_targets.get(resource, 0)
        surplus_after = counts_after.get(resource, 0) - keep_targets.get(resource, 0)
        surplus_relief += max(0, surplus_before) - max(0, surplus_after)
        if surplus_after < 0:
            reserve_damage += abs(surplus_after)

    production_resources = production_resources_for_color(state, color)
    missing_resource_bonus = (
        search_strategy.get("anti_stall_missing_production_bonus", 2)
        if received not in production_resources
        else 0
    )
    completion_bonus = (
        search_strategy.get("anti_stall_trade_completion_bonus", 4)
        if completed_plan
        else 0
    )
    base_score = score_maritime_trade_action(
        action,
        state,
        color,
        strategy,
        hand_pressure=True,
        endgame=is_endgame(state, color, strategy),
    )
    if base_score <= -900:
        base_score = 0

    return (
        base_score
        + improvement_score
        + completion_bonus
        + missing_resource_bonus
        + surplus_relief * search_strategy.get("anti_stall_surplus_relief_weight", 1.2)
        - reserve_damage * search_strategy.get("anti_stall_reserve_damage_penalty", 2)
    )


def hand_is_resource_concentrated(state, color, strategy):
    search_strategy = strategy.get("catanatron_search", {})
    counts = resource_counts(state, color)
    total = sum(counts.values())
    if total < search_strategy.get("anti_stall_min_hand_size", 6):
        return False

    max_count = max(counts.values() or [0])
    if max_count < search_strategy.get("anti_stall_surplus_resource_min_count", 4):
        return False

    ratio = search_strategy.get("anti_stall_surplus_resource_min_ratio", 0.5)
    return total == 0 or max_count / total >= ratio


def choose_anti_stall_trade_action(actions, state, color, strategy):
    search_strategy = strategy.get("catanatron_search", {})
    if not hand_is_resource_concentrated(state, color, strategy):
        return None
    if current_turn_action_count(state, color, "MARITIME_TRADE") >= search_strategy.get(
        "anti_stall_max_trades_per_turn",
        2,
    ):
        return None
    if current_game_action_count(state, color, "MARITIME_TRADE") >= search_strategy.get(
        "anti_stall_max_trades_per_game",
        8,
    ):
        return None

    scored = [
        (score_anti_stall_trade_action(action, state, color, strategy), action)
        for action in actions
    ]
    best_score, selected = max(scored, key=lambda item: item[0])
    if best_score < search_strategy.get("anti_stall_trade_min_score", 6):
        return None
    return selected


def catanatron_search_anti_stall_trade_override(payload, strategy, recommended_action):
    search_strategy = strategy.get("catanatron_search", {})
    if not search_strategy.get("anti_stall_trade_override_enabled", False):
        return None
    if payload.get("current_prompt") != "PLAY_TURN":
        return None
    if action_type(recommended_action) not in set(
        search_strategy.get("anti_stall_trade_override_action_types", ["END_TURN"])
    ):
        return None

    state = payload.get("state", {})
    color = payload.get("color")
    actions = payload.get("legal_actions") or payload.get("playable_actions", [])
    action_types = {action_type(action) for action in actions}
    if action_types.intersection({"BUILD_CITY", "BUILD_SETTLEMENT"}):
        return None

    trade_candidates = [
        action for action in actions if action_type(action) == "MARITIME_TRADE"
    ]
    if not trade_candidates:
        return None

    selected = choose_anti_stall_trade_action(trade_candidates, state, color, strategy)
    if selected is None:
        return None

    selected_id, selected_index = action_id(selected, actions.index(selected))
    return (
        selected_id,
        selected_index,
        "catanatron search anti-stall trade override: convert surplus before pass",
    )


def has_buildable_settlement_location(state, color):
    network_nodes = own_network_nodes(state, color)
    return any(
        node_id in network_nodes and is_settlement_candidate_node(state, node_id)
        for node_id in nodes_by_id(state)
    )


def should_buy_development_card(state, color, strategy, ignore_caps=False):
    dev_strategy = strategy.get("development", {})
    if ignore_caps:
        return True

    bought = current_game_action_count(state, color, "BUY_DEVELOPMENT_CARD")
    played_knights = player_state_value(state, color, "PLAYED_KNIGHT", 0)
    has_army = bool(player_state_value(state, color, "HAS_ARMY", False))
    cities_on_board = 4 - player_state_value(state, color, "CITIES_AVAILABLE", 4)
    settlements_on_board = 5 - player_state_value(state, color, "SETTLEMENTS_AVAILABLE", 5)
    tactical_in_hand = blocking_tactical_development_cards_in_hand(state, color, strategy)

    if tactical_in_hand >= dev_strategy.get("max_unplayed_tactical_cards", 1):
        return False
    if needs_expansion_pressure(state, color, strategy) and bought >= dev_strategy.get(
        "max_cards_during_expansion_pressure", 1
    ):
        return False

    if has_army and bought >= dev_strategy.get("max_cards_after_largest_army", 5):
        return False
    if played_knights >= dev_strategy.get("largest_army_knight_target", 3) and bought >= dev_strategy.get(
        "max_cards_after_knight_target", 6
    ):
        return False
    if cities_on_board < dev_strategy.get("min_cities_before_extra_dev", 1) and bought >= dev_strategy.get(
        "max_cards_before_first_city", 3
    ):
        return False
    if settlements_on_board < dev_strategy.get("min_settlements_before_extra_dev", 3) and bought >= dev_strategy.get(
        "max_cards_before_third_settlement", 4
    ):
        return False
    return bought < dev_strategy.get("max_cards_per_game", 8)


def should_buy_development_card_to_reduce_hand(state, color, strategy):
    hand = strategy.get("hand_management", {})
    dev_strategy = strategy.get("development", {})
    if player_resource_total(state, color) < hand.get("dev_card_hand_pressure_min_cards", 8):
        return False
    if city_materials_should_block_dev_card(state, color, strategy):
        return False
    if blocking_tactical_development_cards_in_hand(state, color, strategy) >= dev_strategy.get(
        "max_unplayed_tactical_cards", 1
    ):
        return False
    return should_buy_development_card(
        state,
        color,
        strategy,
        ignore_caps=is_endgame(state, color, strategy),
    )


def player_threat_score(state, color, strategy):
    threat = strategy.get("leader_threat", {})
    score = (
        player_state_value(state, color, "VICTORY_POINTS", 0)
        * threat.get("public_vp_weight", 1.0)
    )
    score += (
        player_state_value(state, color, "PLAYED_KNIGHT", 0)
        * threat.get("played_knight_weight", 0.8)
    )
    score += (
        player_state_value(state, color, "LONGEST_ROAD_LENGTH", 0)
        * threat.get("longest_road_length_weight", 0.25)
    )
    if player_state_value(state, color, "HAS_ARMY", False):
        score += threat.get("has_largest_army_bonus", 2.0)
    if player_state_value(state, color, "HAS_ROAD", False):
        score += threat.get("has_longest_road_bonus", 1.5)
    for player in state.get("players", []):
        if player.get("color") == color and not player.get("is_bot", True):
            score += threat.get("human_player_bonus", 0)
            break
    return score


def leader_shutdown_threat(state, color, strategy):
    shutdown = strategy.get("leader_shutdown", {})
    if not shutdown.get("enabled", False):
        return {"active": False, "opponent": None}

    opponents = []
    for opponent in opponent_colors(state, color):
        public_vp = player_state_value(state, opponent, "VICTORY_POINTS", 0)
        played_knights = player_state_value(state, opponent, "PLAYED_KNIGHT", 0)
        road_length = player_state_value(state, opponent, "LONGEST_ROAD_LENGTH", 0)
        has_army = bool(player_state_value(state, opponent, "HAS_ARMY", False))
        has_road = bool(player_state_value(state, opponent, "HAS_ROAD", False))
        immediate_public_vp = public_vp + (2 if has_army else 0) + (2 if has_road else 0)
        active = public_vp >= shutdown.get("public_vp_trigger", 8)
        active = active or immediate_public_vp >= shutdown.get("effective_vp_trigger", 9)
        active = active or (
            public_vp >= shutdown.get("near_public_vp_trigger", 7)
            and (
                played_knights >= shutdown.get("played_knights_trigger", 2)
                or road_length >= shutdown.get("road_length_trigger", 7)
                or has_army
                or has_road
            )
        )
        opponents.append(
            {
                "color": opponent,
                "public_vp": public_vp,
                "effective_public_vp": immediate_public_vp,
                "played_knights": played_knights,
                "road_length": road_length,
                "has_army": has_army,
                "has_road": has_road,
                "active": active,
                "threat_score": player_threat_score(state, opponent, strategy),
            }
        )

    if not opponents:
        return {"active": False, "opponent": None}
    strongest = max(
        opponents,
        key=lambda opponent: (
            opponent["active"],
            opponent["effective_public_vp"],
            opponent["public_vp"],
            opponent["threat_score"],
        ),
    )
    return {"active": strongest["active"], "opponent": strongest}


def army_defense_threat(state, color, strategy):
    army_strategy = strategy.get("army_defense", {})
    own_knights = player_state_value(state, color, "PLAYED_KNIGHT", 0)
    own_has_army = bool(player_state_value(state, color, "HAS_ARMY", False))
    shutdown = leader_shutdown_threat(state, color, strategy)
    opponents = []
    for opponent in opponent_colors(state, color):
        opponents.append(
            {
                "color": opponent,
                "public_vp": player_state_value(state, opponent, "VICTORY_POINTS", 0),
                "played_knights": player_state_value(state, opponent, "PLAYED_KNIGHT", 0),
                "has_army": bool(player_state_value(state, opponent, "HAS_ARMY", False)),
                "threat_score": player_threat_score(state, opponent, strategy),
            }
        )
    if not opponents or own_has_army:
        return {"active": False, "opponent": None}

    strongest = max(
        opponents,
        key=lambda opponent: (
            opponent["played_knights"],
            opponent["public_vp"],
            opponent["threat_score"],
        ),
    )
    active = False
    if strongest["played_knights"] >= army_strategy.get("opponent_knights_trigger", 2):
        active = True
    if strongest["has_army"] and strongest["public_vp"] >= army_strategy.get(
        "opponent_army_public_vp_trigger",
        6,
    ):
        active = True
    if own_knights >= army_strategy.get("own_knights_near_army", 2) and strongest[
        "played_knights"
    ] <= own_knights + 1:
        active = True
    if (
        shutdown.get("active")
        and strongest["played_knights"] >= army_strategy.get(
            "leader_shutdown_knights_trigger",
            1,
        )
    ):
        active = True

    return {"active": active, "opponent": strongest}


def should_buy_development_card_for_army_defense(state, color, strategy):
    army_strategy = strategy.get("army_defense", {})
    if not army_strategy.get("enabled", False):
        return False
    if not army_defense_threat(state, color, strategy)["active"]:
        return False
    if blocking_tactical_development_cards_in_hand(state, color, strategy) >= army_strategy.get(
        "max_unplayed_tactical_cards",
        1,
    ):
        return False
    bought = current_game_action_count(state, color, "BUY_DEVELOPMENT_CARD")
    if bought >= army_strategy.get("max_defense_dev_cards_per_game", 5):
        return False
    return True


def should_buy_development_card_for_finish(state, color, strategy):
    finish = strategy.get("finish", {})
    if not finish.get("enabled", False):
        return False
    endgame_active = actual_victory_points(state, color) >= finish.get(
        "min_vp_for_dev",
        strategy.get("endgame", {}).get("threshold_vp", 8),
    )
    shutdown_active = leader_shutdown_threat(state, color, strategy).get("active", False)
    if not endgame_active and not shutdown_active:
        return False

    dev_strategy = strategy.get("development", {})
    tactical_in_hand = blocking_tactical_development_cards_in_hand(state, color, strategy)
    if tactical_in_hand >= finish.get(
        "max_unplayed_tactical_cards",
        dev_strategy.get("max_unplayed_tactical_cards", 1),
    ):
        return False

    if (
        city_plan_is_available(state, color)
        and city_deficit_score(state, color) <= finish.get("city_deficit_blocks_dev_at", 1)
    ):
        return False

    bought = current_game_action_count(state, color, "BUY_DEVELOPMENT_CARD")
    return bought < finish.get(
        "max_dev_cards_per_game",
        dev_strategy.get("max_cards_per_game", 5),
    )


def maritime_trade_completes_finish_plan(action, state, color, strategy):
    counts_after = counts_after_maritime_trade(action, state, color)
    if counts_after is None:
        return False
    if city_plan_is_available(state, color) and all(
        counts_after.get(resource, 0) >= amount
        for resource, amount in RESOURCE_COSTS["CITY"].items()
    ):
        return True
    if (
        player_state_value(state, color, "SETTLEMENTS_AVAILABLE", 0) > 0
        and has_buildable_settlement_location(state, color)
        and all(
            counts_after.get(resource, 0) >= amount
            for resource, amount in RESOURCE_COSTS["SETTLEMENT"].items()
        )
    ):
        return True
    return False


def choose_finish_maritime_trade_action(actions, state, color, strategy):
    candidates = [
        action
        for action in actions
        if maritime_trade_completes_finish_plan(action, state, color, strategy)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda action: score_maritime_trade_action(
            action,
            state,
            color,
            strategy,
            hand_pressure=is_discard_risk(state, color, strategy),
            endgame=True,
        ),
    )


def endgame_road_action_is_strictly_approved(action, state, color, strategy):
    finish = strategy.get("finish", {})
    if not finish.get("strict_endgame_road_gate", False):
        return True
    if actual_victory_points(state, color) < finish.get(
        "strict_road_min_vp",
        strategy.get("endgame", {}).get("threshold_vp", 8),
    ):
        return True
    if should_chase_longest_road(state, color, strategy):
        return True
    if not road_has_endgame_settlement_plan(action, state, color, strategy):
        return False
    return settlement_missing_after_road(state, color) <= finish.get(
        "max_settlement_missing_after_endgame_road",
        1,
    )


def catanatron_search_finish_override(payload, strategy, recommended_action):
    search_strategy = strategy.get("catanatron_search", {})
    finish = strategy.get("finish", {})
    if not search_strategy.get("finish_override_enabled", False):
        return None
    if payload.get("current_prompt") != "PLAY_TURN":
        return None

    state = payload.get("state", {})
    color = payload.get("color")
    actions = payload.get("legal_actions") or payload.get("playable_actions", [])
    if not actions:
        return None

    own_endgame = actual_victory_points(state, color) >= finish.get(
        "min_vp",
        strategy.get("endgame", {}).get("threshold_vp", 8),
    )
    shutdown_active = leader_shutdown_threat(state, color, strategy).get("active", False)
    if not own_endgame and not shutdown_active:
        return None

    grouped = {}
    for index, action in enumerate(actions):
        grouped.setdefault(action_type(action), []).append((index, action))

    if own_endgame and "BUILD_CITY" in grouped:
        candidates = [item[1] for item in grouped["BUILD_CITY"]]
        selected = choose_best_city_action(candidates, state, strategy, color)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "catanatron search finish override: take immediate city VP"

    if own_endgame and "BUILD_SETTLEMENT" in grouped:
        candidates = [item[1] for item in grouped["BUILD_SETTLEMENT"]]
        selected = choose_best_node_action(candidates, state, strategy, color)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "catanatron search finish override: take immediate settlement VP"

    if "PLAY_KNIGHT_CARD" in grouped and (
        shutdown_active
        or player_state_value(state, color, "PLAYED_KNIGHT", 0)
        >= finish.get("play_knight_when_own_knights_at_least", 2)
    ):
        index, selected = grouped["PLAY_KNIGHT_CARD"][0]
        selected_id, selected_index = action_id(selected, index)
        return selected_id, selected_index, "catanatron search finish override: play knight for army/control"

    if own_endgame and "MARITIME_TRADE" in grouped:
        candidates = [item[1] for item in grouped["MARITIME_TRADE"]]
        selected = choose_finish_maritime_trade_action(candidates, state, color, strategy)
        if selected is not None:
            selected_id, selected_index = action_id(selected, actions.index(selected))
            return selected_id, selected_index, "catanatron search finish override: trade into immediate VP plan"

    recommended_type = action_type(recommended_action)
    override_types = set(
        finish.get(
            "dev_override_action_types",
            ["END_TURN", "MARITIME_TRADE", "BUILD_ROAD"],
        )
    )
    if (
        "BUY_DEVELOPMENT_CARD" in grouped
        and recommended_type in override_types
        and not (
            recommended_type == "BUILD_ROAD"
            and endgame_road_action_is_strictly_approved(
                recommended_action,
                state,
                color,
                strategy,
            )
            and settlement_missing_after_road(state, color)
            <= finish.get("dev_keeps_strict_road_if_settlement_missing_at_most", 0)
        )
        and should_buy_development_card_for_finish(state, color, strategy)
    ):
        index, selected = grouped["BUY_DEVELOPMENT_CARD"][0]
        selected_id, selected_index = action_id(selected, index)
        return selected_id, selected_index, "catanatron search finish override: buy dev for late-game outs"

    return None


def catanatron_search_army_defense_override(payload, strategy, recommended_action):
    search_strategy = strategy.get("catanatron_search", {})
    if not search_strategy.get("army_defense_override_enabled", False):
        return None
    if payload.get("current_prompt") != "PLAY_TURN":
        return None

    state = payload.get("state", {})
    color = payload.get("color")
    if not army_defense_threat(state, color, strategy)["active"]:
        return None

    actions = payload.get("legal_actions") or payload.get("playable_actions", [])
    action_types = {action_type(action) for action in actions}
    if action_types.intersection({"BUILD_CITY", "BUILD_SETTLEMENT"}):
        return None

    for index, action in enumerate(actions):
        if action_type(action) == "PLAY_KNIGHT_CARD":
            selected_id, selected_index = action_id(action, index)
            return (
                selected_id,
                selected_index,
                "catanatron search army defense override: play knight before leader secures army",
            )

    recommended_type = action_type(recommended_action)
    passive_types = set(
        search_strategy.get(
            "army_defense_dev_override_action_types",
            ["END_TURN", "MARITIME_TRADE"],
        )
    )
    if recommended_type == "BUILD_ROAD":
        road_score = score_road_action(recommended_action, state, color, strategy)
        if road_score <= search_strategy.get("army_defense_road_override_max_score", 1):
            passive_types.add("BUILD_ROAD")

    if recommended_type not in passive_types:
        return None
    if not should_buy_development_card_for_army_defense(state, color, strategy):
        return None

    for index, action in enumerate(actions):
        if action_type(action) == "BUY_DEVELOPMENT_CARD":
            selected_id, selected_index = action_id(action, index)
            return (
                selected_id,
                selected_index,
                "catanatron search army defense override: buy dev card to contest largest army",
            )
    return None


def coordinate_score(state, coordinate, strategy):
    tile = tile_record_at_coordinate(state, coordinate)
    if tile.get("type") != "RESOURCE_TILE":
        return 0
    return production_weight(strategy, tile.get("number")) * resource_priority(
        strategy, tile.get("resource")
    )


def score_robber_action(action, payload, strategy):
    state = payload.get("state", {})
    leader = payload.get("strategy", {}).get("public_leader", {}).get("color")
    color = payload.get("color")
    robber = strategy.get("robber", {})
    value = action_value(action)
    if not isinstance(value, list) or len(value) != 2:
        return 0
    coordinate, victim = value
    building_colors = tile_building_colors(state, coordinate)
    opponent_count = sum(1 for building_color in building_colors if building_color != color)
    leader_bonus = (
        robber.get("public_leader_bonus", 5)
        if victim == leader or leader in building_colors
        else 0
    )
    victim_bonus = robber.get("victim_bonus", 2) if victim else 0
    self_penalty = (
        robber.get("avoid_self_blocking_penalty", 4)
        if color in building_colors
        else 0
    )
    empty_tile_penalty = robber.get("empty_tile_penalty", 3) if opponent_count == 0 else 0
    threatened_colors = {
        building_color
        for building_color in building_colors
        if building_color != color
    }
    if victim and victim != color:
        threatened_colors.add(victim)
    threat_bonus = max(
        [player_threat_score(state, opponent, strategy) for opponent in threatened_colors]
        or [0]
    ) * robber.get("leader_threat_weight", 0)
    return (
        coordinate_score(state, coordinate, strategy)
        * robber.get("tile_production_weight", 1)
        + leader_bonus
        + victim_bonus
        + threat_bonus
        + opponent_count * robber.get("opponent_building_bonus", 1.25)
        - self_penalty
        - empty_tile_penalty
    )


def choose_robber_action(actions, payload, strategy):
    state = payload.get("state", {})
    color = payload.get("color")
    robber = strategy.get("robber", {})
    if robber.get("avoid_self_blocking_when_alternative", True):
        safe_actions = []
        for action in actions:
            value = action_value(action)
            if not isinstance(value, list) or len(value) != 2:
                continue
            coordinate, victim = value
            building_colors = tile_building_colors(state, coordinate)
            if color in building_colors:
                continue
            if victim or any(building_color != color for building_color in building_colors):
                safe_actions.append(action)
        if safe_actions:
            actions = safe_actions

    return max(actions, key=lambda action: score_robber_action(action, payload, strategy))


def choose_endgame_settlement_road_action(actions, state, color, strategy):
    road_strategy = strategy.get("road", {})
    min_score = road_strategy.get("endgame_settlement_road_min_score", 0.0)
    candidates = [
        action
        for action in actions
        if road_has_endgame_settlement_plan(action, state, color, strategy)
        and endgame_road_action_is_strictly_approved(action, state, color, strategy)
    ]
    if not candidates:
        return None
    selected = choose_best_road_action(candidates, state, color, strategy)
    score = score_road_action(selected, state, color, strategy)
    return selected if score >= min_score else None


def road_has_endgame_settlement_plan(action, state, color, strategy):
    road_strategy = strategy.get("road", {})
    max_missing = road_strategy.get("endgame_settlement_max_missing_after_road", 4)
    if settlement_missing_after_road(state, color) > max_missing:
        return False

    direct_target = direct_settlement_target_after_road(action, state, color, strategy)
    min_route_score = road_strategy.get(
        "endgame_settlement_route_min_score",
        road_strategy.get("settlement_target_min_score", 0),
    )
    if direct_target is not None and direct_target[0] >= min_route_score:
        return True

    current_route_score = best_route_target_score(state, color, strategy)
    next_route_score = best_route_target_score(
        state,
        color,
        strategy,
        extra_edge=action_value(action),
    )
    if next_route_score is None or next_route_score < min_route_score:
        return False
    if current_route_score is None:
        return True
    return next_route_score >= current_route_score + road_strategy.get(
        "endgame_settlement_route_min_improvement",
        0,
    )


def tile_building_colors(state, coordinate):
    node_ids = tile_nodes_for_coordinate(state, coordinate)
    nodes = nodes_by_id(state)
    colors = []
    if node_ids:
        for node_id in node_ids:
            node = nodes.get(node_id)
            if node and node.get("color") is not None:
                colors.append(node.get("color"))
        return colors

    tile = tile_record_at_coordinate(state, coordinate)
    tile_id = tile.get("id")
    if tile_id is not None:
        for node_id, adjacent_tiles in state.get("adjacent_tiles", {}).items():
            if not any(tile.get("id") == tile_id for tile in adjacent_tiles):
                continue
            node = nodes.get(int(node_id)) or nodes.get(node_id)
            if node and node.get("color") is not None:
                colors.append(node.get("color"))
        return colors

    raw_nodes = state.get("nodes", [])
    if isinstance(raw_nodes, dict):
        raw_nodes = raw_nodes.values()
    for node in raw_nodes:
        if node.get("tile_coordinate") == coordinate and node.get("color") is not None:
            colors.append(node.get("color"))
    return colors


def tile_has_building(state, coordinate, color):
    return color in tile_building_colors(state, coordinate)


def _choose_action_core(payload, strategy):
    actions = payload.get("legal_actions") or payload.get("playable_actions", [])
    state = payload.get("state", {})
    color = payload.get("color")

    if not actions:
        return None, 0, "no playable actions"

    grouped = {}
    for index, action in enumerate(actions):
        grouped.setdefault(action_type(action), []).append((index, action))
    current_prompt = payload.get("current_prompt")

    if "ROLL" in grouped:
        index, selected = grouped["ROLL"][0]
        selected_id, selected_index = action_id(selected, index)
        return selected_id, selected_index, "roll immediately"

    if "DISCARD_RESOURCE" in grouped:
        candidates = [item[1] for item in grouped["DISCARD_RESOURCE"]]
        selected = choose_discard_action(candidates, state, color, strategy)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "discard excess resource while preserving city targets"

    if "MOVE_ROBBER" in grouped:
        candidates = [item[1] for item in grouped["MOVE_ROBBER"]]
        selected = choose_robber_action(candidates, payload, strategy)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "rob public leader or strongest tile"

    if current_prompt == "BUILD_INITIAL_SETTLEMENT" and "BUILD_SETTLEMENT" in grouped:
        candidates = [item[1] for item in grouped["BUILD_SETTLEMENT"]]
        selected = choose_best_node_action(candidates, state, strategy, color)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "best initial settlement production/coverage/port plan"

    if current_prompt == "BUILD_INITIAL_ROAD" and "BUILD_ROAD" in grouped:
        candidates = [item[1] for item in grouped["BUILD_ROAD"]]
        selected = choose_initial_road_action(candidates, state, color, strategy)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "initial road toward best settlement/port route"

    endgame = is_endgame(state, color, strategy)

    if "BUILD_CITY" in grouped:
        candidates = [item[1] for item in grouped["BUILD_CITY"]]
        selected = choose_best_city_action(candidates, state, strategy, color)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "city before road: convert resources into VP and stronger production"

    if "BUILD_SETTLEMENT" in grouped:
        candidates = [item[1] for item in grouped["BUILD_SETTLEMENT"]]
        selected = choose_best_node_action(candidates, state, strategy, color)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "best settlement production/coverage/port plan"

    if "PLAY_YEAR_OF_PLENTY" in grouped:
        candidates = [item[1] for item in grouped["PLAY_YEAR_OF_PLENTY"]]
        plan_candidates = [
            action
            for action in candidates
            if year_of_plenty_completes_plan(action, state, color, strategy)
        ]
        if plan_candidates:
            selected = choose_year_of_plenty_action(plan_candidates, state, color, strategy)
            selected_id, selected_index = action_id(selected, actions.index(selected))
            return selected_id, selected_index, "play year of plenty only when it completes an immediate build plan"

    hand_pressure = is_discard_risk(state, color, strategy)
    settlement_endgame = endgame_settlement_mode(state, color, strategy)

    if settlement_endgame and "BUILD_ROAD" in grouped:
        candidates = [item[1] for item in grouped["BUILD_ROAD"]]
        selected = choose_endgame_settlement_road_action(
            candidates,
            state,
            color,
            strategy,
        )
        if selected is not None:
            selected_id, selected_index = action_id(selected, actions.index(selected))
            return selected_id, selected_index, "endgame: road toward winning settlement route"

    if endgame and "MARITIME_TRADE" in grouped:
        trade_key = (payload.get("game_id"), color)
        candidates = [item[1] for item in grouped["MARITIME_TRADE"]]
        selected = choose_maritime_trade_action(
            candidates,
            state,
            color,
            strategy,
            hand_pressure=hand_pressure,
            endgame=True,
        )
        if selected is not None:
            MARITIME_TRADE_COUNTS[trade_key] = MARITIME_TRADE_COUNTS.get(trade_key, 0) + 1
            selected_id, selected_index = action_id(selected, actions.index(selected))
            return selected_id, selected_index, "endgame: targeted maritime trade toward final VP"

    if (
        endgame
        and "BUY_DEVELOPMENT_CARD" in grouped
        and not road_can_flip_longest_road(state, color)
        and should_buy_development_card(state, color, strategy, ignore_caps=True)
    ):
        index, selected = grouped["BUY_DEVELOPMENT_CARD"][0]
        selected_id, selected_index = action_id(selected, index)
        return selected_id, selected_index, "endgame: buy development card for shortest path to final VP"

    if hand_pressure and "MARITIME_TRADE" in grouped:
        trade_key = (payload.get("game_id"), color)
        candidates = [item[1] for item in grouped["MARITIME_TRADE"]]
        selected = choose_maritime_trade_action(
            candidates, state, color, strategy, hand_pressure=True
        )
        if selected is not None:
            MARITIME_TRADE_COUNTS[trade_key] = MARITIME_TRADE_COUNTS.get(trade_key, 0) + 1
            selected_id, selected_index = action_id(selected, actions.index(selected))
            return selected_id, selected_index, "hand pressure: trade surplus before risking discard"

    if (
        hand_pressure
        and "BUY_DEVELOPMENT_CARD" in grouped
        and should_buy_development_card_to_reduce_hand(state, color, strategy)
    ):
        index, selected = grouped["BUY_DEVELOPMENT_CARD"][0]
        selected_id, selected_index = action_id(selected, index)
        return selected_id, selected_index, "hand pressure: buy development card before floating a large hand"

    if "BUILD_ROAD" in grouped:
        candidates = [
            action
            for _index, action in grouped["BUILD_ROAD"]
            if road_action_is_strategy_approved(
                action,
                state,
                color,
                strategy,
                hand_pressure=hand_pressure,
            )
        ]
        if candidates:
            selected = choose_best_road_action(candidates, state, color, strategy)
            selected_id, selected_index = action_id(selected, actions.index(selected))
            return selected_id, selected_index, "road only when it directly enables a near-term settlement or endgame longest road"

    if "PLAY_MONOPOLY" in grouped:
        candidates = [item[1] for item in grouped["PLAY_MONOPOLY"]]
        selected = choose_monopoly_action(candidates, state, color)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "monopoly most visible opponent resource"

    if "PLAY_YEAR_OF_PLENTY" in grouped:
        candidates = [item[1] for item in grouped["PLAY_YEAR_OF_PLENTY"]]
        selected = choose_year_of_plenty_action(candidates, state, color, strategy)
        selected_id, selected_index = action_id(selected, actions.index(selected))
        return selected_id, selected_index, "take scarce resources"

    if "PLAY_ROAD_BUILDING" in grouped and should_play_road_building(state, color, strategy):
        index, selected = grouped["PLAY_ROAD_BUILDING"][0]
        selected_id, selected_index = action_id(selected, index)
        return selected_id, selected_index, "play road building only for settlement targets or longest road"

    if "MARITIME_TRADE" in grouped:
        trade_key = (payload.get("game_id"), color)
        candidates = [item[1] for item in grouped["MARITIME_TRADE"]]
        selected = choose_maritime_trade_action(candidates, state, color, strategy)
        if selected is not None:
            MARITIME_TRADE_COUNTS[trade_key] = MARITIME_TRADE_COUNTS.get(trade_key, 0) + 1
            selected_id, selected_index = action_id(selected, actions.index(selected))
            return selected_id, selected_index, "maritime trade toward city/settlement plan"

    for preferred_type in strategy.get("action_priority", DEFAULT_STRATEGY["action_priority"]):
        if preferred_type == "MARITIME_TRADE":
            continue
        if preferred_type == "BUILD_ROAD":
            continue
        if preferred_type == "PLAY_ROAD_BUILDING":
            continue
        if preferred_type == "BUY_DEVELOPMENT_CARD" and not should_buy_development_card(
            state, color, strategy, ignore_caps=is_endgame(state, color, strategy)
        ):
            continue
        if preferred_type in grouped:
            index, selected = grouped[preferred_type][0]
            selected_id, selected_index = action_id(selected, index)
            return selected_id, selected_index, f"priority {preferred_type}"

    selected_id, selected_index = action_id(actions[0], 0)
    return selected_id, selected_index, "fallback first action"


def choose_action(payload, strategy=None):
    selected_id, action_index, reason, _diagnostics = choose_action_with_diagnostics(
        payload, strategy
    )
    return selected_id, action_index, reason


def choose_action_with_diagnostics(payload, strategy=None):
    strategy = strategy or STRATEGY
    selected_id, action_index, reason = _choose_action_core(payload, strategy)
    selected_id, action_index, reason = apply_catanatron_search_primary(
        payload,
        strategy,
        selected_id,
        action_index,
        reason,
    )
    if "catanatron search" not in reason:
        selected_id, action_index, reason = apply_catanatron_teacher_override(
            payload,
            strategy,
            selected_id,
            action_index,
            reason,
        )
    try:
        diagnostics = build_decision_diagnostics(
            payload,
            strategy,
            selected_id,
            action_index,
            reason,
        )
    except Exception as exc:
        diagnostics = {
            "timestamp": iso_timestamp(),
            "game_id": payload.get("game_id"),
            "state_index": payload.get("state_index"),
            "color": payload.get("color"),
            "strategy_name": strategy.get("name", "default"),
            "selected_action_id": selected_id,
            "selected_action_index": action_index,
            "reason": reason,
            "diagnostics_error": str(exc),
        }
    return selected_id, action_index, reason, diagnostics


def iso_timestamp():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def action_type_counts(actions):
    counts = {}
    for action in actions:
        type_name = action_type(action)
        counts[type_name] = counts.get(type_name, 0) + 1
    return counts


def action_summary(action, fallback_index):
    selected_id, selected_index = action_id(action, fallback_index)
    return {
        "id": selected_id,
        "index": selected_index,
        "type": action_type(action),
        "value": action_value(action),
    }


def selected_action_from_result(actions, selected_id, action_index):
    if selected_id is not None:
        for index, action in enumerate(actions):
            candidate_id, _candidate_index = action_id(action, index)
            if candidate_id == selected_id:
                return index, action
    if isinstance(action_index, int) and 0 <= action_index < len(actions):
        return action_index, actions[action_index]
    for index, action in enumerate(actions):
        _candidate_id, candidate_index = action_id(action, index)
        if candidate_index == action_index:
            return index, action
    return None, None


def catanatron_teacher(payload):
    return payload.get("strategy", {}).get("catanatron_teacher") or {}


def catanatron_search(payload):
    return payload.get("strategy", {}).get("catanatron_search") or {}


def catanatron_search_scores_by_id(payload):
    scores = {}
    for row in catanatron_search(payload).get("action_scores", []):
        if row.get("id") is not None:
            scores[str(row["id"])] = row
    return scores


def catanatron_teacher_scores_by_id(payload):
    scores = {}
    for row in catanatron_teacher(payload).get("action_scores", []):
        if row.get("id") is not None:
            scores[str(row["id"])] = row
    return scores


def teacher_row_for_action(action, fallback_index, teacher_scores):
    candidate_id, _candidate_index = action_id(action, fallback_index)
    if candidate_id is not None:
        return teacher_scores.get(str(candidate_id))
    return None


def action_identity_matches(action, fallback_index, row):
    candidate_id, candidate_index = action_id(action, fallback_index)
    if row.get("id") is not None and candidate_id is not None:
        return str(row["id"]) == str(candidate_id)
    return row.get("index") == candidate_index


def catanatron_teacher_recommended_action(payload, row):
    if not row:
        return None, None
    actions = payload.get("legal_actions") or payload.get("playable_actions", [])
    for index, action in enumerate(actions):
        if action_identity_matches(action, index, row):
            return index, action
    return None, None


def same_action(left, right):
    left_id, left_index = action_id(left, None)
    right_id, right_index = action_id(right, None)
    if left_id is not None and right_id is not None:
        return str(left_id) == str(right_id)
    return action_type(left) == action_type(right) and action_value(left) == action_value(right)


def search_action_passes_guardrails(payload, strategy, action):
    search_strategy = strategy.get("catanatron_search", {})
    if not search_strategy.get("respect_guardrails", True):
        return True

    state = payload.get("state", {})
    prompt = payload.get("current_prompt") or state.get("current_prompt")
    if prompt in {"BUILD_INITIAL_SETTLEMENT", "BUILD_INITIAL_ROAD"}:
        return True

    color = payload.get("color")
    type_name = action_type(action)
    hand_pressure = is_discard_risk(state, color, strategy)
    endgame = is_endgame(state, color, strategy)

    blocked_types = set(search_strategy.get("blocked_types", []))
    if type_name in blocked_types:
        return False

    if type_name == "BUILD_ROAD":
        score = score_road_action(action, state, color, strategy)
        if not endgame_road_action_is_strictly_approved(action, state, color, strategy):
            return False
        if should_chase_longest_road(state, color, strategy):
            return score >= search_strategy.get("longest_road_min_score", -12)
        has_near_settlement_plan = road_has_near_settlement_plan(
            action,
            state,
            color,
            strategy,
        )
        if (
            has_near_settlement_plan
            and search_strategy.get("road_debt_veto_enabled", True)
            and road_debt_for_state(state, color, strategy)
            > search_strategy.get("road_debt_veto_threshold", 3)
            and settlement_missing_after_road(state, color)
            > search_strategy.get("road_debt_veto_max_settlement_missing_after_road", 1)
        ):
            return False
        if has_near_settlement_plan:
            return score >= search_strategy.get("road_min_score", -8)
        return score >= search_strategy.get("dead_road_min_score", 2.0)

    if type_name == "MARITIME_TRADE":
        score = score_maritime_trade_action(
            action,
            state,
            color,
            strategy,
            hand_pressure=hand_pressure,
            endgame=endgame,
        )
        if score < search_strategy.get("maritime_min_score", -6):
            return False
        if not search_strategy.get("respect_maritime_caps", True):
            return True
        if not maritime_trade_limits_reached(
            state,
            color,
            strategy,
            hand_pressure=hand_pressure,
            endgame=endgame,
        ):
            return True
        return maritime_cap_override_allowed(
            score,
            state,
            color,
            strategy,
            hand_pressure=hand_pressure,
            endgame=endgame,
        )

    if type_name == "PLAY_ROAD_BUILDING":
        return should_play_road_building(state, color, strategy)

    return True


def apply_catanatron_search_primary(
    payload,
    strategy,
    selected_id,
    action_index,
    reason,
):
    search_strategy = strategy.get("catanatron_search", {})
    if not search_strategy.get("enabled", False):
        return selected_id, action_index, reason

    current_prompt = payload.get("current_prompt")
    initial_prompts = {"BUILD_INITIAL_SETTLEMENT", "BUILD_INITIAL_ROAD"}
    if (
        current_prompt in initial_prompts
        and not search_strategy.get("override_initial", True)
    ):
        return selected_id, action_index, reason

    recommended = catanatron_search(payload).get("recommended_action")
    recommended_index, recommended_action = catanatron_teacher_recommended_action(
        payload,
        recommended,
    )
    if recommended_action is None:
        return selected_id, action_index, reason

    if (
        action_type(recommended_action) == "MOVE_ROBBER"
        and not search_strategy.get("override_robber", True)
    ):
        return selected_id, action_index, reason

    finish_override = catanatron_search_finish_override(
        payload,
        strategy,
        recommended_action,
    )
    if finish_override is not None:
        return finish_override

    initial_road_override = catanatron_search_initial_road_override(
        payload,
        strategy,
        recommended_action,
    )
    if initial_road_override is not None:
        return initial_road_override

    city_override = catanatron_search_city_override(
        payload,
        strategy,
        recommended_action,
    )
    if city_override is not None:
        return city_override

    army_defense_override = catanatron_search_army_defense_override(
        payload,
        strategy,
        recommended_action,
    )
    if army_defense_override is not None:
        return army_defense_override

    anti_stall_trade_override = catanatron_search_anti_stall_trade_override(
        payload,
        strategy,
        recommended_action,
    )
    if anti_stall_trade_override is not None:
        return anti_stall_trade_override

    if not search_action_passes_guardrails(payload, strategy, recommended_action):
        return selected_id, action_index, f"{reason}; catanatron search rejected by guardrails"

    road_override = catanatron_search_road_override(
        payload,
        strategy,
        recommended_action,
    )
    if road_override is not None:
        return road_override

    recommended_id, recommended_action_index = action_id(
        recommended_action,
        recommended_index,
    )
    return (
        recommended_id,
        recommended_action_index,
        "catanatron search primary",
    )


def teacher_action_passes_strategy_gate(payload, strategy, action):
    state = payload.get("state", {})
    color = payload.get("color")
    type_name = action_type(action)
    hand_pressure = is_discard_risk(state, color, strategy)
    endgame = is_endgame(state, color, strategy)

    if type_name == "BUILD_ROAD":
        return road_action_is_strategy_approved(
            action,
            state,
            color,
            strategy,
            hand_pressure=hand_pressure,
        )
    if type_name == "MARITIME_TRADE":
        actions = payload.get("legal_actions") or payload.get("playable_actions", [])
        candidates = [
            candidate
            for candidate in actions
            if action_type(candidate) == "MARITIME_TRADE"
        ]
        selected = choose_maritime_trade_action(
            candidates,
            state,
            color,
            strategy,
            hand_pressure=hand_pressure,
            endgame=endgame,
        )
        return selected is not None and same_action(selected, action)
    if type_name == "BUY_DEVELOPMENT_CARD":
        return (
            should_buy_development_card(state, color, strategy, ignore_caps=endgame)
            or should_buy_development_card_to_reduce_hand(state, color, strategy)
        )
    if type_name == "PLAY_ROAD_BUILDING":
        return should_play_road_building(state, color, strategy)
    return True


def apply_catanatron_teacher_override(
    payload,
    strategy,
    selected_id,
    action_index,
    reason,
):
    teacher_strategy = strategy.get("catanatron_teacher", {})
    if not teacher_strategy.get("enabled", False):
        return selected_id, action_index, reason

    current_prompt = payload.get("current_prompt")
    initial_prompts = {"BUILD_INITIAL_SETTLEMENT", "BUILD_INITIAL_ROAD"}
    if (
        current_prompt in initial_prompts
        and not teacher_strategy.get("override_initial", False)
    ):
        return selected_id, action_index, reason

    actions = payload.get("legal_actions") or payload.get("playable_actions", [])
    selected_local_index, selected_action = selected_action_from_result(
        actions,
        selected_id,
        action_index,
    )
    recommended = catanatron_teacher(payload).get("recommended_action")
    recommended_index, recommended_action = catanatron_teacher_recommended_action(
        payload,
        recommended,
    )
    if recommended_action is None:
        return selected_id, action_index, reason

    recommended_type = action_type(recommended_action)
    if recommended_type in set(teacher_strategy.get("blocked_types", [])):
        return selected_id, action_index, reason
    if teacher_strategy.get("respect_strategy_gates", True) and not teacher_action_passes_strategy_gate(
        payload,
        strategy,
        recommended_action,
    ):
        return selected_id, action_index, reason

    selected_type = action_type(selected_action) if selected_action is not None else None
    teacher_scores = catanatron_teacher_scores_by_id(payload)
    selected_teacher_row = (
        teacher_row_for_action(selected_action, selected_local_index, teacher_scores)
        if selected_action is not None
        else None
    )
    selected_teacher_score = (
        selected_teacher_row.get("score")
        if selected_teacher_row is not None
        else None
    )
    recommended_teacher_score = recommended.get("score")

    should_override = False
    override_reason = None
    if (
        teacher_strategy.get("same_type_override_enabled", True)
        and selected_type == recommended_type
        and selected_local_index != recommended_index
        and (
            selected_teacher_score is None
            or recommended_teacher_score is None
            or recommended_teacher_score > selected_teacher_score
        )
    ):
        should_override = True
        override_reason = f"{reason}; catanatron teacher prefers same action type"

    allowed_anti_pass_types = set(
        teacher_strategy.get(
            "anti_pass_action_types",
            [
                "BUILD_CITY",
                "BUILD_SETTLEMENT",
                "BUILD_ROAD",
                "BUY_DEVELOPMENT_CARD",
                "MARITIME_TRADE",
                "PLAY_KNIGHT_CARD",
                "PLAY_YEAR_OF_PLENTY",
                "PLAY_MONOPOLY",
                "PLAY_ROAD_BUILDING",
            ],
        )
    )
    if (
        not should_override
        and teacher_strategy.get("avoid_pass_enabled", True)
        and selected_type == "END_TURN"
        and recommended_type in allowed_anti_pass_types
    ):
        should_override = True
        override_reason = f"{reason}; catanatron teacher avoids pass"

    if not should_override:
        return selected_id, action_index, reason

    recommended_id, recommended_action_index = action_id(
        recommended_action,
        recommended_index,
    )
    return recommended_id, recommended_action_index, override_reason


def score_candidate_for_diagnostics(action, payload, strategy):
    state = payload.get("state", {})
    color = payload.get("color")
    type_name = action_type(action)
    current_prompt = payload.get("current_prompt")
    scoring = strategy.get("scoring", {})
    keep_targets = strategy.get("hand_management", {}).get("discard_keep_targets", {})

    try:
        if type_name == "BUILD_SETTLEMENT":
            return node_score(state, action_value(action), strategy, color)
        if type_name == "BUILD_CITY":
            return node_score(state, action_value(action), strategy, color)
        if type_name == "BUILD_ROAD":
            if current_prompt == "BUILD_INITIAL_ROAD":
                return initial_road_score(action, state, color, strategy)
            return score_road_action(action, state, color, strategy)
        if type_name == "MARITIME_TRADE":
            return score_maritime_trade_action(
                action,
                state,
                color,
                strategy,
                hand_pressure=is_discard_risk(state, color, strategy),
                endgame=is_endgame(state, color, strategy),
            )
        if type_name == "MOVE_ROBBER":
            return score_robber_action(action, payload, strategy)
        if type_name == "DISCARD_RESOURCE":
            return discard_score(action, state, color, strategy, scoring, keep_targets)
        if type_name == "PLAY_YEAR_OF_PLENTY":
            return score_year_of_plenty_action(action, state, color, strategy)
        if type_name == "PLAY_MONOPOLY":
            return sum(
                resource_count(state, other_color, action_value(action))
                for other_color in state.get("colors", [])
                if other_color != color
            )
        if type_name == "PLAY_ROAD_BUILDING":
            return 1 if should_play_road_building(state, color, strategy) else -999
        if type_name == "BUY_DEVELOPMENT_CARD":
            return 1 if should_buy_development_card(
                state,
                color,
                strategy,
                ignore_caps=is_endgame(state, color, strategy),
            ) else -999
        if type_name == "ROLL":
            return 999
        if type_name == "END_TURN":
            return 0
    except Exception as exc:
        return {"error": str(exc)}
    return None


def normalized_score_for_json(score):
    if isinstance(score, (int, float)):
        return round(score, 4)
    return score


def candidate_scores_for_diagnostics(payload, strategy, per_type_limit=5, overall_limit=12):
    actions = payload.get("legal_actions") or payload.get("playable_actions", [])
    search_scores = catanatron_search_scores_by_id(payload)
    teacher_scores = catanatron_teacher_scores_by_id(payload)
    rows = []
    for index, action in enumerate(actions):
        score = score_candidate_for_diagnostics(action, payload, strategy)
        row = action_summary(action, index)
        row["score"] = normalized_score_for_json(score)
        search_row = teacher_row_for_action(action, index, search_scores)
        if search_row is not None:
            row["catanatron_search_score"] = normalized_score_for_json(
                search_row.get("score")
            )
            row["catanatron_search_scored"] = search_row.get("alpha_beta_scored", False)
        teacher_row = teacher_row_for_action(action, index, teacher_scores)
        if teacher_row is not None:
            row["catanatron_value_score"] = normalized_score_for_json(
                teacher_row.get("score")
            )
            row["catanatron_pruned"] = teacher_row.get("pruned", False)
        rows.append(row)

    def sort_key(row):
        score = row.get("score")
        return score if isinstance(score, (int, float)) else -1000000

    by_type = {}
    for row in rows:
        by_type.setdefault(row["type"], []).append(row)
    for type_name, type_rows in by_type.items():
        by_type[type_name] = sorted(type_rows, key=sort_key, reverse=True)[:per_type_limit]

    return {
        "top_overall": sorted(rows, key=sort_key, reverse=True)[:overall_limit],
        "top_by_type": by_type,
    }


def self_summary(state, color):
    pieces = board_piece_counts(state, color)
    return {
        "actual_victory_points": actual_victory_points(state, color),
        "public_victory_points": player_state_value(state, color, "VICTORY_POINTS", 0),
        "resources": resource_counts(state, color),
        "resource_total": player_resource_total(state, color),
        "development_cards": {
            card_type: development_count(state, color, card_type)
            for card_type in TACTICAL_DEVELOPMENT_TYPES + ("VICTORY_POINT",)
        },
        "pieces": pieces,
        "longest_road_length": player_state_value(state, color, "LONGEST_ROAD_LENGTH", 0),
        "has_longest_road": bool(player_state_value(state, color, "HAS_ROAD", False)),
        "has_largest_army": bool(player_state_value(state, color, "HAS_ARMY", False)),
    }


def build_decision_diagnostics(
    payload,
    strategy,
    selected_id,
    action_index,
    reason,
    error=None,
    fallback=False,
):
    actions = payload.get("legal_actions") or payload.get("playable_actions", [])
    state = payload.get("state", {})
    color = payload.get("color")
    selected_local_index, selected_action = selected_action_from_result(
        actions, selected_id, action_index
    )
    record = {
        "timestamp": iso_timestamp(),
        "game_id": payload.get("game_id"),
        "state_index": payload.get("state_index"),
        "color": color,
        "current_prompt": payload.get("current_prompt"),
        "strategy_name": strategy.get("name", "default"),
        "legal_action_count": len(actions),
        "legal_action_type_counts": action_type_counts(actions),
        "selected_action_id": selected_id,
        "selected_action_index": action_index,
        "selected_action_local_index": selected_local_index,
        "selected_action": (
            action_summary(selected_action, selected_local_index)
            if selected_action is not None
            else None
        ),
        "reason": reason,
        "fallback": fallback,
        "hand_pressure": is_discard_risk(state, color, strategy) if color else False,
        "self": self_summary(state, color) if color else {},
        "players": payload.get("strategy", {}).get("players", []),
        "public_leader": payload.get("strategy", {}).get("public_leader"),
        "catanatron_search": {
            "source": catanatron_search(payload).get("source"),
            "depth": catanatron_search(payload).get("depth"),
            "prunning": catanatron_search(payload).get("prunning"),
            "value_fn": catanatron_search(payload).get("value_fn"),
            "elapsed_ms": catanatron_search(payload).get("elapsed_ms"),
            "recommended_action": catanatron_search(payload).get("recommended_action"),
            "error": catanatron_search(payload).get("error"),
        },
        "catanatron_teacher": {
            "source": catanatron_teacher(payload).get("source"),
            "recommended_action": catanatron_teacher(payload).get("recommended_action"),
            "error": catanatron_teacher(payload).get("error"),
        },
        "candidate_scores": candidate_scores_for_diagnostics(payload, strategy),
    }
    if error is not None:
        record["error"] = error
    return record


def write_decision_log(path, record):
    if not path:
        return
    try:
        log_path = Path(path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        print(f"Failed to write decision log {path}: {exc}")


class DecisionHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/decide":
            self.send_error(404, "Not found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
            selected_id, action_index, reason, diagnostics = choose_action_with_diagnostics(
                payload, STRATEGY
            )
            response = {"action_index": action_index, "reason": reason}
            if selected_id is not None:
                response["action_id"] = selected_id
            write_decision_log(DECISION_LOG_PATH, diagnostics)
            self._send_json(response)
        except Exception as exc:
            self._send_json(self._fallback_response(raw_body, exc), status=200)

    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format % args))

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _fallback_response(self, raw_body, exc):
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            actions = payload.get("legal_actions") or payload.get("playable_actions", [])
            for index, action in enumerate(actions):
                if action_type(action) == "END_TURN":
                    selected_id, selected_index = action_id(action, index)
                    response = {
                        "action_index": selected_index,
                        "reason": "safe fallback end turn",
                        "error": str(exc),
                    }
                    if selected_id is not None:
                        response["action_id"] = selected_id
                    write_decision_log(
                        DECISION_LOG_PATH,
                        build_decision_diagnostics(
                            payload,
                            STRATEGY,
                            selected_id,
                            selected_index,
                            response["reason"],
                            error=str(exc),
                            fallback=True,
                        ),
                    )
                    return response
            write_decision_log(
                DECISION_LOG_PATH,
                build_decision_diagnostics(
                    payload,
                    STRATEGY,
                    None,
                    0,
                    "unsafe fallback first action",
                    error=str(exc),
                    fallback=True,
                ),
            )
        except Exception:
            write_decision_log(
                DECISION_LOG_PATH,
                {
                    "timestamp": iso_timestamp(),
                    "reason": "unsafe fallback first action",
                    "fallback": True,
                    "error": str(exc),
                },
            )
        return {"action_index": 0, "reason": "unsafe fallback first action", "error": str(exc)}


def main():
    global STRATEGY, DECISION_LOG_PATH
    parser = argparse.ArgumentParser(description="Local heuristic Codex Catanatron webhook adapter")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    default_strategy_path = Path(__file__).with_name("strategy.json")
    parser.add_argument(
        "--strategy",
        default=str(default_strategy_path) if default_strategy_path.exists() else None,
        help="Path to a JSON strategy profile with scoring weights.",
    )
    parser.add_argument(
        "--decision-log",
        default=None,
        help="Append one JSONL diagnostics record per webhook decision.",
    )
    args = parser.parse_args()

    STRATEGY = load_strategy(args.strategy)
    DECISION_LOG_PATH = args.decision_log
    server = HTTPServer((args.host, args.port), DecisionHandler)
    strategy_name = STRATEGY.get("name", "default")
    print(f"Listening on http://{args.host}:{args.port}/decide ({strategy_name})")
    if DECISION_LOG_PATH:
        print(f"Decision log: {DECISION_LOG_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
