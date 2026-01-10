import asyncio

from internal.runtime.system import run_cli

if __name__ == "__main__":
    try:
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        pass
