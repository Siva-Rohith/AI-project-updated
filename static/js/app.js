let controller = null;
let chatHistory = [];
let isProcessing = false;
let loginState = { logged_in: false, user_name: "" };

const chatBox = document.getElementById("chatBox");
const msgInput = document.getElementById("msg");
const modeSelect = document.getElementById("mode");
const emptyState = document.getElementById("emptyState");
const stopBtn = document.getElementById("stopBtn");
const historyList = document.getElementById("historyList");

function getTheme() {
    return localStorage.getItem("suraksha-theme") || "dark";
}

function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("suraksha-theme", theme);
}

function toggleTheme() {
    applyTheme(getTheme() === "dark" ? "light" : "dark");
}

function syncEmptyState() {
    if (!emptyState || !chatBox) return;
    emptyState.classList.toggle("hidden", chatBox.children.length > 0);
}

function setActiveModeCard(mode) {
    document.querySelectorAll(".mode-card").forEach((button) => {
        button.classList.toggle("active", button.dataset.mode === mode);
    });
}

function attachThemeHandlers() {
    applyTheme(getTheme());
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
        button.addEventListener("click", toggleTheme);
    });
}

function attachPromptHandlers() {
    document.querySelectorAll("[data-prompt]").forEach((button) => {
        button.addEventListener("click", () => {
            if (!msgInput) return;
            msgInput.value = button.dataset.prompt || "";
            msgInput.focus();
        });
    });
}

function attachModeHandlers() {
    document.querySelectorAll(".mode-card").forEach((button) => {
        button.addEventListener("click", () => {
            const nextMode = button.dataset.mode || "auto";
            if (modeSelect) {
                modeSelect.value = nextMode;
            }
            setActiveModeCard(nextMode);
        });
    });

    if (modeSelect) {
        modeSelect.addEventListener("change", () => {
            setActiveModeCard(modeSelect.value);
        });
        setActiveModeCard(modeSelect.value);
    }
}

async function fetchLoginState() {
    const res = await fetch("/check-login");
    loginState = await res.json();
    return loginState;
}

async function isUserLoggedIn() {
    const state = await fetchLoginState();
    return !!state.logged_in;
}

function addMessage(content, type, isHtml = false) {
    if (!chatBox) return null;

    const div = document.createElement("div");
    div.className = "msg " + type;

    if (isHtml) {
        div.innerHTML = content;
    } else {
        div.innerText = content;
    }

    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
    syncEmptyState();
    return div;
}

function clearChatView() {
    if (chatBox) {
        chatBox.innerHTML = "";
    }
    chatHistory = [];
    syncEmptyState();
}

function updateStopButtonState(disabled) {
    if (stopBtn) {
        stopBtn.disabled = disabled;
    }
}

function renderHistoryItems(items) {
    if (!historyList) return;

    if (!items.length) {
        historyList.innerHTML = '<div class="history-empty">No saved chats yet.</div>';
        return;
    }

    historyList.innerHTML = "";
    items.forEach((item) => {
        const button = document.createElement("button");
        button.className = "history-item";
        button.type = "button";
        button.innerHTML = `
            <strong>${item.title || "Untitled chat"}</strong>
            <span>${item.preview || ""}</span>
        `;
        button.addEventListener("click", () => {
            if (msgInput && item.message) {
                msgInput.value = item.message;
                msgInput.focus();
            }
        });
        historyList.appendChild(button);
    });
}

async function loadChatHistory() {
    if (!historyList) return;

    const res = await fetch("/chat-history");
    const data = await res.json();
    renderHistoryItems(data.items || []);
}

