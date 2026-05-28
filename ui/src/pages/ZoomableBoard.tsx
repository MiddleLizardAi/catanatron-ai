import { useCallback, useContext, useEffect, useState } from "react";
import { TransformWrapper, TransformComponent } from "react-zoom-pan-pinch";
import memoize from "fast-memoize";
import { useMediaQuery, useTheme } from "@mui/material";

import useWindowSize from "../utils/useWindowSize";

import "./Board.scss";
import { store } from "../store";
import { isPlayersTurn } from "../utils/stateUtils";
import { getState, postAction } from "../utils/apiClient";
import type { CatanState } from "../store";
import { useParams } from "react-router";
import ACTIONS from "../actions";
import Board from "./Board";
import type { GameAction, TileCoordinate } from "../utils/api.types";
import { canLocalPlayerAct } from "../utils/localPlayer";

/**
 * Returns object representing actions to be taken if click on node.
 * @returns {3 => ["BLUE", "BUILD_CITY", 3], ...}
 */
function buildNodeActions(state: CatanState, search: string) {
  if (!state.gameState)
    throw new Error("GameState is not ready!");

  if (!isPlayersTurn(state.gameState) || !canLocalPlayerAct(state.gameState, search)) {
    return {};
  }

  const nodeActions: Record<number, GameAction> = {};
  const buildInitialSettlementActions = state.gameState.is_initial_build_phase
    ? state.gameState.current_playable_actions.filter(
        (action) => action[1] === "BUILD_SETTLEMENT"
      )
    : [];
  const inInitialBuildPhase = state.gameState.is_initial_build_phase;
  if (inInitialBuildPhase) {
    buildInitialSettlementActions.forEach((action) => {
      nodeActions[action[2]] = action;
    });
  } else if (state.isBuildingSettlement) {
    state.gameState.current_playable_actions
      .filter((action) => action[1] === "BUILD_SETTLEMENT")
      .forEach((action) => {
        nodeActions[action[2]] = action;
      });
  } else if (state.isBuildingCity) {
    state.gameState.current_playable_actions
      .filter((action) => action[1] === "BUILD_CITY")
      .forEach((action) => {
        nodeActions[action[2]] = action;
      });
  }
  return nodeActions;
}

function buildEdgeActions(state: CatanState, search: string) {
  if (!state.gameState)
    throw new Error("GameState is not ready!");
  if (!isPlayersTurn(state.gameState) || !canLocalPlayerAct(state.gameState, search)) {
    return {};
  }

  const edgeActions: Record<`${number},${number}`, GameAction> = {};
  const buildInitialRoadActions = state.gameState.is_initial_build_phase
    ? state.gameState.current_playable_actions.filter(
        (action) => action[1] === "BUILD_ROAD"
      )
    : [];
  const inInitialBuildPhase = state.gameState.is_initial_build_phase;
  if (inInitialBuildPhase) {
    buildInitialRoadActions.forEach((action) => {
      edgeActions[`${action[2][0]},${action[2][1]}`] = action;
    });
  } else if (state.isBuildingRoad || state.isRoadBuilding) {
    state.gameState.current_playable_actions
      .filter((action) => action[1] === "BUILD_ROAD")
      .forEach((action) => {
        edgeActions[`${action[2][0]},${action[2][1]}`] = action;
      });
  }
  return edgeActions;
}

type ZoomableBoardProps = {
  replayMode: boolean;
}

