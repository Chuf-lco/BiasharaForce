from groq import Groq
from dotenv import load_dotenv
import os

load_dotenv()
groq_client = Groq()

def test_transcription():
    audio_file_path = "test_audio.mp3" # Make sure this file exists in your folder!
    
    if not os.path.exists(audio_file_path):
        print("❌ Please add an audio file named 'test_audio.mp3' to your folder!")
        return

    with open(audio_file_path, "rb") as file:
        print("🎙️ Transcribing audio...")
        transcription = groq_client.audio.transcriptions.create(
            file=(audio_file_path, file.read()),
            model="whisper-large-v3",
            response_format="text",
            language="sw" # Swahili, but handles English/Sheng perfectly
        )
        print(f"\n✅ TRANSCRIBED TEXT:\n{transcription}")

if __name__ == "__main__":
    test_transcription()