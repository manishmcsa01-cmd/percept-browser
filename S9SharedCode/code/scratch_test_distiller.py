import asyncio
from browser.client import V9Client
from browser.skill import BrowserSkill

async def main():
    client = V9Client(base_url="http://localhost:8109", agent="browser")
    skill = BrowserSkill()
    
    with open("scratch_a11y_dump.py", "r") as f:
        pass
    
    # We will use the exact text from my previous dump
    text = """
[67]<a>llama.cpp</a>
[73]<a>deepseek-ai/DeepSeek-R1 Text Generation  685B  Updated Mar 27, 2025  5.35M   13.4k</a>
[74]<a>meta-llama/Meta-Llama-3-8B Text Generation  8B  Updated Sep 27, 2024  1.29M   6.57k</a>
[75]<a>meta-llama/Llama-3.1-8B-Instruct Text Generation  8B  Updated Sep 25, 2024  9.89M   6.05k</a>
[78]<a>meta-llama/Llama-2-7b-chat-hf Text Generation  7B  Updated Apr 17, 2024  251k  4.77k</a>
[79]<a>deepseek-ai/DeepSeek-V4-Pro Text Generation  862B  Updated 3 days ago  4.06M   4.76k</a>
"""
    
    goal = "extract top 3 model cards"
    url = "https://huggingface.co/models?pipeline_tag=text-generation&sort=likes"
    
    print("Calling distiller...")
    res = await skill._distill_comparison(client, "Turn 1: ok", text, goal, url)
    print("Result:", res)

if __name__ == "__main__":
    asyncio.run(main())
