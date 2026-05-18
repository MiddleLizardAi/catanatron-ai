import cn from "classnames";
import Paper from "@mui/material/Paper";

import "./Tile.scss";
import brickTile from "../assets/tile_brick.png";
import desertTile from "../assets/tile_desert.png";
import grainTile from "../assets/tile_wheat.png";
import lumberTile from "../assets/tile_wood.png";
import oreTile from "../assets/tile_ore.png";
import woolTile from "../assets/tile_sheep.png";
import maritimeTile from "../assets/tile_maritime.png";
import number2 from "../assets/numbers/2.circle.fill.svg";
import number3 from "../assets/numbers/3.circle.fill.svg";
import number4 from "../assets/numbers/4.circle.fill.svg";
import number5 from "../assets/numbers/5.circle.fill.svg";
import number6 from "../assets/numbers/6.circle.fill.svg";
import number8 from "../assets/numbers/8.circle.fill.svg";
import number9 from "../assets/numbers/9.circle.fill.svg";
import number10 from "../assets/numbers/10.circle.fill.svg";
import number11 from "../assets/numbers/11.circle.fill.svg";
import number12 from "../assets/numbers/12.circle.fill.svg";
import { SQRT3, tilePixelVector } from "../utils/coordinates";
import {
  type Direction,
  type ResourceCard,
  type Tile,
} from "../utils/api.types";

type NumberTokenProps = {
  number: number;
  className?: string;
  style?: Partial<React.CSSProperties>;
  flashing?: boolean;
};

export function NumberToken({
  number,
  className,
  style,
  flashing,
}: NumberTokenProps) {
  const tokenImage = NUMBER_TOKEN_IMAGES[number];

  return (
    <Paper
      elevation={3}
      className={cn("number-token", className, { flashing })}
      style={style}
    >
      {tokenImage && (
        <span
          className={cn(
            "number-token__disc",
            number === 6 || number === 8
              ? "number-token__disc--red"
              : "number-token__disc--black"
          )}
        >
          <img src={tokenImage} alt={number.toString()} />
        </span>
      )}
    </Paper>
  );
}

const NUMBER_TOKEN_IMAGES: Record<number, string> = {
  2: number2,
  3: number3,
  4: number4,
  5: number5,
  6: number6,
  8: number8,
  9: number9,
  10: number10,
  11: number11,
  12: number12,
};

const RESOURCES: { [K in ResourceCard]: string } = {
  BRICK: brickTile,
  SHEEP: woolTile,
  ORE: oreTile,
  WOOD: lumberTile,
  WHEAT: grainTile,
} as const;

const calculatePortPosition = (
  direction: Direction,
  size: number
): { x: number; y: number } => {
  let x = 0;
  let y = 0;
  if (direction.includes("SOUTH")) {
    y += size / 3;
  } else if (direction.includes("NORTH")) {
    y -= size / 3;
  }
  if (direction.includes("WEST")) {
    x -= size / 4;
    if (direction === "WEST") {
      x = -size / 3;
    }
  } else if (direction.includes("EAST")) {
    x += size / 4;
    if (direction === "EAST") {
      x = size / 3;
    }
  }
  return { x, y };
};

const Port = ({
  resource,
  style,
}: {
  resource: ResourceCard;
  style: Partial<React.CSSProperties>;
}) => {
  let ratio;
  let tile;
  if (resource in RESOURCES) {
    ratio = "2:1";
    tile = RESOURCES[resource];
  } else {
    ratio = "3:1";
    tile = maritimeTile;
  }

  return (
    <div
      className="port"
      style={{
        ...style,
        backgroundImage: `url("${tile}")`,
        height: 60,
        backgroundSize: "contain",
        width: 52,
        backgroundRepeat: "no-repeat",
      }}
    >
      {ratio}
    </div>
  );
};

type TileProps = {
  center: any;
  coordinate: any;
  tile: Tile;
  size: any;
  onClick?: React.MouseEventHandler<HTMLDivElement>;
  flashing: boolean;
};

export default function Tile({
  center,
  coordinate,
  tile,
  size,
  onClick,
  flashing,
}: TileProps) {
  const w = SQRT3 * size;
  const h = 2 * size;
  const [centerX, centerY] = center;
  const [x, y] = tilePixelVector(coordinate, size, centerX, centerY);

  let contents;
  let resourceTile;
  if (tile.type === "RESOURCE_TILE") {
    contents = <NumberToken number={tile.number} flashing={flashing} />;
    resourceTile = RESOURCES[tile.resource];
  } else if (tile.type === "DESERT") {
    resourceTile = desertTile;
  } else if (tile.type === "PORT") {
    const { x, y } = calculatePortPosition(tile.direction, size);
    contents = (<Port resource={tile.resource} style={{ left: x, top: y }}  />)
    }

  return (
    <div
      key={coordinate}
      className={cn("tile", { "tile--robber-target": flashing })}
      style={{
        left: x - w / 2,
        top: y - h / 2,
        width: w,
        height: h,
        backgroundImage: `url("${resourceTile}")`,
        backgroundSize: "contain",
        backgroundRepeat: "no-repeat",
        backgroundPositionY: "6px",
        backgroundPositionX: "1px",
      }}
      onClick={onClick}
    >
      {contents}
    </div>
  );
}
