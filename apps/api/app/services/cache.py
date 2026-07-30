from __future__ import annotations
import json
from typing import Any
from ..config import get_settings
class Cache:
    def __init__(self):
        self.client = None
        try:
            import redis
            self.client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True, socket_connect_timeout=0.2, socket_timeout=0.2); self.client.ping()
        except Exception: self.client = None
    def get_json(self,key:str)->Any|None:
        if not self.client:return None
        try:
            raw=self.client.get(key); return json.loads(raw) if raw else None
        except Exception:return None
    def set_json(self,key:str,value:Any,ttl:int=60)->None:
        if not self.client:return
        try:self.client.setex(key,ttl,json.dumps(value,ensure_ascii=False,default=str))
        except Exception:pass
    def delete_prefix(self,prefix:str)->None:
        if not self.client:return
        try:
            for key in self.client.scan_iter(f"{prefix}*"):self.client.delete(key)
        except Exception:pass
cache=Cache()
