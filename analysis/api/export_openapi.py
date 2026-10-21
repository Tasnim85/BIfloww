"""Write the API description (OpenAPI) to analysis/api/openapi.json, for the Next.js app.

    python -m analysis.api.export_openapi
    npx openapi-typescript analysis/api/openapi.json -o <next-app>/src/lib/analyst-types.ts

The TypeScript types then come from the SAME Pydantic contracts as the Python code.
"""
import json
from pathlib import Path

from analysis.api.main import create_app

OUT = Path(__file__).parent / "openapi.json"

if __name__ == "__main__":
    spec = create_app().openapi()
    OUT.write_text(json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"OK {OUT} ({len(spec['paths'])} routes)")
