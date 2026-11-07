# EKS deployment guide

This is the production path for the reference product. It assumes an AWS account with permissions to create VPC, EKS, RDS, S3 and IAM resources.

## 1. Provision the cluster

```bash
eksctl create cluster -f deploy/eks/cluster.yaml
aws eks update-kubeconfig --name meridian --region us-east-1
```

The cluster uses three managed node groups: `system` (on-demand), `platform` (on-demand) and `batch-spot` (spot, tainted). Add Karpenter or Cluster Autoscaler if you want scale-to-zero batch nodes; the reference deployment does not require it because workers are stateless and queue-driven.

## 2. Provision data services

**RDS PostgreSQL** (Multi-AZ in production):

```bash
aws rds create-db-instance \
  --db-instance-identifier meridian \
  --db-instance-class db.r6g.large \
  --engine postgres --engine-version 16.4 \
  --allocated-storage 200 --storage-encrypted \
  --master-username meridian --manage-master-user-password \
  --backup-retention-period 35 --multi-az \
  --vpc-security-group-ids REPLACE_SG
```

Use the managed password secret ARN with External Secrets Operator, or store the complete DSN in AWS Secrets Manager under `meridian/database-url`.

**S3 lake bucket**:

```bash
aws s3api create-bucket --bucket REPLACE-meridian-lake --region us-east-1
aws s3api put-public-access-block --bucket REPLACE-meridian-lake \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket REPLACE-meridian-lake --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket REPLACE-meridian-lake \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"REPLACE_KEY_ID"}}]}'
```

**EFS** for shared run logs and uploaded files:

```bash
aws efs create-file-system --creation-token meridian --encrypted --performance-mode generalPurpose
# create mount targets in each private subnet, then:
kubectl apply -f deploy/eks/storageclass-efs.yaml
```

The API reads per-run JSONL logs from the shared volume. In a larger deployment, ship JSONL to Loki/OpenSearch and remove the PVC dependency.

## 3. Platform add-ons

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add jetstack https://charts.jetstack.io
helm repo add external-secrets https://charts.external-secrets.io

helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace
helm upgrade --install cert-manager jetstack/cert-manager -n cert-manager --create-namespace --set crds.enabled=true
helm upgrade --install external-secrets external-secrets/external-secrets -n external-secrets --create-namespace

# OpenTelemetry collector + Prometheus + Jaeger are optional; point MERIDIAN_OTEL_EXPORTER_OTLP_ENDPOINT at your collector.
```

## 4. IAM for the platform (IRSA)

```bash
aws iam create-policy --policy-name MeridianLakeAccess \
  --policy-document file://deploy/eks/iam-policy.json

eksctl create iamserviceaccount \
  --cluster meridian --region us-east-1 \
  --namespace meridian --name meridian-platform \
  --attach-policy-arn arn:aws:iam::ACCOUNT:policy/MeridianLakeAccess \
  --approve --override-existing-serviceaccounts
```

The service account annotation in `deploy/k8s/serviceaccounts.yaml` must match the role ARN. Do not put access keys in Kubernetes Secrets when IRSA is available.

## 5. Secrets

Create `meridian/database-url` and `meridian/jwt-secret` in AWS Secrets Manager. Sync them with an `ExternalSecret` into `meridian-secrets`:

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: meridian-secrets
  namespace: meridian
spec:
  refreshInterval: 1h
  secretStoreRef: { name: aws-secretsmanager, kind: ClusterSecretStore }
  target: { name: meridian-secrets }
  data:
    - { secretKey: MERIDIAN_DATABASE_URL, remoteRef: { key: meridian/database-url } }
    - { secretKey: MERIDIAN_JWT_SECRET, remoteRef: { key: meridian/jwt-secret } }
```

Do not apply `deploy/k8s/secret.example.yaml` in production.

## 6. Build and push images

```bash
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export REGISTRY=$ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com
aws ecr create-repository --repository-name meridian/api --image-scanning-configuration scanOnPush=true
aws ecr create-repository --repository-name meridian/web --image-scanning-configuration scanOnPush=true
aws ecr get-login-password | docker login --username AWS --password-stdin $REGISTRY

docker build -f services/platform-api/Dockerfile -t $REGISTRY/meridian/api:0.1.0 .
docker build -f apps/web/Dockerfile \
  --build-arg NEXT_PUBLIC_API_URL=https://meridian.example.com \
  --build-arg NEXT_PUBLIC_WS_URL=wss://meridian.example.com \
  -t $REGISTRY/meridian/web:0.1.0 apps/web

docker push $REGISTRY/meridian/api:0.1.0
docker push $REGISTRY/meridian/web:0.1.0
```

## 7. Deploy

Edit the placeholders in `deploy/k8s/configmap.yaml`, `pvc.yaml`, `serviceaccounts.yaml`, `ingress.yaml`, then:

```bash
kubectl apply -k deploy/k8s
kubectl -n meridian rollout status deploy/meridian-api
kubectl -n meridian rollout status deploy/meridian-worker
kubectl -n meridian rollout status deploy/meridian-scheduler
kubectl -n meridian rollout status deploy/meridian-web
```

If you use a different registry, run `kustomize edit set image ghcr.io/REPLACE_ORG/meridian-api=$REGISTRY/meridian/api:0.1.0` inside `deploy/k8s`.

## 8. DNS and TLS

Point `meridian.example.com` at the ingress-nginx load balancer. cert-manager issues the certificate for `meridian-tls`. The ingress routes `/api/*`, `/health*` and `/docs*` to the API and everything else to Next.js, so browser calls stay same-origin.

## 9. Verify

```bash
curl -fsS https://meridian.example.com/health/ready
curl -fsS https://meridian.example.com/metrics | head
kubectl -n meridian get pods,hpa,pdb
kubectl -n meridian logs deploy/meridian-worker --tail=20
```

Sign in with the IdP configured in `MERIDIAN_OIDC_ISSUER`. The OIDC user must be provisioned in the `users` table (via SCIM sync or an admin bootstrap job); the design package describes the production SCIM flow.

## Scaling notes

- API: HPA on CPU/memory, 2–12 replicas. Stateless; metadata in RDS.
- Worker: HPA on CPU, 2–30 replicas. Tasks are leased with `FOR UPDATE SKIP LOCKED`; start more replicas for backlog.
- Scheduler: one replica with a Postgres advisory lock; two replicas are safe but unnecessary.
- Web: 2 replicas behind the ingress.
- For large Spark/dbt jobs, replace in-process transforms with Argo Workflows / Spark Operator as described in the design docs; the DAG contract stays the same.
- For per-tenant isolation, create a namespace and KMS key per tenant; the current reference runs one tenant per deployment.
