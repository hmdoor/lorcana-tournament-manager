# Stakeholder Map

The "assumptions to test" column lists beliefs that discovery should confirm or
reject. Update it as interviews come in.

## Stakeholders

| Stakeholder | Role in events | What they care about | Influence | Interest | Assumptions to test |
|---|---|---|---|---|---|
| **Tournament organizer (TO)** | Registers players, pairs rounds, enters results, runs the top cut | Rounds start on time; no pairing or scoring mistakes; less stress; easy to learn | High | High | Time between rounds is their biggest pain. They use paper, spreadsheets or an official tool. |
| **Competitive players** | Play every round, follow standings closely | Fair pairings, correct tiebreakers, knowing where they stand, their own history | Medium | High | They want standings during the event and records across events. |
| **Casual players** | Play for fun, may drop early | Short waits, a friendly event, knowing where to sit | Low | Medium | They care more about waiting less than about statistics. |
| **Store owner / manager** | Hosts events, pays for prizes and space | Attendance, repeat customers, events that finish on time, low cost | High | Medium | Attendance and retention data would affect how they plan events. |
| **Judges** | Rule on disputes, handle time calls | Clear match records, an accurate round timer | Medium | Medium | They need to see and correct past results. |
| **Ravensburger organized play** | Sets official rules and event requirements | Events follow official policy; required reporting is done | High | Low | Some events must also be reported in an official system. The app must not conflict with that. |
| **Product owner (you)** | Builds and runs the project | A tool people actually use; evidence for a portfolio | High | High | (Watch for your own bias toward features you'd like to build.) |

## Power–interest grid

```
              Low interest                     High interest
          ┌──────────────────────────────┬──────────────────────────────┐
  High    │ KEEP SATISFIED               │ MANAGE CLOSELY               │
influence │ Ravensburger organized play  │ Tournament organizers        │
          │ Store owners                 │                              │
          ├──────────────────────────────┼──────────────────────────────┤
  Low     │ MONITOR                      │ KEEP INFORMED                │
influence │                              │ Competitive players          │
          │                              │ Casual players, judges       │
          └──────────────────────────────┴──────────────────────────────┘
```

## Engagement plan

| Stakeholder | How to involve them | How often |
|---|---|---|
| Organizers | Interviews, event observation, hands-on testing of each release, pilot partner | Every sprint during the pilot |
| Players | Survey, short interviews between rounds, feedback after events | Each event |
| Store owners | Short interview; share a summary of attendance results | Start and end of the pilot |
| Judges | One interview; review of how results are corrected | Once, then as needed |
| Ravensburger organized play | Read the current official tournament rules; no direct contact planned | Before each release that touches rules |
