from __future__ import annotations
import threading,time
from collections import defaultdict,deque
from ..config import get_settings
class SlidingWindowRateLimiter:
    def __init__(self,limit:int,window_seconds:int=60):
        self.limit=limit;self.window_seconds=window_seconds;self._events=defaultdict(deque);self._lock=threading.Lock();self.redis=None
        try:
            import redis
            self.redis=redis.Redis.from_url(get_settings().redis_url,decode_responses=True,socket_connect_timeout=0.2,socket_timeout=0.2);self.redis.ping()
        except Exception:self.redis=None
    def allow(self,key:str)->bool:
        now=time.time()
        if self.redis:
            redis_key=f"rate:{key}"
            try:
                with self.redis.pipeline(transaction=True) as pipe:
                    pipe.zremrangebyscore(redis_key,0,now-self.window_seconds);pipe.zcard(redis_key);pipe.zadd(redis_key,{f"{now:.6f}":now});pipe.expire(redis_key,self.window_seconds+1);results=pipe.execute()
                if int(results[1])>=self.limit:self.redis.zrem(redis_key,f"{now:.6f}");return False
                return True
            except Exception:self.redis=None
        monotonic=time.monotonic()
        with self._lock:
            queue=self._events[key]
            while queue and queue[0]<=monotonic-self.window_seconds:queue.popleft()
            if len(queue)>=self.limit:return False
            queue.append(monotonic);return True
