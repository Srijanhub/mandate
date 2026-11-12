"""Export FastAPI OpenAPI 3.1 schema into a Postman Collection v2.1 JSON file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.api.main import app

_FIELD_EXAMPLES: dict[str, Any] = {
    "text": "/mandate Buy a scented candle under $45, verified sellers only",
    "prompt": "Buy a birthday candle under $45 from a verified seller",
    "mandate_id": "mnd_sample_001",
    "case_id": "case_sample_001",
    "product_id": "prod-gift-02",
    "url": "https://merchant.example.com/products/candle",
    "query": "scented candle",
    "task_slug": "mandate-recheck/sweep",
    "reason": "Demo purchase aligned with active mandate constraints",
    "rationale": "Meets spending limit and seller verification policy",
    "actor": "user-1",
    "owner_id": "user-1",
    "currency": "USD",
    "new_amount": "55.00",
    "max_total_amount": "60.00",
    "recipient_email": "teammate@example.com",
    "subject": "Weekly Mandate Digest",
    "body": "Summary of approved purchases.",
    "phone_number": "+14155550199",
    "challenge_id": "otp_sample_001",
    "code": "123456",
    "demo_email": "vinay@example.com",
    "demo_name": "Vinay Khandia",
    "display_name": "Vinay Khandia",
}


def _resolve_ref(ref: str, components: dict[str, Any]) -> dict[str, Any]:
    prefix = "#/components/schemas/"
    if ref.startswith(prefix):
        name = ref[len(prefix) :]
        target = components.get(name)
        if isinstance(target, dict):
            return target
    return {}


def _example_from_schema(
    node: Any,
    components: dict[str, Any],
    *,
    field_name: str = "",
    seen_refs: frozenset[str] = frozenset(),
) -> Any:
    if not isinstance(node, dict):
        return {}

    if "$ref" in node:
        ref = str(node["$ref"])
        if ref in seen_refs:
            return {}
        return _example_from_schema(
            _resolve_ref(ref, components),
            components,
            field_name=field_name,
            seen_refs=seen_refs | {ref},
        )

    if "allOf" in node and isinstance(node["allOf"], list):
        merged: dict[str, Any] = {}
        for sub in node["allOf"]:
            val = _example_from_schema(sub, components, field_name=field_name, seen_refs=seen_refs)
            if isinstance(val, dict):
                merged.update(val)
        return merged

    if "anyOf" in node and isinstance(node["anyOf"], list):
        non_null = [s for s in node["anyOf"] if not (isinstance(s, dict) and s.get("type") == "null")]
        chosen = non_null[0] if non_null else (node["anyOf"][0] if node["anyOf"] else {})
        return _example_from_schema(chosen, components, field_name=field_name, seen_refs=seen_refs)

    if "example" in node:
        return node["example"]
    if "default" in node and node["default"] is not None:
        return node["default"]
    if "enum" in node and isinstance(node["enum"], list) and node["enum"]:
        return node["enum"][0]

    schema_type = node.get("type")
    if schema_type == "object" or "properties" in node:
        props = node.get("properties")
        if not isinstance(props, dict) or not props:
            return _FIELD_EXAMPLES.get(field_name, {})
        obj: dict[str, Any] = {}
        for prop_name, prop_schema in props.items():
            obj[prop_name] = _example_from_schema(
                prop_schema, components, field_name=prop_name, seen_refs=seen_refs
            )
        return obj

    if schema_type == "array":
        item_schema = node.get("items") or {}
        if field_name == "input_args":
            return ["case_sample_001"]
        return [
            _example_from_schema(item_schema, components, field_name=field_name, seen_refs=seen_refs)
        ]

    if schema_type == "boolean":
        return True
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 10.0

    if field_name in _FIELD_EXAMPLES:
        return _FIELD_EXAMPLES[field_name]
    fmt = node.get("format")
    if fmt == "date-time":
        return "2026-11-12T12:00:00Z"
    if fmt == "email":
        return "user@example.com"
    if fmt == "uri":
        return "https://example.com"
    return "sample"


def _extract_request_body_example(op: dict[str, Any], components: dict[str, Any]) -> Any | None:
    req_body = op.get("requestBody")
    if not isinstance(req_body, dict):
        return None
    content = req_body.get("content")
    if not isinstance(content, dict):
        return None
    app_json = content.get("application/json")
    if not isinstance(app_json, dict):
        return None
    if "example" in app_json:
        return app_json["example"]
    schema = app_json.get("schema")
    if not isinstance(schema, dict):
        return {}
    return _example_from_schema(schema, components)


def openapi_to_postman(schema: dict[str, Any]) -> dict[str, Any]:
    components = (schema.get("components") or {}).get("schemas") or {}
    items: list[dict[str, Any]] = []

    for path, methods in schema.get("paths", {}).items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not isinstance(op, dict):
                continue

            postman_path = path
            path_vars: list[dict[str, str]] = []
            query_params: list[dict[str, Any]] = []
            for param in op.get("parameters") or []:
                if not isinstance(param, dict):
                    continue
                pname = str(param.get("name") or "")
                pin = param.get("in")
                example_val = _example_from_schema(
                    param.get("schema") or {}, components, field_name=pname
                )
                val_str = str(example_val).lower() if isinstance(example_val, bool) else str(example_val)
                if pin == "path" and pname:
                    postman_path = postman_path.replace("{" + pname + "}", ":" + pname)
                    path_vars.append({"key": pname, "value": val_str})
                elif pin == "query" and pname:
                    query_params.append(
                        {
                            "key": pname,
                            "value": val_str,
                            "disabled": not bool(param.get("required", False)),
                        }
                    )

            url_obj: dict[str, Any] = {
                "raw": "{{baseUrl}}" + postman_path,
                "host": ["{{baseUrl}}"],
                "path": [seg for seg in postman_path.strip("/").split("/") if seg],
            }
            if query_params:
                url_obj["query"] = query_params
            if path_vars:
                url_obj["variable"] = path_vars

            req: dict[str, Any] = {
                "method": method.upper(),
                "header": [
                    {"key": "Content-Type", "value": "application/json"},
                    {
                        "key": "x-api-key",
                        "value": "{{apiToken}}",
                        "disabled": True,
                        "description": "Alternative auth header (collection uses Bearer {{apiToken}} by default).",
                    },
                ],
                "url": url_obj,
            }

            if method.lower() in {"post", "put", "patch"}:
                example_body = _extract_request_body_example(op, components)
                if example_body is not None:
                    req["body"] = {
                        "mode": "raw",
                        "raw": json.dumps(example_body, indent=2),
                        "options": {"raw": {"language": "json"}},
                    }

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
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{apiToken}}", "type": "string"}],
        },
        "variable": [
            {"key": "baseUrl", "value": "http://localhost:8000", "type": "string"},
            {"key": "apiToken", "value": "dev-user-token-change-me", "type": "string"},
        ],
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
    print(
        f"Wrote OpenAPI schema ({openapi_path}) and "
        f"{len(collection['item'])} Postman endpoints ({postman_path})"
    )


if __name__ == "__main__":
    main()
