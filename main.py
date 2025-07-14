from operator import add
from pydantic_ai import Agent
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIModel
from pydantic import BaseModel
from dotenv import load_dotenv
import os
import speech_recognition as sr
from internal.tools.tools import add_all_tools



class CityLocation(BaseModel):
    city: str
    country: str

def Voice_To_Text(duration=5):  
    r = sr.Recognizer() 
    with sr.Microphone() as source: 
        print("請開始說話:") 
        r.adjust_for_ambient_noise(source) 
        audio = r.listen(source, phrase_time_limit=duration) 
    try: 
        Text = r.recognize_google(audio, language="zh-TW") 
    except sr.UnknownValueError: 
        Text = "無法翻譯" 
    except sr.RequestError as e: 
        Text = "無法翻譯{0}".format(e) 
    return Text 


def main() -> None:
    load_dotenv()
    print(Voice_To_Text())
    ollama_model = OpenAIModel(
        model_name='qwen3:14b', provider=OpenAIProvider(base_url=f'{os.getenv("OLLAMA_BASE_URL")}/v1')
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