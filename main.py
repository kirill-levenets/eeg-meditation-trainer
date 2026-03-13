import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.ui.app_manager import EEGMeditationApp


def main() -> None:
    app = EEGMeditationApp()
    app.run()


if __name__ == "__main__":
    main()
