import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from flip7 import Flip7, simpleRisk, simpleRiskEstimator
from display import CursesDisplay, HumanCursesStrategy
from collections import Counter


def humanPlayers(player_names):
    if not player_names:
        player_names = ["Eloise", "Jules", "Thibault", "Paul", "Elias"]

    game = Flip7(player_names)
    game.showBustChance = False

    ui = CursesDisplay(game)

    # Default: all players are human-controlled via curses UI
    for p in game.players:
        p.strategy = HumanCursesStrategy(ui)

    with ui.session():
        game.play()
        # Render to show the last frame
        ui.render()
        ui.waitForKey()


def cpuPlayers(nrCpus=5, log=False):
    game = Flip7(["Accurate", "Estimate"])
    game.showLog = False
    game.players[0].strategy = simpleRisk(0.25)
    game.players[1].strategy = simpleRiskEstimator(30)
    for p in game.players:
        p.cpu = True

    winner = game.play()
    return winner


def _run_games_batch(n: int):
    """Run `n` CPU games in this process and return (n, Counter(winners))."""
    local = Counter()
    for _ in range(n):
        local[cpuPlayers().name] += 1
    return n, local


def playLotsOfGames():
    nrGames = 100000
    workers = 7

    # Smaller chunks -> more frequent progress updates.
    # Tune this: smaller = smoother progress but slightly more overhead.
    chunk_size = 1000

    # Build chunk sizes that sum to nrGames.
    chunks = [chunk_size] * (nrGames // chunk_size)
    tail = nrGames % chunk_size
    if tail:
        chunks.append(tail)

    results = Counter()
    completed_games = 0

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_run_games_batch, n) for n in chunks]

        for fut in as_completed(futures):
            n, c = fut.result()
            results += c
            completed_games += n
            print(f"{completed_games / nrGames:.0%}", end="\r")

    print("100%")
    print(results)


if __name__ == "__main__":
    # Player names are taken from command-line arguments
    # Example: python main.py Alice Bob Charlie
    player_names = sys.argv[1:]
    if not player_names:
        player_names = ["Eloise", "Jules", "Thibault", "Paul", "Elias"]
    humanPlayers(player_names)
    # playLotsOfGames()
