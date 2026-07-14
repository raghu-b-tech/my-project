/**
 * FanPath frontend.
 *
 * No framework, no build step, on purpose: this keeps the repo small,
 * keeps every line auditable in one file, and means correctness doesn't
 * depend on a bundler that might behave differently on someone else's
 * machine. Assistant and user text is always inserted with `textContent`,
 * never `innerHTML` - the second, independent XSS guard described in
 * `app/security.py` is only meaningful if this half of the contract holds.
 */

(() => {
  "use strict";

  const RTL_LANGUAGES = new Set(["ar"]);

  const transcript = document.getElementById("transcript");
  const emptyState = document.getElementById("empty-state");
  const srStatus = document.getElementById("sr-status");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("message-input");
  const sendButton = document.getElementById("send-button");
  const languageSelect = document.getElementById("language-select");
  const zoneSelect = document.getElementById("zone-select");
  const sensoryToggle = document.getElementById("sensory-toggle");
  const micButton = document.getElementById("mic-button");

  const userTemplate = document.getElementById("user-message-template");
  const assistantTemplate = document.getElementById("assistant-message-template");
  const errorTemplate = document.getElementById("error-message-template");

  const CATEGORY_LABELS = {
    NAVIGATE: "Navigate",
    ACCESS: "Accessibility",
    LIVE: "Live status",
    GENERAL: "FanPath",
  };

  function accessibilityNeeds() {
    return Array.from(document.querySelectorAll('input[name="access"]:checked')).map(
      (el) => el.value
    );
  }

  function applyLanguageDirection() {
    const lang = languageSelect.value;
    document.documentElement.lang = lang;
    document.documentElement.dir = RTL_LANGUAGES.has(lang) ? "rtl" : "ltr";
  }

  function applySensoryMode() {
    document.body.classList.toggle("needs-calm", sensoryToggle.checked);
  }

  function autoGrow() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 128)}px`;
  }

  function appendUserMessage(text) {
    emptyState.remove();
    const node = userTemplate.content.cloneNode(true);
    node.querySelector(".msg__body").textContent = text;
    transcript.appendChild(node);
    transcript.scrollTop = transcript.scrollHeight;
  }

  function appendAssistantShell() {
    const node = assistantTemplate.content.cloneNode(true);
    const article = node.querySelector(".msg--assistant");
    article.classList.add("msg--pending");
    transcript.appendChild(node);
    const inserted = transcript.lastElementChild;
    transcript.scrollTop = transcript.scrollHeight;
    return inserted;
  }

  function appendErrorMessage(text) {
    const node = errorTemplate.content.cloneNode(true);
    node.querySelector(".msg__body").textContent = text;
    transcript.appendChild(node);
    transcript.scrollTop = transcript.scrollHeight;
  }

  /** Parses one Server-Sent Events buffer into {event, data} records. */
  function parseSseChunk(buffer) {
    const records = [];
    const blocks = buffer.split("\n\n");
    const remainder = blocks.pop() ?? "";
    for (const block of blocks) {
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data = line.slice(6);
      }
      if (data) records.push({ event, data: JSON.parse(data) });
    }
    return { records, remainder };
  }

  async function askFanPath(message) {
    appendUserMessage(message);
    const shell = appendAssistantShell();
    const bodyEl = shell.querySelector(".msg__body");
    const categoryEl = shell.querySelector(".status-strip__category");
    const etaEl = shell.querySelector(".status-strip__eta");

    srStatus.textContent = "FanPath is answering.";
    sendButton.disabled = true;

    let assembled = "";

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          language: languageSelect.value,
          current_zone: zoneSelect.value,
          accessibility_needs: accessibilityNeeds(),
        }),
      });

      if (response.status === 429) {
        throw new Error("You're sending messages faster than FanPath can answer. Wait a moment and try again.");
      }
      if (!response.ok || !response.body) {
        throw new Error("FanPath couldn't reach the assistant. Please try again.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const { records, remainder } = parseSseChunk(buffer);
        buffer = remainder;

        for (const { event, data } of records) {
          if (event === "meta") {
            categoryEl.textContent = CATEGORY_LABELS[data.category] || data.category;
            etaEl.textContent = data.eta_minutes != null ? `${data.eta_minutes} min` : "";
          } else if (event === "token") {
            assembled += data.text;
            bodyEl.textContent = assembled;
            transcript.scrollTop = transcript.scrollHeight;
          } else if (event === "error") {
            throw new Error(data.message || "Something went wrong.");
          }
        }
      }

      shell.classList.remove("msg--pending");
      srStatus.textContent = assembled || "FanPath finished answering.";
    } catch (err) {
      shell.remove();
      appendErrorMessage(err.message || "Something went wrong. Please try again.");
      srStatus.textContent = "FanPath ran into a problem.";
    } finally {
      sendButton.disabled = false;
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    autoGrow();
    askFanPath(message);
  });

  input.addEventListener("input", autoGrow);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      input.value = chip.textContent.trim();
      autoGrow();
      form.requestSubmit();
    });
  });

  languageSelect.addEventListener("change", applyLanguageDirection);
  sensoryToggle.addEventListener("change", applySensoryMode);
  applyLanguageDirection();

  // --- Optional voice input (feature-detected; the app is fully usable
  // without it, which matters since Web Speech API support is inconsistent
  // across browsers) ---
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (SpeechRecognition) {
    const recognizer = new SpeechRecognition();
    recognizer.continuous = false;
    recognizer.interimResults = false;

    micButton.hidden = false;
    micButton.addEventListener("click", () => {
      recognizer.lang = languageSelect.value;
      micButton.setAttribute("aria-pressed", "true");
      recognizer.start();
    });
    recognizer.addEventListener("result", (event) => {
      input.value = event.results[0][0].transcript;
      autoGrow();
    });
    recognizer.addEventListener("end", () => micButton.setAttribute("aria-pressed", "false"));
    recognizer.addEventListener("error", () => micButton.setAttribute("aria-pressed", "false"));
  }
})();
