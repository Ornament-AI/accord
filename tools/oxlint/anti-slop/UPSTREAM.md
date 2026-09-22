# Upstream provenance

- Source: https://github.com/dmmulroy/anti-slop
- Source commit: `c44ef22ca116d0ba62a3ff663a0bd13a3f3fa40b`
- Installed paths: `tools/oxlint/anti-slop/index.ts`, `tools/oxlint/anti-slop/rules/`, `tools/oxlint/anti-slop/shared/`, `tools/oxlint/anti-slop/effect/`, and `tools/oxlint/anti-slop/vendor/`
- Installer: `skills/install-anti-slop/scripts/install.mjs` from the source commit above
- Intentional deviations: the optional Effect rules are vendored but not registered because this repository does not directly depend on Effect. Generated API types at `frontend/src/types/api.generated.ts` are excluded from policy lint; the repository generates and verifies that file separately. A local `package.json` marks the vendored TypeScript plugin as an ES module without changing the application package type.
