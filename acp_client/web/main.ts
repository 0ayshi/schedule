import DOMPurify from "dompurify";
import { marked } from "marked";
import * as acp from "@agentclientprotocol/sdk";
import { createWebSocketStream } from "@agentclientprotocol/sdk/experimental/ws-client";

// -----------------------------------------------------------------------------
// STUDENT CONFIGURATION: set this to the ACP agent's WebSocket endpoint.
// Use wss:// when the web client is served over HTTPS.
// -----------------------------------------------------------------------------
const ACP_WEBSOCKET_ENDPOINT = "ws://127.0.0.1:7331/acp";

type TextPart = { type: "text"; text: string };
type ImagePart = { type: "image"; data: string; mimeType: string };
type MessagePart = TextPart | ImagePart;

interface ChatMessage {
  role: "user" | "assistant" | "system";
  parts: MessagePart[];
}

type ThemePreference = "light" | "dark" | "system";

const cancelButton = getElement<HTMLButtonElement>("cancel");
const promptForm = getElement<HTMLFormElement>("prompt-form");
const promptInput = getElement<HTMLTextAreaElement>("prompt");
const sendButton = getElement<HTMLButtonElement>("send");
const messagesElement = getElement<HTMLElement>("messages");
const statusElement = getElement<HTMLElement>("connection-status");
const themeToggle = getElement<HTMLButtonElement>("theme-toggle");
// code updated
const imageInput = getElement<HTMLInputElement>("image-upload");
const imageStatus = getElement<HTMLElement>("image-status");


const themeStorageKey = "acp-chat-theme";
let themePreference = readStoredTheme() ?? "system";

let connection: acp.ClientConnection | null = null;
let sessionId: string | null = null;
let isBusy = false;
let messages: ChatMessage[] = [];
// code updated - connect new html elements
let selectedImage: ImagePart | null = null;

function getElement<T extends Element>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing element #${id}`);
  return element as unknown as T;
}

// code updated
// converts selected img into ACP's base64 img format
async function imageFileToPart(file: File): Promise<ImagePart> {
  const allowedTypes = ["image/png", "image/jpeg", "image/webp"];

  if (!allowedTypes.includes(file.type)) {
    throw new Error("Please select a PNG, JPEG, or WebP image.");
  }

  if (file.size > 5 * 1024 * 1024) {
    throw new Error("The image must be 5 MB or smaller.");
  }

  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();

    reader.onload = () => {
      if (typeof reader.result === "string") {
        resolve(reader.result);
      } else {
        reject(new Error("The image could not be read."));
      }
    };

    reader.onerror = () => reject(new Error("The image could not be read."));
    reader.readAsDataURL(file);
  });

  return {
    type: "image",
    data: dataUrl.split(",", 2)[1],
    mimeType: file.type,
  };
}


function readStoredTheme(): ThemePreference | null {
  try {
    const stored = window.localStorage.getItem(themeStorageKey);
    return stored === "light" || stored === "dark" || stored === "system" ? stored : null;
  } catch {
    return null;
  }
}

