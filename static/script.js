
let currentChatId = null;


// Display message
function addMessage(text) {
    const chat = document.getElementById("chatMessages");
    const message = document.createElement("p");

    message.textContent = text;
    chat.appendChild(message);
}


// Load saved chats
async function loadChatHistory() {
    const history = document.getElementById("chatHistory");

    try {
        const response = await fetch("/history");

        if (!response.ok) {
            throw new Error("History could not load");
        }

        const chats = await response.json();
        history.innerHTML = "";

        chats.forEach(item => {
            const container = document.createElement("div");

            // Open Chat
            const button = document.createElement("button");
            button.textContent = item.title;
            button.onclick = () => openChat(item.id);

            // Rename Button
            const renameButton = document.createElement("button");
            renameButton.textContent = "Rename";
            renameButton.style.backgroundColor = "#2563eb";
            renameButton.style.color = "#ffffff";
            renameButton.style.border = "none";
            renameButton.style.borderRadius = "6px";
            renameButton.style.padding = "6px 12px";
            renameButton.style.marginLeft = "8px";
            renameButton.style.cursor = "pointer";
            renameButton.style.fontWeight = "bold";

            renameButton.onclick = async () => {
                const newTitle = prompt("Enter new chat name:", item.title);

                if (!newTitle || !newTitle.trim()) return;

                try {
                    const result = await fetch("/rename-chat/" + item.id, {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json"
                        },
                        body: JSON.stringify({
                            title: newTitle.trim()
                        })
                    });

                    if (!result.ok) {
                        throw new Error("Rename failed");
                    }

                    await loadChatHistory();

                } catch (error) {
                    alert("Unable to rename this chat.");
                }
            };

            // Delete Button
            const deleteButton = document.createElement("button");
            deleteButton.textContent = "Delete";
            deleteButton.style.backgroundColor = "#dc2626";
            deleteButton.style.color = "#ffffff";
            deleteButton.style.border = "none";
            deleteButton.style.borderRadius = "6px";
            deleteButton.style.padding = "6px 12px";
            deleteButton.style.marginLeft = "8px";
            deleteButton.style.cursor = "pointer";
            deleteButton.style.fontWeight = "bold";

            deleteButton.onclick = async () => {
                if (!confirm("Are you sure you want to delete this chat?")) return;

                try {
                    const result = await fetch("/delete-chat/" + item.id, {
                        method: "DELETE"
                    });

                    if (!result.ok) {
                        throw new Error("Delete failed");
                    }

                    if (currentChatId === item.id) {
                        currentChatId = null;
                        document.getElementById("chatMessages").innerHTML = "";
                    }

                    await loadChatHistory();

                } catch (error) {
                    alert("Unable to delete this chat.");
                }
            };

            container.appendChild(button);
            container.appendChild(renameButton);
            container.appendChild(deleteButton);

            history.appendChild(container);
        });

    } catch (error) {
        console.log("History loading error:", error);
    }
}


// Send message
async function sendMessage() {
    const input = document.getElementById("userInput");
    const chat = document.getElementById("chatMessages");
    const sendButton = document.querySelector(".input-area button");

    const text = input.value.trim();

    if (text === "" || sendButton.disabled) return;

    addMessage("You: " + text);

    input.value = "";
    sendButton.disabled = true;
    sendButton.textContent = "Thinking...";

    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ message: text })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.reply || "Request failed");
        }

        addMessage("SHA CORE AI: " + (data.reply || "No response received."));

        await loadChatHistory();

    } catch (error) {
        addMessage("SHA CORE AI: " + error.message);
    } finally {
        sendButton.disabled = false;
        sendButton.textContent = "Send";
        chat.scrollTop = chat.scrollHeight;
        input.focus();
    }
}


// Open saved conversation
async function openChat(id) {
    try {
        const response = await fetch("/history/" + id);

        if (!response.ok) {
            throw new Error("Chat could not open");
        }

        const messages = await response.json();
        currentChatId = id;

        const chat = document.getElementById("chatMessages");
        chat.innerHTML = "";

        messages.forEach(message => {
            const label = message.role === "user"
                ? "You: "
                : "SHA CORE AI: ";

            addMessage(label + message.content);
        });

        chat.scrollTop = chat.scrollHeight;

    } catch (error) {
        alert("Unable to open this conversation.");
    }
}


// Start new chat
async function newChat() {
    try {
        const response = await fetch("/new-chat", {
            method: "POST"
        });

        if (!response.ok) {
            throw new Error("New chat failed");
        }

        currentChatId = null;

        document.getElementById("chatMessages").innerHTML = "";
        document.getElementById("userInput").value = "";
        document.getElementById("userInput").focus();

    } catch (error) {
        alert("Unable to start a new chat.");
    }
}


// Enter key sends message
document.getElementById("userInput").addEventListener("keydown", function(event) {
    if (event.key === "Enter") {
        sendMessage();
    }
});


// Load history when website opens
loadChatHistory();
