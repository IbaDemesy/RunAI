import unittest
from types import SimpleNamespace
from unittest.mock import patch

from test_h import main


class AgentRunnerTests(unittest.TestCase):
    def test_main_runs_agent_and_prints_result(self):
        result = SimpleNamespace(status="completed", answer="Test answer")

        with (
            patch("test_h.load_dotenv") as load_dotenv,
            patch("test_h.Client") as client_class,
            patch("builtins.print") as print_result,
        ):
            client_class.return_value.run_session.return_value = result

            main()

        load_dotenv.assert_called_once_with()
        client_class.return_value.run_session.assert_called_once_with(
            agent="h/web-surfer-pro",
            messages="Find the top story on Hacker News",
        )
        print_result.assert_called_once_with("completed", "Test answer")


if __name__ == "__main__":
    unittest.main()
