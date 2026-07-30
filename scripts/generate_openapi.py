from __future__ import annotations
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps'/'api'))
from app.main import app
output=ROOT/'packages'/'contracts'/'openapi.json'
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(app.openapi(),ensure_ascii=False,indent=2),encoding='utf-8')
print(output)
