import type { Color, GameState } from "./api.types";

const COLORS: Color[] = ["RED", "BLUE", "ORANGE", "WHITE"];

export function colorFromSearch(search: string): Color | null {
  const value = new URLSearchParams(search).get("player")?.toUpperCase();
  return COLORS.includes(value as Color) ? (value as Color) : null;
}

export function humanColors(gameState: GameState): Color[] {
  return gameState.colors.filter(
    (color) => !gameState.bot_colors.includes(color)
  );
}

export function localHumanColor(gameState: GameState, search: string): Color | null {
  const requestedColor = colorFromSearch(search);
  const humans = humanColors(gameState);

  if (requestedColor && humans.includes(requestedColor)) {
    return requestedColor;
  }

  return humans[0] ?? null;
}

export function canLocalPlayerAct(gameState: GameState, search: string): boolean {
  return localHumanColor(gameState, search) === gameState.current_color;
}