export default function ZoomableBoard({ replayMode }: ZoomableBoardProps) {
  const { gameId } = useParams();
  const { state, dispatch } = useContext(store);
  const { width, height } = useWindowSize();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.up("md"));
  const [show, setShow] = useState(false);
  const gameState = state.gameState
  if (!gameState)
    throw new Error("GameState is not ready!");
  if (!gameId)
    throw new Error("expecting gameId in URL");

  // TODO: Move these up to GameScreen and let Zoomable be presentational component
  // https://stackoverflow.com/questions/61255053/react-usecallback-with-parameter
  const buildOnNodeClick = useCallback(
    memoize((id, action) => async () => {
      console.log("Clicked Node ", id, action);
      if (action) {
        try {
          const nextGameState = await postAction(
            gameId,
            action,
            gameState.state_index,
          );
          dispatch({ type: ACTIONS.SET_GAME_STATE, data: nextGameState });
        } catch (error) {
          console.error("Failed to submit node action; refreshing latest state", error);
          const latestState = await getState(gameId, "latest");
          dispatch({ type: ACTIONS.SET_GAME_STATE, data: latestState });
        }
      }
    }),
    [gameId, dispatch, gameState.state_index]
  );
  const buildOnEdgeClick = useCallback(
    memoize((id, action) => async () => {
      console.log("Clicked Edge ", id, action);
      if (action) {
        try {
          const nextGameState = await postAction(
            gameId,
            action,
            gameState.state_index,
          );
          dispatch({ type: ACTIONS.SET_GAME_STATE, data: nextGameState });
        } catch (error) {
          console.error("Failed to submit edge action; refreshing latest state", error);
          const latestState = await getState(gameId, "latest");
          dispatch({ type: ACTIONS.SET_GAME_STATE, data: latestState });
        }
      }
    }),
    [gameId, dispatch, gameState.state_index]
  );
  const isMoveRobberPrompt =
    !replayMode &&
    gameState.current_prompt === "MOVE_ROBBER" &&
    canLocalPlayerAct(gameState, window.location.search);
  const handleTileClick = useCallback(
    memoize(async (coordinate: TileCoordinate) => {
      console.log("Clicked Tile ", coordinate);
      if (isMoveRobberPrompt) {
        // Find the "MOVE_ROBBER" action in current_playable_actions that
        // corresponds to the tile coordinate selected by the user
        const matchingAction = gameState.current_playable_actions.find(
          (action) =>
            action[1] === "MOVE_ROBBER" &&
            action[2][0].every(
              (val: number, index: number) => val === coordinate[index],
            ),
        );
        if (matchingAction) {
          try {
            const nextGameState = await postAction(
              gameId,
              matchingAction,
              gameState.state_index,
            );
            dispatch({ type: ACTIONS.SET_GAME_STATE, data: nextGameState });
          } catch (error) {
            console.error("Failed to submit robber action; refreshing latest state", error);
            const latestState = await getState(gameId, "latest");
            dispatch({ type: ACTIONS.SET_GAME_STATE, data: latestState });
          }
        } else {
          const latestState = await getState(gameId, "latest");
          dispatch({ type: ACTIONS.SET_GAME_STATE, data: latestState });
        }
      }
    }),
    [
      isMoveRobberPrompt,
      gameState.current_playable_actions,
      gameState.state_index,
      gameId,
      dispatch,
    ]
  );

  const nodeActions = replayMode ? {} : buildNodeActions(state, window.location.search);
  const edgeActions = replayMode ? {} : buildEdgeActions(state, window.location.search);
  const robberCoordinates = new Set(
    isMoveRobberPrompt
      ? gameState.current_playable_actions
          .filter((action) => action[1] === "MOVE_ROBBER")
          .map((action) => `${action[2][0]}`)
      : []
  );

  useEffect(() => {
    setTimeout(() => {
      setShow(true);
    }, 300);
  }, []);

  if (!width || !height) return;

  return (
    <TransformWrapper>
      <div className="board-container">
        <TransformComponent>
          <Board
            width={width}
            height={height}
            buildOnNodeClick={buildOnNodeClick}
            buildOnEdgeClick={buildOnEdgeClick}
            handleTileClick={handleTileClick}
            nodeActions={nodeActions}
            edgeActions={edgeActions}
            replayMode={replayMode}
            show={show}
            gameState={gameState}
            isMobile={isMobile}
            isMovingRobber={isMoveRobberPrompt}
            robberCoordinates={robberCoordinates}
          />
        </TransformComponent>
      </div>
    </TransformWrapper>
  );
}
