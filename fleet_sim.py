"""
Self-Healing Decentralized Autonomous Logistics Fleet -- simulation engine.

Pure standard-library, no I/O in the core logic. Everything significant is
appended to Simulation.log; the dashboard only needs Simulation.get_state().

Sections (in build order):
  1. Data structures      : Vehicle, Task, Bid, Intersection
  2. TaskAllocator        : Contract Net Protocol (announce -> bid -> award)
  3. Simulation.tick()    : movement, battery, arrivals
  4. IntersectionManager  : first-come-first-served crossing
  5. FailureHandler       : fail a vehicle, re-auction its tasks
  6. Simulation.get_state(): the dashboard contract
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

Point = Tuple[float, float]

# --------------------------------------------------------------------------
# Tunable constants
# --------------------------------------------------------------------------
DEFAULT_SPEED = 10.0        # grid units a vehicle moves per tick
DRAIN_PER_UNIT = 0.05       # battery % consumed per grid unit travelled
IDLE_RECHARGE = 0.5         # battery % regained per tick while idle (docked)
BATTERY_RESERVE = 10.0      # a bidder must still have >= this % after its trip
BATTERY_CRITICAL = 5.0      # a working vehicle at/below this % is declared failed

W_DIST = 1.0                # bid weight: distance (incl. work already committed)
W_BATTERY = 0.5             # bid weight: battery deficit (100 - battery)
W_LOAD = 40.0               # bid weight: tasks already held (prefers idle vehicles)

PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}


def dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def segment_point_distance(p: Point, a: Point, b: Point) -> float:
    """Shortest distance from point p to the segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    seg_len2 = dx * dx + dy * dy
    if seg_len2 == 0:
        return dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / seg_len2))
    return dist(p, (a[0] + t * dx, a[1] + t * dy))


# --------------------------------------------------------------------------
# 1. Data structures
# --------------------------------------------------------------------------
@dataclass
class Task:
    id: str
    pickup: Point
    dropoff: Point
    priority: str = "normal"            # "high" | "normal" | "low"
    status: str = "pending"             # "pending" | "assigned" | "completed"
    assigned_to: Optional[str] = None
    # internal bookkeeping (not exposed in get_state)
    created_at: float = 0.0
    picked_up: bool = False
    reassigned_from: Optional[str] = None
    no_bidder_logged: bool = False


@dataclass
class Bid:
    vehicle_id: str
    score: float        # lower is better
    distance: float     # committed route + approach to pickup
    battery: int
    workload: int


@dataclass
class Vehicle:
    id: str
    x: float
    y: float
    battery: float = 100.0
    capacity: int = 3                   # max tasks held at once (current + queued)
    status: str = "idle"                # "idle" | "delivering" | "negotiating" | "failed"
    current_task: Optional[str] = None
    destination: Optional[Point] = None
    # internal bookkeeping (not exposed in get_state)
    task_queue: List[str] = field(default_factory=list)
    phase: Optional[str] = None         # "to_pickup" | "to_dropoff"
    failure_reason: Optional[str] = None

    @property
    def pos(self) -> Point:
        return (self.x, self.y)

    @property
    def workload(self) -> int:
        return len(self.task_queue) + (1 if self.current_task else 0)

    def committed_route(self, tasks: Dict[str, Task]) -> Tuple[float, Point]:
        """Total distance of work already accepted, and where it ends."""
        pos, total = self.pos, 0.0
        if self.current_task:
            t = tasks[self.current_task]
            if self.phase == "to_pickup":
                total += dist(pos, t.pickup) + dist(t.pickup, t.dropoff)
            else:
                total += dist(pos, t.dropoff)
            pos = t.dropoff
        for tid in self.task_queue:
            t = tasks[tid]
            total += dist(pos, t.pickup) + dist(t.pickup, t.dropoff)
            pos = t.dropoff
        return total, pos

    def bid_for(self, task: Task, tasks: Dict[str, Task]) -> Optional[Bid]:
        """Contract Net: a vehicle's bid (lower score = better) or None to decline."""
        if self.status == "failed" or self.workload >= self.capacity:
            return None
        committed, end_pos = self.committed_route(tasks)
        approach = dist(end_pos, task.pickup)
        trip = dist(task.pickup, task.dropoff)
        needed = (committed + approach + trip) * DRAIN_PER_UNIT
        if self.battery - needed < BATTERY_RESERVE:
            return None                 # can't finish safely -> decline
        score = (W_DIST * (committed + approach)
                 + W_BATTERY * (100.0 - self.battery)
                 + W_LOAD * self.workload)
        return Bid(self.id, round(score, 2), round(committed + approach, 1),
                   round(self.battery), self.workload)

    def start_next_task(self, tasks: Dict[str, Task]) -> None:
        if self.current_task or not self.task_queue:
            return
        tid = min(self.task_queue,
                  key=lambda i: (PRIORITY_RANK[tasks[i].priority], tasks[i].created_at, i))
        self.task_queue.remove(tid)
        self.current_task = tid
        self.phase = "to_pickup"
        self.destination = tasks[tid].pickup
        self.status = "delivering"


