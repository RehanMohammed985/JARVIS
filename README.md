# JARVIS (Joint Assistant for Research, Voice, Interaction, and Scripting)

Jarvis is a local voice  assistant built in Python for macOS. It uses OpenAI’s GPT models to interpret natural language commands and perform useful tasks such as answering questions, opening apps, and creating files — all from your terminal. Yes the inspo is from Iron Man

---

## ✨ Features

- 🔊 Optional voice interaction (uses speech recognition and text-to-speech)
- 🧠 Connects to OpenAI’s Chat API (GPT-3.5 / GPT-4)
- ⚙️ Executes system-level commands (open apps, create files, etc.)
- 🔁 Easily extendable to support other LLMs like Cohere
- 🧪 Run locally without cloud infrastructure
- 🔐 API keys managed securely using `.env`

---

## 🚀 Setup Instructions

### 1. Prerequisites

- macOS
- Python 3.13+
- OpenAI API Key (https://platform.openai.com/account/api-keys)
- (Optional) Cohere API Key (https://dashboard.cohere.ai)

### 2. Clone the Repository

```bash
git clone https://github.com/your-username/jarvis.git
cd jarvis
```

### 3. Create and Activate a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Add Your API Keys

Create a `.env` file in the root directory:

```
OPENAI_API_KEY=your-openai-api-key
COHERE_API_KEY=your-cohere-api-key  # Optional
```

> ⚠️ Do not commit `.env` to GitHub. Add it to `.gitignore`.

---

## 🧠 Usage

Start Jarvis from the command line:

```bash
python main.py
```

You'll be prompted to choose your preferred LLM (OpenAI or Cohere).  
Then you can type or speak your query (depending on setup).

**Example Commands:**

- “What’s the capital of Japan?”
- “Open Safari”
- “Create a Python project folder named weatherbot”

---

## 📁 Project Structure

```
jarvis/
├── main.py               # Entry point for the assistant
├── .env                  # Stores API keys (not committed)
├── venv/                 # Python virtual environment (excluded)
├── README.md             # This file
├── requirements.txt      # Python dependencies
```

---

## ✅ To-Do / Future Improvements

- [ ] Add plugin support for third-party services (e.g. calendar, email)
- [ ] Voice wake word detection
- [ ] GUI interface (optional)

---

## 🛡️ Security

- Store API keys in a `.env` file.
- Add `.env`, `venv/`, and `__pycache__/` to `.gitignore`.

```
# .gitignore
.env
venv/
__pycache__/
```

---

## 📄 License

This project is licensed under the **MIT License**.

---

## 🙋‍♂️ Author

Created by **Rehan Mohammed** — feel free to connect: `rehanmoin91@gmail.com`