function syncSidebarForAuth() {
    const guestPromptsBlock = document.getElementById("guestPromptsBlock");
    const historyBlock = document.getElementById("historyBlock");
    const guestLimitCard = document.getElementById("guestLimitCard");
    const settingsCard = document.getElementById("settingsCard");
    const settingsUser = document.getElementById("settingsUser");
    const indexAuthButton = document.getElementById("indexAuthButton");

    if (loginState.logged_in) {
        guestPromptsBlock?.classList.add("hidden");
        guestLimitCard?.classList.add("hidden");
        historyBlock?.classList.remove("hidden");
        settingsCard?.classList.remove("hidden");
        if (settingsUser) {
            settingsUser.textContent = `Logged in as ${loginState.user_name || "User"}`;
        }
        if (indexAuthButton) {
            indexAuthButton.textContent = "Open Chat";
            indexAuthButton.onclick = () => {
                window.location.href = "/chat";
            };
        }
        loadChatHistory().catch(console.error);
    } else {
        guestPromptsBlock?.classList.remove("hidden");
        guestLimitCard?.classList.remove("hidden");
        historyBlock?.classList.add("hidden");
        settingsCard?.classList.add("hidden");
        if (historyList) {
            historyList.innerHTML = "";
        }
        if (indexAuthButton) {
            indexAuthButton.textContent = "Login";
            indexAuthButton.onclick = () => showLoginPopup();
        }
    }
}

async function initializeAuthUI() {
    await fetchLoginState();
    syncSidebarForAuth();
}

async function sendMessage() {
    if (isProcessing || !msgInput || !modeSelect) return;

    const msg = msgInput.value.trim();
    const mode = modeSelect.value;

    if (!msg) return;

    isProcessing = true;
    updateStopButtonState(false);

    const loggedIn = await isUserLoggedIn();
    if (chatHistory.length >= 4 && !loggedIn) {
        showLoginPopup();
        isProcessing = false;
        updateStopButtonState(true);
        return;
    }

    addMessage(msg, "user");
    chatHistory.push({ message: msg, response: "" });
    msgInput.value = "";

    let botDiv;
    let progress = 0;
    let interval = null;

    if (mode === "scenario" || mode === "image") {
        const label = mode === "scenario" ? "Visualizing scenario..." : "Generating image...";
        botDiv = addMessage(label + " 0%", "bot");
        interval = setInterval(() => {
            progress += 5;
            if (!botDiv) return;
            if (progress >= 98) {
                botDiv.innerText = mode === "scenario" ? "Finalizing scenario..." : "Finalizing image...";
            } else {
                botDiv.innerText = `${label} ${progress}%`;
            }
        }, 1100);
    } else if (mode === "auto") {
        botDiv = addMessage("Analyzing request...", "bot");
        interval = setInterval(() => {
            if (botDiv) {
                botDiv.innerText = progress > 88 ? "Generating result..." : "Analyzing request...";
            }
            progress += 10;
        }, 900);
    } else {
        botDiv = addMessage("Thinking...", "bot");
    }

    controller = new AbortController();

    try {
        const res = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: msg,
                mode: mode,
                history: chatHistory
            }),
            signal: controller.signal
        });

        const contentType = res.headers.get("content-type");

        if (contentType && contentType.includes("application/json")) {
            const data = await res.json();

            if ((data.mode === "image" || data.mode === "scenario") && interval) {
                clearInterval(interval);
                interval = null;
            }

            if (data.response && botDiv) {
                botDiv.innerText = data.response;
                chatHistory[chatHistory.length - 1].response = data.response;
            }

            if (data.type === "image" && botDiv) {
                botDiv.innerHTML = "";
                const img = document.createElement("img");
                img.src = data.url;
                img.alt = "Generated road safety image";
                botDiv.appendChild(img);
                chatHistory[chatHistory.length - 1].response = "[Image Generated]";
                return;
            }

            if (data.type === "scenario" && botDiv) {
                botDiv.innerHTML = "";
                const textDiv = document.createElement("div");
                textDiv.innerText = data.text;
                botDiv.appendChild(textDiv);

                const img = document.createElement("img");
                img.src = data.url;
                img.alt = "Generated traffic scenario";
                botDiv.appendChild(img);

                chatHistory[chatHistory.length - 1].response = data.text;
                return;
            }

            return;
        }

        if (interval) {
            clearInterval(interval);
            interval = null;
        }

        if (botDiv) {
            botDiv.innerText = "";
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let fullText = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split("\n");

            for (const line of lines) {
                if (!line.trim()) continue;

                try {
                    const json = JSON.parse(line);
                    if (json.response && botDiv) {
                        botDiv.innerText += json.response;
                        fullText += json.response;
                        chatBox.scrollTop = chatBox.scrollHeight;
                    }
                } catch (error) {
                    console.error("Stream parse error", error);
                }
            }
        }

        chatHistory[chatHistory.length - 1].response = fullText;
        if (loginState.logged_in) {
            loadChatHistory().catch(console.error);
        }
    } catch (err) {
        if (botDiv) {
            if (err.name === "AbortError") {
                botDiv.innerText += " [Stopped]";
            } else {
                botDiv.innerText = "Connection error.";
            }
        }
        if (err.name !== "AbortError") {
            console.error(err);
        }
    } finally {
        if (interval) {
            clearInterval(interval);
        }
        isProcessing = false;
        updateStopButtonState(true);
    }
}

