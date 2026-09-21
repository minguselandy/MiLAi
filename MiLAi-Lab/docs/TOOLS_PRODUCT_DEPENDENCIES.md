# Active Tools → Product Dependency Boundary

The machine-readable inventory is
[`tools-product-dependencies.json`](tools-product-dependencies.json). It covers active Python
files under `tools/`; immutable material under `studies/archive/` is outside this gate.

The inventory currently records 10 files and 18 file/module dependencies:

- `PUBLIC`: 11 dependencies through explicit Product package entry points.
- `TESTKIT`: no current dependency; `milai.testkit` is the only approved prefix.
- `LEGACY_PRIVATE`: 6 exact file/module dependencies retained for existing harnesses.

`LEGACY_PRIVATE` is a grandfathered state, not approval for the package prefix. The same module
imported from another tool fails the gate. A submodule beneath a public root also fails unless that
exact submodule is classified as public or testkit. Static imports, `__import__(...)`, and literal
`importlib.import_module(...)` calls are scanned.

Run the gate from the Lab root:

```bash
uv run milai-lab-check-tools-boundary
```

Any intentional public/testkit dependency change must update the inventory in the same PR. A new
private dependency is not an inventory refresh: it requires a separate boundary decision and a
public or Product testkit contract. Existing private dependencies should be removed from both the
source and grandfather list when their replacement contracts are available.
