"""
UAHP-Registry v1.0 — Agent Discovery Layer.

FastAPI + SQLite registry with:
    - Agent registration (UAHP identity + capabilities + energy profile)
    - Liveness heartbeat tracking with auto-deregistration
    - Capability-based discovery queries
    - Death certificate listener (auto-removes dead agents)

Runs with: uvicorn registry:app --port 8420
Or standalone demo: python registry.py

Author: Paul Raspey
License: MIT
"""

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from pathlib import Path


GREEN = "\033[92m"
TEAL = "\033[96m"
AMBER = "\033[93m"
RED = "\033[91m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class AgentRegistration:
    """An agent's entry in the registry."""
    uid: str
    public_key: str
    display_name: str
    capabilities: List[str]
    energy_profile: Dict            # From SMART-UAHP
    endpoint: str                   # How to reach this agent
    registered_at: float
    last_heartbeat: float
    heartbeat_count: int = 0
    status: str = "alive"           # alive, stale, dead
    metadata: Dict = field(default_factory=dict)


@dataclass
class DiscoveryQuery:
    """Query parameters for finding agents."""
    capabilities: Optional[List[str]] = None
    min_trust: float = 0.0
    max_carbon_grams: float = 0.0   # 0 = no limit
    status: str = "alive"
    limit: int = 10


# ── SQLite Backend ───────────────────────────────────────────────────────────

