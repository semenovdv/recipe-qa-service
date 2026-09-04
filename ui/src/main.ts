import "./style.css";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");

type Citation = { title: string; url: string };
type AskResponse = {
  answer: string;
  citations: Citation[];
  refused: boolean;
  refusal_reason: "out_of_corpus" | "out_of_domain" | "safety" | null;
  trace: TraceStep[];
};
type TraceStep = { key: string; label: string; status: "pending" | "running" | "complete" | "skipped" | "failed"; duration_ms: number | null; detail: string };

const form = document.querySelector<HTMLFormElement>("#ask-form")!;
const questionInput = document.querySelector<HTMLTextAreaElement>("#question")!;
const submitButton = document.querySelector<HTMLButtonElement>("#submit-button")!;
const status = document.querySelector<HTMLElement>("#status")!;
const result = document.querySelector<HTMLElement>("#result")!;
const welcome = document.querySelector<HTMLElement>("#welcome")!;
const userMessage = document.querySelector<HTMLElement>("#user-message")!;
const userQuestion = document.querySelector<HTMLElement>("#user-question")!;
const answer = document.querySelector<HTMLElement>("#answer")!;
const refusal = document.querySelector<HTMLElement>("#refusal")!;
const citations = document.querySelector<HTMLElement>("#citations")!;
const citationList = document.querySelector<HTMLUListElement>("#citation-list")!;
const traceEmpty = document.querySelector<HTMLElement>("#trace-empty")!;
const traceList = document.querySelector<HTMLOListElement>("#trace-list")!;
const advancedMode = document.querySelector<HTMLInputElement>("#advanced-mode")!;

let requestNumber = 0;
let traceSteps: TraceStep[] = [];
let traceTimer: number | undefined;
let answerStreamTimer: number | undefined;
const traceStartedAt = new Map<string, number>();

function clearResult(): void {
  result.hidden = true;
  welcome.hidden = false;
  userMessage.hidden = true;
  userQuestion.textContent = "";
  answer.textContent = "";
  refusal.hidden = true;
  refusal.textContent = "";
  citations.hidden = true;
  citationList.replaceChildren();
  status.hidden = true;
  status.textContent = "";
  status.className = "status";
  traceList.hidden = true;
  traceEmpty.hidden = false;
  traceList.replaceChildren();
  traceSteps = [];
  traceStartedAt.clear();
  if (traceTimer !== undefined) window.clearInterval(traceTimer);
  traceTimer = undefined;
  if (answerStreamTimer !== undefined) window.clearInterval(answerStreamTimer);
  answerStreamTimer = undefined;
}

function showStatus(message: string, kind: "loading" | "error"): void {
  status.hidden = false;
  status.className = `status ${kind}`;
  status.textContent = message;
}

function isAskResponse(value: unknown): value is AskResponse {
  if (!value || typeof value !== "object") return false;
  const body = value as Partial<AskResponse>;
  return typeof body.answer === "string"
    && typeof body.refused === "boolean"
    && (body.refusal_reason === null || typeof body.refusal_reason === "string")
    && Array.isArray(body.citations)
    && Array.isArray(body.trace)
    && body.citations.every((citation) =>
      citation && typeof citation.title === "string" && typeof citation.url === "string");
}

function renderResponse(body: AskResponse): void {
  if (traceTimer !== undefined) window.clearInterval(traceTimer);
  traceTimer = undefined;
  welcome.hidden = true;
  result.hidden = false;
  streamAnswer(body.answer);
  if (body.refused) {
    refusal.hidden = false;
    refusal.textContent = `Request refused: ${body.refusal_reason ?? "unknown"}`;
  }
  if (body.citations.length > 0) {
    citations.hidden = false;
    for (const citation of body.citations) {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.textContent = citation.title;
      link.href = citation.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      item.append(link);
      citationList.append(item);
    }
  }
  renderTrace(body.trace);
}

function streamAnswer(value: string): void {
  if (answerStreamTimer !== undefined) window.clearInterval(answerStreamTimer);
  const chunks = value.split(/(\s+)/);
  let index = 0;
  let visible = "";
  answer.innerHTML = "";
  answerStreamTimer = window.setInterval(() => {
    visible += chunks[index++] ?? "";
    answer.innerHTML = renderMarkdown(visible);
    if (index >= chunks.length) {
      window.clearInterval(answerStreamTimer);
      answerStreamTimer = undefined;
    }
  }, 24);
}

