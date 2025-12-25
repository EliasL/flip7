import sys
from cardGame import (
    Game,
    Deck,
    Player,
    Card,
    ActionType,
    Action,
    Observation,
    Strategy,
    RandomStrategy,
)

from display import CursesDisplay, HumanCursesStrategy, DisplayWrapperStrategy


class Flip7(Game):
    FREEZE = "Freeze"
    FLIP_THREE = "Flip three"
    SECOND_CHANCE = "Second chance"
    TIMES_TWO = "x2"

    EFFECTS = [FREEZE, FLIP_THREE]

    # Internal flow phases for the strategy-driven engine
    PHASE_FLIP = "Flip card"  # active player decides draw/pass
    PHASE_EFFECT_CHOOSE = "Choose effect target"  # effect owner chooses target player

    def __init__(self, playerNames):
        super().__init__(playerNames)
        self.effectsToResolve: list[Card] = []
        self.maxScore = 200  # First to reach 200 or more wins
        self.showBustChance = True
        # This game is played with open hands
        self.openHands = True

        # Strategy-driven engine state
        self.phase: str = Flip7.PHASE_FLIP
        self._pending_effect: Card | None = None
        self._pending_effect_owner: Player | None = None

        # Ensure every player has a strategy; callers can override later.
        for p in self.players:
            p.strategy = RandomStrategy()

        self.coloredWords = {
            Flip7.FREEZE: "cyan",
            "frozen": "cyan",
            Flip7.FLIP_THREE: "yellow",
            Flip7.SECOND_CHANCE: "red",
            Flip7.TIMES_TWO: "green",
            "Busted": "red",
            "Passed": "green",
        }

    def newDeck(self):
        deck = Deck()
        # Add numbers
        for i in range(0, 13):
            deck.addCard(i, copies=max(i, 1))

        for c in deck:
            c.special = False

        # Extra cards
        deck.addCard(Flip7.FREEZE, 3)
        deck.addCard(Flip7.FLIP_THREE, 3)
        deck.addCard(Flip7.SECOND_CHANCE, 3)
        deck.addCard(Flip7.TIMES_TWO)
        for i in range(1, 6):
            deck.addCard(f"+{2 * i}")

        for c in deck:
            if c.special is None:
                c.special = True

        return deck

    def get_observation(self) -> Observation:
        obs = super().get_observation()

        pending_effect = str(self._pending_effect) if self._pending_effect else None
        pending_owner = (
            self._pending_effect_owner.i if self._pending_effect_owner else None
        )

        if self.showBustChance:
            bust_probabilities = [
                self.bustProbability(p, self.deck) for p in self.players
            ]
        else:
            bust_probabilities = None

        obs.extras = {
            "effects_to_resolve": [str(c) for c in self.effectsToResolve],
            "effect_owners": [c.owner.i for c in self.effectsToResolve],
            "pending_effect": pending_effect,
            "pending_effect_owner": pending_owner,
            "bust_probabilities": bust_probabilities,
        }
        return obs

    def get_legal_actions(self, player: Player) -> list[Action]:
        if all(p.isDone for p in self.players):
            return []

        if player.isDone:
            return []

        if self.phase == Flip7.PHASE_FLIP:
            if player is not self.turnPlayer:
                return []
            return [
                Action(ActionType.DRAW, acting_player=player),
                Action(ActionType.PASS, acting_player=player),
            ]

        if self.phase == Flip7.PHASE_EFFECT_CHOOSE:
            if (
                self._pending_effect_owner is None
                or player is not self._pending_effect_owner
            ):
                return []

            targets = [p for p in self.players if not p.isDone]

            return [
                Action(ActionType.CHOOSE_PLAYER, acting_player=player, target_player=t)
                for t in targets
            ]

        return []

    def apply_action(self, action: Action) -> None:
        actor = action.acting_player

        match self.phase:
            case Flip7.PHASE_FLIP:
                match action.type:
                    case ActionType.PASS:
                        self.log(actor, "passes")
                        actor.status = "Passed"
                        self._end_round_for(actor)

                    case ActionType.DRAW:
                        self._apply_draw(actor, three_turn=False)
                    case _:
                        raise ValueError(
                            f"Illegal action {action.type} in phase {self.phase}"
                        )

            case Flip7.PHASE_EFFECT_CHOOSE:
                if action.type != ActionType.CHOOSE_PLAYER:
                    raise ValueError(
                        "Only CHOOSE_PLAYER is legal in EFFECT_CHOOSE phase"
                    )

                if self._pending_effect is None or self._pending_effect_owner is None:
                    raise RuntimeError("No pending effect to resolve")

                if actor is not self._pending_effect_owner:
                    raise ValueError(
                        "Only the pending effect owner may choose a target"
                    )

                if action.target_player is None:
                    raise ValueError("CHOOSE_PLAYER requires target_player")

                target = action.target_player

                if self._pending_effect.value == Flip7.FREEZE:
                    self.log(actor, "freezes", target)
                    target.status = "Frozen"
                    self._end_round_for(target)
                    self._start_next_effect_if_any()
                    return

                if self._pending_effect.value == Flip7.FLIP_THREE:
                    self.log(actor, "forces", target, "to draw flip three cards")
                    self._apply_flip_three_chain(target)
                    return

                # Unknown effect -> continue
                self._start_next_effect_if_any()

            case _:
                raise ValueError(f"Unknown phase {self.phase}")

    def _start_next_effect_if_any(self) -> None:
        """Pop the next effect and switch to EFFECT_CHOOSE; or return to TURN when queue is empty."""
        if not self.effectsToResolve:
            self._pending_effect = None
            self._pending_effect_owner = None
            self.phase = Flip7.PHASE_FLIP
            self.activePlayer = self.turnPlayer
            return

        effect = self.effectsToResolve.pop(0)
        self._pending_effect = effect
        self._pending_effect_owner = effect.owner
        self.phase = Flip7.PHASE_EFFECT_CHOOSE

        # During effect resolution, the effect owner becomes the active player.
        self.activePlayer = self._pending_effect_owner

    def _end_round_for(self, player: Player) -> None:
        player.isDone = True
        self.effectsToResolve = [c for c in self.effectsToResolve if c.owner != player]

    def _apply_draw(self, player: Player, three_turn: bool = False) -> Card:
        """Draw 1 card; queue effects; optionally resolve immediately."""
        assert not player.isDone

        new_card = player.drawCard(self.deck)

        self.log(player, "draws a", new_card)

        # Match
        if self.playerHasMatch(player):
            if Flip7.SECOND_CHANCE in player.hand:
                player.hand.remove(Flip7.SECOND_CHANCE)
                player.hand.remove(new_card)
                self.log(player, "lost their", Flip7.SECOND_CHANCE, end="!\n")
            else:
                self.log(player, "has a match!", color="red")
                player.status = "Busted"
                self._end_round_for(player)
                return new_card

        # 7 unique
        if not player.isDone and len(player.hand.getNormalCards()) == 7:
            self.log(player, "managed to flip7!", color="green")
            self._end_round_for(player)

        # Effects
        elif not player.isDone and new_card in Flip7.EFFECTS:
            self.effectsToResolve.append(new_card)
            if not three_turn:
                self._start_next_effect_if_any()

        return new_card

    def _apply_flip_three_chain(self, target: Player) -> None:
        """Forced 3 draws; effects queued during chain; resolve after chain."""
        for _ in range(3):
            self._apply_draw(target, three_turn=True)
            if target.isDone:
                break
        if not target.isDone:
            self.log(target, "survived the", Flip7.FLIP_THREE, color="green")

        self._start_next_effect_if_any()

    def playerHasMatch(self, player: Player, newCard=None):
        onlyNumbersHand = player.hand.getNormalCards()

        if newCard is not None:
            if not newCard.special:
                onlyNumbersHand.append(newCard)

        # Check if there are any matches by converting to set
        return len(onlyNumbersHand) != len(set(onlyNumbersHand))

    def matchProbability(self, player: Player, deck: Deck):
        """
        Probability that the very next card is a number that matches
        a number already in the player's hand.
        """
        hand = {c for c in player.hand.getNormalCards()}
        if not hand or len(deck) == 0:
            return 0.0

        matching_in_deck = sum(
            1 for card in deck if (not card.special and card in hand)
        )
        return matching_in_deck / len(deck)

    def bustProbability(self, player: Player, deck: Deck):
        # If the player has a second chance and can choose someone else
        # if they draw a flip three, their chance of busting is 0
        if Flip7.SECOND_CHANCE in player.hand:
            if self.nrPlayersStillPlaying != 1:
                return 0.0
            else:
                directMatchProbability = 0.0
        else:
            # Probability of drawing a card with a number already in the hand
            directMatchProbability = self.matchProbability(player, deck)

        # Special case:
        # If there is only one player left, they would be forced to
        # pick themselves as a flip-three target, so we also factor in
        # the chance of busting via a flip-three chain.
        if Flip7.FLIP_THREE in deck and self.nrPlayersStillPlaying == 1:
            matchByFlipThree = self.matchByFlipThreeProbability(player, deck)
        else:
            matchByFlipThree = 0.0

        return directMatchProbability + matchByFlipThree

    def matchByFlipThreeProbability(self, player: Player, deck: Deck):
        # To not modify the original deck, we copy it
        deck = deck.copy()

        # First we see what the probability of getting a flip three is
        nrFlipThree = deck.count(Flip7.FLIP_THREE)
        if nrFlipThree == 0:
            return 0.0

        p_getF3 = nrFlipThree / len(deck)
        assert p_getF3 > 0.0, (
            "Don't call this function if the deck doesn't have a flip three"
        )

        # Once we draw the flip three, that card leaves the deck
        deck.remove(Flip7.FLIP_THREE)

        # Approximate the probability of getting matches in the three
        # cards drawn due to the flip three. We treat the three draws as
        # (approximately) independent, using the single-draw probability.
        p_single = self.matchProbability(player, deck)
        q_single = 1 - p_single

        # For each second chance in the hand, we need one additional match
        # to actually bust. If we have L "lives", we bust only if the
        # number of matches X in the three cards satisfies X >= L + 1.
        L = player.hand.count(Flip7.SECOND_CHANCE)

        # X ~ Binomial(n=3, p=p_single) under our independence approximation.
        # So:
        #   P(X = k) = C(3, k) * p_single^k * q_single^(3-k)
        # and
        #   P(X >= L+1) = sum_{k=L+1}^{3} P(X = k)
        if L >= 3:
            # You can't bust in three cards if you have 3 or more lives
            p_match_in_three = 0.0
        else:
            if L == 0:
                # P(X >= 1) = 1 - (1 - p)^3
                p_match_in_three = 1 - q_single**3
            elif L == 1:
                # P(X >= 2) = 3 p^2 (1-p) + p^3
                p_match_in_three = 3 * (p_single**2) * q_single + p_single**3
            else:  # L == 2
                # P(X >= 3) = p^3
                p_match_in_three = p_single**3

        # It's only an approximation since, in reality, the draws
        # would not be independent. We also ignore the chance of
        # drawing further flip-three or second-chance cards inside
        # these three draws.

        return p_getF3 * p_match_in_three

    def getPlayerHandScore(self, player: Player):
        if self.playerHasMatch(player):
            return 0
        else:
            score = 0
            if len(player.hand.getNormalCards()) == 7:
                score += 15

            for c in player.hand:
                if not c.special or "+" in c.value:
                    score += int(c)
                if c.value == Flip7.TIMES_TWO:
                    score *= 2
            return score

    def updatePlayerScores(self):
        for p in self.players:
            handScore = self.getPlayerHandScore(p)
            self.log(p, "gets", handScore, "points")
            p.score += handScore

    def play(self):
        self.phase = Flip7.PHASE_FLIP
        self._pending_effect = None
        self._pending_effect_owner = None

        while not self.gameOver:
            if not all(p.isDone for p in self.players):
                obs = self.get_observation()
                legal = self.get_legal_actions(self.activePlayer)
                chosen = self.activePlayer.strategy.choose_action(obs, legal)
                if self.gameOver:
                    break
                self.apply_action(chosen)

                if self.phase == Flip7.PHASE_FLIP:
                    self.endTurn()
                elif self.phase == Flip7.PHASE_EFFECT_CHOOSE:
                    pass

            else:
                self.log("All players are done", color="magenta")
                self.updatePlayerScores()

                self.endRound()
                self.phase = Flip7.PHASE_FLIP
                self._pending_effect = None
                self._pending_effect_owner = None

                if any(p.score >= self.maxScore for p in self.players):
                    self.isDone = True
                    break

                self.showPlayerScores()
                self.log("---------")
                self.log("Starting round", self.round, color="magenta")

        self.log(f"The game is over! {self.getLeader()} won!", color="magenta")
        self.showPlayerScores()


if __name__ == "__main__":
    # Player names are taken from command-line arguments
    # Example: python main.py Alice Bob Charlie
    player_names = sys.argv[1:]

    if not player_names:
        player_names = ["Eloise", "Jules", "Thibault", "Paul", "Elias"]

    game = Flip7(player_names)
    game.showBustChance = False
    # game.maxScore = 20

    ui = CursesDisplay(game)

    # Default: all players are human-controlled via curses UI
    for p in game.players:
        p.strategy = HumanCursesStrategy(ui)

    # Example bot setup (optional):
    # game.players[1].strategy = DisplayWrapperStrategy(game.players[1].strategy, ui)

    with ui.session():
        game.play()
        # Render to show the last frame
        ui.render()
        ui.waitForKey()
