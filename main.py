import os
import openai
import speech_recognition as sr
import pyttsx3
from dotenv import load_dotenv

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
    return response.choices[0].message.content

if __name__ == "__main__":
    print("Jarvis is ready. Say something!")
    while True:
        command = listen()
        if command.lower() in ["exit", "quit", "stop"]:
            print("Goodbye!")
            break
        response = ask_gpt(command)
        print(f"Jarvis: {response}")
        speak(response)
