import { useEffect, useState } from "react";

import die1 from "../assets/dice/die.face.1.fill.svg";
import die2 from "../assets/dice/die.face.2.fill.svg";
import die3 from "../assets/dice/die.face.3.fill.svg";
import die4 from "../assets/dice/die.face.4.fill.svg";
import die5 from "../assets/dice/die.face.5.fill.svg";
import die6 from "../assets/dice/die.face.6.fill.svg";
import die1Red from "../assets/dice/die.face.1.red.svg";
import die2Red from "../assets/dice/die.face.2.red.svg";
import die3Red from "../assets/dice/die.face.3.red.svg";
import die4Red from "../assets/dice/die.face.4.red.svg";
import die5Red from "../assets/dice/die.face.5.red.svg";
import die6Red from "../assets/dice/die.face.6.red.svg";

import "./DiceRoll.scss";

const lightDice = [die1, die2, die3, die4, die5, die6];
const redDice = [die1Red, die2Red, die3Red, die4Red, die5Red, die6Red];

type DiceRollProps = {
  values?: [number, number] | null;
};

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
      <img
        src={lightDice[firstDie - 1]}
        alt={`First die: ${firstDie}`}
        className={isRolling ? "dice-roll__die rolling" : "dice-roll__die"}
      />
      <img
        src={redDice[secondDie - 1]}
        alt={`Second die: ${secondDie}`}
        className={isRolling ? "dice-roll__die rolling" : "dice-roll__die"}
      />
    </div>
  );
}
