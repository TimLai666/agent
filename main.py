import argparse
import asyncio

from internal.runtime.system import run_cli


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the agent CLI.")
    parser.add_argument(
        "--prompt",
        nargs="+",
        help="Run once with the provided prompt.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Read a single input (or speech) then exit.",
    )
    args = parser.parse_args()
    try:
        prompt = " ".join(args.prompt) if args.prompt else None
        asyncio.run(run_cli(prompt_once=prompt, single_turn=args.once))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
