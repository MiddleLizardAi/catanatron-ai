import React, {
  useState,
  useRef,
  useEffect,
  useContext,
  useCallback,
} from "react";
import memoize from "fast-memoize";
import { Button } from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import AccountBalanceIcon from "@mui/icons-material/AccountBalance";
import BuildIcon from "@mui/icons-material/Build";
import NavigateNextIcon from "@mui/icons-material/NavigateNext";
import MenuItem from "@mui/material/MenuItem";
import ClickAwayListener from "@mui/material/ClickAwayListener";
import Grow from "@mui/material/Grow";
import Paper from "@mui/material/Paper";
import Popper from "@mui/material/Popper";
import MenuList from "@mui/material/MenuList";
import SimCardIcon from "@mui/icons-material/SimCard";
import { useParams } from "react-router";

import Hidden from "../components/Hidden";
import Prompt from "../components/Prompt";
import ResourceCards from "../components/ResourceCards";
import ResourceSelector from "../components/ResourceSelector";
import DiscardPlannerDialog from "../components/DiscardPlannerDialog";
import { store } from "../store";
import ACTIONS from "../actions";
import type { GameAction, ResourceCard } from "../utils/api.types"; // Add GameState to the import, adjust path if needed
import { getHumanColor, playerKey } from "../utils/stateUtils";
import { getState, postAction } from "../utils/apiClient";
import { humanizeTradeAction } from "../utils/promptUtils";
import { useDiscardBatchSubmission } from "../hooks/useDiscardBatchSubmission";
import { canLocalPlayerAct, localHumanColor } from "../utils/localPlayer";

import "./ActionsToolbar.scss";
import { useSnackbar } from "notistack";
import { dispatchSnackbar } from "../components/Snackbar";

const RESOURCE_ORDER: ResourceCard[] = [
  "WOOD",
  "BRICK",
  "SHEEP",
  "WHEAT",
  "ORE",
];

