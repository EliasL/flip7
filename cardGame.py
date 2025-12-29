from __future__ import annotations
import random
from abc import ABC, abstractmethod
from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Any
from time import sleep


class ActionType(Enum):
    """Generic action types for turn-based games.

    Specific games can decide which of these they actually use and
    can further specialize semantics via the payload field in Action.
    """

    DRAW = auto()
    PASS = auto()
    CHOOSE_PLAYER = auto()
    PLAY_CARD = auto()
    RESPOND = auto()


@dataclass(frozen=True)
class Action:
    type: ActionType
    acting_player: Player
    target_player: Optional[Player] = None
    payload: Optional[dict[str, Any]] = None


@dataclass
class Observation:
    """A view of the game state for a single player."""

    actingPlayer: Player  # The acting player
    turnPlayer: Player
    leadingPlayer: Player
    nr_players_still_playing: int
    phase: str
    round: int
    scores: list[int]
    is_done: list[bool]
    deck_size: int
    own_hand: list[str]
    open_hands: bool
    other_hands: Optional[list[list[str]]] = None
    extras: Optional[dict[str, Any]] = None


class Strategy(ABC):
    """Base class for decision-making strategies.

    Concrete implementations can represent human input (via a UI layer),
    simple bots, or learning-based agents. They receive an Observation
    and a list of legal Actions and must return one of those actions.
    """

    @abstractmethod
    def choose_action(
        self, observation: Observation, legal_actions: list[Action]
    ) -> Action: ...


class RandomStrategy(Strategy):
    """Simple strategy that selects uniformly at random among legal actions."""

    def choose_action(
        self, observation: Observation, legal_actions: list[Action]
    ) -> Action:
        if not legal_actions:
            raise ValueError("RandomStrategy requires at least one legal action.")
        return random.choice(legal_actions)


class Card:
    # In this script (making Flip7) we don't use suit
    def __init__(self, value, suit=None):
        self.value = str(value)
        self.suit = suit
        # Usefull tag (True, False for example)
        self.special = None
        self.owner: Player = None

    def __int__(self):
        return int(self.value)

    def __str__(self):
        if self.suit is None:
            return self.value
        else:
            return self.value + self.suit

    def __hash__(self):
        return str(self).__hash__()

    __repr__ = __str__

    def __eq__(self, card):
        if not isinstance(card, Card):
            card = Card(card)

        return self.value == card.value and self.suit == card.suit


class Deck(list[Card]):
    @property
    def nrCards(self):
        return len(self)

    def addCard(self, card, copies=1):
        if not isinstance(card, Card):
            card = Card(card)
        for _ in range(copies):
            self.append(card)

    def addCards(self, cards):
        for v in cards:
            self.addCard(v)

    def peekRandomCards(self, nr=1):
        assert nr >= 1
        if self.nrCards == 0:
            return None
        return random.sample(self, nr)

    def peekRandomCard(self):
        return self.peekRandomCards(1)[0]

    def takeRandomCards(self, nr=1):
        # Take cards without removing
        cards = self.peekRandomCards(nr)
        if cards is None:
            return None
        # Remove cards taken
        for c in cards:
            self.remove(c)
        return cards

    def takeRandomCard(self):
        return self.takeRandomCards(1)[0]

    def remove(self, card):
        if not isinstance(card, Card):
            card = Card(card)
        return super().remove(card)

    def getNormalCards(self):
        return [c for c in self if not c.special]

    def getSpecialCards(self):
        return [c for c in self if c.special]

    def __str__(self):
        return ", ".join(map(str, self))


class Player:
    def __init__(self, name=None, index=None):
        self.hand = Hand(self)
        self.isDone = False
        self.status = None
        self.score = 0
        self.name = str(name)
        self._index = index
        self.strategy = None

        self.cpu = False  #

    @property
    def i(self) -> int:
        """Stable index of the player within the game."""
        if self._index is None:
            raise ValueError("Player index has not been assigned.")
        return self._index

    def drawCard(self, deck: Deck):
        newCard = deck.takeRandomCard()
        newCard.owner = self
        self.hand.addCard(newCard)
        return newCard

    def emptyHand(self):
        self.hand.clear()

    def __str__(self):
        # Add a bold effect to names
        return self.name


class Hand(Deck):
    # A hand is basically just a tiny deck. Many of the same functions
    # for a deck is usefull for a deck as well. (addCard, takeCard, ...)
    def __init__(self, owner: Player = None):
        super().__init__()
        self.owner: Player = owner


