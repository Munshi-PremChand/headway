# Infrastructure — provisioned and proven

Project `headway-atah-2026`, organisation `<organisation>`, billing `<billing-account-id>`
(`billingEnabled: true`). Provisioned 2026-08-27.

## The security claim, and its proof

HEADWAY's architectural claim is that **a hallucination cannot reach the outside world**, because the
component that talks to a model has no permission to write anything, and the component that writes has no
access to a model. That is enforced by IAM, not by a prompt.

| Service account | Role | Can | Cannot |
|---|---|---|---|
| `sa-reader` | `roles/aiplatform.user` | call Gemini on Vertex | **write any bucket** |
| `sa-publisher` | `roles/storage.objectAdmin` | write the feed bucket | **call Vertex at all** |
| `sa-composer` | `roles/datastore.user` | read/write the claim ledger | call Vertex, write buckets |

### Measured proof, 2026-08-27

```
$ gcloud storage cp probe.txt gs://headway-atah-2026-feeds/probe.txt \
    --impersonate-service-account=sa-publisher@headway-atah-2026.iam.gserviceaccount.com
  → succeeded

$ gcloud storage cp probe.txt gs://headway-atah-2026-feeds/should-not-exist.txt \
    --impersonate-service-account=sa-reader@headway-atah-2026.iam.gserviceaccount.com
  → ERROR: HTTPError 403: sa-reader@headway-atah-2026.iam.gserviceaccount.com does not have
    storage.objects.get access to the Google Cloud Storage object. Permission denied on resource
    '//storage.googleapis.com/projects/_/buckets/headway-atah-2026-feeds/objects/should-not-exist.txt'

$ gcloud storage ls gs://headway-atah-2026-feeds/
  gs://headway-atah-2026-feeds/probe.txt        ← should-not-exist.txt is genuinely absent
```

This is the demo artifact. Not a diagram of a boundary — the boundary refusing, in Google's own words,
with the bucket listing as the receipt.

**Note on reproducing it:** IAM binding propagation took **4 retries at 20-second intervals** (~80s) before
impersonation worked. A first attempt fails with "Failed to impersonate", which is a *different* error from
the deny and must not be mistaken for it. Budget for propagation before filming.

## Resources

| Resource | Value |
|---|---|
| Project | `headway-atah-2026` |
| Organisation | `<organisation>` (`520136476995`) |
| Billing | `<billing-account-id>` |
| Feed bucket | `gs://headway-atah-2026-feeds` (asia-south1, uniform access) |
| Vertex location | **`global`** — host `aiplatform.googleapis.com`, path `locations/global` |

APIs enabled: `aiplatform` · `run` · `firestore` · `pubsub` · `storage` · `secretmanager` · `cloudbuild` ·
`artifactregistry` · `cloudtrace` · `logging` · `generativelanguage` · `bigquerystorage`.

## Bucket region

`asia-south1` (Mumbai) — chosen because the target operators are Indian and the feed should be served near
its riders. It is also a small, true detail that supports the project's framing.

## Still outstanding

- **Application Default Credentials.** `gcloud auth application-default login` has not been run, and there
  is no ADC file. Raw REST calls with `gcloud auth print-access-token` work (that is how the live Gemini
  call was made), but `google-genai`, `google-cloud-storage` and `google-cloud-firestore` read ADC and will
  fail without it. Either run that command, or point `GOOGLE_APPLICATION_CREDENTIALS` at a service-account
  key.
- Cloud Run services are not deployed yet.
- Firestore database not created yet (`gcloud firestore databases create`).