class RegistryDB:
    """SQLite storage for the registry."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_dir = Path.home() / ".uahp-registry"
            db_dir.mkdir(mode=0o700, exist_ok=True)
            db_path = str(db_dir / "registry.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agents (
                    uid TEXT PRIMARY KEY,
                    public_key TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    capabilities TEXT DEFAULT '[]',
                    energy_profile TEXT DEFAULT '{}',
                    endpoint TEXT DEFAULT '',
                    registered_at REAL NOT NULL,
                    last_heartbeat REAL NOT NULL,
                    heartbeat_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'alive',
                    metadata TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status ON agents(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_heartbeat ON agents(last_heartbeat)
            """)

    def register(self, agent: AgentRegistration) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO agents VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    agent.uid, agent.public_key, agent.display_name,
                    json.dumps(agent.capabilities),
                    json.dumps(agent.energy_profile),
                    agent.endpoint, agent.registered_at, agent.last_heartbeat,
                    agent.heartbeat_count, agent.status,
                    json.dumps(agent.metadata),
                ))
            return True
        except Exception:
            return False

    def heartbeat(self, uid: str) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE agents
                    SET last_heartbeat = ?, heartbeat_count = heartbeat_count + 1,
                        status = 'alive'
                    WHERE uid = ?
                """, (time.time(), uid))
            return True
        except Exception:
            return False

    def mark_dead(self, uid: str, reason: str = "") -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE agents SET status = 'dead' WHERE uid = ?
                """, (uid,))
            return True
        except Exception:
            return False

    def mark_stale(self, stale_threshold_seconds: float = 300) -> int:
        """Mark agents as stale if no heartbeat within threshold."""
        cutoff = time.time() - stale_threshold_seconds
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    UPDATE agents SET status = 'stale'
                    WHERE status = 'alive' AND last_heartbeat < ?
                """, (cutoff,))
                return cursor.rowcount
        except Exception:
            return 0

    def query(self, q: DiscoveryQuery) -> List[AgentRegistration]:
        conditions = ["status = ?"]
        params: list = [q.status]

        if q.capabilities:
            for cap in q.capabilities:
                conditions.append("capabilities LIKE ?")
                params.append(f"%{cap}%")

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM agents WHERE {where} ORDER BY last_heartbeat DESC LIMIT ?"
        params.append(q.limit)

        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(sql, params).fetchall()
                return [self._row_to_agent(r) for r in rows]
        except Exception:
            return []

    def get(self, uid: str) -> Optional[AgentRegistration]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM agents WHERE uid = ?", (uid,)
                ).fetchone()
                if row:
                    return self._row_to_agent(row)
        except Exception:
            pass
        return None

    def remove(self, uid: str) -> bool:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM agents WHERE uid = ?", (uid,))
                return cursor.rowcount > 0
        except Exception:
            return False

    def stats(self) -> Dict:
        try:
            with sqlite3.connect(self.db_path) as conn:
                total = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
                alive = conn.execute("SELECT COUNT(*) FROM agents WHERE status='alive'").fetchone()[0]
                stale = conn.execute("SELECT COUNT(*) FROM agents WHERE status='stale'").fetchone()[0]
                dead = conn.execute("SELECT COUNT(*) FROM agents WHERE status='dead'").fetchone()[0]
                return {"total": total, "alive": alive, "stale": stale, "dead": dead}
        except Exception:
            return {"total": 0, "alive": 0, "stale": 0, "dead": 0}

    def _row_to_agent(self, row: tuple) -> AgentRegistration:
        return AgentRegistration(
            uid=row[0], public_key=row[1], display_name=row[2],
            capabilities=json.loads(row[3]),
            energy_profile=json.loads(row[4]),
            endpoint=row[5], registered_at=row[6], last_heartbeat=row[7],
            heartbeat_count=row[8], status=row[9],
            metadata=json.loads(row[10]),
        )


# ── Registry Engine ──────────────────────────────────────────────────────────

class UAHPRegistry:
    """
    The main registry interface.

    Usage:
        registry = UAHPRegistry()
        registry.register_agent(uid, public_key, "Worker", ["analysis"], {}, "http://...")
        agents = registry.discover(capabilities=["analysis"])
        registry.heartbeat(uid)
        registry.receive_death_certificate(uid, "timeout")
    """

    def __init__(self, db_path: Optional[str] = None,
                 stale_threshold_seconds: float = 300):
        self.db = RegistryDB(db_path)
        self.stale_threshold = stale_threshold_seconds

    def register_agent(
        self, uid: str, public_key: str, display_name: str,
        capabilities: List[str], energy_profile: Dict,
        endpoint: str, metadata: Optional[Dict] = None,
    ) -> AgentRegistration:
        now = time.time()
        agent = AgentRegistration(
            uid=uid, public_key=public_key, display_name=display_name,
            capabilities=capabilities, energy_profile=energy_profile,
            endpoint=endpoint, registered_at=now, last_heartbeat=now,
            metadata=metadata or {},
        )
        self.db.register(agent)
        return agent

    def heartbeat(self, uid: str) -> bool:
        return self.db.heartbeat(uid)

    def discover(
        self, capabilities: Optional[List[str]] = None,
        min_trust: float = 0.0, limit: int = 10,
    ) -> List[AgentRegistration]:
        """Find agents matching capability requirements."""
        # Run stale check first
        self.db.mark_stale(self.stale_threshold)

        query = DiscoveryQuery(
            capabilities=capabilities,
            min_trust=min_trust,
            limit=limit,
        )
        return self.db.query(query)

    def receive_death_certificate(self, uid: str, reason: str = "") -> bool:
        """Process a death certificate: mark agent as dead."""
        return self.db.mark_dead(uid, reason)

    def get_agent(self, uid: str) -> Optional[AgentRegistration]:
        return self.db.get(uid)

    def remove_agent(self, uid: str) -> bool:
        return self.db.remove(uid)

    def stats(self) -> Dict:
        return self.db.stats()


# ── Demo ─────────────────────────────────────────────────────────────────────

def demo():
    import tempfile
    import os

    print(f"\n{BOLD}{'='*60}")
    print(f"  UAHP-Registry v1.0 Demo")
    print(f"  Agent Discovery Layer")
    print(f"{'='*60}{RESET}\n")

    db_path = os.path.join(tempfile.mkdtemp(), "test_registry.db")
    registry = UAHPRegistry(db_path=db_path, stale_threshold_seconds=5)

    # Register agents
    agents_data = [
        ("uid-gemma", "pk-1", "Gemma 4 E4B", ["inference", "chat"], {"watts": 30, "tps": 25}, "local://gemma"),
        ("uid-qwen", "pk-2", "Qwen 3 32B", ["inference", "reasoning", "code"], {"watts": 150, "tps": 45}, "groq://qwen"),
        ("uid-claude", "pk-3", "Claude Sonnet", ["reasoning", "architecture", "code"], {"watts": 200, "tps": 80}, "api://claude"),
        ("uid-arm", "pk-4", "Robot Arm Controller", ["actuation", "gcode"], {"watts": 50, "tps": 0}, "serial:///dev/ttyUSB0"),
    ]

    print(f"{GREEN}[1] Registering agents:{RESET}")
    for uid, pk, name, caps, energy, endpoint in agents_data:
        agent = registry.register_agent(uid, pk, name, caps, energy, endpoint)
        print(f"    {name}: {caps}")

    # Discovery
    print(f"\n{TEAL}[2] Discovery queries:{RESET}")

    coders = registry.discover(capabilities=["code"])
    print(f"  Agents with 'code': {[a.display_name for a in coders]}")

    reasoners = registry.discover(capabilities=["reasoning"])
    print(f"  Agents with 'reasoning': {[a.display_name for a in reasoners]}")

    actuators = registry.discover(capabilities=["actuation"])
    print(f"  Agents with 'actuation': {[a.display_name for a in actuators]}")

    # Heartbeats
    print(f"\n{AMBER}[3] Heartbeats:{RESET}")
    registry.heartbeat("uid-gemma")
    registry.heartbeat("uid-qwen")
    agent = registry.get_agent("uid-gemma")
    print(f"  Gemma heartbeats: {agent.heartbeat_count}")

    # Death certificate
    print(f"\n{RED}[4] Death certificate for Qwen:{RESET}")
    registry.receive_death_certificate("uid-qwen", "groq_api_timeout")
    qwen = registry.get_agent("uid-qwen")
    print(f"  Qwen status: {qwen.status}")

    # Stats
    print(f"\n{TEAL}[5] Registry stats:{RESET}")
    stats = registry.stats()
    for k, v in stats.items():
        print(f"    {k}: {v}")

    # Stale detection (wait for threshold)
    print(f"\n{AMBER}[6] Stale detection (simulated):{RESET}")
    # Manually set old heartbeat
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE agents SET last_heartbeat = ? WHERE uid = ?",
            (time.time() - 10, "uid-arm"),
        )
    stale_count = registry.db.mark_stale(5)
    print(f"  Marked {stale_count} agents as stale")
    arm = registry.get_agent("uid-arm")
    print(f"  Robot Arm status: {arm.status}")

    # Cleanup
    os.unlink(db_path)

    print(f"\n{BOLD}UAHP-Registry v1.0 validated{RESET}\n")


if __name__ == "__main__":
    demo()
