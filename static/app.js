const bodyEl = document.body;
const ROLE = bodyEl.dataset.role;
const TOKEN = bodyEl.dataset.token;
let secondsLeft = Number(bodyEl.dataset.secondsLeft || 0);
const MAX_FILE_MB = Number(bodyEl.dataset.maxFileMb || 25);

const joinOverlay = document.getElementById("join-overlay");
const joinForm = document.getElementById("join-form");
const nameInput = document.getElementById("name-input");
const messagesEl = document.getElementById("messages");
const chatForm = document.getElementById("chat-form");
const msgInput = document.getElementById("msg-input");
const fileInput = document.getElementById("file-input");
const dropZone = document.getElementById("drop-zone");
const timerEl = document.getElementById("timer");
const userListEl = document.getElementById("user-list");
const userCountEl = document.getElementById("user-count");
const typingEl = document.getElementById("typing-indicator");
const storageInfoEl = document.getElementById("storage-info");
const copyJoinBtn = document.getElementById("copy-join-btn");
const endNowBtn = document.getElementById("end-now-btn");

let ws = null;
let myName = ROLE === "host" ? "Host" : "";
let typingTimeout = null;

function formatTimer(sec) {
  const s = Math.max(0, Number(sec) || 0);
  const mins = Math.floor(s / 60);
  const rem = s % 60;
  return `${String(mins).padStart(2, "0")}:${String(rem).padStart(2, "0")}`;
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

function appendSystemEvent(text) {
  const div = document.createElement("div");
  div.className = "sys-event";
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function appendMessage(msg) {
  const div = document.createElement("div");
  div.className = `msg ${msg.role === "host" ? "from-host" : ""}`;

  const header = document.createElement("div");
  header.className = "msg-meta";
  header.textContent = `${msg.sender}${msg.role === "host" ? " · HOST" : ""}`;
  div.appendChild(header);

  if (msg.text) {
    const p = document.createElement("p");
    p.textContent = msg.text;
    div.appendChild(p);
  }

  if (msg.file) {
    const link = document.createElement("a");
    link.className = "file-link";
    link.href = `/api/files/${encodeURIComponent(msg.file.id)}?token=${encodeURIComponent(TOKEN)}`;
    link.download = msg.file.name;
    link.textContent = `Download: ${msg.file.name} (${formatBytes(msg.file.size)})`;
    div.appendChild(link);
  }

  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderUsers(users) {
  userListEl.innerHTML = "";
  userCountEl.textContent = String(users.length);
  users.forEach((u) => {
    const li = document.createElement("li");
    li.textContent = u;
    userListEl.appendChild(li);
  });
}

async function loadInitialMeta() {
  const res = await fetch(`/api/meta?token=${encodeURIComponent(TOKEN)}`);
  if (!res.ok) {
    window.location.reload();
    return;
  }
  const data = await res.json();
  secondsLeft = data.seconds_left;
  storageInfoEl.textContent = `${data.used_mb} / ${data.max_total_mb} MB`;
  renderUsers(data.users || []);
  (data.history || []).forEach(appendMessage);
}

function connectSocket(displayName) {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${proto}//${window.location.host}/ws?token=${encodeURIComponent(TOKEN)}&name=${encodeURIComponent(displayName)}`;
  ws = new WebSocket(wsUrl);

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "message") {
      appendMessage(data.message);
      if (data.message.file) {
        loadInitialMeta().catch(() => {});
      }
    } else if (data.type === "presence") {
      renderUsers(data.users || []);
      if (typeof data.seconds_left === "number") secondsLeft = data.seconds_left;
      if (data.event) appendSystemEvent(data.event);
    } else if (data.type === "typing") {
      if (data.user !== myName) {
        typingEl.textContent = `${data.user} is typing...`;
        clearTimeout(typingTimeout);
        typingTimeout = setTimeout(() => {
          typingEl.textContent = "";
        }, 1500);
      }
    } else if (data.type === "pong") {
      if (typeof data.seconds_left === "number") secondsLeft = data.seconds_left;
    } else if (data.type === "error") {
      appendSystemEvent(data.message);
    } else if (data.type === "session_ended") {
      appendSystemEvent(data.reason || "Session ended.");
      setTimeout(() => {
        window.location.reload();
      }, 900);
    }
  };
}

joinForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  myName = nameInput.value.trim() || "Guest";
  joinOverlay.classList.add("hidden");
  await loadInitialMeta();
  connectSocket(myName);
});

msgInput.addEventListener("input", () => {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "typing" }));
  }
});

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = msgInput.value.trim();
  if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
  ws.send(JSON.stringify({ type: "chat", text }));
  msgInput.value = "";
});

async function handleFileUpload(file) {
  if (!file) return;
  if (file.size > MAX_FILE_MB * 1024 * 1024) {
    appendSystemEvent(`File too large (max ${MAX_FILE_MB} MB).`);
    return;
  }
  const formData = new FormData();
  formData.append("sender", myName || "Guest");
  formData.append("file", file);

  const res = await fetch(
    `/api/upload?token=${encodeURIComponent(TOKEN)}&sender=${encodeURIComponent(myName || "Guest")}`,
    { method: "POST", body: formData }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    appendSystemEvent(err.detail || "Upload failed.");
  }
}

fileInput.addEventListener("change", () => {
  if (fileInput.files && fileInput.files[0]) {
    handleFileUpload(fileInput.files[0]);
    fileInput.value = "";
  }
});

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("drag-over");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag-over");
  if (e.dataTransfer?.files?.[0]) {
    handleFileUpload(e.dataTransfer.files[0]);
  }
});

copyJoinBtn?.addEventListener("click", async () => {
  const joinUrl = `${window.location.origin}/?token=${encodeURIComponent(TOKEN)}`;
  try {
    await navigator.clipboard.writeText(joinUrl);
    appendSystemEvent("Join link copied to clipboard.");
  } catch {
    appendSystemEvent(joinUrl);
  }
});

endNowBtn?.addEventListener("click", async () => {
  if (!confirm("End the room now and wipe all messages and files?")) return;
  await fetch(`/api/end?token=${encodeURIComponent(TOKEN)}`, { method: "POST" });
});

setInterval(() => {
  secondsLeft = Math.max(0, secondsLeft - 1);
  timerEl.textContent = formatTimer(secondsLeft);
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "ping" }));
  }
}, 1000);