@dataclass
class Intersection:
    id: str
    x: float
    y: float
    radius: float = 12.0

    @property
    def center(self) -> Point:
        return (self.x, self.y)

    def contains(self, x: float, y: float) -> bool:
        return math.hypot(x - self.x, y - self.y) <= self.radius


# --------------------------------------------------------------------------
# 2. Task allocation (Contract Net Protocol)
# --------------------------------------------------------------------------
class TaskAllocator:
    def __init__(self, sim: "Simulation"):
        self.sim = sim

    def collect_bids(self, task: Task) -> List[Bid]:
        bids = [b for v in self.sim.vehicles.values()
                if (b := v.bid_for(task, self.sim.tasks)) is not None]
        return sorted(bids, key=lambda b: (b.score, b.vehicle_id))

    def allocate(self, task: Task) -> Optional[str]:
        """Announce the task, gather bids, award to the best. Returns winner id."""
        bids = self.collect_bids(task)
        if not bids:
            return None
        win = bids[0]
        v = self.sim.vehicles[win.vehicle_id]
        task.status, task.assigned_to = "assigned", v.id
        v.task_queue.append(task.id)
        v.start_next_task(self.sim.tasks)

        detail = (f"best of {len(bids)} bid(s): score {win.score}, {win.distance} units away, "
                  f"battery {win.battery}%, load {win.workload}/{v.capacity}")
        if task.reassigned_from:
            self.sim.log_event(f"Task {task.id} reassigned from {task.reassigned_from} "
                               f"to {v.id} ({detail})")
        else:
            self.sim.log_event(f"Vehicle {v.id} won Task {task.id} ({detail})")
        return v.id

    def allocate_pending(self) -> None:
        pending = [t for t in self.sim.tasks.values() if t.status == "pending"]
        pending.sort(key=lambda t: (PRIORITY_RANK[t.priority], t.created_at, t.id))
        for t in pending:
            if self.allocate(t) is None and not t.no_bidder_logged:
                t.no_bidder_logged = True
                self.sim.log_event(f"Task {t.id} has no eligible bidder; waiting in pool")


