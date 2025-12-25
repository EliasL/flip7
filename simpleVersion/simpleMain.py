from cardGame import Game, Deck, Player, Card, Colors


class Flip7(Game):
    FREEZE = f"{Colors.BLUE}Freeze{Colors.RESET}"
    FLIP_THREE = f"{Colors.YELLOW}Flip three{Colors.RESET}"
    SECOND_CHANCE = f"{Colors.RED}Second chance{Colors.RESET}"
    TIMES_TWO = "x2"  # unchanged

    EFFECTS = [FREEZE, FLIP_THREE]

    def __init__(self, playerNames):
        super().__init__(playerNames)
        self.effectsToResolve: list[Card] = []
        self.maxScore = 200  # First to reach 200 or more wins
        self.showProbability = True

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

    def doTurn(self, player: Player, threeTurn=False):
        if self.showProbability:
            bustChance = f" ({round(self.matchProbability(player, self.deck) * 100)}%)"
        else:
            bustChance = ""

        if threeTurn:
            self.log(f"Card nr {threeTurn}{bustChance}")
            self.log(player.hand)
            self.input("Press enter to flip")
            answer = "y"
        else:
            self.log(f"{player}'s turn{bustChance}:")
            self.log(player.hand)
            answer = self.input("Take another card? (y/n): ").lower()

        if answer != "y":
            self.endRoundFor(player)
            return

        # Else:
        newCard = player.drawCard(self.deck)
        self.log(player.hand)

        # There is a match!
        if self.playerHasMatch(player):
            self.log("Match!", color=Colors.MAGENTA)
            if Flip7.SECOND_CHANCE in player.hand:
                self.log("You lost your second chance!")
                player.hand.remove(Flip7.SECOND_CHANCE)
                player.hand.remove(newCard)
                self.log(player.hand)
            else:
                self.endRoundFor(player)

        # Not match, there are 7 unique normal cards
        elif len(player.hand.getNormalCards()) == 7:
            self.log(player, "flipped 7!")
            self.endRoundFor(player)

        # There is an effect card
        elif newCard in Flip7.EFFECTS:
            # When resolving a flip three, we apply effects
            # afterwards if the player has not busted
            if threeTurn:
                self.effectsToResolve.append(newCard)
            else:
                self.resolveEffect(newCard)

    def endRoundFor(self, player: Player):
        player.isDone = True
        # We remove the effects belonging to the player
        # who is out of the round
        self.effectsToResolve = [c for c in self.effectsToResolve if c.owner != player]
        self.log("The round is over for", player, color=Colors.MAGENTA)

    def doTrippleTurn(self, player: Player):
        for i in range(3):
            self.doTurn(player, threeTurn=i + 1)
            # If the player busts before the three cards
            # have been drawn we stop early
            if player.isDone:
                break
        if not player.isDone:
            self.log(player, "survived the flip three!", color=Colors.GREEN)

        while len(self.effectsToResolve) > 0:
            effectCard = self.effectsToResolve.pop(0)
            self.resolveEffect(effectCard)

    def resolveEffect(self, effectCard: Card):
        self.tabLevel += 1
        self.log("Resolving", effectCard)

        # Card owner chooses a player
        player = self.choosePlayer(effectCard.owner)

        if effectCard.value == Flip7.FREEZE:
            self.log(player, "is frozen!", color=Colors.BLUE)
            self.endRoundFor(player)

        if effectCard.value == Flip7.FLIP_THREE:
            self.log(player, "needs to draw three cards!", color=Colors.YELLOW)
            self.doTrippleTurn(player)

        self.tabLevel -= 1

    def playerHasMatch(self, player: Player, newCard=None):
        onlyNumbersHand = player.hand.getNormalCards()

        if newCard is not None:
            if not newCard.special:
                onlyNumbersHand.append(newCard)

        # Check if there are any matches by converting to set
        return len(onlyNumbersHand) != len(set(onlyNumbersHand))

    def directMatchProbability(self, player: Player, deck: Deck):
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

    def matchProbability(self, player: Player, deck: Deck):
        # If the player has a second chance and can choose someone else
        # if they draw a flip three, their chance of busting is 0
        if Flip7.SECOND_CHANCE in player.hand:
            if self.nrPlayersStillPlaying != 1:
                return 0.0
            else:
                directMatchProbability = 0.0
        else:
            # Probability of drawing a card with a number already in the hand
            directMatchProbability = self.directMatchProbability(player, deck)

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
        p_single = self.directMatchProbability(player, deck)
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
            p.score += self.getPlayerHandScore(p)

    def play(self):
        self.log("Game start!", color=Colors.MAGENTA)
        while not self.gameOver:
            if not all([p.isDone for p in self.players]):
                p = self.currentPlayer
                if p.isDone:
                    self.log(f"{p} passes")
                else:
                    self.doTurn(p)
                    self.log()

                self.endTurn()

            else:
                self.updatePlayerScores()

                if any([p.score >= self.maxScore for p in self.players]):
                    self.isDone = True
                    break

                self.endRound()
                self.showPlayerScores()
                self.log()
                self.log("Starting round", self.round, color=Colors.MAGENTA)

        self.log(f"The game is over! {self.getLeader()} won!", color=Colors.MAGENTA)
        self.showPlayerScores()


if __name__ == "__main__":
    game = Flip7(["Elias", "Lars"])
    game.play()
