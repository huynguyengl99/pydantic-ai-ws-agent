"""Print the server's AsyncAPI schema, which the web client is generated from."""

from fastapi.testclient import TestClient

from app.main import app

print(TestClient(app).get("/asyncapi.json").text)
