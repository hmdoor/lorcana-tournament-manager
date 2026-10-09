# Lorcana Tournament Manager

Runs Disney Lorcana events on your own computer: registration, Swiss pairings,
best-of-3 results, standings with tiebreakers, a top cut bracket and a projector
round timer. It needs Python 3.10 or newer and nothing else.

## Start it

Double-click **Start Lorcana Tournament.command**, or run:

```bash
python3 -m lorcana
```

Your browser opens at http://127.0.0.1:8000. Keep the terminal window open while
the event runs; press Ctrl+C there to stop.

Tournaments are saved in the `data` folder as they change, so closing the browser
or restarting the computer loses nothing. Use **Settings → Export tournament file**
for a backup copy.

## Running an event

1. Create a tournament and choose the round length and top cut.
2. Add players, one at a time or by pasting a list.
3. Press the big button in the gold bar. It always shows the next step:
   start round 1, pair the next round, start the top cut, and so on.
4. On **Pairings**, tap each match's score (games won, left player first).
5. Open the projector timer with the ⛶ button next to the clock.

Every change can be reversed with **Undo**.

## Rules used

- Match win 3 points, draw 1, loss 0. A bye is a 2–0 win.
- Tiebreakers: opponents' match win %, game win %, opponents' game win %
  (each with a 33% floor).
- Pairings stay within point groups and avoid rematches. Byes go to the lowest
  point group, never twice to the same player.
- Late players take a loss for each round they missed.
- Top cut seeds the best non-dropped players; seeds 1 and 2 can only meet in the final.

## Project documents

- [Discovery plan](docs/discovery/README.md): research questions, stakeholders,
  interview guides, survey and event observation sheet

## For developers

- `lorcana/rules.py` holds all tournament logic, with no web or storage code.
- `lorcana/storage.py` saves tournaments as JSON files (swap this out for a database
  when hosting).
- `lorcana/server.py` is the web server and JSON API.
- `lorcana/static/` holds the browser screens.

Run the tests with `python3 -m unittest`.
