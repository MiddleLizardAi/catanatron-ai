import cn from "classnames";

import "./PlayerStateBox.scss";
import { type Color, type PlayerState } from "../utils/api.types";
import ResourceCards from "./ResourceCards";

export default function PlayerStateBox({ playerState, playerKey, color, showHand }: {
  playerState: PlayerState; playerKey: string; color: Color; showHand: boolean }) {
  const publicVps = playerState[`${playerKey}_VICTORY_POINTS`];
  const actualVps = playerState[`${playerKey}_ACTUAL_VICTORY_POINTS`];
  const visibleVps = showHand ? actualVps : publicVps;
  return (
    <div className={cn("player-state-box foreground", color)}>
      <ResourceCards playerState={playerState} playerKey={playerKey} visible={showHand} />
      <div className="scores">
        <div
          className={cn("num-knights center-text", {
            bold: playerState[`${playerKey}_HAS_ARMY`],
          })}
          title="Knights Played"
        >
          <span>{playerState[`${playerKey}_PLAYED_KNIGHT`]}</span>
          <small>knights</small>
        </div>
        <div
          className={cn("num-roads center-text", {
            bold: playerState[`${playerKey}_HAS_ROAD`],
          })}
          title="Longest Road"
        >
          {playerState[`${playerKey}_LONGEST_ROAD_LENGTH`]}
          <small>roads</small>
        </div>
        <div
          className={cn("victory-points center-text", {
            bold: visibleVps >= 10,
          })}
          title={showHand ? "Victory Points" : "Public Victory Points"}
        >
          {visibleVps}
          <small>VPs</small>
        </div>
      </div>
    </div>
  );
}
