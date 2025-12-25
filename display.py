from __future__ import annotations

import curses
import io
import re
import time
from dataclasses import dataclass
from typing import Optional

# Import types from cardGame so strategies/actions are compatible.
from cardGame import Action, ActionType, Observation, Strategy, Game

# Standard color-pair ids we initialize in `_start_curses`.
# These ids are stable so we don't need per-instance lookup tables.
_COLOR_NAME_TO_PAIR_ID: dict[str, int] = {
    "black": 1,
    "red": 2,
    "green": 3,
    "yellow": 4,
    "blue": 5,
    "magenta": 6,
    "cyan": 7,
    "white": 8,
}

# Semantic aliases for convenience.
_SEMANTIC_COLORS: dict[str, str] = {
    "info": "cyan",
    "warn": "yellow",
    "warning": "yellow",
    "error": "red",
    "success": "green",
}


@dataclass
class _Choice:
    key: str
    label: str
    action: Action


class CursesDisplay:
    """A curses-based display and input helper.

    The display is created once and can be shared by multiple strategies.
    Rendering is triggered each time `choose_action(...)` is called.

    This class is *not* tightly coupled to Flip7; it uses Observation.extras
    keys when present, but falls back gracefully.
    """

    def __init__(self, game: Game):
        self.game: Game = game
        self._stdscr: Optional["curses._CursesWindow"] = None

        self._messages: list[tuple[str, int]] = []
        # Cap stored messages; the number *displayed* is computed from screen size.
        self._max_messages = 200

        # Per-word highlight rules for the on-screen log.
        # Stored as (compiled_regex, color, style) in insertion order.
        self._log_highlights: list[tuple[re.Pattern[str], object, object]] = []

        # Overwrite normal log function
        game.log = self.curses_log

        if hasattr(game, "coloredWords"):
            for key, value in game.coloredWords.items():
                self.add_log_highlight(key, color=value, style="bold")

            for p in game.players:
                self.add_log_highlight(str(p), style="bold")

    # ------------------------- public API -------------------------

    def add_log_highlight(self, word: str, *, color=None, style=None) -> None:
        """Highlight a whole word (case-insensitive) in the on-screen log panel."""
        w = (word or "").strip()
        if not w:
            return
        rx = re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE)
        self._log_highlights.append((rx, color, style))

    def clear_log_highlights(self) -> None:
        self._log_highlights.clear()

    def push_message(self, msg: str, *, attr: int = 0) -> None:
        if msg.strip() == "":
            return
        self._messages.append((msg, attr))
        if len(self._messages) > self._max_messages:
            self._messages = self._messages[-self._max_messages :]

    def choose_action(
        self, obs: Observation = None, legal: list[Action] = None
    ) -> Action:
        """Render and ask the user for an action.

        - In FLIP phase: (d)raw / (p)ass
        - In EFFECT_CHOOSE: number keys select a target
        - q quits by raising KeyboardInterrupt
        """

        if legal is None:
            legal = self.game.get_legal_actions(self.game.activePlayer)
        if obs is None:
            obs = self.game.get_observation()

        # Initial render so the user sees state before pressing anything.
        self.render(obs, legal)

        while True:
            ch = self.waitForKey()

            # Terminal resize counts as an input event → re-render.
            if ch == "<RESIZE>":
                self.render(obs, legal)
                continue

            if ch in ("q", "Q"):
                self.game.gameOver = True
                return None

            choice = self._map_key_to_choice(ch, obs, legal)
            if choice is not None:
                return choice.action

    def render(self, obs: Observation = None, legal: list[Action] = None) -> None:
        """Render the current state without requiring input."""
        if legal is None:
            legal = self.game.get_legal_actions(self.game.activePlayer)
        if obs is None:
            obs = self.game.get_observation()

        if self._stdscr is None:
            raise RuntimeError(
                "CursesDisplay.render() called outside of an active curses session"
            )

        self._stdscr.erase()

        h, w = self._stdscr.getmaxyx()

        # Layout columns
        left_w = max(40, min(w // 2, 70))
        right_x = left_w + 1

        # Header
        header = self._build_header(obs)
        self._addnstr(0, 0, header, w - 1, attr=curses.A_BOLD)
        self._hline(1, 0, w)

        # Left: players and hands
        y = 2
        y = self._draw_players_panel(y, 0, left_w, obs)

        # Right: actions + messages
        ry = 2
        ry = self._draw_actions_panel(ry, right_x, w - right_x - 1, obs, legal)
        self._hline(ry + 1, right_x, w - right_x - 1)

        # Log panel height adapts to remaining space (accounts for Actions/Effects height).
        log_y = ry + 2
        log_w = w - right_x - 1
        # Reserve the last row for the footer.
        max_log_lines = max(0, (h - 2) - log_y + 1)
        self._draw_messages_panel(log_y, right_x, log_w, max_lines=max_log_lines)

        # Footer hint
        footer = "Keys: d=draw, p=pass, 1-9=choose target, q=quit"
        self._addnstr(h - 1, 0, footer, w - 1, attr=curses.A_DIM)

        self._stdscr.noutrefresh()
        curses.doupdate()

    def _build_attr(self, *, color=None, style=None) -> int:
        attr = 0

        # Apply color if curses is active.
        if color is not None and self._stdscr is not None and curses.has_colors():
            if isinstance(color, str):
                name = _SEMANTIC_COLORS.get(
                    color.strip().lower(), color.strip().lower()
                )
                pair_id = _COLOR_NAME_TO_PAIR_ID.get(name)
                if pair_id is not None:
                    attr |= curses.color_pair(pair_id)
            elif isinstance(color, int):
                try:
                    attr |= curses.color_pair(color)
                except Exception:
                    pass

        # Apply style attributes.
        if style is not None:
            if isinstance(style, str):
                parts = [p.strip().lower() for p in style.split(",") if p.strip()]
            elif isinstance(style, (list, tuple, set)):
                parts = [str(p).strip().lower() for p in style if str(p).strip()]
            else:
                parts = [str(style).strip().lower()] if str(style).strip() else []

            for part in parts:
                if part == "bold":
                    attr |= curses.A_BOLD
                elif part == "dim":
                    attr |= curses.A_DIM
                elif part == "reverse":
                    attr |= curses.A_REVERSE
                elif part == "underline":
                    attr |= curses.A_UNDERLINE

        return attr

    def curses_log(self, *args, color=None, style=None, **kwargs):
        buf = io.StringIO()
        print(*args, **kwargs, file=buf)
        msg = buf.getvalue().rstrip("\n")
        if not msg:
            return

        attr = self._build_attr(color=color, style=style)
        self.push_message(msg, attr=attr)

    def waitForKey(self) -> str:
        assert self._stdscr is not None

        # Blocking wait for the next key/event.
        ch = self._stdscr.getch()

        if ch == curses.KEY_RESIZE:
            return "<RESIZE>"

        # Printable ASCII (and most common single-byte keys)
        try:
            return chr(ch)
        except Exception:
            return ""

    # ------------------------- helpers -------------------------

    def _merge_attrs(self, base_attr: int, hl_attr: int) -> int:
        """Combine attrs, but let highlight COLOR override base COLOR.

        Bitwise-OR of two color pairs is undefined in curses (it can yield a third
        pair, e.g. green|yellow -> blue). Styles are OR-ed normally.
        """
        base_color = base_attr & curses.A_COLOR
        base_style = base_attr & ~curses.A_COLOR

        hl_color = hl_attr & curses.A_COLOR
        hl_style = hl_attr & ~curses.A_COLOR

        color = hl_color if hl_color else base_color
        return base_style | hl_style | color

    def _highlight_spans(self, s: str) -> list[tuple[int, int, int]]:
        """Return non-overlapping (start,end,hl_attr) spans. First-added wins."""
        if not self._log_highlights:
            return []

        taken: list[tuple[int, int]] = []
        spans: list[tuple[int, int, int]] = []
        for rx, color, style in self._log_highlights:
            hl_attr = self._build_attr(color=color, style=style)
            for m in rx.finditer(s):
                a, b = m.span()
                if a == b:
                    continue
                if any(not (b <= ta or a >= tb) for ta, tb in taken):
                    continue
                taken.append((a, b))
                spans.append((a, b, hl_attr))
        spans.sort(key=lambda t: t[0])
        return spans

    def _draw_highlighted_line(
        self, y: int, x: int, s: str, width: int, base_attr: int = 0
    ) -> None:
        if width <= 0:
            return
        spans = self._highlight_spans(s)
        if not spans:
            self._addnstr(y, x, s, width, attr=base_attr)
            return

        cur = 0
        cx = x
        for a, b, hl_attr in spans:
            if a > cur:
                seg = s[cur:a]
                if seg:
                    n = max(0, width - (cx - x))
                    if n <= 0:
                        return
                    self._addnstr(y, cx, seg, n, attr=base_attr)
                    cx += min(len(seg), n)
            seg = s[a:b]
            if seg:
                n = max(0, width - (cx - x))
                if n <= 0:
                    return
                self._addnstr(y, cx, seg, n, attr=self._merge_attrs(base_attr, hl_attr))
                cx += min(len(seg), n)
            cur = b

        if cur < len(s):
            seg = s[cur:]
            n = max(0, width - (cx - x))
            if n <= 0:
                return
            self._addnstr(y, cx, seg, n, attr=base_attr)

    def _map_key_to_choice(
        self, ch: str, obs: Observation, legal: list[Action]
    ) -> Optional[_Choice]:
        choices = self._build_choices(obs, legal)
        for c in choices:
            if ch == c.key:
                return c
        return None

    def _build_choices(self, obs: Observation, legal: list[Action]) -> list[_Choice]:
        # Prefer explicit mapping by action type.
        out: list[_Choice] = []

        # DRAW / PASS
        draw = next((a for a in legal if a.type == ActionType.DRAW), None)
        if draw is not None:
            out.append(_Choice("d", "Draw", draw))

        pas = next((a for a in legal if a.type == ActionType.PASS), None)
        if pas is not None:
            out.append(_Choice("p", "Pass", pas))

        # CHOOSE_PLAYER targets
        targets = [a for a in legal if a.type == ActionType.CHOOSE_PLAYER]
        if targets:
            # number keys 1..9
            for i, a in enumerate(targets, start=1):
                key = str(i)
                label = f"Choose player {a.target_player}"
                out.append(_Choice(key, label, a))

        # Fallback: enumerate any remaining legal actions
        used = {id(c.action) for c in out}
        extra = [a for a in legal if id(a) not in used]
        for i, a in enumerate(extra, start=1):
            key = f"{i}"
            out.append(_Choice(key, a.type, a))

        return out

    def _build_header(self, obs: Observation) -> str:
        return (
            f"Flip7  |  Round {obs.round}  |  Phase: {obs.phase}  |  "
            f"Active: {obs.actingPlayer}  |  Deck: {obs.deck_size}"
        )

    def _draw_players_panel(self, y: int, x: int, w: int, obs: Observation) -> int:
        bust_probs = obs.extras.get("bust_probabilities", None)

        players = self.game.players

        self._addnstr(y, x, "Players", w - 1, attr=curses.A_BOLD)
        y += 1

        for p in players:
            is_acting = p == obs.actingPlayer

            flags = []
            if p.status:
                flags.append(p.status)
            if is_acting:
                flags.append("ACTING")

            flag_s = (" [" + ",".join(flags) + "]") if flags else ""

            prob_s = ""
            if isinstance(bust_probs, list):
                try:
                    prob = bust_probs[p.i]
                    prob_s = f" bust≈{prob:.0%}"
                except Exception:
                    prob_s = ""

            score = f"score={p.score}"
            if hasattr(self.game, "getPlayerHandScore"):
                score += f"+({self.game.getPlayerHandScore(p)})"

            line = f"{p.i + 1}: {p.name} {score}{prob_s}{flag_s}"
            attr = curses.A_REVERSE if is_acting else 0
            self._draw_highlighted_line(y, x, line, w - 1, base_attr=attr)
            y += 1

            # Hand
            for wrapped in self._wrap(p.hand, w - 3):
                self._draw_highlighted_line(y, x + 2, wrapped, w - 3, base_attr=0)
                y += 1

            y += 1

        return y

    def _draw_actions_panel(
        self, y: int, x: int, w: int, obs: Observation, legal: list[Action]
    ) -> int:
        self._addnstr(y, x, "Actions", w - 1, attr=curses.A_BOLD)
        y += 1

        choices = self._build_choices(obs, legal)
        if not choices:
            self._addnstr(y, x, "(no actions)", w - 1, attr=curses.A_DIM)
            return y + 1

        for c in choices:
            self._draw_highlighted_line(y, x, f"[{c.key}] {c.label}", w - 1)
            y += 1

        # Effect queue (Flip7-specific extras, but safe if absent)
        extras = obs.extras
        effs = extras.get("effects_to_resolve", [])
        owners = extras.get("effect_owners", [])
        pending = extras.get("pending_effect", None)

        if pending or effs:
            pending_owner_i = int(extras.get("pending_effect_owner", None))
            pending_owner = self.game.players[pending_owner_i]

            y += 1
            self._addnstr(y, x, "Effects", w - 1, attr=curses.A_BOLD)
            y += 1

            if pending:
                self._draw_highlighted_line(
                    y,
                    x,
                    f"Pending: {pending} (owner {pending_owner})",
                    w - 1,
                )
                y += 1

            if effs:
                for i, e in enumerate(effs):
                    owner = owners[i] if i < len(owners) else "?"
                    self._addnstr(y, x, f"Queued: {e} (owner {owner})", w - 1)
                    y += 1

        return y

    def _draw_messages_panel(self, y: int, x: int, w: int, *, max_lines: int) -> None:
        """Draw the log panel.

        `max_lines` is the total number of rows available for the panel (including the
        "Log" header). The content shown is chosen to fit the available height.
        """
        if max_lines <= 0:
            return

        self._addnstr(y, x, "Log", w - 1, attr=curses.A_BOLD)
        y += 1
        max_lines -= 1

        if max_lines <= 0:
            return

        if not self._messages:
            self._addnstr(y, x, "", w - 1, attr=curses.A_DIM)
            return

        # Build wrapped lines from newest to oldest until we fill the available space.
        lines: list[tuple[str, int]] = []
        for msg, attr in reversed(self._messages[-self._max_messages :]):
            wrapped = self._wrap(msg, w - 1)
            # Add in reverse so overall order becomes oldest->newest after final reverse.
            for ln in reversed(wrapped):
                lines.append((ln, attr))
                if len(lines) >= max_lines:
                    break
            if len(lines) >= max_lines:
                break

        # We collected lines newest-first; flip to display oldest->newest.
        for ln, attr in reversed(lines):
            self._draw_highlighted_line(y, x, ln, w - 1, base_attr=attr)
            y += 1

    def _wrap(self, s: str, width: int) -> list[str]:
        if not isinstance(s, str):
            s = str(s)
        if width <= 5:
            return [s[:width]]

        words = s.split(" ")
        lines: list[str] = []
        cur = ""
        for w in words:
            if not cur:
                cur = w
                continue
            if len(cur) + 1 + len(w) <= width:
                cur += " " + w
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def _addnstr(self, y: int, x: int, s: str, n: int, *, attr: int = 0) -> None:
        if self._stdscr is None:
            return
        h, w = self._stdscr.getmaxyx()
        if y < 0 or y >= h:
            return
        if x < 0 or x >= w:
            return
        try:
            self._stdscr.addnstr(y, x, s, max(0, n), attr)
        except curses.error:
            # Happens when writing in the last column/row on some terminals.
            pass

    def _hline(self, y: int, x: int, width: int) -> None:
        if self._stdscr is None:
            return
        try:
            self._stdscr.hline(y, x, curses.ACS_HLINE, max(0, width))
        except curses.error:
            pass

    # ------------------------- curses session (owned by application) -------------------------

    class _Session:
        def __init__(self, outer: "CursesDisplay"):
            self.outer = outer
            self.started_here = False

        def __enter__(self):
            if self.outer._stdscr is None:
                self.started_here = True
                self.outer._start_curses()
            return self.outer

        def __exit__(self, exc_type, exc, tb):
            if self.started_here:
                self.outer._stop_curses()
            # Don't suppress exceptions.
            return False

    def session(self) -> "CursesDisplay._Session":
        return CursesDisplay._Session(self)

    def _start_curses(self) -> None:
        self._stdscr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        try:
            curses.curs_set(0)
        except curses.error:
            pass

        self._stdscr.keypad(True)
        self._stdscr.nodelay(False)

        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
            except Exception:
                pass

            # Pair ids are fixed by `_COLOR_NAME_TO_PAIR_ID`.
            for name, pair_id in _COLOR_NAME_TO_PAIR_ID.items():
                try:
                    fg = getattr(curses, f"COLOR_{name.upper()}")
                    curses.init_pair(pair_id, fg, -1)
                except Exception:
                    pass

    def _stop_curses(self) -> None:
        if self._stdscr is None:
            return
        try:
            self._stdscr.keypad(False)
        except Exception:
            pass
        try:
            curses.nocbreak()
        except Exception:
            pass
        try:
            curses.echo()
        except Exception:
            pass
        try:
            curses.endwin()
        except Exception:
            pass
        self._stdscr = None


class HumanCursesStrategy(Strategy):
    """A human-controlled strategy that uses a shared CursesDisplay."""

    def __init__(self, display: CursesDisplay):
        super().__init__()
        self.display = display

    def choose_action(self, obs: Observation, legal_actions: list[Action]) -> Action:
        return self.display.choose_action(obs, legal_actions)


class DisplayWrapperStrategy(Strategy):
    """Wrap any other strategy to render the UI before it picks an action.

    Useful to *watch* bots.

    Optionally sleeps briefly after each render to make the game observable.
    """

    def __init__(self, inner: Strategy, display: CursesDisplay, delay_s: float = 0.15):
        super().__init__()
        self.inner = inner
        self.display = display
        self.delay_s = delay_s

    def choose_action(self, obs: Observation, legal_actions: list[Action]) -> Action:
        self.display.render(obs, legal_actions)
        if self.delay_s > 0:
            time.sleep(self.delay_s)
        return self.inner.choose_action(obs, legal_actions)
