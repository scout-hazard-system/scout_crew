# Third-party and companion licenses

**License:** Apache License, Version 2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).

The original source code in this repository is licensed under **Apache License,
Version 2.0**. The full license text is in [`../LICENSE`](../LICENSE).

Attribution and third-party notices are summarized in [`../NOTICE`](../NOTICE).

## Important separation of rights

1. **Repository source code** is Apache-2.0.
2. **Model weights** (for example Llama, Qwen, or other Ollama models) are
   licensed separately by their publishers. Distributing or serving those
   weights requires compliance with each model license.
3. **Map data from OpenStreetMap**, when used by companion navigation
   components, remains under the **ODbL 1.0** and requires OSM attribution.
4. **System dependencies** (CrewAI, Qt/PySide6, and others) retain their
   upstream licenses.

When preparing a distribution package for grant reporting or external release,
include:

- `LICENSE`
- `NOTICE`
- this `LICENSES/` directory
- a generated dependency license inventory from the release environment
