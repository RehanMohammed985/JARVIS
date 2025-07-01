# JARVIS (Joint Assistant for Research, Voice, Interaction, and Scripting)

A local voice assistant for Mac that uses OpenAI’s GPT models to answer questions, open apps, create files/projects, and perform tasks — all running locally.

---

## Features

- Voice input and output (can be toggled off for text-only mode)
- Connects to OpenAI GPT API for natural language understanding and responses
- Can open applications, create files, run commands on your Mac
- Easily extensible to integrate other LLM APIs (e.g., Cohere)
- Local environment setup with Python and virtualenv

---

## Getting Started

### Prerequisites

- macOS computer
- Python 3.13+ installed
- OpenAI API key (see https://platform.openai.com/account/api-keys)
- (Optional) Cohere API key for alternative LLM usage

### Installation

1. Clone or download this repository.

2. Create and activate a Python virtual environment:

   python3 -m venv venv
   source venv/bin/activate
   
3. Install dependencies:
   
   pip install -r requirements.txt

4. Create a .env file in the project root with your API keys:
  OPENAI_API_KEY=your-openai-api-key

Usage

On running, choose which LLM to use (OpenAI or Cohere).
Type or speak your command.
The assistant will respond and perform actions accordingly.
Type exit to quit.

Security

Important: Never commit your .env file or API keys to public repositories. Use .gitignore to exclude sensitive files.

  

