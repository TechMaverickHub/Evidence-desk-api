# Testing WebSockets

You can use the same `TestClient` to test WebSockets.

For this, you use the `TestClient` in a `with` statement, connecting to the WebSocket:

```Python hl_lines="27-31"
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket

app = FastAPI()


@app.get("/")
async def read_main():
    return {"msg": "Hello World"}


@app.websocket("/ws")
async def websocket(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"msg": "Hello WebSocket"})
    await websocket.close()


def test_read_main():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"msg": "Hello World"}


def test_websocket():
    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        data = websocket.receive_json()
        assert data == {"msg": "Hello WebSocket"}
```

/// note

For more details, check Starlette's documentation for <a href="https://www.starlette.io/testclient/#testing-websocket-sessions" class="external-link" target="_blank">testing WebSockets</a>.

///
