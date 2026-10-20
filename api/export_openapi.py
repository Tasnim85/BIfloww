"""Write the API description (OpenAPI) to api/openapi.json, for the Next.js app (step 7).

    python -m api.export_openapi
    npx openapi-typescript api/openapi.json -o <next-app>/src/lib/api-types.ts

The TypeScript types are then generated from the SAME Pydantic contracts: if a contract
changes, re-run both commands and the compiler shows every place to update.
"""
import json
from pathlib import Path

from api.main import create_app

OUT = Path(__file__).parent / "openapi.json"

if __name__ == "__main__":
    OUT.write_text(json.dumps(create_app().openapi(), indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"OK {OUT} ({len(create_app().openapi()['paths'])} routes)")
