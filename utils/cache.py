import json, os, time, pathlib
CACHE_DIR = pathlib.Path("cache"); CACHE_DIR.mkdir(exist_ok=True)

def get_cached(path:str, ttl_seconds:int):
    f = CACHE_DIR / path
    if f.exists() and (time.time() - f.stat().st_mtime) < ttl_seconds:
        with open(f, "r") as fh: return json.load(fh)
    return None

def set_cached(path:str, obj):
    f = CACHE_DIR / path
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "w") as fh: json.dump(obj, fh)
    return obj
import json, os, time, pathlib
CACHE_DIR = pathlib.Path("cache"); CACHE_DIR.mkdir(exist_ok=True)

def get_cached(path:str, ttl_seconds:int):
    f = CACHE_DIR / path
    if f.exists() and (time.time() - f.stat().st_mtime) < ttl_seconds:
        with open(f, "r") as fh: return json.load(fh)
    return None

def set_cached(path:str, obj):
    f = CACHE_DIR / path
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "w") as fh: json.dump(obj, fh)
    return obj
