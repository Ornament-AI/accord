# OpenAPI TypeScript runtime

This workspace exists only for `scripts/generate-api-types.sh`. Accord's
authoritative frontend compiler is the exact `typescript@7.0.2` dependency in
`frontend/package.json`.

TypeScript 7.0 intentionally does not expose the stable JavaScript compiler API
that `openapi-typescript@7.13.0` imports. The TypeScript team recommends running
TypeScript 7 alongside `@typescript/typescript6` for tools that still require
that API in its
[TypeScript 7.0 guidance](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/#running-side-by-side-with-typescript-6-0).

Keeping the compatibility runtime in this tooling-only workspace prevents it
from becoming the frontend's compiler or satisfying application dependencies.
Remove this workspace once `openapi-typescript` supports the TypeScript 7 API.
