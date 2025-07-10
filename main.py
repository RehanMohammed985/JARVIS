import os
import openai
import speech_recognition as sr
import pyttsx3
from dotenv import load_dotenv
import subprocess

# Load your OpenAI API key from the .env file
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

def ask_gpt(prompt):
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
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
        subprocess.run(['open', filepath])  # 'open' for MacOS, use 'xdg-open' for Linux, or 'start' for Windows
        return f"Opened file '{filename}'."
    except Exception as e:
        return f"Failed to open file: {e}"

def handle_command(command):
    command_lower = command.lower()

    if "create a file named" in command_lower and "with content" in command_lower:
        try:
            parts = command_lower.split("create a file named")[1].split("with content")
            filename = parts[0].strip().replace(" ", "_")
            content = parts[1].strip()
            return create_file(filename, content)
        except Exception as e:
            return f"Couldn't parse the create file command: {e}"

    elif "open the file" in command_lower:
        try:
            filename = command_lower.split("open the file")[1].strip().replace(" ", "_")
            return open_file(filename)
        except Exception as e:
            return f"Couldn't parse the open file command: {e}"

    else:
        return ask_gpt(command)

if __name__ == "__main__":
    print("Jarvis is ready. Say something!")
    while True:
        command = listen()
        if command.lower() in ["exit", "quit", "stop"]:
            print("Goodbye!")
            break
        response = handle_command(command)
        print(f"Jarvis: {response}")
        speak(response)
