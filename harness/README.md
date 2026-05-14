# Harness service definitions

Service + connector YAMLs for the 4 microservices in this repo, ready to
import into Harness CD.

```
harness/
├── connectors/
│   └── dockerhub.yaml        Docker Hub connector (public, anonymous)
└── services/
    ├── checkout.yaml         main / orchestrator       :8000
    ├── inventory.yaml        downstream                :8001
    ├── payment.yaml          downstream                :8002
    └── notification.yaml     downstream                :8003

../k8s/                       K8s manifests referenced by the service YAMLs
├── checkout/
│   ├── deployment.yaml       1 replica, image: <+artifact.image>
│   └── service.yaml          ClusterIP, name=checkout, port 8000
├── inventory/                ports 8001
├── payment/                  ports 8002
└── notification/             ports 8003
```

| File | Identifier | Role | Image |
| --- | --- | --- | --- |
| [services/checkout.yaml](services/checkout.yaml) | `checkout` | main / orchestrator | `docker.io/pritishharness/blast-radius-checkout:{1.0.0,1.0.1-broken}` |
| [services/inventory.yaml](services/inventory.yaml) | `inventory` | downstream | `docker.io/pritishharness/blast-radius-inventory:1.0.0` |
| [services/payment.yaml](services/payment.yaml) | `payment` | downstream | `docker.io/pritishharness/blast-radius-payment:1.0.0` |
| [services/notification.yaml](services/notification.yaml) | `notification` | downstream | `docker.io/pritishharness/blast-radius-notification:1.0.0` |

All scoped to **org `default`**, **project `Contextual_menace`**.
The `checkout` service has a `depends-on: inventory,payment,notification`
tag &mdash; the explicit edge for blast-radius tooling.

---

## End-to-end flow

```
1. docker login                                # one-time
2. ./scripts/build_and_push.sh                 # builds + pushes 5 images
3. Upload k8s/ manifests to Harness File Store # one-time, see Section 2
4. Apply harness/connectors/dockerhub.yaml     # one-time
5. Apply harness/services/*.yaml               # one-time
6. Run a Harness pipeline:
     - tag = 1.0.0          -> healthy deploy
     - tag = 1.0.1-broken   -> blast radius lights up
```

---

## 1. Build and push images

The build script lives at the repo root in [`scripts/build_and_push.sh`](../scripts/build_and_push.sh).
It produces five tags:

```
docker.io/pritishharness/blast-radius-inventory:1.0.0
docker.io/pritishharness/blast-radius-payment:1.0.0
docker.io/pritishharness/blast-radius-notification:1.0.0
docker.io/pritishharness/blast-radius-checkout:1.0.0
docker.io/pritishharness/blast-radius-checkout:1.0.1-broken      <-- bad deploy
```

The two checkout tags share source code; the broken one bakes
`SERVICE_VERSION=1.0.1-broken` and `BROKEN=1` into the image via
`ARG`s in `services/checkout/Dockerfile`. Same idea as a real bad
deploy: a discrete, immutable, taggable artifact.

```bash
docker login                              # docker hub creds
./scripts/build_and_push.sh               # build + push everything
PUSH=0 ./scripts/build_and_push.sh        # build only, no push
DOCKERHUB_USER=otheruser ./scripts/build_and_push.sh  # different account
```

The script uses `--platform linux/amd64` by default (override with
`PLATFORM=linux/arm64`); pick the architecture your Harness delegate /
target cluster uses.

---

## 2. Upload the K8s manifests

Each service's [`harness/services/*.yaml`](services/) references two
files in the project's **File Store**:

```
/blast-radius/<service>/deployment.yaml
/blast-radius/<service>/service.yaml
```

(These are the same files in [`../k8s/`](../k8s/) of this repo.)

Without them, the `K8sRollingDeploy` step fails with:

```
No manifests found in stage deploy. K8sRollingDeploy step
requires at least one manifest defined in stage service definition
```

### Option A &mdash; upload via Harness UI (fastest, no Git needed)

In the Harness UI for project `Contextual_menace`:

1. Go to **Project Settings** &rarr; **File Store**.
2. Create folder `blast-radius`.
3. Inside it create subfolders `checkout`, `inventory`, `payment`,
   `notification`.
4. In each subfolder, click **+ New File** twice:
   - Name `deployment.yaml`, paste contents of
     [`k8s/<service>/deployment.yaml`](../k8s/).
   - Name `service.yaml`, paste contents of
     [`k8s/<service>/service.yaml`](../k8s/).

Final layout:

```
File Store
└── blast-radius/
    ├── checkout/
    │   ├── deployment.yaml
    │   └── service.yaml
    ├── inventory/
    │   ├── deployment.yaml
    │   └── service.yaml
    ├── payment/
    │   ├── deployment.yaml
    │   └── service.yaml
    └── notification/
        ├── deployment.yaml
        └── service.yaml
```

### Option B &mdash; reference from Git instead

If you'd rather keep the manifests in this repo and have Harness pull
them at deploy time, replace the `manifests` block in each
`harness/services/<svc>.yaml` from:

```yaml
              store:
                type: Harness
                spec:
                  files:
                    - /blast-radius/<svc>/deployment.yaml
                    - /blast-radius/<svc>/service.yaml
```