function PlayButtons() {
  const { gameId } = useParams();
  if (!gameId) {
    console.error("Game ID is not found in URL parameters.");
    return null;
  }
  const { state, dispatch } = useContext(store);
  const { enqueueSnackbar, closeSnackbar } = useSnackbar();
  const [resourceSelectorOpen, setResourceSelectorOpen] = useState(false);
  const [discardPlannerOpen, setDiscardPlannerOpen] = useState(false);
  const [isActionPending, setIsActionPending] = useState(false);
  const { isSubmitting, submitDiscardBatch } = useDiscardBatchSubmission();

  const refreshLatestState = useCallback(async () => {
    const latestState = await getState(gameId, "latest");
    dispatch({ type: ACTIONS.SET_GAME_STATE, data: latestState });
    dispatchSnackbar(enqueueSnackbar, closeSnackbar, latestState);
  }, [gameId, dispatch, enqueueSnackbar, closeSnackbar]);

  const carryOutAction = useCallback(
    memoize((action?: GameAction) => async () => {
      try {
        if (!action) {
          await refreshLatestState();
          return;
        }
        setIsActionPending(true);
        const gameState = await postAction(
          gameId,
          action,
          state.gameState?.state_index,
        );
        dispatch({ type: ACTIONS.SET_GAME_STATE, data: gameState });
        dispatchSnackbar(enqueueSnackbar, closeSnackbar, gameState);
      } catch (error) {
        console.error("Failed to submit action; refreshing latest state", error);
        await refreshLatestState();
      } finally {
        setIsActionPending(false);
      }
    }),
    [
      gameId,
      dispatch,
      enqueueSnackbar,
      closeSnackbar,
      refreshLatestState,
      state.gameState?.state_index,
    ],
  );

  const {
    gameState,
    isPlayingMonopoly,
    isPlayingYearOfPlenty,
    isRoadBuilding,
  } = state;
  if (gameState === null) {
    return null;
  }
  const key = playerKey(gameState, gameState.current_color);
  const isRoll =
    gameState.current_prompt === "PLAY_TURN" &&
    !gameState.player_state[`${key}_HAS_ROLLED`];
  const isDiscard = gameState.current_prompt === "DISCARD";
  const isMovingRobber = gameState.current_prompt === "MOVE_ROBBER";
  const isPlayingDevCard =
    isPlayingMonopoly || isPlayingYearOfPlenty || isRoadBuilding;
  const playableAction = useCallback(
    (actionType: string) =>
      gameState.current_playable_actions.find((action) => action[1] === actionType),
    [gameState.current_playable_actions],
  );
  const playableEndTurnAction = gameState.current_playable_actions.find(
    (action) => action[1] === "END_TURN",
  );
  const playableRollAction = gameState.current_playable_actions.find(
    (action) => action[1] === "ROLL",
  );
  const humanColor = localHumanColor(gameState, window.location.search) ?? getHumanColor(gameState);
  const discardActionType =
    gameState.current_playable_actions.find(
      (action) => action[1] === "DISCARD_RESOURCE",
    )?.[1] ?? "DISCARD_RESOURCE";
  const setIsPlayingMonopoly = useCallback(() => {
    dispatch({ type: ACTIONS.SET_IS_PLAYING_MONOPOLY });
  }, [dispatch]);
  const getDiscardResourceCounts = useCallback(() => {
    return RESOURCE_ORDER.reduce(
      (counts, resource) => {
        const inHand = gameState.player_state[`${key}_${resource}_IN_HAND`];
        if (inHand > 0) {
          counts[resource] = inHand;
        }
        return counts;
      },
      {} as Partial<Record<ResourceCard, number>>,
    );
  }, [gameState.player_state, key]);
  const getValidYearOfPlentyOptions = useCallback(() => {
    return gameState.current_playable_actions
      .filter((action) => action[1] === "PLAY_YEAR_OF_PLENTY")
      .map((action) => action[2]);
  }, [gameState.current_playable_actions]);
  const handleResourceSelection = useCallback(
    async (selectedResources: ResourceCard | ResourceCard[]) => {
      setResourceSelectorOpen(false);
      try {
        let action: GameAction;
        if (isPlayingMonopoly) {
          action = [
            humanColor,
            "PLAY_MONOPOLY",
            selectedResources as ResourceCard,
          ];
        } else if (isPlayingYearOfPlenty) {
          action = [
            humanColor,
            "PLAY_YEAR_OF_PLENTY",
            selectedResources as [ResourceCard] | [ResourceCard, ResourceCard],
          ];
        } else {
          console.error("Invalid resource selector mode");
          await refreshLatestState();
          return;
        }
        setIsActionPending(true);
        const nextGameState = await postAction(
          gameId,
          action,
          gameState.state_index,
        );
        dispatch({ type: ACTIONS.SET_GAME_STATE, data: nextGameState });
        dispatchSnackbar(enqueueSnackbar, closeSnackbar, nextGameState);
      } catch (error) {
        console.error("Failed to submit development-card action; refreshing latest state", error);
        await refreshLatestState();
      } finally {
        setIsActionPending(false);
      }
    },
    [
      gameId,
      humanColor,
      dispatch,
      enqueueSnackbar,
      closeSnackbar,
      isPlayingMonopoly,
      isPlayingYearOfPlenty,
      refreshLatestState,
      gameState.state_index,
    ],
  );
  const handleOpenResourceSelector = useCallback(() => {
    setResourceSelectorOpen(true);
  }, []);
  const handleOpenDiscardPlanner = useCallback(() => {
    setDiscardPlannerOpen(true);
  }, []);
  const handleDiscardSelection = useCallback(
    async (resources: ResourceCard[]) => {
      setDiscardPlannerOpen(false);
      try {
        const nextGameState = await submitDiscardBatch({
          discardActionType,
          gameId,
          humanColor,
          resources,
          stateIndex: gameState.state_index,
        });
        dispatch({ type: ACTIONS.SET_GAME_STATE, data: nextGameState });
        dispatchSnackbar(enqueueSnackbar, closeSnackbar, nextGameState);
      } catch (error) {
        console.error("Failed to submit discard action; refreshing latest state", error);
        await refreshLatestState();
      }
    },
    [
      discardActionType,
      gameId,
      humanColor,
      submitDiscardBatch,
      dispatch,
      enqueueSnackbar,
      closeSnackbar,
      refreshLatestState,
      gameState.state_index,
    ],
  );
  const setIsPlayingYearOfPlenty = useCallback(() => {
    dispatch({ type: ACTIONS.SET_IS_PLAYING_YEAR_OF_PLENTY });
  }, [dispatch]);
  const playRoadBuilding = useCallback(async () => {
    const action = playableAction("PLAY_ROAD_BUILDING");
    if (!action) {
      await refreshLatestState();
      return;
    }
    try {
      setIsActionPending(true);
      const gameState = await postAction(
        gameId,
        action,
        state.gameState?.state_index,
      );
      dispatch({ type: ACTIONS.PLAY_ROAD_BUILDING });
      dispatch({ type: ACTIONS.SET_GAME_STATE, data: gameState });
      dispatchSnackbar(enqueueSnackbar, closeSnackbar, gameState);
    } catch (error) {
      console.error("Failed to play road building; refreshing latest state", error);
      await refreshLatestState();
    } finally {
      setIsActionPending(false);
    }
  }, [
    gameId,
    dispatch,
    enqueueSnackbar,
    closeSnackbar,
    playableAction,
    refreshLatestState,
    state.gameState?.state_index,
  ]);
  const playKnightCard = useCallback(async () => {
    const action = playableAction("PLAY_KNIGHT_CARD");
    if (!action) {
      await refreshLatestState();
      return;
    }
    try {
      setIsActionPending(true);
      const gameState = await postAction(
        gameId,
        action,
        state.gameState?.state_index,
      );
      dispatch({ type: ACTIONS.SET_GAME_STATE, data: gameState });
      dispatchSnackbar(enqueueSnackbar, closeSnackbar, gameState);
    } catch (error) {
      console.error("Failed to play knight card; refreshing latest state", error);
      await refreshLatestState();
    } finally {
      setIsActionPending(false);
    }
  }, [
    gameId,
    dispatch,
    enqueueSnackbar,
    closeSnackbar,
    playableAction,
    refreshLatestState,
    state.gameState?.state_index,
  ]);
  const useItems = [
    {
      label: "Monopoly",
      disabled: !playableAction("PLAY_MONOPOLY"),
      onClick: setIsPlayingMonopoly,
    },
    {
      label: "Year of Plenty",
      disabled: !playableAction("PLAY_YEAR_OF_PLENTY"),
      onClick: setIsPlayingYearOfPlenty,
    },
    {
      label: "Road Building",
      disabled: !playableAction("PLAY_ROAD_BUILDING"),
      onClick: playRoadBuilding,
    },
    {
      label: "Knight",
      disabled: !playableAction("PLAY_KNIGHT_CARD"),
      onClick: playKnightCard,
    },
  ];

  const buildActionTypes = new Set(
    gameState.is_initial_build_phase
      ? []
      : gameState.current_playable_actions
          .filter(
            (action) =>
              action[1].startsWith("BUY") || action[1].startsWith("BUILD"),
          )
          .map((a) => a[1]),
  );
  const buyDevelopmentCardAction = playableAction("BUY_DEVELOPMENT_CARD");
  const buyDevCard = useCallback(async () => {
    if (!buyDevelopmentCardAction) {
      await refreshLatestState();
      return;
    }
    try {
      setIsActionPending(true);
      const nextGameState = await postAction(
        gameId,
        buyDevelopmentCardAction,
        gameState.state_index,
      );
      dispatch({ type: ACTIONS.SET_GAME_STATE, data: nextGameState });
      dispatchSnackbar(enqueueSnackbar, closeSnackbar, nextGameState);
    } catch (error) {
      console.error("Failed to buy development card; refreshing latest state", error);
      await refreshLatestState();
    } finally {
      setIsActionPending(false);
    }
  }, [
    gameId,
    buyDevelopmentCardAction,
    dispatch,
    enqueueSnackbar,
    closeSnackbar,
    refreshLatestState,
    gameState.state_index,
  ]);
  const setIsBuildingSettlement = useCallback(() => {
    dispatch({ type: ACTIONS.SET_IS_BUILDING_SETTLEMENT });
  }, [dispatch]);
  const setIsBuildingCity = useCallback(() => {
    dispatch({ type: ACTIONS.SET_IS_BUILDING_CITY });
  }, [dispatch]);
  const toggleBuildingRoad = useCallback(() => {
    dispatch({ type: ACTIONS.TOGGLE_BUILDING_ROAD });
  }, [dispatch]);
  const buildItems = [
    {
      label: "Development Card",
      disabled: !buyDevelopmentCardAction,
      onClick: buyDevCard,
    },
    {
      label: "City",
      disabled: !buildActionTypes.has("BUILD_CITY"),
      onClick: setIsBuildingCity,
    },
    {
      label: "Settlement",
      disabled: !buildActionTypes.has("BUILD_SETTLEMENT"),
      onClick: setIsBuildingSettlement,
    },
    {
      label: "Road",
      disabled: !buildActionTypes.has("BUILD_ROAD"),
      onClick: toggleBuildingRoad,
    },
  ];

  const tradeActions = gameState.current_playable_actions.filter(
    (action) => action[1] === "MARITIME_TRADE",
  );
  const tradeItems = React.useMemo(() => {
    const items = tradeActions.map((action) => {
      const label = humanizeTradeAction(action);
      return {
        label: label,
        disabled: false,
        onClick: carryOutAction(action),
      };
    });

    return items.sort((a, b) => a.label.localeCompare(b.label));
  }, [tradeActions, carryOutAction]);

  const rollAction = carryOutAction(playableRollAction ?? [humanColor, "ROLL", null]);
  const endTurnAction = carryOutAction(playableEndTurnAction);
  const hasPlayableDevCardAction = useItems.some((item) => !item.disabled);
  const hasPlayableBuildAction = buildItems.some((item) => !item.disabled);

  useEffect(() => {
    if (isRoll && humanColor === gameState.current_color && !isActionPending) {
      rollAction();
    }
  }, [gameState.current_color, humanColor, isActionPending, isRoll, rollAction]);

  return (
    <>
      <OptionsButton
        disabled={isActionPending || !hasPlayableDevCardAction || isPlayingDevCard}
        menuListId="use-menu-list"
        icon={<SimCardIcon />}
        items={useItems}
      >
        Use
      </OptionsButton>
      <OptionsButton
        disabled={isActionPending || !hasPlayableBuildAction || isPlayingDevCard}
        menuListId="build-menu-list"
        icon={<BuildIcon />}
        items={buildItems}
      >
        Buy
      </OptionsButton>
      <OptionsButton
        disabled={isActionPending || tradeItems.length === 0 || isPlayingDevCard}
        menuListId="trade-menu-list"
        icon={<AccountBalanceIcon />}
        items={tradeItems}
      >
        Trade
      </OptionsButton>
      <Button
        disabled={
          gameState.is_initial_build_phase ||
          isActionPending ||
          isRoadBuilding ||
          isSubmitting ||
          isMovingRobber ||
          (!isDiscard &&
            !isPlayingYearOfPlenty &&
            !isPlayingMonopoly &&
            !isRoll &&
            !playableEndTurnAction)
        }
        variant="contained"
        color="primary"
        startIcon={<NavigateNextIcon />}
        onClick={
          isDiscard
            ? handleOpenDiscardPlanner
            : isPlayingYearOfPlenty || isPlayingMonopoly
                ? handleOpenResourceSelector
                : isRoll
                  ? undefined
                  : endTurnAction
        }
      >
        {isDiscard
          ? "DISCARD"
          : isMovingRobber
            ? "ROBBER"
            : isPlayingYearOfPlenty || isPlayingMonopoly
              ? "SELECT"
              : isRoll
                ? "ROLLING"
                : "END"}
      </Button>
      <ResourceSelector
        open={resourceSelectorOpen}
        onClose={() => {
          setResourceSelectorOpen(false);
          dispatch({ type: ACTIONS.CANCEL_MONOPOLY });
          dispatch({ type: ACTIONS.CANCEL_YEAR_OF_PLENTY });
        }}
        options={getValidYearOfPlentyOptions()}
        onSelect={handleResourceSelection}
        mode={isPlayingMonopoly ? "monopoly" : "yearOfPlenty"}
      />
      <DiscardPlannerDialog
        open={discardPlannerOpen}
        onClose={() => setDiscardPlannerOpen(false)}
        onConfirm={handleDiscardSelection}
        remainingDiscardCount={gameState.current_discard_count}
        discardResourceCounts={getDiscardResourceCounts()}
        submitting={isSubmitting}
      />
    </>
  );
}