function applyTheme(): void {
  const isDark = themePreference === "dark" ||
    (themePreference === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = isDark ? "dark" : "light";
  const label = isDark ? themeToggle.dataset.lightLabel : themeToggle.dataset.darkLabel;
  themeToggle.textContent = label ?? (isDark ? "Light mode" : "Dark mode");
  themeToggle.setAttribute("aria-pressed", String(isDark));
}

function storeTheme(): void {
  try {
    window.localStorage.setItem(themeStorageKey, themePreference);
  } catch {
    // The theme still applies for this page if storage is unavailable.
  }
}

function setStatus(text: string, kind: "idle" | "working" | "ready" | "error"): void {
  statusElement.textContent = text;
  statusElement.className = `status status-${kind}`;
}

function setBusy(value: boolean): void {
  isBusy = value;
  promptInput.disabled = !connection || value;
  imageInput.disabled = !connection || value;   // code updated - img picker follows connection state
  sendButton.disabled = !connection || value;
  cancelButton.disabled = !connection || !value;
}

function addMessage(message: ChatMessage): ChatMessage {
  messages.push(message);
  renderMessages();
  return message;
}

function appendText(message: ChatMessage, text: string): void {
  const lastPart = message.parts.at(-1);
  if (lastPart?.type === "text") {
    lastPart.text += text;
  } else {
    message.parts.push({ type: "text", text });
  }
  renderMessages();
}

function appendImage(message: ChatMessage, data: string, mimeType: string): void {
  message.parts.push({ type: "image", data, mimeType });
  renderMessages();
}

function markdownToHtml(text: string): string {
  const html = marked.parse(text, { async: false }) as string;
  return DOMPurify.sanitize(html);
}

function renderMessages(): void {
  messagesElement.replaceChildren();

  for (const message of messages) {
    const article = document.createElement("article");
    article.className = `message message-${message.role}`;

    const label = document.createElement("div");
    label.className = "message-label";
    label.textContent = message.role === "user" ? "You" : message.role === "assistant" ? "Agent" : "System";
    article.append(label);

    const body = document.createElement("div");
    body.className = "message-body";

    for (const part of message.parts) {
      if (part.type === "text") {
        const text = document.createElement("div");
        if (message.role === "assistant") {
          text.innerHTML = markdownToHtml(part.text);
        } else {
          text.textContent = part.text;
        }
        body.append(text);
      } else {
        const image = document.createElement("img");
        image.className = "assistant-image";
        image.alt = "Image supplied by the ACP agent";
        image.src = `data:${part.mimeType};base64,${part.data}`;
        body.append(image);
      }
    }

    article.append(body);
    messagesElement.append(article);
  }

  messagesElement.scrollTop = messagesElement.scrollHeight;
}

function currentAssistantMessage(): ChatMessage {
  const current = messages.at(-1);
  if (current?.role === "assistant") return current;
  return addMessage({ role: "assistant", parts: [] });
}

// #region streamed-session-update
function handleSessionUpdate(notification: acp.SessionNotification): void {
  if (notification.sessionId !== sessionId) return;

  const update = notification.update;
  switch (update.sessionUpdate) {
    case "agent_message_chunk": {
      if (update.content.type === "text") {
        appendText(currentAssistantMessage(), update.content.text);
      } else if (update.content.type === "image") {
        appendImage(currentAssistantMessage(), update.content.data, update.content.mimeType);
      }
      setStatus("Agent is responding", "working");
      break;
    }
    case "agent_thought_chunk":
      setStatus("Agent is thinking", "working");
      break;
    case "tool_call":
    case "tool_call_update":
      setStatus("Agent is using a tool", "working");
      break;
    default:
      break;
  }
}
// #endregion streamed-session-update

function makeClient(): acp.ClientApp {
  return acp
    .client({ name: "acp-chat-web-client" })
    .onNotification(acp.methods.client.session.update, (context) => {
      handleSessionUpdate(context.params);
    })
    .onRequest(acp.methods.client.session.requestPermission, async (context) => {
      // The demo has no tools requiring approval. If an agent does ask, reject
      // it rather than silently granting an unknown operation.
      const option = context.params.options.find((item) => item.kind.startsWith("reject"));
      if (option) {
        return { outcome: { outcome: "selected", optionId: option.optionId } };
      }
      return { outcome: { outcome: "cancelled" } };
    });
}

// #region connect-and-session
async function connect(): Promise<void> {
  const endpoint = ACP_WEBSOCKET_ENDPOINT.trim();
  if (!endpoint) throw new Error("Set ACP_WEBSOCKET_ENDPOINT in web/main.ts.");

  disconnect();
  setStatus("Connecting", "working");

  // # code updated: const stream = createWebSocketStream(endpoint);
  // changed: tells the browser to request no WebSocket subprotocol, matching the supplied Python bridge.
  const stream = createWebSocketStream(endpoint, { protocols: [] });
  const nextConnection = makeClient().connect(stream);
  connection = nextConnection;
  void nextConnection.closed.then(() => {
    if (connection !== nextConnection) return;
    connection = null;
    sessionId = null;
    setBusy(false);
    setStatus("Disconnected", "idle");
  });

  try {
    await nextConnection.agent.request(acp.methods.agent.initialize, {
      protocolVersion: acp.PROTOCOL_VERSION,
      clientCapabilities: {},
    });
    const session = await nextConnection.agent.request(acp.methods.agent.session.new, {
      cwd: "/",
      mcpServers: [],
    });
    sessionId = session.sessionId;
    setBusy(false);
    setStatus("Ready", "ready");
    promptInput.focus();
  } catch (error) {
    disconnect();
    throw error;
  }
}
// #endregion connect-and-session

function disconnect(): void {
  connection?.close();
  connection = null;
  sessionId = null;
  setBusy(false);
}

// #region send-prompt - code updated
// so can send text+img
async function sendPrompt(
  text: string,
  image: ImagePart | null,
): Promise<void> {
  if (!connection || !sessionId || isBusy) return;

  const parts: MessagePart[] = [];

  if (text) {
    parts.push({ type: "text", text });
  }

  if (image) {
    parts.push(image);
  }

  if (parts.length === 0) return;

  addMessage({ role: "user", parts });
  setBusy(true);
  setStatus("Sending", "working");

  try {
    const result = await connection.agent.request(
      acp.methods.agent.session.prompt,
      {
        sessionId,
        prompt: parts,
      },
    );

    if (
      typeof result === "object" &&
      result !== null &&
      "stopReason" in result &&
      result.stopReason === "cancelled"
    ) {
      addMessage({
        role: "system",
        parts: [{ type: "text", text: "The turn was cancelled." }],
      });
    }

    setStatus("Ready", "ready");
  } catch (error) {
    addMessage({
      role: "system",
      parts: [{ type: "text", text: `ACP error: ${errorMessage(error)}` }],
    });
    setStatus("Error", "error");
  } finally {
    setBusy(false);
  }
}
// #endregion send-prompt

async function cancelPrompt(): Promise<void> {
  if (!connection || !sessionId || !isBusy) return;
  setStatus("Cancelling", "working");
  await connection.agent.notify(acp.methods.agent.session.cancel, { sessionId });
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function reportConnectionError(error: unknown): void {
  setStatus("Connection failed", "error");
  addMessage({ role: "system", parts: [{ type: "text", text: errorMessage(error) }] });
}

themeToggle.addEventListener("click", () => {
  const isDark = document.documentElement.dataset.theme === "dark";
  themePreference = isDark ? "light" : "dark";
  storeTheme();
  applyTheme();
});

const colorScheme = window.matchMedia("(prefers-color-scheme: dark)");
colorScheme.addEventListener("change", () => {
  if (themePreference === "system") applyTheme();
});

cancelButton.addEventListener("click", () => {
  void cancelPrompt();
});

// handle user selcting an img - code updated
imageInput.addEventListener("change", async () => {
  const file = imageInput.files?.[0];
  selectedImage = null;

  if (!file) {
    imageStatus.textContent = "No image selected";
    return;
  }

  try {
    selectedImage = await imageFileToPart(file);
    imageStatus.textContent = `Selected: ${file.name}`;
  } catch (error) {
    imageInput.value = "";
    imageStatus.textContent = errorMessage(error);
  }
});

// code updated - form submission updated to include selected img
promptForm.addEventListener("submit", (event) => {
  event.preventDefault();

  const text = promptInput.value.trim();
  const image = selectedImage;

  if (!text && !image) return;

  promptInput.value = "";
  imageInput.value = "";
  imageStatus.textContent = "No image selected";
  selectedImage = null;

  void sendPrompt(text, image);
});


promptInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    promptForm.requestSubmit();
  }
});

window.addEventListener("beforeunload", disconnect);

applyTheme();
void connect().catch(reportConnectionError);
