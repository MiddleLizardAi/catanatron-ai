import {
  SQRT3,
  tilePixelVector,
  type CubeCoordinate,
} from "../utils/coordinates";

type RobberProps = {
  center: [number, number];
  size: number;
  coordinate: CubeCoordinate;
};

export default function Robber({ center, size, coordinate }: RobberProps) {
  const [centerX, centerY] = center;
  const w = SQRT3 * size;
  const [tileX, tileY] = tilePixelVector(coordinate, size, centerX, centerY);
  const [deltaX, deltaY] = [-w / 2 + w / 8, 0];
  const x = tileX + deltaX;
  const y = tileY + deltaY;

  return (
    <div
      className="robber"
      style={{
        left: x,
        top: y,
        width: size * 0.43,
        height: size * 0.5,
      }}
      aria-label="Robber"
    >
      <span className="robber__head" />
      <span className="robber__body" />
      <span className="robber__base" />
    </div>
  );
}
