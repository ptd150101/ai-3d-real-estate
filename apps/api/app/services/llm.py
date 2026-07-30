from __future__ import annotations
import json
from typing import Any
import httpx
from ..config import get_settings
class LLMClient:
    def __init__(self):self.settings=get_settings()
    @property
    def enabled(self)->bool:return bool(self.settings.enable_llm and self.settings.llm_base_url and self.settings.llm_api_key)
    async def chat_json(self,messages:list[dict[str,str]],schema_hint:dict[str,Any]|None=None)->dict[str,Any]|None:
        if not self.enabled:return None
        payload={"model":self.settings.llm_model,"messages":messages,"temperature":0.1}
        if schema_hint:payload["response_format"]={"type":"json_object"}
        headers={"Authorization":f"Bearer {self.settings.llm_api_key}","Content-Type":"application/json"}
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response=await client.post(f"{self.settings.llm_base_url.rstrip('/')}/chat/completions",json=payload,headers=headers);response.raise_for_status();return json.loads(response.json()["choices"][0]["message"]["content"])
        except Exception:return None
