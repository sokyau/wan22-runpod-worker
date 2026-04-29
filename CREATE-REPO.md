# Create This Worker Repo

GitHub repo:

```text
sokyau/wan22-runpod-worker
```

Recommended visibility:

```text
Public
```

Public is easiest because RunPod can pull the GHCR image without extra registry credentials. If you choose private, configure GHCR credentials in RunPod before creating the endpoint.

After the repo exists, push the contents of this folder as the repo root:

```text
projects/Formula&faith/AGENTES/MEDIA/export/formula-faith-wan22-runpod-worker/
```

Expected GHCR image after GitHub Actions succeeds:

```text
ghcr.io/sokyau/wan22-runpod-worker:latest
```

Do not add model weights to this repo.
