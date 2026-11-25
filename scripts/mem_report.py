"""Per-process memory inside the container (RSS and PSS = shared pages split fairly)."""
from pathlib import Path

total = 0
for p in sorted(Path("/proc").glob("[0-9]*"), key=lambda x: int(x.name)):
    try:
        cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode()[:80]
        roll = (p / "smaps_rollup").read_text()
    except OSError:
        continue
    vals = {line.split(":")[0]: int(line.split()[1]) for line in roll.splitlines() if line.startswith(("Rss:", "Pss:"))}
    if cmd:
        total += vals.get("Pss", 0)
        print(f"{p.name:>6} RSS {vals.get('Rss', 0) / 1024:7.0f} MB  PSS {vals.get('Pss', 0) / 1024:7.0f} MB  {cmd}")
print(f"total PSS {total / 1024:.0f} MB")
