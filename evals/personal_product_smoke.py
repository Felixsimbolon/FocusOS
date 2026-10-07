"""Anonymous production verification for personal-product routes; no credentials or writes."""
import argparse
from uuid import uuid4
from hosted_smoke import status

def main():
 parser=argparse.ArgumentParser();parser.add_argument("--api",default="https://focusos-api.vercel.app");parser.add_argument("--web",default="https://focusos-web-five.vercel.app");args=parser.parse_args()
 id=uuid4()
 checks=[(args.web+path,"GET",{200}) for path in ("/", "/activity", "/tasks", "/schedule", "/system", "/memories")]
 checks += [(args.api+path,"GET",{401}) for path in ("/jobs","/product/export","/product/diagnostics","/product/focus-blocks")]
 checks += [(args.web+path,"GET",{401}) for path in ("/api/jobs","/api/product/export","/api/product/diagnostics")]
 checks += [(args.api+f"/product/focus-blocks/{id}/cancel","POST",{401}), (args.api+"/internal/jobs/tick","POST",{401,503})]
 for url,method,expected in checks:
  observed=status(url,method)
  print(f"{method} {url}: {observed}; expected {sorted(expected)}")
  if observed not in expected:raise SystemExit(1)
 print(f"Personal product smoke: {len(checks)}/{len(checks)} passed. No authenticated/provider acceptance claimed.")
if __name__=="__main__":main()
