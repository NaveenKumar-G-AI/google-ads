#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,subprocess,urllib.request,urllib.parse

def token()->str:return subprocess.check_output(["gcloud","auth","print-access-token"],text=True).strip()
def request(url:str,*,method="GET",body=None):
    raw=None if body is None else json.dumps(body).encode();req=urllib.request.Request(url,data=raw,method=method,headers={"Authorization":f"Bearer {token()}","Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=60) as r:
        data=r.read();return json.loads(data) if data else {}
def main()->None:
    p=argparse.ArgumentParser();p.add_argument("--project",required=True);p.add_argument("--region",required=True);p.add_argument("--worker-pool",default="recovery-worker");p.add_argument("--port",type=int,default=8080);p.add_argument("--apply",action="store_true");a=p.parse_args()
    if not 1<=a.port<=65535:raise SystemExit("--port must be 1..65535")
    name=f"projects/{a.project}/locations/{a.region}/workerPools/{a.worker_pool}";base=f"https://run.googleapis.com/v2/{name}";pool=request(base);containers=list((pool.get("template") or {}).get("containers") or [])
    if not containers:raise SystemExit("worker pool has no containers")
    c=dict(containers[0]);c["ports"]=[{"containerPort":a.port}];c["startupProbe"]={"httpGet":{"path":"/startup","port":a.port},"timeoutSeconds":2,"periodSeconds":5,"failureThreshold":24};c["livenessProbe"]={"httpGet":{"path":"/health","port":a.port},"timeoutSeconds":2,"periodSeconds":20,"failureThreshold":3};containers[0]=c
    body={"name":name,"template":{"containers":containers}};q=urllib.parse.urlencode({"updateMask":"template.containers","validateOnly":"false" if a.apply else "true","forceNewRevision":"true"});out=request(base+"?"+q,method="PATCH",body=body);print(json.dumps({"applied":a.apply,"worker_pool":name,"port":a.port,"operation":out.get("name"),"done":out.get("done",False)},indent=2))
if __name__=="__main__":main()