# --------------------------------------------------------------------------
# 4. Intersection negotiation (first-come-first-served)
# --------------------------------------------------------------------------
class IntersectionManager:
    def __init__(self, sim: "Simulation", intersections: List[Intersection]):
        self.sim = sim
        self.intersections = intersections
        self.arrivals: Dict[Tuple[str, str], float] = {}   # (vehicle, inter) -> first arrival time
        self.waiting: Dict[Tuple[str, str], float] = {}    # (vehicle, inter) -> wait start

    def resolve(self, requests: List[Tuple[Vehicle, Intersection, float]],
                vehicles: Iterable[Vehicle], now: float) -> Set[str]:
        """Return ids of vehicles that must yield (wait a tick) this tick."""
        yielding: Set[str] = set()
        live: Set[Tuple[str, str]] = set()
        by_inter: Dict[str, List[Tuple[Vehicle, Intersection]]] = {}
        for v, inter, eta in requests:
            key = (v.id, inter.id)
            live.add(key)
            self.arrivals.setdefault(key, eta)          # keep the ORIGINAL timestamp
            by_inter.setdefault(inter.id, []).append((v, inter))

        vehicles = list(vehicles)
        for iid, reqs in by_inter.items():
            inter = reqs[0][1]
            reqs.sort(key=lambda r: (self.arrivals[(r[0].id, iid)], r[0].id))
            occupants = [o for o in vehicles
                         if o.status != "failed" and o.destination is not None
                         and inter.contains(o.x, o.y)]
            winner = None if occupants else reqs[0][0].id
            for v, _ in reqs:
                key = (v.id, iid)
                if v.id == winner:
                    if key in self.waiting:
                        self.sim.log_event(f"Vehicle {v.id} cleared to enter {iid} after waiting "
                                           f"{now - self.waiting.pop(key):.1f} time unit(s)")
                    continue
                yielding.add(v.id)
                if key not in self.waiting:
                    self.waiting[key] = now
                    if occupants:
                        why = f"intersection occupied by {occupants[0].id}"
                    else:
                        why = (f"{winner} arrived first, t={self.arrivals[(winner, iid)]:.1f} "
                               f"vs t={self.arrivals[key]:.1f}")
                    self.sim.log_event(f"Vehicle {v.id} yielded at {iid} ({why})")

        for key in list(self.arrivals):                  # drop stale requests
            if key not in live:
                self.arrivals.pop(key, None)
                self.waiting.pop(key, None)
        return yielding

    def forget(self, vehicle_id: str) -> None:
        for d in (self.arrivals, self.waiting):
            for key in [k for k in d if k[0] == vehicle_id]:
                del d[key]


# --------------------------------------------------------------------------
# 5. Failure & self-healing
# --------------------------------------------------------------------------
class FailureHandler:
    REASONS = {
        "breakdown": "mechanical breakdown",
        "battery_critical": "battery critical",
        "blocked": "path blocked",
    }

    def __init__(self, sim: "Simulation"):
        self.sim = sim

    def fail_vehicle(self, vehicle_id: str, mode: str = "breakdown") -> bool:
        """Fail a vehicle and re-auction everything it was holding."""
        sim = self.sim
        v = sim.vehicles[vehicle_id]
        if v.status == "failed":
            return False
        if mode not in self.REASONS:
            raise ValueError(f"mode must be one of {sorted(self.REASONS)}")
        if mode == "battery_critical":
            v.battery = min(v.battery, 2.0)
        v.status, v.failure_reason = "failed", self.REASONS[mode]
        sim.log_event(f"Vehicle {v.id} failed ({v.failure_reason})")

        orphaned = ([v.current_task] if v.current_task else []) + list(v.task_queue)
        v.current_task, v.destination, v.phase, v.task_queue = None, None, None, []
        sim.intersections.forget(v.id)

        released: List[Task] = []
        for tid in orphaned:
            t = sim.tasks[tid]
            if t.picked_up:                              # cargo is stranded where v stopped
                t.pickup = (round(v.x, 1), round(v.y, 1))
                t.picked_up = False
                sim.log_event(f"Task {tid} cargo stranded at ({t.pickup[0]}, {t.pickup[1]}); "
                              f"new pickup point set")
            t.status, t.assigned_to, t.reassigned_from = "pending", None, v.id
            t.no_bidder_logged = False
            released.append(t)

        released.sort(key=lambda t: (PRIORITY_RANK[t.priority], t.created_at, t.id))
        for t in released:
            if sim.allocator.allocate(t) is None:
                t.no_bidder_logged = True
                sim.log_event(f"Task {t.id} has no eligible bidder after {v.id} failed; "
                              f"waiting in pool")
        return True

    def check_battery(self, v: Vehicle) -> None:
        if v.status != "failed" and v.current_task and v.battery <= BATTERY_CRITICAL:
            self.fail_vehicle(v.id, "battery_critical")

    def repair_vehicle(self, vehicle_id: str, battery: float = 100.0) -> None:
        v = self.sim.vehicles[vehicle_id]
        if v.status == "failed":
            v.status, v.failure_reason, v.battery = "idle", None, battery
            self.sim.log_event(f"Vehicle {v.id} repaired and back in service")


