"""Bounded scheduler runner. Secret stays in env; no session/provider data is printed."""
import argparse
import os
from urllib.parse import urlparse
import httpx

def drain(api: str, secret: str, max_steps: int = 20) -> int:
    parsed=urlparse(api)
    if parsed.scheme!="https" and not (parsed.scheme=="http" and parsed.hostname in ("localhost","127.0.0.1")):
        raise ValueError("Use HTTPS for a remote worker endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or len(secret)<32:
        raise ValueError("Worker configuration invalid")
    count=0
    with httpx.Client(timeout=70,follow_redirects=False) as client:
        for _ in range(max_steps):
            response=client.post(api.rstrip("/")+"/internal/jobs/tick",headers={"Authorization":"Bearer "+secret})
            if response.status_code!=200: raise RuntimeError("Worker request failed: HTTP "+str(response.status_code))
            state=response.json().get("state")
            if state=="idle": break
            count+=1
    return count

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--api",default=os.environ.get("FOCUSOS_API_URL",""));parser.add_argument("--max-steps",type=int,default=20)
    args=parser.parse_args()
    if not 1<=args.max_steps<=40: parser.error("max steps must be 1-40")
    try: count=drain(args.api,os.environ.get("FOCUSOS_WORKER_SECRET",""),args.max_steps)
    except Exception as exc:
        print("Worker stopped: "+type(exc).__name__);raise SystemExit(1)
    print("Worker steps attempted: "+str(count))
if __name__=="__main__":main()
