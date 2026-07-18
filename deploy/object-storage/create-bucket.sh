#!/bin/sh
# Idempotent MinIO bucket bootstrap for Accord local/deploy object storage
# (ADR 0010 §4). Runs inside the official `minio/mc` image (Alpine ash, not
# bash) as the `minio-init` one-shot compose service. Safe to run on every
# `docker compose up` — creates the bucket only if it does not already exist,
# and never fails the whole compose stack if the bucket is already there.
set -eu

: "${OBJECT_STORAGE_ENDPOINT:=http://minio:9000}"
: "${OBJECT_STORAGE_BUCKET:=accord-artifacts}"
: "${OBJECT_STORAGE_ACCESS_KEY:=minioadmin}"
: "${OBJECT_STORAGE_SECRET_KEY:=minioadmin}"

echo "[minio-init] configuring mc alias for $OBJECT_STORAGE_ENDPOINT"
mc alias set accord-minio "$OBJECT_STORAGE_ENDPOINT" "$OBJECT_STORAGE_ACCESS_KEY" "$OBJECT_STORAGE_SECRET_KEY"

if mc ls "accord-minio/$OBJECT_STORAGE_BUCKET" >/dev/null 2>&1; then
    echo "[minio-init] bucket '$OBJECT_STORAGE_BUCKET' already exists, skipping create"
else
    echo "[minio-init] creating bucket '$OBJECT_STORAGE_BUCKET'"
    mc mb "accord-minio/$OBJECT_STORAGE_BUCKET"
fi

# Private bucket only — application credentials access via OBJECT_STORAGE_*;
# no public/anonymous policy is ever applied (ADR 0010 §4: "Bucket is
# private; application credentials only").
mc anonymous set none "accord-minio/$OBJECT_STORAGE_BUCKET" || true

echo "[minio-init] bucket '$OBJECT_STORAGE_BUCKET' ready"
