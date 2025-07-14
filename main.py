from operator import add
from pydantic_ai import Agent
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
from pydantic import BaseModel
from dotenv import load_dotenv
import os

from internal.tools.tools import add_all_tools


class CityLocation(BaseModel):
    city: str
    country: str


def main() -> None:
    load_dotenv()

    ollama_model = OpenAIModel(
        model_name='llama3.2', provider=OpenAIProvider(base_url=f'{os.getenv("OLLAMA_BASE_URL")}/v1')
    )
    agent = Agent(ollama_model, output_type=CityLocation)

    add_all_tools(agent)

    result = agent.run_sync('Where were the olympics held in 2012?')
    print(result.output)
    # > city='London' country='United Kingdom'
    print(result.usage())
    # > Usage(requests=1, request_tokens=57, response_tokens=8, total_tokens=65)


if __name__ == "__main__":
    main()
