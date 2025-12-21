import random
from abc import ABC, abstractmethod


class Colors:
    # ANSI color codes
    BLUE = "\033[94m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[35m"
    GREEN = "\033[32m"
    BOLD = "\033[1m"
    RESET = "\033[0m"
    BOLD_OFF = "\033[22m"


class Card:
    # In this script (making Flip7) we don't use suit
    def __init__(self, value, suit=None):
        self.value = str(value)
        self.suit = suit
        self.owner: Player = None
        self.special = None  # Usefull flag

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

    def peekRandomCard(self):
        if self.nrCards == 0:
            return None
        # Does not remove cards from the deck
        return random.choice(self)

    def takeRandomCard(self):
        if self.nrCards == 0:
            return None
        # Removes a card from the deck
        i = random.randint(0, self.nrCards - 1)
        return self.pop(i)

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


class Hand(Deck):
    # A hand is basically just a tiny deck. Many of the same functions
    # for a deck is usefull for a deck as well. (addCard, takeCard, ...)
    def __init__(self):
        super().__init__()


class Player:
    def __init__(self, name=None):
        self.hand = Hand()
        self.isDone = False
        self.score = 0
        self.name = name

    def takeCard(self, deck: Deck):
        newCard = deck.takeRandomCard()
        newCard.owner = self
        self.hand.addCard(newCard)
        return newCard

    def __str__(self):
        # Add a bold effect to names
        return Colors.BOLD + self.name + Colors.BOLD_OFF


class Game(ABC):
    def __init__(self, playerNames):
        self.deck = self.newDeck()
        self.players = [Player(n) for n in playerNames]
        self.nrPlayers = len(self.players)
        self.currentPlayerNr = 0
        self.isDone = False  # Marks the end of the game
        self.round = 1
        self.tabLevel = 0

    @abstractmethod
    def newDeck(self) -> Deck: ...

    def getCurrentPlayer(self):
        return self.players[self.currentPlayerNr]

    def nrPlayersNotDone(self):
        return sum([p.isDone for p in self.players])

    def playersNotDone(self):
        return [p for p in self.players if not p.isDone]

    def endTurn(self):
        self.currentPlayerNr = (self.currentPlayerNr + 1) % len(self.players)

    def endRound(self):
        self.resetDeck()
        self.resetPlayers()
        # Set starting player
        # Assuming first round started with player 0
        # Assuming round number starts with 1
        self.currentPlayerNr = self.round % len(self.players)

        self.round += 1

    def getLeader(self, highestScore=True):
        f = max if highestScore else min
        return f(self.players, key=lambda p: p.score)

    def resetPlayers(self):
        for p in self.players:
            p.isDone = False
            p.hand.clear()

    def resetDeck(self):
        self.deck = self.newDeck()

    def showPlayerScores(self):
        self.log("Player scores:")
        players = sorted(self.players, key=lambda p: p.score, reverse=True)
        for p in players:
            self.log(p.name, p.score, sep=": ")

    def log(self, *args, color=None, **kwargs):
        print("  " * self.tabLevel, end="")
        if color:
            print(color, end="")
        print(*args, **kwargs)
        if color:
            print(Colors.RESET, end="")

    def input(self, prompt):
        prompt = "  " * self.tabLevel + prompt
        return input(prompt)

    def choosePlayer(self, chooser: Player, canChooseSelf=True) -> Player:
        options = self.playersNotDone()
        if not canChooseSelf and chooser in options:
            options.remove(chooser)
        while True:
            self.log(chooser, "chooses a player:")
            for i, p in enumerate(options):
                self.log(i + 1, p, sep=") ")
            try:
                i = int(self.input("Choice: "))
                player = options[i - 1]
                break
            except (ValueError, IndexError):
                self.log("Invalid choice!")
        return player
