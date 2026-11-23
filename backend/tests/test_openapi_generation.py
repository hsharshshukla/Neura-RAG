from __future__ import annotations

from app.main import app


def _resolve_ref(schema: dict, ref: str) -> dict:
    assert ref.startswith("#/components/schemas/")
    name = ref.rsplit("/", 1)[-1]
    return schema["components"]["schemas"][name]


def test_complete_app_openapi_generation_and_upload_file_schema() -> None:
    schema = app.openapi()

    assert "/api/v1/chat/stream" in schema["paths"]

    upload_operation = schema["paths"]["/api/v1/upload"]["post"]
    request_body_schema = upload_operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    if "$ref" in request_body_schema:
        request_body_schema = _resolve_ref(schema, request_body_schema["$ref"])

    file_schema = request_body_schema["properties"]["file"]
    if "$ref" in file_schema:
        file_schema = _resolve_ref(schema, file_schema["$ref"])

    assert file_schema.get("type") == "string"
    assert file_schema.get("format") == "binary"
