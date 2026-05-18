import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import type { Color, GameState } from "../utils/api.types";
import { humanColors } from "../utils/localPlayer";

type JoinLinksProps = {
  gameId: string;
  gameState: GameState;
};

function playerLabel(gameState: GameState, color: Color): string {
  const player = gameState.players?.find((candidate) => candidate.color === color);
  return player?.name || color;
}

function joinUrl(gameId: string, color: Color): string {
  const origin = window.location.origin;
  return `${origin}/games/${gameId}?player=${color}`;
}

function JoinLinks({ gameId, gameState }: JoinLinksProps) {
  const humans = humanColors(gameState);

  if (humans.length <= 1) {
    return null;
  }

  const copyLink = async (color: Color) => {
    const url = joinUrl(gameId, color);
    await navigator.clipboard?.writeText(url);
  };

  return (
    <section className="join-links" aria-label="Join links">
      <div className="join-links__title">Join links</div>
      <div className="join-links__items">
        {humans.map((color) => (
          <a
            className={`join-links__item join-links__item--${color.toLowerCase()}`}
            href={`/games/${gameId}?player=${color}`}
            key={color}
          >
            <span className="join-links__player">{playerLabel(gameState, color)}</span>
            <span className="join-links__color">{color}</span>
            <button
              aria-label={`Copy ${color} join link`}
              className="join-links__copy"
              onClick={(event) => {
                event.preventDefault();
                void copyLink(color);
              }}
              title="Copy link"
              type="button"
            >
              <ContentCopyIcon fontSize="inherit" />
            </button>
          </a>
        ))}
      </div>
    </section>
  );
}

export default JoinLinks;