function renderTrace(steps: TraceStep[]): void {
  traceSteps = steps;
  traceEmpty.hidden = true;
  traceList.hidden = false;
  traceList.replaceChildren();
  for (const step of steps) {
    if (step.status === "running" && !traceStartedAt.has(step.key)) {
      traceStartedAt.set(step.key, performance.now());
    }
    const item = document.createElement("li");
    item.className = `trace-step ${step.status}`;
    const marker = document.createElement("span");
    marker.className = "trace-marker";
    const copy = document.createElement("div");
    copy.className = "trace-copy";
    const label = document.createElement("strong");
    label.textContent = step.label;
    const detail = document.createElement("small");
    detail.textContent = step.detail || step.status;
    copy.append(label, detail);
    const duration = document.createElement("time");
    const liveDuration = step.status === "running" && traceStartedAt.has(step.key)
      ? Math.round(performance.now() - traceStartedAt.get(step.key)!)
      : step.duration_ms;
    duration.textContent = liveDuration === null ? "—" : `${liveDuration} ms`;
    item.append(marker, copy, duration);
    traceList.append(item);
  }
}

function startTraceClock(): void {
  if (traceTimer !== undefined) window.clearInterval(traceTimer);
  traceTimer = window.setInterval(() => renderTrace(traceSteps), 1000);
}

async function consumeStream(response: Response, currentRequest: number): Promise<void> {
  if (!response.ok || !response.body) throw new Error("The service could not answer this question.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const chunk = await reader.read();
    buffer += decoder.decode(chunk.value ?? new Uint8Array(), { stream: !chunk.done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim() || currentRequest !== requestNumber) continue;
      const event = JSON.parse(line) as { type: string; steps?: TraceStep[]; response?: AskResponse; detail?: string };
      if (event.type === "trace" && event.steps) {
        renderTrace(event.steps);
        if (event.steps.some((step) => step.status === "running" && step.key === "generate")) {
          welcome.hidden = true;
          result.hidden = false;
          answer.innerHTML = '<span class="answer-cursor">▋</span>';
        }
      } else if (event.type === "result" && event.response) {
        if (!isAskResponse(event.response)) throw new Error("The service returned an invalid response.");
        status.hidden = true;
        renderResponse(event.response);
      } else if (event.type === "error") {
        throw new Error(event.detail ?? "Something went wrong.");
      }
    }
    if (chunk.done) break;
  }
}

function escapeHtml(value: string): string {
  const entities: Record<string, string> = {
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#039;",
  };
  return value.replace(/[&<>"']/g, (character) => entities[character] ?? character);
}

function renderMarkdown(value: string): string {
  return escapeHtml(value)
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^[-*] (.+)$/gm, "<div class=\"answer-list-item\">$1</div>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a class="inline-citation" href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\n/g, "<br>");
}

function setQuestion(question: string): void {
  questionInput.value = question;
  questionInput.focus();
}

document.querySelectorAll<HTMLButtonElement>(".suggestion").forEach((button) => {
  button.addEventListener("click", () => setQuestion(button.dataset.question ?? ""));
});

document.querySelector<HTMLButtonElement>("#new-chat")?.addEventListener("click", () => {
  requestNumber += 1;
  questionInput.value = "";
  clearResult();
  setQuestion("");
});

questionInput.addEventListener("input", () => {
  questionInput.style.height = "auto";
  questionInput.style.height = `${Math.min(questionInput.scrollHeight, 160)}px`;
});

questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionInput.value.trim();
  clearResult();
  if (!question) {
    showStatus("Please enter a question.", "error");
    questionInput.focus();
    return;
  }

  const currentRequest = ++requestNumber;
  submitButton.disabled = true;
  welcome.hidden = true;
  userMessage.hidden = false;
  userQuestion.textContent = question;
  status.hidden = true;
  traceStartedAt.clear();
  renderTrace([
    { key: "extract", label: "First LLM request · query plan", status: "pending", duration_ms: null, detail: "Waiting" },
    { key: "embed", label: "LLM embeddings", status: "pending", duration_ms: null, detail: "Waiting" },
    { key: "retrieve", label: "Database · top 15 by embedding", status: "pending", duration_ms: null, detail: "Waiting" },
    { key: "generate", label: "Second LLM request · answer", status: "pending", duration_ms: null, detail: "Waiting" },
  ]);
  startTraceClock();
  try {
    const endpoint = `${API_BASE}${advancedMode.checked ? "/ask/advanced/stream" : "/ask/stream"}`;
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Accept": "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    if (currentRequest !== requestNumber) return;
    await consumeStream(response, currentRequest);
  } catch (error) {
    if (currentRequest === requestNumber) {
      showStatus(error instanceof Error ? error.message : "Something went wrong.", "error");
    }
  } finally {
    if (currentRequest === requestNumber) submitButton.disabled = false;
  }
});
