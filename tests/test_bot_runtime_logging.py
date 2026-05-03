import unittest

from translator_service.bot.runtime import build_polling_started_message


class BotRuntimeLoggingTest(unittest.TestCase):
    def test_polling_started_message_explains_that_bot_is_waiting(self):
        message = build_polling_started_message()

        self.assertIn("Telegram bot", message)
        self.assertIn("polling", message)
        self.assertIn("/start", message)


if __name__ == "__main__":
    unittest.main()
