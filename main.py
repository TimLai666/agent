from operator import add
from pydantic_ai import Agent
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
from pydantic import BaseModel
from dotenv import load_dotenv
import os

from internal.tools.tools import add_all_tools
from internal.tools.voice_manager import VoiceManager



class CityLocation(BaseModel):
    city: str
    country: str




def main() -> None:
    load_dotenv()

    # 語音輸入功能測試於主程式
    voice_manager = VoiceManager()
    recognized_text = voice_manager.recognize_speech()
    ollama_model = OpenAIModel(
        model_name='qwen3:14b', provider=OpenAIProvider(base_url=f'{os.getenv("OLLAMA_BASE_URL")}/v1')

    )
    agent = Agent(ollama_model, output_type=CityLocation)

    add_all_tools(agent)

    result = agent.run_sync(recognized_text)
    print(result.output)
    # > city='London' country='United Kingdom'
    print(result.usage())
    # > Usage(requests=1, request_tokens=57, response_tokens=8, total_tokens=65)


if __name__ == "__main__":
    main()