export default function ActionsToolbar({
  isBotThinking,
  replayMode,
}: {
  isBotThinking: boolean;
  replayMode: boolean;
}) {
  const { state, dispatch } = useContext(store);
  const { gameState } = state;
  if (gameState === null) {
    console.error("No gameState found...");
    return null;
  }
  const openLeftDrawer = useCallback(() => {
    dispatch({
      type: ACTIONS.SET_LEFT_DRAWER_OPENED,
      data: true,
    });
  }, [dispatch]);

  const openRightDrawer = useCallback(() => {
    dispatch({
      type: ACTIONS.SET_RIGHT_DRAWER_OPENED,
      data: true,
    });
  }, [dispatch]);

  const botsTurn = gameState.bot_colors.includes(gameState.current_color);
  const humanColor = localHumanColor(gameState, window.location.search) ?? getHumanColor(gameState);
  const localCanAct = canLocalPlayerAct(gameState, window.location.search);
  return (
    <>
      <div className="state-summary">
        <Hidden breakpoint={{ size: "md", direction: "up" }}>
          <Button className="open-drawer-btn" onClick={openLeftDrawer}>
            <ChevronLeftIcon />
          </Button>
        </Hidden>
        {humanColor && (
          <ResourceCards
            playerState={gameState.player_state}
            playerKey={playerKey(gameState, humanColor)}
            visible={true}
          />
        )}
        <Hidden breakpoint={{ size: "lg", direction: "up" }}>
          <Button
            className="open-drawer-btn"
            onClick={openRightDrawer}
            style={{ marginLeft: "auto" }}
          >
            <ChevronRightIcon />
          </Button>
        </Hidden>
      </div>
      <div className="actions-toolbar">
        {!(botsTurn || gameState.winning_color) && !replayMode && localCanAct && (
          <PlayButtons />
        )}
        {(botsTurn || gameState.winning_color || !localCanAct) && (
          <Prompt gameState={gameState} isBotThinking={isBotThinking} />
        )}
        {/* <Button
          disabled={disabled}
          className="confirm-btn"
          variant="contained"
          color="primary"
          onClick={onTick}
        >
          Ok
        </Button> */}

        {/* <Button onClick={zoomIn}>Zoom In</Button>
      <Button onClick={zoomOut}>Zoom Out</Button> */}
      </div>
    </>
  );
}