# --------------------------------------------------------------------------
# 3 + 6. Simulation (ties everything together; get_state() is the dashboard API)
# --------------------------------------------------------------------------
class Simulation:
    def __init__(self, num_vehicles: int = 6, grid_size: Tuple[int, int] = (300, 300),
                 seed: Optional[int] = None, task_spawn_prob: float = 0.0,
                 speed: float = DEFAULT_SPEED, dt: float = 1.0,
                 intersections: Optional[List[Intersection]] = None):
        self.rng = random.Random(seed)
        self.grid_w, self.grid_h = grid_size
        self.speed, self.dt = speed, dt
        self.task_spawn_prob = task_spawn_prob
        self.time = 0.0
        self.completed_count = 0
        self.vehicles: Dict[str, Vehicle] = {}
        self.tasks: Dict[str, Task] = {}
        self.log: List[dict] = []
        self._task_counter = 0

        self.allocator = TaskAllocator(self)
        self.failures = FailureHandler(self)
        self.intersections = IntersectionManager(
            self, intersections or [Intersection("I1", self.grid_w / 3, self.grid_h / 3),
                                    Intersection("I2", 2 * self.grid_w / 3, 2 * self.grid_h / 3)])

        for _ in range(num_vehicles):
            self.add_vehicle(x=self.rng.uniform(0, self.grid_w), y=self.rng.uniform(0, self.grid_h),
                             battery=self.rng.uniform(70, 100), capacity=self.rng.choice([2, 3, 4]))

    # ---- setup helpers ---------------------------------------------------
    def log_event(self, message: str) -> None:
        self.log.append({"time": round(self.time, 1), "message": message})

    def add_vehicle(self, x: float, y: float, battery: float = 100.0, capacity: int = 3,
                    vehicle_id: Optional[str] = None) -> Vehicle:
        vid = vehicle_id or f"V{len(self.vehicles) + 1}"
        v = Vehicle(vid, float(x), float(y), float(battery), capacity)
        self.vehicles[vid] = v
        return v

    def add_task(self, pickup: Point, dropoff: Point, priority: str = "normal") -> Task:
        if priority not in PRIORITY_RANK:
            raise ValueError("priority must be 'high', 'normal' or 'low'")
        self._task_counter += 1
        t = Task(f"T{self._task_counter}", tuple(pickup), tuple(dropoff), priority,
                 created_at=self.time)
        self.tasks[t.id] = t
        self.log_event(f"Task {t.id} created ({priority} priority)")
        if self.allocator.allocate(t) is None:
            t.no_bidder_logged = True
            self.log_event(f"Task {t.id} has no eligible bidder; waiting in pool")
        return t

    def spawn_random_task(self) -> Task:
        pt = lambda: (round(self.rng.uniform(0, self.grid_w)), round(self.rng.uniform(0, self.grid_h)))
        prio = self.rng.choices(["high", "normal", "low"], weights=[2, 5, 3])[0]
        return self.add_task(pt(), pt(), prio)

    def fail_vehicle(self, vehicle_id: str, mode: str = "breakdown") -> bool:
        return self.failures.fail_vehicle(vehicle_id, mode)

    # ---- the tick --------------------------------------------------------
    def tick(self) -> dict:
        self.time += self.dt
        if self.task_spawn_prob and self.rng.random() < self.task_spawn_prob:
            self.spawn_random_task()
        self.allocator.allocate_pending()

        # plan moves + collect intersection requests
        plans: Dict[str, Point] = {}
        requests: List[Tuple[Vehicle, Intersection, float]] = []
        for v in self.vehicles.values():
            if v.status == "failed" or v.destination is None:
                continue
            nxt = self._next_position(v)
            plans[v.id] = nxt
            for inter in self.intersections.intersections:
                if inter.contains(v.x, v.y):
                    continue                              # already inside: no request needed
                if segment_point_distance(inter.center, v.pos, nxt) <= inter.radius:
                    edge = max(0.0, dist(v.pos, inter.center) - inter.radius)
                    eta = (self.time - self.dt) + (edge / self.speed) * self.dt
                    requests.append((v, inter, eta))

        yielding = self.intersections.resolve(requests, self.vehicles.values(), self.time)

        # apply moves
        for vid, nxt in plans.items():
            v = self.vehicles[vid]
            if vid in yielding:
                v.status = "negotiating"
                continue
            v.battery = max(0.0, v.battery - dist(v.pos, nxt) * DRAIN_PER_UNIT)
            v.x, v.y = nxt
            v.status = "delivering"
            self._handle_arrivals(v)

        for v in self.vehicles.values():
            if v.status == "idle":
                v.battery = min(100.0, v.battery + IDLE_RECHARGE)
        for v in list(self.vehicles.values()):
            self.failures.check_battery(v)
        return self.get_state()

    def _next_position(self, v: Vehicle) -> Point:
        d = dist(v.pos, v.destination)
        if d <= self.speed:
            return v.destination
        f = self.speed / d
        return (v.x + (v.destination[0] - v.x) * f, v.y + (v.destination[1] - v.y) * f)

    def _handle_arrivals(self, v: Vehicle) -> None:
        for _ in range(3):                               # pickup + dropoff may coincide
            if v.destination is None or dist(v.pos, v.destination) > 1e-6:
                return
            t = self.tasks[v.current_task]
            if v.phase == "to_pickup":
                t.picked_up, v.phase, v.destination = True, "to_dropoff", t.dropoff
                self.log_event(f"Vehicle {v.id} picked up Task {t.id}")
            else:
                t.status, t.picked_up = "completed", False
                self.completed_count += 1
                self.log_event(f"Vehicle {v.id} completed Task {t.id}")
                v.current_task, v.phase, v.destination = None, None, None
                v.start_next_task(self.tasks)
                if v.current_task is None:
                    v.status = "idle"
                    return

    # ---- dashboard contract ---------------------------------------------
    def get_state(self, log_limit: Optional[int] = None) -> dict:
        """Full snapshot in the agreed shape. Returns fresh copies (safe to serialize/mutate)."""
        log = self.log if log_limit is None else self.log[-log_limit:]
        return {
            "vehicles": [
                {"id": v.id, "x": round(v.x, 1), "y": round(v.y, 1),
                 "battery": round(v.battery), "capacity": v.capacity,
                 "status": v.status, "current_task": v.current_task,
                 "destination": list(v.destination) if v.destination else None}
                for v in self.vehicles.values()],
            "tasks": [
                {"id": t.id, "pickup": list(t.pickup), "dropoff": list(t.dropoff),
                 "priority": t.priority, "status": t.status, "assigned_to": t.assigned_to}
                for t in self.tasks.values()],
            "log": [dict(e) for e in log],
            "completed_count": self.completed_count,
        }


