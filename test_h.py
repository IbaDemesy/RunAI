from dotenv import load_dotenv
from hai_agents import Client

load_dotenv()
client = Client()
result = client.run_session(
    agent="h/web-surfer-pro",
    messages="Find the top story on Hacker News",
)
print(result.status, result.answer)