class Game(ABC):
    def __init__(self, playerNames):
        self.deck = self.newDeck()
        self.nrPlayers = len(playerNames)
        self.players = [Player(n, i) for i, n in enumerate(playerNames)]
        self.turnPlayer: Player = self.players[0]  # Player whos turn it is
        # Active player (p2 might need to make an action during p1's turn)
        self.activePlayer: Player = self.players[0]
        self.round = 1
        self.phase: str = None
        self.gameOver = False  # Marks the end of the game

        self.openHands = False
        self.allCPUs = False
        self.delayTime = 1.5

        self.coloredWords = None
        self.showLog = True

    @abstractmethod
    def newDeck(self) -> Deck: ...

    @property
    def nrPlayersDone(self) -> int:
        return sum([p.isDone for p in self.players])

    @property
    def nrPlayersStillPlaying(self) -> int:
        return len(self.players) - self.nrPlayersDone

    @property
    def playersNotDone(self) -> list[Player]:
        return [p for p in self.players if not p.isDone]

    @property
    def everyoneIsDone(self) -> bool:
        return len(self.playersNotDone) == 0

    def get_observation(self, open_hands: bool = None) -> Observation:
        """Construct a generic Observation for the given player.

        Game-specific subclasses can override this to enrich the observation
        (for example, adding entries into `extras` such as effects to resolve),
        but this base implementation provides a sensible default view that is
        independent of any particular UI.
        """
        if open_hands is None:
            open_hands = self.openHands

        scores = [p.score for p in self.players]
        is_done = [p.isDone for p in self.players]
        # The hand of the active player
        if self.activePlayer:
            own_hand = [str(c) for c in self.activePlayer.hand]
        else:
            own_hand = None

        other_hands: Optional[list[list[str]]]
        if open_hands:
            other_hands = [
                [str(c) for c in p.hand] for p in self.players if p != self.activePlayer
            ]
        else:
            other_hands = None

        return Observation(
            actingPlayer=self.activePlayer,
            turnPlayer=self.turnPlayer,
            leadingPlayer=self.getLeader(),
            nr_players_still_playing=self.nrPlayersStillPlaying,
            phase=self.phase,
            round=self.round,
            scores=scores,
            is_done=is_done,
            deck_size=len(self.deck),
            own_hand=own_hand,
            open_hands=open_hands,
            other_hands=other_hands,
            extras=None,
        )

    def play(self):
        self.allCPUs = all([p.cpu for p in self.players])
        # Ensure every player has a strategy
        for p in self.players:
            assert p.strategy is not None, "Give the player a strategy!"

    def get_legal_actions(self, player: Player) -> list[Action]:
        """Return the list of legal actions for the given player.

        This method is intentionally left for game-specific subclasses to
        implement, since the action space and turn structure depend on the
        concrete game (e.g. Flip7 vs. another variant). The base
        implementation raises NotImplementedError.
        """

        raise NotImplementedError(
            "get_legal_actions must be implemented by a concrete Game subclass"
        )

    def apply_action(self, action: Action) -> None:
        """Apply a chosen action to the game state.

        Concrete games must implement how each ActionType affects the
        underlying state (drawing cards, resolving effects, advancing
        turns/rounds, etc.). This base implementation only serves as a
        placeholder.
        """

        raise NotImplementedError(
            "apply_action must be implemented by a concrete Game subclass"
        )

    def endTurn(self):
        # Redefines turn player so that it is the next (not-done) player's turn.
        if self.everyoneIsDone:
            return

        i = self.turnPlayer.i
        for _ in range(len(self.players)):
            i = (i + 1) % len(self.players)
            if not self.players[i].isDone:
                self.turnPlayer = self.players[i]
                self.activePlayer = self.turnPlayer
                return

        # Fallback: if everyone became done unexpectedly
        self.activePlayer = self.turnPlayer

    def endRound(self):
        self.resetDeck()
        self.resetPlayers()
        # Set starting player
        # Assuming first round started with player 0
        # Assuming round number starts with 1
        i = self.round % len(self.players)
        self.turnPlayer = self.players[i]
        self.activePlayer = self.turnPlayer

        self.round += 1

    def getLeader(self, highestScore=True):
        f = max if highestScore else min
        return f(self.players, key=lambda p: p.score)

    def resetPlayers(self):
        for p in self.players:
            p.isDone = False
            p.status = None
            p.emptyHand()

    def resetDeck(self):
        self.deck = self.newDeck()

    def showPlayerScores(self):
        self.log("Player scores:")
        players = sorted(self.players, key=lambda p: p.score, reverse=True)
        for p in players:
            self.log(p.name, p.score, sep=": ")

    def log(self, *args, **kwargs):
        if self.showLog:
            print(*args, **kwargs)

    def wait(self, time=None):
        if time is None:
            time = self.delayTime
        # Deactivate wait if there are only cpus
        if not self.allCPUs:
            sleep(time)
