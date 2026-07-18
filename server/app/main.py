from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from chanx.fast_channels import asyncapi_docs, asyncapi_spec_json, asyncapi_spec_yaml
from chanx.fast_channels.type_defs import AsyncAPIConfig
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute

from app import db
from app.assistant.consumer import RUNNING, AgentConsumer, conversation_group
from app.assistant.harness import PENDING_APPROVALS
from app.assistant.messages import NotificationMessage, NotificationPayload
from app.config import settings
from app.layers import setup_layers

setup_layers()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    await db.init_db()
    yield


app = FastAPI(title="Pydantic AI WS Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

asyncapi_conf = AsyncAPIConfig(
    description="Typed WebSocket contract for the Pydantic AI task assistant",
    version="1.0.0",
)


@app.get("/asyncapi", tags=["Documentation"])
async def asyncapi_documentation(request: Request) -> HTMLResponse:
    return await asyncapi_docs(request=request, app=app, config=asyncapi_conf)


@app.get("/asyncapi.json", tags=["Documentation"])
async def asyncapi_json_spec(request: Request) -> JSONResponse:
    return await asyncapi_spec_json(request=request, app=app, config=asyncapi_conf)


@app.get("/asyncapi.yaml", tags=["Documentation"])
async def asyncapi_yaml_spec(request: Request) -> Response:
    return await asyncapi_spec_yaml(request=request, app=app, config=asyncapi_conf)


@app.get("/conversations", tags=["Conversations"])
async def list_conversations() -> list[db.ConversationItem]:
    return await db.list_conversations()


@app.delete("/conversations/{conversation_id}", tags=["Conversations"])
async def delete_conversation(conversation_id: str) -> dict[str, bool]:
    running = RUNNING.pop(conversation_id, None)
    if running is not None:
        running.cancel()
    PENDING_APPROVALS.pop(conversation_id, None)
    if not await db.delete_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Unknown conversation")
    return {"deleted": True}


class NotifyRequest(BaseModel):
    title: str
    body: str


@app.post("/conversations/{conversation_id}/notify", tags=["Notifications"])
async def notify_conversation(
    conversation_id: str, request: NotifyRequest
) -> dict[str, bool]:
    """Broadcast a notification into a conversation from plain HTTP.

    Demonstrates chanx's broadcast-from-anywhere: any HTTP endpoint, background
    job, or worker can push typed events to WebSocket clients via the channel layer.
    """
    await AgentConsumer.broadcast_event(
        NotificationMessage(
            payload=NotificationPayload(title=request.title, body=request.body)
        ),
        groups=conversation_group(conversation_id),
    )
    return {"delivered": True}


ws_app = Starlette(routes=[WebSocketRoute("/agent", AgentConsumer.as_asgi())])
app.mount("/ws", ws_app)
