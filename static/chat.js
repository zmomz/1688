const messagesDiv = document.getElementById("messages");
const form = document.getElementById("chat-form");
const input = document.getElementById("user-input");
const sendBtn = document.getElementById("send-btn");
const statusEl = document.getElementById("status");
const progressBar = document.getElementById("progress-bar");
const progressText = document.getElementById("progress-text");

let ws = null;

function connect() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
        statusEl.textContent = "Connected";
        statusEl.className = "status status-connected";
        sendBtn.disabled = false;
    };

    ws.onclose = () => {
        statusEl.textContent = "Disconnected";
        statusEl.className = "status status-disconnected";
        sendBtn.disabled = true;
        // Reconnect after 3 seconds
        setTimeout(connect, 3000);
    };

    ws.onerror = () => {
        statusEl.textContent = "Error";
        statusEl.className = "status status-disconnected";
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleMessage(msg);
    };
}

function handleMessage(msg) {
    switch (msg.type) {
        case "progress":
            progressBar.style.display = "block";
            progressText.textContent = msg.text;
            break;

        case "assistant_message":
            hideProgress();
            appendMessage("assistant", msg.text);
            break;

        case "results_summary":
            hideProgress();
            appendResults(msg);
            break;

        case "error":
            hideProgress();
            appendMessage("error", msg.text);
            break;
    }
}

function hideProgress() {
    progressBar.style.display = "none";
}

function appendMessage(role, text) {
    const wrapper = document.createElement("div");
    wrapper.className = `message ${role}`;

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;

    wrapper.appendChild(bubble);
    messagesDiv.appendChild(wrapper);
    scrollToBottom();
}

function appendResults(msg) {
    const wrapper = document.createElement("div");
    wrapper.className = "message assistant";

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    let html = `<strong>Found ${msg.total} products</strong>`;
    if (msg.terms_searched) {
        html += ` for: ${msg.terms_searched.join(", ")}`;
    }

    if (msg.products && msg.products.length > 0) {
        html += `<table class="results-table">
            <thead>
                <tr>
                    <th></th>
                    <th>Title</th>
                    <th>Price</th>
                    <th>MOQ</th>
                    <th>Supplier</th>
                </tr>
            </thead>
            <tbody>`;

        for (const p of msg.products) {
            const title = p.title ? (p.title.length > 50 ? p.title.substring(0, 50) + "..." : p.title) : "—";
            const price = formatPrice(p.price_min, p.price_max, p.price_unit);
            const moq = p.moq ? `${p.moq} ${p.moq_unit || ""}`.trim() : "—";
            const supplier = p.supplier_name || "—";
            const imgTag = p.image_url
                ? `<img class="product-img" src="${escapeHtml(p.image_url)}" alt="" loading="lazy">`
                : "";

            html += `<tr>
                <td>${imgTag}</td>
                <td><a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">${escapeHtml(title)}</a></td>
                <td>${escapeHtml(price)}</td>
                <td>${escapeHtml(moq)}</td>
                <td>${escapeHtml(supplier)}</td>
            </tr>`;
        }

        html += `</tbody></table>`;
    }

    const showing = msg.products ? msg.products.length : 0;
    if (msg.total > showing) {
        html += `<p class="results-meta">Showing ${showing} of ${msg.total} products.</p>`;
    }
    if (msg.file_path) {
        html += `<p class="results-meta">Full results saved to: ${escapeHtml(msg.file_path)}</p>`;
    }

    bubble.innerHTML = html;
    wrapper.appendChild(bubble);
    messagesDiv.appendChild(wrapper);
    scrollToBottom();
}

function formatPrice(min, max, unit) {
    if (min == null && max == null) return "—";
    unit = unit || "元";
    if (min === max || max == null) return `${min} ${unit}`;
    if (min == null) return `${max} ${unit}`;
    return `${min} - ${max} ${unit}`;
}

function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = String(str);
    return div.innerHTML;
}

function scrollToBottom() {
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Send message
form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;

    appendMessage("user", text);
    ws.send(JSON.stringify({ text }));
    input.value = "";
});

// Initialize
connect();
