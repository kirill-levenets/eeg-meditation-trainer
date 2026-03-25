import argparse
import os
import sys

os.environ["KIVY_NO_ARGS"] = "1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.ui.app_manager import EEGMeditationApp


def main() -> None:
    parser = argparse.ArgumentParser(description="EEG Meditation Trainer")
    parser.add_argument(
        "--serial", metavar="PATH",
        help="Serial device path to read from (e.g. /tmp/mindwave_b from splitter)"
    )
    args, kivy_args = parser.parse_known_args()
    # Pass remaining args back to Kivy
    sys.argv = [sys.argv[0]] + kivy_args

    app = EEGMeditationApp()
    if args.serial:
        app.serial_device_override = args.serial
    app.run()


if __name__ == "__main__":
    main()
