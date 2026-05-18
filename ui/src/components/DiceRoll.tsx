import { useEffect, useState } from "react";

import "./DiceRoll.scss";

const PIP_POSITIONS = {
  1: ["center"],
  2: ["top-left", "bottom-right"],
  3: ["top-left", "center", "bottom-right"],
  4: ["top-left", "top-right", "bottom-left", "bottom-right"],
  5: ["top-left", "top-right", "center", "bottom-left", "bottom-right"],
  6: ["top-left", "top-right", "middle-left", "middle-right", "bottom-left", "bottom-right"],
} as const;

type DiceRollProps = {
  values?: [number, number] | null;
};

function Die({ color, value, rolling }: { color: "yellow" | "red"; value: number; rolling: boolean }) {
  return (
    <span
      aria-label={`${color} die: ${value}`}
      className={`dice-roll__die dice-roll__die--${color}${rolling ? " rolling" : ""}`}
    >
      {PIP_POSITIONS[value as keyof typeof PIP_POSITIONS].map((position) => (
        <span className={`dice-roll__pip dice-roll__pip--${position}`} key={position} />
      ))}
    </span>
  );
}

export default function DiceRoll({ values }: DiceRollProps) {
  const [isRolling, setIsRolling] = useState(false);

  useEffect(() => {
    if (!values) {
      return;
    }

    setIsRolling(true);
    const timeout = window.setTimeout(() => setIsRolling(false), 500);
    return () => window.clearTimeout(timeout);
  }, [values]);

  if (!values) {
    return null;
  }

  const [firstDie, secondDie] = values;

  return (
    <div className="dice-roll" aria-label={`Dice roll ${firstDie + secondDie}`}>
      <span className="dice-roll__label">Roll {firstDie + secondDie}</span>
      <Die color="yellow" value={firstDie} rolling={isRolling} />
      <Die color="red" value={secondDie} rolling={isRolling} />
    </div>
  );
}