to:

```yaml
              store:
                type: Github                       # or Bitbucket / Gitlab
                spec:
                  connectorRef: <your-git-connector>
                  gitFetchType: Branch
                  branch: main
                  paths:
                    - k8s/<svc>/deployment.yaml
                    - k8s/<svc>/service.yaml
                  repoName: <your-repo>            # only for account/org connectors
```

This needs a Git connector in the project. Push the repo somewhere
Harness can read, point the connector at it, and skip the File Store
step.

### What's in the manifests

- `<+artifact.image>` resolves to the full image path + tag picked
  during the pipeline run, so you don't have to template it manually.
- `<+serviceVariables.SERVICE_VERSION>`, `INVENTORY_URL`, `PAYMENT_URL`,
  `NOTIFICATION_URL`, `PORT` come from the service's `variables` block.
- The `K8s Service` is `name=<svc>` &mdash; same as the URLs in the
  `INVENTORY_URL` etc. variables (`http://inventory:8001`, ...) so
  cluster DNS resolves correctly out of the box, as long as all four
  services deploy into the same namespace.
- `BROKEN` is **not** set in the K8s `env`. The image tag bakes it in
  (`:1.0.1-broken` has `BROKEN=1` baked at Docker build time).
  Override only if you want to flip behaviour without rebuilding.

---

## 3. Apply the Harness YAMLs

### Option A &mdash; Harness UI

Connector first (services reference it by `connectorRef: dockerhub`):

1. **Connectors** &rarr; **+ New Connector** &rarr; click **YAML** &rarr;
   paste [`connectors/dockerhub.yaml`](connectors/dockerhub.yaml)
   &rarr; Save.

Then each service:

2. **Services** &rarr; **+ New Service** &rarr; click **YAML** &rarr;
   paste one of the files in [`services/`](services/) &rarr; Save.
3. Repeat for the other three.

### Option B &mdash; Git Experience

If your project's Git Experience is pointed at this repo, drop the
files under your configured `connectors/` and `services/` paths and
they will sync automatically.

### Option C &mdash; Harness API / curl

```bash
export HARNESS_ACCOUNT_ID=NjU5NDczNGEtMTE1My00Mz
export HARNESS_API_KEY=pat.xxx.yyy.zzz
export HARNESS_BASE=https://devday.harness.io

# Connector
curl -sS -X POST \
  "$HARNESS_BASE/ng/api/connectors?accountIdentifier=$HARNESS_ACCOUNT_ID" \
  -H "x-api-key: $HARNESS_API_KEY" \
  -H 'Content-Type: application/yaml' \
  --data-binary @harness/connectors/dockerhub.yaml

# Services
for f in harness/services/*.yaml; do
  curl -sS -X POST \
    "$HARNESS_BASE/ng/api/servicesV2?accountIdentifier=$HARNESS_ACCOUNT_ID" \
    -H "x-api-key: $HARNESS_API_KEY" \
    -H 'Content-Type: application/yaml' \
    --data-binary @"$f"
done
```

### Option D &mdash; Harness MCP from this agent

Once your MCP is pointed at the devday.harness.io account, the agent
can apply everything:

```
harness_create resource_type=connector body=<contents of connectors/dockerhub.yaml>
harness_create resource_type=service   body=<contents of services/<svc>.yaml>
```

(We tried this once already &mdash; the MCP this repo is wired to
points at `harness0.harness.io`, account `l7B_kbSEQD2wjrM7PShm5w`,
and `Contextual_menace` is in `devday.harness.io`, account
`NjU5NDczNGEtMTE1My00Mz`. Reconfigure to apply automatically.)

---

## 4. Use them in a pipeline

In your Stage's **Service** step, pick one of the four services. The
artifact tag is `<+input>` so the pipeline will prompt for it. Pass:

- `1.0.0` for the healthy deploy
- `1.0.1-broken` for the blast-radius deploy (checkout only)

After a `1.0.1-broken` deploy, the running checkout pod will:

1. Accept traffic, return `200` on `/health` (passes liveness probes).
2. Return `500` on `/checkout` after charging payment and reserving
   inventory but before notifying or committing.

That mismatch &mdash; a healthy-looking deploy that quietly corrupts
state in inventory and payment &mdash; is the blast radius the demo
puts on screen.

---

## What's intentionally left for you

- **Connector auth** &mdash; `Anonymous` because the images are public.
  Switch to `UsernamePassword` + a Harness secret if you make them
  private.
- **Image digest pinning** &mdash; the YAMLs deliberately omit the
  `digest:` field. **Don't add it back as `""` or `<+input>`** &mdash;
  if you do, Harness will fail the service step with
  `Artifact image SHA256 validation failed: image sha256 digest mismatch`
  even when the tag and image exist. Add `digest: sha256:<hex>` only
  when you want strict pinning to a known digest.
- **Cross-namespace deploys** &mdash; the manifests assume all four
  services land in the same namespace so DNS resolves
  `http://inventory:8001` etc. If you split them across namespaces,
  switch the URL service variables to FQDN form
  (`http://inventory.<ns>.svc.cluster.local:8001`).
- **Replicas / resources** &mdash; `replicas: 1` and tiny CPU/memory
  requests because this is a demo. Bump for anything real.
