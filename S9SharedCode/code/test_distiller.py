import asyncio
from gateway import LLM

async def main():
    prompt = """You are the Distiller skill. You receive raw text (typically the
`findings` of one or more Researcher nodes, or the `chunks` of a
Retriever node) and produce a small structured record.

You make no tool calls. You do no web access. Everything you need is
already in the prompt under INPUTS.

Procedure:
  1. Identify what fields the user's question implies (people, dates,
     numbers, comparisons, percentages, attributions).
  2. Pull those fields out of the inputs.
  3. Emit a compact JSON record. Fields with no evidence in the inputs
     are omitted, not made up.

Output schema (JSON, no prose, no markdown fences):

  {
    "fields": { "<field_name>": "<value>", ... },
    "rationale": "<one short sentence saying which input supports each field>"
  }

Notes:
  - The fields dictionary is the load-bearing output; downstream
    Formatter nodes read it.
  - When the question is a comparison (`fastest growing`, `largest`),
    emit a `comparison` key with `winner: <id>` and `reason: <short>`.
  - When the question's evidence is missing, set `fields: {}` and put
    the gap in `rationale`. Do not invent.

A Critic node may run after you. Its evaluation will fail if you
invented fields or made claims unsupported by the inputs.

USER_QUERY: Compare Top 3 HuggingFace Text-Generation Models Sorted By Likes

QUESTION: Extract model_name, param_count, description

INPUTS:
[
  {
    "id": "USER_QUERY",
    "kind": "query",
    "value": "Compare Top 3 HuggingFace Text-Generation Models Sorted By Likes"
  },
  {
    "id": "n:2",
    "kind": "upstream",
    "skill": "browser",
    "output": {
      "url": "https://huggingface.co/models?pipeline_tag=text-generation&library=transformers&sort=likes",
      "goal": "filter Tasks=Text Generation, Libraries=Transformers, Sort=Most Likes; then extract the top 3 model cards",
      "path": "a11y",
      "turns": 1,
      "content": "Top 3 models:\n1. deepseek-ai/DeepSeek-R1 (685B, 5.35M likes)\n2. meta-llama/Meta-Llama-3-8B (8B, 1.3M likes)\n3. meta-llama/Llama-3.1-8B-Instruct (8B, 1M+ likes)",
      "extracted_data": {
        "cost_summary": {
          "path": "a11y",
          "turns": 1,
          "input_tokens": 2172,
          "output_tokens": 188,
          "cost": 0.0,
          "wall_clock_time": 11.47706651687622
        }
      },
      "final_url": "https://huggingface.co/models?pipeline_tag=text-generation&library=transformers&sort=likes"
    }
  }
]"""
    res = LLM().chat(
        prompt=prompt,
        agent="distiller",
        session="s8-test",
        provider="gemini",
        max_tokens=2048,
        temperature=0.1
    )
    print("=== RAW LLM OUTPUT ===")
    print(res)

if __name__ == "__main__":
    asyncio.run(main())
