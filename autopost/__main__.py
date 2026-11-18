import argparse
import logging
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="Pop-culture Telegram autopost")
    parser.add_argument("--dry-run", action="store_true",
                        help="не отправлять в Telegram, сохранять пост в ./out")
    args = parser.parse_args()
    if args.dry_run:
        os.environ["DRY_RUN"] = "1"

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    for noisy in ("httpx", "httpx2", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    from .config import load_settings
    from .pipeline import run

    run(load_settings())


if __name__ == "__main__":
    main()