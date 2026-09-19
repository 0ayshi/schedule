# ACP Chat Web Client

This is a small browser client for the [Agent Client Protocol](https://agentclientprotocol.com). It connects to an ACP agent over WebSocket and displays streamed assistant messages.

## Run locally

Install the dependencies and start the development server:

```bash
npm install
npm run dev
```

Open <http://127.0.0.1:5173/>. The client connects to `ws://127.0.0.1:7331/acp` by default. Start an ACP server at that address before opening the page.

The marked `ACP_WEBSOCKET_ENDPOINT` constant near the top of `web/main.ts` is the only connection setting. The client implements ACP initialisation, session creation, prompts, streamed text updates and cancellation.
