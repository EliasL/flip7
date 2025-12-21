from cardGame import Game, Deck, Hand, Player, Card, Colors


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

    def newDeck(self):
        deck = Deck()
        # Add numbers
        for i in range(0, 13):
            deck.addCard(i, copies=max(i, 1))

        for c in deck:
            setattr(c, "isNumber", True)

        # Extra cards
        deck.addCard(Flip7.FREEZE, 3)
        deck.addCard(Flip7.FLIP_THREE, 3)
        deck.addCard(Flip7.SECOND_CHANCE, 3)
        deck.addCard(Flip7.TIMES_TWO)
        for i in range(1, 6):
            deck.addCard(f"+{2 * i}")

        for c in deck:
            if not hasattr(c, "isNumber"):
                setattr(c, "isNumber", False)

        return deck

    def doTurn(self, player: Player, threeTurn=False):
        bustChance = f"{round(self.matchProbability(player) * 100)}%"

        if threeTurn:
            self.log(f"Card nr {threeTurn} ({bustChance})")
        else:
            self.log(f"{player}'s turn ({bustChance}):")
        self.log(player.hand)

        if threeTurn:
            answer = "y"
            self.input("Press enter to flip")
        else:
            answer = self.input("Take another card? (y/n): ").lower()

        if answer == "y":
            newCard = player.takeCard(self.deck)
            self.log(player.hand)

            if self.playerHasMatch(player):
                self.log("Match!", color=Colors.MAGENTA)
                if Flip7.SECOND_CHANCE in player.hand:
                    self.log("You lost your second chance!")
                    player.hand.remove(Flip7.SECOND_CHANCE)
                    player.hand.remove(newCard)
                    self.log(player.hand)
                else:
                    self.endRoundFor(player)

            if len(self.getNumbersOnlyHand(player)) == 7:
                self.endRoundFor(player)

            elif newCard in Flip7.EFFECTS:
                # When resolving a flip three, we apply effects
                # afterwards if the player has not busted
                if threeTurn:
                    self.effectsToResolve.append(newCard)
                else:
                    self.resolveEffect(newCard)

        else:
            self.endRoundFor(player)

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
        while True:
            self.log(effectCard.owner, "chooses a player:")
            for i, p in enumerate(self.playersNotDone()):
                self.log(i + 1, p, sep=") ")
            try:
                i = int(self.input("Choice: "))
                player = self.playersNotDone()[i - 1]
                break
            except (ValueError, IndexError):
                self.log("Invalid choice!")

        if effectCard.value == Flip7.FREEZE:
            self.log(player, "is frozen!", color=Colors.BLUE)
            self.endRoundFor(player)

        if effectCard.value == Flip7.FLIP_THREE:
            self.log(player, "needs to draw three cards!", color=Colors.YELLOW)
            self.doTrippleTurn(player)

        self.tabLevel -= 1

    def getNumbersOnlyHand(self, player):
        onlyNumbersHand = Hand()
        for c in player.hand:
            if c.isNumber:
                onlyNumbersHand.addCard(c)
        return onlyNumbersHand

    def playerHasMatch(self, player, newCard=None):
        onlyNumbersHand = self.getNumbersOnlyHand(player)

        if newCard is not None:
            if newCard.isNumber:
                onlyNumbersHand.addCard(newCard)

        # Check if there are any matches by converting to set
        return len(onlyNumbersHand) != len(set(onlyNumbersHand))

    def matchProbability(self, player):
        # Probability of drawing a card with a number already in the hand
        if Flip7.SECOND_CHANCE in player.hand:
            return 0
        nrMatches = 0
        for c in self.deck:
            if self.playerHasMatch(player, newCard=c):
                nrMatches += 1
        return nrMatches / len(self.deck)

    def getPlayerHandScore(self, player):
        if self.playerHasMatch(player):
            return 0
        else:
            score = 0
            if len(self.getNumbersOnlyHand(player)) == 7:
                score += 15

            for c in player.hand:
                if c.isNumber or "+" in c.value:
                    score += int(c)
                if c.value == Flip7.TIMES_TWO:
                    score *= 2
            return score

    def updatePlayerScores(self):
        for p in self.players:
            p.score += self.getPlayerHandScore(p)

    def play(self):
        self.log("Game start!", color=Colors.MAGENTA)
        while not self.isDone:
            if not all([p.isDone for p in self.players]):
                p = self.getCurrentPlayer()
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
    game = Flip7(["Elias", "Eloise", "Jules"])
    game.play()
