"""LLM 연결 — Claude(Anthropic) · OpenAI · Ollama(로컬) · 없음.

.env 의 LLM_PROVIDER 로 전환. 숫자 계산은 하지 않고 도구 선택·문장 작성만 담당.
"""
from __future__ import annotations

import json
import os

from tools.registry import schema_for

DEFAULTS = {
    "anthropic": "claude-haiku-5-5",
    "openai": "gpt-4o-mini",
    "ollama": "qwen2.5:3b",
}


def config() -> dict:
    prov = os.getenv("LLM_PROVIDER", "none").lower()
    return {
        "provider": prov,
        "model": os.getenv("LLM_MODEL") or DEFAULTS.get(prov, ""),
        "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434/v1"),
    }


class LLM:
    """도구 호출 1회분 대화 인터페이스. step() → ('tools', [(id,name,args)]) 또는 ('text', 문자열)."""

    def __init__(self, system: str):
        c = config()
        self.provider, self.model, self.system = c["provider"], c["model"], system
        self.messages: list = []
        if self.provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic(timeout=40)
            self.tools = schema_for("anthropic")
        elif self.provider in ("openai", "ollama"):
            from openai import OpenAI
            if self.provider == "ollama":
                self.client = OpenAI(base_url=c["ollama_url"], api_key="ollama", timeout=120)
            else:
                self.client = OpenAI(timeout=40)
            self.tools = schema_for("openai")
            self.messages.append({"role": "system", "content": system})
        else:
            raise RuntimeError("LLM 미설정 (LLM_PROVIDER=none)")

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"

    def user(self, text: str):
        self.messages.append({"role": "user", "content": text})

    def step(self):
        if self.provider == "anthropic":
            r = self.client.messages.create(model=self.model, max_tokens=1200, system=self.system,
                                            tools=self.tools, messages=self.messages)
            self.messages.append({"role": "assistant", "content": r.content})
            calls = [(b.id, b.name, b.input) for b in r.content if b.type == "tool_use"]
            if calls:
                return "tools", calls
            return "text", "".join(b.text for b in r.content if b.type == "text")
        r = self.client.chat.completions.create(model=self.model, messages=self.messages, tools=self.tools, temperature=0.2)
        m = r.choices[0].message
        self.messages.append(m.model_dump(exclude_none=True))
        if m.tool_calls:
            calls = []
            for tc in m.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                calls.append((tc.id, tc.function.name, args))
            return "tools", calls
        return "text", m.content or ""

    def tool_results(self, results: list[tuple[str, str]]):
        """results: [(call_id, json 문자열)]"""
        if self.provider == "anthropic":
            self.messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": cid, "content": out} for cid, out in results]})
        else:
            for cid, out in results:
                self.messages.append({"role": "tool", "tool_call_id": cid, "content": out})
