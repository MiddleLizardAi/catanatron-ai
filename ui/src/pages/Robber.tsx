import {
  SQRT3,
  tilePixelVector,
  type CubeCoordinate,
} from "../utils/coordinates";
import robberIcon from "../assets/icons/figure.and.child.holdinghands.svg";

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
        width: size * 0.55,
        height: size * 0.62,
      }}
    >
      <img src={robberIcon} alt="Robber" />
    </div>
  );
}