function stopResponse() {
    if (controller) {
        controller.abort();
    }
    isProcessing = false;
    updateStopButtonState(true);
}

function showLoginPopup() {
    const popup = document.getElementById("loginPopup");
    if (popup) {
        popup.style.display = "flex";
    }
}

function closePopup() {
    const popup = document.getElementById("loginPopup");
    if (popup) {
        popup.style.display = "none";
    }
}

async function login() {
    const username = document.getElementById("username")?.value.trim();
    const password = document.getElementById("password")?.value.trim();

    if (!username || !password) {
        alert("Please enter username and password");
        return;
    }

    const res = await fetch("/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            username,
            password,
            history: chatHistory
        })
    });

    const data = await res.json();

    if (data.status === "success") {
        closePopup();
        await initializeAuthUI();
        if (window.location.pathname === "/chat") {
            chatHistory = [];
        }
        alert("Login successful!");
    } else {
        alert(data.message || "Invalid credentials");
    }
}

function toggleAuth(showRegister) {
    const loginSection = document.getElementById("loginSection");
    const registerSection = document.getElementById("registerSection");

    if (loginSection && registerSection) {
        loginSection.style.display = showRegister ? "none" : "block";
        registerSection.style.display = showRegister ? "block" : "none";
    }
}

async function register() {
    const name = document.getElementById("reg_name")?.value.trim();
    const mobile = document.getElementById("reg_mobile")?.value.trim();
    const email = document.getElementById("reg_email")?.value.trim();
    const password = document.getElementById("reg_password")?.value.trim();

    if (!name || !mobile || !email || !password) {
        alert("Please fill all fields");
        return;
    }

    const res = await fetch("/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, mobile, password })
    });

    const data = await res.json();
    if (data.status === "success") {
        alert("Account created! Now you can login.");
        toggleAuth(false);
    } else {
        alert(data.message || "Registration failed");
    }
}

async function logout() {
    await fetch("/logout", { method: "POST" });
    loginState = { logged_in: false, user_name: "" };
    clearChatView();
    syncSidebarForAuth();
    if (window.location.pathname === "/") {
        return;
    }
}

function attachPageActions() {
    const newChatBtn = document.getElementById("newChatBtn");
    if (newChatBtn) {
        newChatBtn.addEventListener("click", clearChatView);
    }

    document.querySelectorAll("[data-open-login]").forEach((button) => {
        button.addEventListener("click", showLoginPopup);
    });

    const logoutBtn = document.getElementById("logoutBtn");
    if (logoutBtn) {
        logoutBtn.addEventListener("click", logout);
    }
}

if (msgInput) {
    msgInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            sendMessage();
        }
    });
}

attachThemeHandlers();
attachPromptHandlers();
attachModeHandlers();
attachPageActions();
syncEmptyState();
initializeAuthUI().catch(console.error);