type OptionItem = {
  label: string;
  disabled: boolean;
  onClick: (event: MouseEvent | TouchEvent) => void;
};

type OptionsButtonProps = {
  menuListId: string;
  icon: any;
  children: React.ReactNode;
  items: OptionItem[];
  disabled: boolean;
};

function OptionsButton({
  menuListId,
  icon,
  children,
  items,
  disabled,
}: OptionsButtonProps) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLButtonElement>(null);

  const handleToggle = () => {
    setOpen((prevOpen) => !prevOpen);
  };
  const handleClose =
    (onClick?: (event: MouseEvent | TouchEvent) => void) =>
    (event: MouseEvent | TouchEvent) => {
      if (
        anchorRef.current &&
        anchorRef.current.contains(event.target as Node)
      ) {
        return;
      }

      onClick && onClick(event);
      setOpen(false);
    };
  function handleListKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Tab") {
      event.preventDefault();
      setOpen(false);
    }
  }
  // return focus to the button when we transitioned from !open -> open
  const prevOpen = useRef(open);
  useEffect(() => {
    if (prevOpen.current === true && open === false) {
      anchorRef.current && anchorRef.current.focus();
    }

    prevOpen.current = open;
  }, [open]);

  return (
    <React.Fragment>
      <Button
        disabled={disabled}
        ref={anchorRef}
        aria-controls={open ? menuListId : undefined}
        aria-haspopup="true"
        variant="contained"
        color="secondary"
        startIcon={icon}
        onClick={handleToggle}
      >
        {children}
      </Button>
      <Popper
        className="action-popover"
        open={open}
        anchorEl={anchorRef.current}
        placement="top"
        modifiers={[
          {
            name: "offset",
            options: {
              offset: [0, 88],
            },
          },
        ]}
        role={undefined}
        transition
      >
        {({ TransitionProps, placement }) => (
          <Grow
            {...TransitionProps}
            style={{
              transformOrigin:
                placement === "bottom" ? "center top" : "center bottom",
            }}
          >
            <Paper>
              <ClickAwayListener onClickAway={handleClose()}>
                <MenuList
                  autoFocusItem={open}
                  id={menuListId}
                  onKeyDown={handleListKeyDown}
                >
                  {items.map((item) => (
                    <MenuItem
                      key={item.label}
                      onClick={
                        handleClose(
                          item.onClick,
                        ) as unknown as React.MouseEventHandler
                      }
                      disabled={item.disabled}
                    >
                      {item.label}
                    </MenuItem>
                  ))}
                </MenuList>
              </ClickAwayListener>
            </Paper>
          </Grow>
        )}
      </Popper>
    </React.Fragment>
  );
}
