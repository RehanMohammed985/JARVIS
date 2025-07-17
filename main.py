import os
import openai
import speech_recognition as sr
import pyttsx3
from dotenv import load_dotenv
import subprocess
import json

# Load OpenAI API key from .env
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

recognizer = sr.Recognizer()
engine = pyttsx3.init()

def speak(text):
    engine.say(text)
    engine.runAndWait()

def listen():
    with sr.Microphone() as source:
        print("Listening...")
        audio = recognizer.listen(source)
    try:
        command = recognizer.recognize_google(audio)
        print(f"You said: {command}")
        return command
    except sr.UnknownValueError:
        return "Sorry, I did not understand that."
    except sr.RequestError:
        return "Sorry, there was a problem with the speech recognition service."

def listen_for_wake_word(wake_word="jarvis"):
    while True:
        print("Listening for wake word...")
        with sr.Microphone() as source:
            audio = recognizer.listen(source)
        try:
            phrase = recognizer.recognize_google(audio).lower()
            print(f"Heard: {phrase}")
            if wake_word in phrase:
                speak("Yes?")
                return
        except sr.UnknownValueError:
            continue
        except sr.RequestError:
            print("Speech recognition error.")
            continue

def ask_gpt(prompt):
    response = openai.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

def create_file(filename, content):
    try:
        with open(filename, 'w') as f:
            f.write(content)
        return f"File '{filename}' created successfully."
    except Exception as e:
        return f"Failed to create file: {e}"

def open_file(filename):
    try:
        filepath = os.path.abspath(filename)
        subprocess.run(['open', filepath])  # macOS only; adjust for other OSes
        return f"Opened file '{filename}'."
    except Exception as e:
        return f"Failed to open file: {e}"

def handle_command(command):
    system_prompt = """
    You are a smart assistant that converts natural language voice commands into structured Python actions.
    Available actions: create_file, open_file, ask_gpt
    For create_file: include 'filename' and 'content'
    For open_file: include 'filename'
    If the command doesn't match any action, fallback to ask_gpt.
    Respond in pure JSON only, no explanations.
    Example:
    {
      "action": "create_file",
      "filename": "notes.txt",
      "content": "Remember to call mom."
    }
    """

    try:
        gpt_response = openai.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": command}
            ]
        )
        parsed = json.loads(gpt_response.choices[0].message.content)
        action = parsed.get("action")

        if action == "create_file":
            return create_file(parsed["filename"], parsed["content"])
        elif action == "open_file":
            return open_file(parsed["filename"])
        else:
            return ask_gpt(command)

    except Exception as e:
        print("Error handling command:", e)
        return ask_gpt(command)

if __name__ == "__main__":
    print("Jarvis is always listening... Say 'Jarvis' to begin.")
    while True:
        listen_for_wake_word("jarvis")
        command = listen()
        if command.lower() in ["exit", "quit", "stop"]:
            print("Goodbye!")
            speak("Goodbye!")
            break
        response = handle_command(command)
        print(f"Jarvis: {response}")
        speak(response)
