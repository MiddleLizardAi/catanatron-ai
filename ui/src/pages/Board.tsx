import classnames from "classnames";
import { useId } from "react";

import { SQRT3, tilePixelVector } from "../utils/coordinates";
import type { GameAction, GameState, TileCoordinate } from "../utils/api.types";
import Tile from "./Tile";
import Node from "./Node";
import Edge, { toEdgeId, type EdgeId } from "./Edge";
import Robber from "./Robber";

import "./Board.scss";

/**
 * This uses the formulas: W = SQRT3 * size and H = 2 * size.
 * Math comes from https://www.redblobgames.com/grids/hexagons/.
 */
function computeDefaultSize(divWidth: number, divHeight: number): number {
  const numLevels = 6; // 3 rings + 1/2 a tile for the outer water ring
  // divHeight = numLevels * (3h/4) + (h/4), implies:
  const maxSizeThatRespectsHeight = (4 * divHeight) / (3 * numLevels + 1) / 2;
  const correspondingWidth = SQRT3 * maxSizeThatRespectsHeight;
  let size: number;
  if (numLevels * correspondingWidth < divWidth) {
    // thus complete board would fit if we pick size based on height (height is limiting factor)
    size = maxSizeThatRespectsHeight;
  } else {
    // we'll have to decide size based on width.
    const maxSizeThatRespectsWidth = divWidth / numLevels / SQRT3;
    size = maxSizeThatRespectsWidth;
  }
  return size;
}

type Point = {
  x: number;
  y: number;
};

type BoundaryEdge = {
  start: Point;
  end: Point;
};

const HEX_VERTICES = [
  [0, -1],
  [SQRT3 / 2, -0.5],
  [SQRT3 / 2, 0.5],
  [0, 1],
  [-SQRT3 / 2, 0.5],
  [-SQRT3 / 2, -0.5],
] as const;
const HEX_SIDE_BY_NEIGHBOR_INDEX = [1, 0, 5, 4, 3, 2] as const;

function pointKey(point: Point): string {
  return `${Math.round(point.x * 1000)},${Math.round(point.y * 1000)}`;
}

function orderBoundaryPoints(edges: BoundaryEdge[]): Point[] {
  if (edges.length < 3) {
    return [];
  }

  const edgesByPoint = new Map<string, BoundaryEdge[]>();
  edges.forEach((edge) => {
    [pointKey(edge.start), pointKey(edge.end)].forEach((key) => {
      const connectedEdges = edgesByPoint.get(key) || [];
      connectedEdges.push(edge);
      edgesByPoint.set(key, connectedEdges);
    });
  });

  const firstEdge = edges[0];
  const points: Point[] = [firstEdge.start];
  const firstKey = pointKey(firstEdge.start);
  let previousKey = firstKey;
  let current = firstEdge.end;

  while (points.length <= edges.length) {
    const currentKey = pointKey(current);
    if (currentKey === firstKey) {
      break;
    }

    points.push(current);
    const nextEdge = (edgesByPoint.get(currentKey) || []).find((edge) => {
      const startKey = pointKey(edge.start);
      const endKey = pointKey(edge.end);
      return startKey !== previousKey && endKey !== previousKey;
    });
    if (!nextEdge) {
      break;
    }
    previousKey = currentKey;
    current = nextEdge.end;
    if (pointKey(current) === previousKey) {
      current = nextEdge.start;
    }
  }

  return points;
}

function buildSmoothPath(points: Point[], center: Point): string {
  if (points.length < 3) {
    return "";
  }

  const coastline = points.map((point, index) => {
    const dx = point.x - center.x;
    const dy = point.y - center.y;
    const wobble = 1 + (((index * 37) % 11) - 5) * 0.008;
    return {
      x: center.x + dx * wobble,
      y: center.y + dy * wobble,
    };
  });

  const lerp = (from: Point, to: Point, amount: number): Point => ({
    x: from.x + (to.x - from.x) * amount,
    y: from.y + (to.y - from.y) * amount,
  });
  const cornerCut = 0.38;
  const start = lerp(coastline[0], coastline[1], cornerCut);
  let path = `M ${start.x} ${start.y}`;

  coastline.forEach((point, index) => {
    const previous = coastline[(index - 1 + coastline.length) % coastline.length];
    const next = coastline[(index + 1) % coastline.length];
    const beforeCorner = lerp(point, previous, cornerCut);
    const afterCorner = lerp(point, next, cornerCut);
    path += ` L ${beforeCorner.x} ${beforeCorner.y} Q ${point.x} ${point.y} ${afterCorner.x} ${afterCorner.y}`;
  });

  return `${path} Z`;
}

type BoardProps = {
  width: number;
  height: number;
  buildOnNodeClick: (id: number, action?: GameAction) => React.MouseEventHandler<HTMLDivElement>;
  buildOnEdgeClick: (id: [number, number], action?: GameAction) => React.MouseEventHandler<HTMLDivElement>;
  handleTileClick: (coordinate: TileCoordinate) => void;
  nodeActions?: Record<number, GameAction>;
  edgeActions?: Record<EdgeId, GameAction>;
  replayMode: boolean;
  gameState: GameState;
  isMobile: boolean;
  show: boolean;
  isMovingRobber: boolean;
  robberCoordinates?: Set<string>;
}

