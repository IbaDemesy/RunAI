from dotenv import load_dotenv
from hai_agents import Client


def main():
    load_dotenv()
    client = Client()
    result = client.run_session(
        agent="h/web-surfer-pro",
        messages="Find the top story on Hacker News",
    )
    print(result.status, result.answer)


if __name__ == "__main__":
    main()