# --------------------------------------------------------------------------
# Standalone test:  python fleet_sim.py [--json] [--ticks N]
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    full_json = "--json" in sys.argv
    n_ticks = int(sys.argv[sys.argv.index("--ticks") + 1]) if "--ticks" in sys.argv else 45

    sim = Simulation(num_vehicles=0, seed=42)            # hand-placed scenario
    for x, y, b in [(20, 100, 90), (100, 14, 95), (260, 250, 88),
                    (230, 280, 80), (40, 220, 75), (150, 60, 99)]:
        sim.add_vehicle(x, y, b, capacity=3)

    sim.add_task((30, 100), (180, 100), "normal")        # V1 crosses I1 heading east
    sim.add_task((100, 24), (100, 180), "high")          # V2 crosses I1 heading north
    sim.add_task((250, 250), (150, 250), "normal")       # V3 -- will fail mid-delivery

    seen_log = 0
    for step in range(1, n_ticks + 1):
        if step == 4:
            sim.fail_vehicle("V3", "breakdown")          # self-healing demo
        if step == 6:
            sim.add_task((60, 200), (240, 60), "high")   # late high-priority arrival
        state = sim.tick()

        if full_json:
            print(json.dumps(state))
        else:
            print(f"--- t={sim.time:.1f}  completed={state['completed_count']}")
            for v in state["vehicles"]:
                print(f"  {v['id']}: ({v['x']:6.1f},{v['y']:6.1f}) bat={v['battery']:3d}% "
                      f"{v['status']:<11} task={v['current_task']} dest={v['destination']}")
            for e in state["log"][seen_log:]:
                print(f"  [log {e['time']:>5}] {e['message']}")
        seen_log = len(state["log"])
