# Discovery Plan

**Project:** Lorcana Tournament Manager
**Owner:** hmdoor (Business Analyst / Product Owner)
**Status:** Planned

## Purpose

Learn how local Disney Lorcana events are run today, where time is lost and
mistakes happen, and what organizers, players and stores need. The findings decide
what gets built next, and the measurements taken now become the baseline for
judging whether the app helps.

## Research questions

| ID | Question |
|---|---|
| RQ1 | How do organizers run an event today, step by step, and with what tools? |
| RQ2 | Where do delays, errors and disputes happen during an event? |
| RQ3 | What do players need to know before, during and after an event? |
| RQ4 | What data would stores and organizers use (attendance, deck trends, player history), and for what decisions? |
| RQ5 | What constraints exist: devices, Wi-Fi, official reporting rules, store layout, budget? |
| RQ6 | How do players feel about their names, records and decks being tracked or published? |

## Participants

| Group | Target | How to recruit |
|---|---|---|
| Organizers / store staff who run events | 3–5 | Ask at local stores; Lorcana community Discord servers |
| Players (mix of casual and competitive) | 6–10 interviews, 30+ survey responses | At events, between rounds; store social media |
| Store owners or managers | 1–2 | Through the organizers |
| Judges (optional) | 1 | Through the organizers |

## Methods and timeline

| Week | Activity | Output |
|---|---|---|
| 1 | Recruit participants. Observe and time one event without changing anything. | [Observation sheet](event-observation-sheet.md) with baseline times |
| 2–3 | Organizer and player interviews | Notes using the [notes template](interview-notes-template.md) |
| 2–4 | Run the [player survey](survey.md) at 2–3 events | Survey results |
| 4 | Synthesis: group notes into themes (affinity mapping) | Findings report, personas, journey map |
| 5 | Turn findings into requirements and user stories | Requirements and backlog (step 6 of the roadmap) |

## Ethics and privacy

- Read the consent script at the start of every interview and note the answer.
- Each participant gets an ID (TO-01 for organizers, P-01 for players, SO-01 for
  store owners). Real names go only in a private key kept off GitHub.
- Raw notes go in `docs/discovery/raw/`, which is excluded from git. Only
  anonymized summaries and findings are committed.
- Participants can withdraw at any time, and their notes are then deleted.

## Traceability

Every finding cites the sessions it came from, and every requirement cites the
findings behind it:

```
Interview TO-02, observation OBS-01  →  Finding F-03  →  Requirement REQ-07  →  User story US-12
```

That chain is how you show an interviewer that the backlog came from evidence, not
guesses.

## Documents

- [Stakeholder map](stakeholder-map.md)
- [Organizer interview guide](interview-guide-organizers.md)
- [Player interview guide](interview-guide-players.md)
- [Player survey](survey.md)
- [Event observation sheet](event-observation-sheet.md)
- [Interview notes template](interview-notes-template.md)
