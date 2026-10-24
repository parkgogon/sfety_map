"""Generate a contact-free local fixture. Never calls a production API."""
import json
from pathlib import Path
import sys
root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[4]
sys.path.insert(0, str(root))
fixture = root / "docs/evidence/2026-10-25/nearby/fixture-server.py"
namespace = {"__file__": str(fixture)}
exec(fixture.read_text().split("class Handler")[0], namespace)
print(json.dumps(namespace["payload"], ensure_ascii=False))
