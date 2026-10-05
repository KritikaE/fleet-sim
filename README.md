# Fleet Simulation Engine — Integration Guide

Self-Healing Decentralized Autonomous Logistics Fleet (KPIT hackathon). Standard-library Python only.

## Files
- `fleet_sim.py` — the engine. Import `Simulation` from it.
- `run_demo.py` — streams states as JSON Lines (one full state per tick).
- `sample_states.jsonl` — 60 pre-recorded ticks for building the dashboard without running the engine.

## Quick use
```python
from fleet_sim import Simulation

sim = Simulation(num_vehicles=6, seed=1, task_spawn_prob=0.1)
state = sim.tick()        # advance one tick, returns the state dict
state = sim.get_state()   # read current state without advancing
state = sim.get_state(log_limit=20)  # only the latest 20 log entries
```

## State shape (the only thing the dashboard reads)
```
{"vehicles": [{"id","x","y","battery","capacity","status","current_task","destination"}],
 "tasks":    [{"id","pickup","dropoff","priority","status","assigned_to"}],
 "log":      [{"time","message"}],
 "completed_count": int}
```
- vehicle status: idle / delivering / negotiating / failed
- task status: pending / assigned / completed; priority: high / normal / low
- `destination` is null for idle/failed vehicles; `assigned_to` is null for pending tasks
- x, y are rounded to 1 decimal; battery is an integer percent
- the log is the full history unless `log_limit` is given

## Controls (for dashboard buttons)
- `sim.add_task((x1, y1), (x2, y2), "high")` — new delivery, auctioned immediately
- `sim.fail_vehicle("V3", "breakdown")` — modes: `breakdown`, `battery_critical`, `blocked`
- `sim.failures.repair_vehicle("V3")` — bring a failed vehicle back

## Map constants (not part of get_state)
- Grid 300 x 300 (`sim.grid_w`, `sim.grid_h`)
- Intersections: I1 (100, 100), I2 (200, 200), radius 12 — see `sim.intersections.intersections`
- Vehicle speed: 10 units per tick

## Running
```
python run_demo.py --delay 0.5            # live stream, scripted scenario
python run_demo.py --random --out s.jsonl # random fleet, also saved to file
python fleet_sim.py                       # human-readable test output
```