export default function Board({
  width,
  height,
  buildOnNodeClick,
  buildOnEdgeClick,
  handleTileClick,
  nodeActions,
  edgeActions,
  replayMode,
  gameState,
  isMobile,
  show,
  isMovingRobber,
  robberCoordinates,
}: BoardProps) {
  const sandId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  // TODO: Keep in sync with CSS
  const containerHeight = height - 144 - 38 - 40;
  const containerWidth = isMobile ? width - 280 : width;
  const center: [number, number] = [containerWidth / 2, containerHeight / 2];
  const size = computeDefaultSize(containerWidth, containerHeight);
  if (!size) {
    return null;
  }

  const landTiles = gameState.tiles
    .filter(({ tile }) => tile.type === "RESOURCE_TILE" || tile.type === "DESERT");
  const landCoordinates = new Set(
    landTiles.map(({ coordinate }) => coordinate.join(","))
  );
  const coastlineEdges = landTiles.flatMap(({ coordinate }) => {
    const neighbors: TileCoordinate[] = [
      [coordinate[0] + 1, coordinate[1] - 1, coordinate[2]],
      [coordinate[0] + 1, coordinate[1], coordinate[2] - 1],
      [coordinate[0], coordinate[1] + 1, coordinate[2] - 1],
      [coordinate[0] - 1, coordinate[1] + 1, coordinate[2]],
      [coordinate[0] - 1, coordinate[1], coordinate[2] + 1],
      [coordinate[0], coordinate[1] - 1, coordinate[2] + 1],
    ];
    const [x, y] = tilePixelVector(coordinate, size, center[0], center[1]);
    const coastlineRadius = size;

    return neighbors.flatMap((neighbor, neighborIndex): BoundaryEdge[] => {
      if (landCoordinates.has(neighbor.join(","))) {
        return [];
      }

      const sideIndex = HEX_SIDE_BY_NEIGHBOR_INDEX[neighborIndex];
      const start = HEX_VERTICES[sideIndex];
      const end = HEX_VERTICES[(sideIndex + 1) % HEX_VERTICES.length];
      return [{
        start: {
          x: x + start[0] * coastlineRadius,
          y: y + start[1] * coastlineRadius,
        },
        end: {
          x: x + end[0] * coastlineRadius,
          y: y + end[1] * coastlineRadius,
        },
      }];
    });
  });
  const coastlinePoints = orderBoundaryPoints(coastlineEdges);
  const sandPath = buildSmoothPath(coastlinePoints, {
    x: center[0],
    y: center[1],
  });
  const sandLayer = sandPath ? (
    <svg
      className="sand-continent"
      width={containerWidth}
      height={containerHeight}
      viewBox={`0 0 ${containerWidth} ${containerHeight}`}
      aria-hidden="true"
    >
      <defs>
        <radialGradient id={`${sandId}-sand-gradient`} cx="48%" cy="43%" r="62%">
          <stop offset="0%" stopColor="#fff0ad" />
          <stop offset="52%" stopColor="#f3cc78" />
          <stop offset="81%" stopColor="#d99b4b" />
          <stop offset="100%" stopColor="#f3d58e" />
        </radialGradient>
        <filter id={`${sandId}-sand-soften`} x="-8%" y="-8%" width="116%" height="116%">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.018 0.031"
            numOctaves="2"
            seed="8"
            result="noise"
          />
          <feDisplacementMap
            in="SourceGraphic"
            in2="noise"
            scale={size * 0.055}
            xChannelSelector="R"
            yChannelSelector="G"
            result="displaced"
          />
          <feDropShadow
            in="displaced"
            dx="0"
            dy="4"
            stdDeviation="5"
            floodColor="rgba(4, 70, 105, 0.22)"
          />
        </filter>
        <pattern
          id={`${sandId}-sand-grain`}
          width="26"
          height="24"
          patternUnits="userSpaceOnUse"
        >
          <circle cx="5" cy="7" r="1.2" fill="rgba(125, 81, 36, 0.16)" />
          <circle cx="19" cy="15" r="0.9" fill="rgba(255, 245, 190, 0.32)" />
          <circle cx="13" cy="21" r="0.8" fill="rgba(150, 94, 39, 0.12)" />
        </pattern>
      </defs>
      <path
        className="sand-continent__shape"
        d={sandPath}
        fill={`url(#${sandId}-sand-gradient)`}
        filter={`url(#${sandId}-sand-soften)`}
      />
      <path
        className="sand-continent__grain"
        d={sandPath}
        fill={`url(#${sandId}-sand-grain)`}
      />
    </svg>
  ) : null;

  const tiles = gameState.tiles.map(({ coordinate, tile }) => (
    <Tile
      key={`${coordinate}`}
      center={center}
      coordinate={coordinate}
      tile={tile}
      size={size}
      flashing={!!robberCoordinates?.has(`${coordinate}`)}
      onClick={
        !isMovingRobber || robberCoordinates?.has(`${coordinate}`)
          ? () => handleTileClick(coordinate)
          : undefined
      }
    />
  ));
  const nodes = Object.values(gameState.nodes).map(
    ({ color, building, direction, tile_coordinate, id }) => (
      <Node
        key={id}
        center={center}
        size={size}
        coordinate={tile_coordinate}
        direction={direction}
        building={building}
        color={color}
        flashing={!replayMode && !!nodeActions && id in nodeActions}
        onClick={buildOnNodeClick(
          id,
          nodeActions ? nodeActions[id] : undefined
        )}
      />
    )
  );
  const edges = Object.values(gameState.edges).map(
    ({ color, direction, tile_coordinate, id }) => (
      <Edge
        id={`${id[0]},${id[1]}`}
        key={`${id}`}
        center={center}
        size={size}
        coordinate={tile_coordinate}
        direction={direction}
        color={color}
        flashing={!!edgeActions && toEdgeId(id) in edgeActions}
        onClick={buildOnEdgeClick(id, edgeActions ? edgeActions[toEdgeId(id)]: undefined)}
      />
    )
  );
  return (
    <div className={classnames("board", { show })}>
      {sandLayer}
      {tiles}
      {edges}
      {nodes}
      <Robber
        center={center}
        size={size}
        coordinate={gameState.robber_coordinate}
      />
    </div>
  );
}
