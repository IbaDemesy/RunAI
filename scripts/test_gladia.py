import sys

from dotenv import load_dotenv

load_dotenv()

from gladiaio_sdk import GladiaClient

SAMPLE_AUDIO = "https://media.githubusercontent.com/media/gladiaio/gladia-samples/main/data/anna-and-sasha-16000.wav"

audio = sys.argv[1] if len(sys.argv) > 1 else SAMPLE_AUDIO
client = GladiaClient().prerecorded()
response = client.transcribe(audio, {"language_config": {"languages": ["en", "fr"]}})
print(response.status, response.result.transcription.full_transcript)
