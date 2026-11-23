
let currentChatId = null;
let lastAIReply = "";
let recognition = null;
let currentVoiceAudio = null;
let isVoiceGenerating = false;


// Display message
function addMessage(text) {
    const chat = document.getElementById("chatMessages");
    const message = document.createElement("p");
    message.textContent = text;
    chat.appendChild(message);
}


// Clear chat messages
function clearChatMessages() {
    const chat = document.getElementById("chatMessages");
    chat.querySelectorAll(":scope > p").forEach(message => message.remove());
}


// Load saved chats
async function loadChatHistory() {
    const history = document.getElementById("chatHistory");

    try {
        const response = await fetch("/history");
        if (!response.ok) throw new Error("History could not load");

        const chats = await response.json();
        history.innerHTML = "";

        chats.forEach(item => {
            const container = document.createElement("div");

            const button = document.createElement("button");
            button.textContent = item.title;
            button.onclick = () => openChat(item.id);

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
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({title: newTitle.trim()})
                    });

                    if (!result.ok) throw new Error("Rename failed");
                    await loadChatHistory();

                } catch (error) {
                    alert("Unable to rename this chat.");
                }
            };

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

                    if (!result.ok) throw new Error("Delete failed");

                    if (currentChatId === item.id) {
                        currentChatId = null;
                        lastAIReply = "";
                        clearChatMessages();
                        showPage("home");
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

    const sendButton = document.querySelector(
        '.input-area button[onclick="sendMessage()"]'
    );

    const text = input.value.trim();

    if (!sendButton || text === "" || sendButton.disabled) return;

    addMessage("You: " + text);

    input.value = "";
    sendButton.disabled = true;
    sendButton.textContent = "Thinking...";

    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({message: text})
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.reply || "Request failed");
        }

        lastAIReply = data.reply || "No response received.";
        addMessage("SHA CORE AI: " + lastAIReply);

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

        if (!response.ok) throw new Error("Chat could not open");

        const messages = await response.json();
        currentChatId = id;
        lastAIReply = "";

        showPage("chat");

        const chat = document.getElementById("chatMessages");
        clearChatMessages();

        messages.forEach(message => {
            const label = message.role === "user"
                ? "You: "
                : "SHA CORE AI: ";

            addMessage(label + message.content);

            if (message.role !== "user") {
                lastAIReply = message.content;
            }
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

        if (!response.ok) throw new Error("New chat failed");

        currentChatId = null;
        lastAIReply = "";

        clearChatMessages();
        showPage("chat");

        document.getElementById("userInput").value = "";
        document.getElementById("userInput").focus();

    } catch (error) {
        alert("Unable to start a new chat.");
    }
}


// Urdu / English voice input
function startVoiceInput() {
    const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
        alert("Voice input is not supported in this browser.");
        return;
    }

    recognition = new SpeechRecognition();

    const language = document.getElementById("voiceLanguage").value;

    recognition.lang = language;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onresult = function(event) {
        document.getElementById("userInput").value =
            event.results[0][0].transcript;
    };

    recognition.onerror = function(event) {
        alert("Microphone error: " + event.error);
    };

    recognition.start();
}


// Speak AI reply using ElevenLabs
async function speakLastReply() {
    if (isVoiceGenerating) return;

    if (!lastAIReply) {
        alert("Pehle AI se message bhejein.");
        return;
    }

    const language = document.getElementById("voiceLanguage").value;

    if (language !== "ur-PK") {
        alert("ElevenLabs Urdu voice abhi configured hai.");
        return;
    }

    isVoiceGenerating = true;
    window.speechSynthesis.cancel();

    const text = lastAIReply
        .replace(/SHA CORE AI/gi, "Sha Core AI")
        .trim();

    const chunks = text.match(/[\s\S]{1,900}(?:\s|$)|[\s\S]{1,900}/g) || [];

    try {
        for (const chunk of chunks) {
            if (!isVoiceGenerating) break;

            const response = await fetch("/text-to-speech", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    text: chunk.trim(),
                    language: language
                })
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.error || "Voice generation failed.");
            }

            if (!isVoiceGenerating) break;

            const audioBlob = await response.blob();
            const audioUrl = URL.createObjectURL(audioBlob);
            const audio = new Audio(audioUrl);

            currentVoiceAudio = audio;

            await new Promise((resolve, reject) => {
                audio.onended = resolve;
                audio.onerror = () => reject(new Error("Audio playback failed."));
                audio.play().catch(reject);
            });

            URL.revokeObjectURL(audioUrl);

            if (currentVoiceAudio === audio) {
                currentVoiceAudio = null;
            }
        }

    } catch (error) {
        if (isVoiceGenerating) {
            alert(error.message || "Voice playback failed.");
        }
    } finally {
        currentVoiceAudio = null;
        isVoiceGenerating = false;
    }
}


// Stop current voice
function stopVoice() {
    isVoiceGenerating = false;

    if (currentVoiceAudio) {
        currentVoiceAudio.pause();
        currentVoiceAudio.currentTime = 0;
        currentVoiceAudio = null;
    }
}


// IMAGE GENERATION
let isImageGenerating = false;

async function generateImage() {
    if (isImageGenerating) return;

    const promptInput = document.getElementById("imagePrompt");
    const button = document.getElementById("generateImageBtn");
    const status = document.getElementById("imageStatus");
    const image = document.getElementById("generatedImage");

    const prompt = promptInput.value.trim();

    if (!prompt) {
        status.textContent = "Please describe the image first.";
        return;
    }

    if (prompt.length > 2048) {
        status.textContent = "Prompt is too long. Maximum 2048 characters.";
        return;
    }

    isImageGenerating = true;
    button.disabled = true;
    button.textContent = "Generating...";
    status.textContent = "Creating your image. Please wait...";
    image.style.display = "none";

    try {
        const response = await fetch("/generate-image", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ prompt })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || "Image generation failed.");
        }

        if (!data.image || !data.image.startsWith("data:image/")) {
            throw new Error("Invalid image received.");
        }

        image.src = data.image;
        image.style.display = "block";
        status.textContent = "Your image is ready!";

    } catch (error) {
        status.textContent = error.message || "Something went wrong.";
    } finally {
        isImageGenerating = false;
        button.disabled = false;
        button.textContent = "✦ Generate Image";
    }
}


// ENTER KEY SENDS MESSAGE
document.getElementById("userInput").addEventListener("keydown", function(event) {
    if (event.key === "Enter") {
        sendMessage();
    }
});


// PAGE NAVIGATION
function showPage(page) {
    const pages = {
        home: document.getElementById("homePage"),
        chat: document.getElementById("chatPage"),
        image: document.getElementById("imagePage")
    };

    if (!pages[page]) return;

    Object.entries(pages).forEach(([name, element]) => {
        if (element) element.hidden = name !== page;
    });

    document.querySelectorAll(".nav-item").forEach(button => {
        button.classList.remove("active");
    });

    const activeButton = document.getElementById(
        page === "home" ? "homeNav" :
        page === "chat" ? "chatNav" : "imageNav"
    );

    if (activeButton) activeButton.classList.add("active");
}


// LOAD WEBSITE
showPage("home");
loadChatHistory();
