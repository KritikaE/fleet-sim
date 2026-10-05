"""
Streams the fleet simulation as JSON, one full get_state() per line (JSON Lines).

  python run_demo.py                        # 60 ticks to stdout, no delay
  python run_demo.py --out states.jsonl     # also save to a file
  python run_demo.py --delay 0.5            # live pacing, 0.5 s per tick
  python run_demo.py --random               # random fleet + random tasks instead of the scripted scenario
"""
import argparse
import json
import sys
import time

from fleet_sim import Simulation


def scripted_demo() -> Simulation:
    """Shows all three headline behaviours: auction, intersection yield, self-healing."""
    sim = Simulation(num_vehicles=0, seed=42)
    for x, y, b in [(20, 100, 90), (100, 14, 95), (260, 250, 88),
                    (230, 280, 80), (40, 220, 75), (150, 60, 99)]:
        sim.add_vehicle(x, y, b, capacity=3)
    sim.add_task((30, 100), (180, 100), "normal")   # V1 crosses I1 heading east
    sim.add_task((100, 24), (100, 180), "high")     # V2 crosses I1 heading north -> yields
    sim.add_task((250, 250), (150, 250), "normal")  # V3 fails mid-delivery -> reassigned
    return sim


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticks", type=int, default=60)
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between ticks")
    ap.add_argument("--out", help="also write each state as a line to this file")
    ap.add_argument("--random", action="store_true")
    args = ap.parse_args()

    sim = Simulation(num_vehicles=6, seed=1, task_spawn_prob=0.15) if args.random else scripted_demo()
    out = open(args.out, "w") if args.out else None
    try:
        for step in range(1, args.ticks + 1):
            if not args.random:
                if step == 4:
                    sim.fail_vehicle("V3", "breakdown")
                if step == 6:
                    sim.add_task((60, 200), (240, 60), "high")
            line = json.dumps(sim.tick())
            print(line, flush=True)
            if out:
                out.write(line + "\n")
            if args.delay:
                time.sleep(args.delay)
    finally:
        if out:
            out.close()


if __name__ == "__main__":
    main()
