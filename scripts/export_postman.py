"""Export FastAPI OpenAPI 3.1 schema into a Postman Collection v2.1 JSON file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.api.main import app


def openapi_to_postman(schema: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for path, methods in schema.get("paths", {}).items():
        for method, op in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            raw_url = "{{baseUrl}}" + path
            req: dict[str, Any] = {
                "method": method.upper(),
                "header": [{"key": "Content-Type", "value": "application/json"}],
                "url": {
                    "raw": raw_url,
                    "host": ["{{baseUrl}}"],
                    "path": [seg for seg in path.strip("/").split("/") if seg],
                },
            }
            if method.lower() in {"post", "put", "patch"}:
                req["body"] = {"mode": "raw", "raw": "{}"}

            items.append(
                {
                    "name": op.get("summary") or f"{method.upper()} {path}",
                    "request": req,
                }
            )

    return {
        "info": {
            "name": schema.get("info", {}).get("title", "Mandate API"),
            "description": schema.get("info", {}).get("description", ""),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [{"key": "baseUrl", "value": "http://localhost:8000"}],
        "item": items,
    }


def main() -> None:
    docs_dir = Path(__file__).resolve().parents[1] / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    schema = app.openapi()

    openapi_path = docs_dir / "openapi.json"
    openapi_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    postman_path = docs_dir / "mandate-postman-collection.json"
    collection = openapi_to_postman(schema)
    postman_path.write_text(json.dumps(collection, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote OpenAPI schema ({openapi_path}) and {len(collection['item'])} Postman endpoints ({postman_path})")


if __name__ == "__main__":
    main()
