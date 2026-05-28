# Agent Node Sandbox Runner Reachability

## Symptom

Agent nodes failed before or during sandbox-backed task execution even though the sandbox runner containers appeared healthy.

## What Was Checked

- Verified the agent execution path starts a sandbox session in `BaseNode.orchestrate` and routes sandbox tasks through `run_sandbox`.
- Probed `http://127.0.0.1:8771/health` and `http://127.0.0.1:8772/health` from the Windows host.
- Inspected the running Docker containers with `docker inspect`.

## Root Cause

The backend was configured to reach sandbox runners directly on host ports `8771` and `8772`, but in this environment those direct host publications were not reachable even after container recreation.

The sandbox runners themselves were healthy on the internal Docker network, so the failure was specifically the host-to-runner network path.

That meant agent nodes could not complete sandbox session setup or sandbox execution requests through the configured direct runner URLs.

## Fix

- Updated `start.sh` to start Docker services as part of the normal dev startup flow.
- Attached `nginx-internal` to the internal sandbox Docker network.
- Added internal proxy routes in `nginx-internal` for each sandbox runner shard.
- Switched backend sandbox runner base URLs to `http://127.0.0.1:8888/_sandbox/0` and `http://127.0.0.1:8888/_sandbox/1`.

This keeps the sandbox runners isolated on the internal Docker network while giving the host backend a stable reachable path.

## Validation

After the change, recreate `nginx-internal` and the sandbox runners, then verify:

```bash
curl --noproxy '*' http://127.0.0.1:8888/_sandbox/0/health
curl --noproxy '*' http://127.0.0.1:8888/_sandbox/1/health
```

Expected result:

- both health endpoints respond successfully through nginx-internal