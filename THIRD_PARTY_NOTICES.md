# Third-party notices

The project's AGPL-3.0-only license covers its original application code and
documentation. It does not replace licenses or copyright notices belonging
to dependencies, public datasets or unmodified third-party archives.

## Main libraries

| Component | License | Upstream |
| --- | --- | --- |
| React / React DOM | MIT | https://github.com/facebook/react |
| Lucide icons | ISC | https://github.com/lucide-icons/lucide |
| Plotly.js / Plotly.py | MIT | https://github.com/plotly |
| Vite | MIT | https://github.com/vitejs/vite |
| TypeScript | Apache-2.0 | https://github.com/microsoft/TypeScript |
| FastAPI / Pydantic | MIT | https://github.com/fastapi/fastapi / https://github.com/pydantic/pydantic |
| pandas | BSD-3-Clause, with bundled third-party notices | https://github.com/pandas-dev/pandas |
| NumPy | BSD-3-Clause and bundled dependency licenses | https://github.com/numpy/numpy |
| openpyxl | MIT | https://foss.heptapod.net/openpyxl/openpyxl |
| HTTPX / Uvicorn | BSD-3-Clause | https://github.com/encode |
| ItsDangerous | BSD-3-Clause | https://github.com/pallets/itsdangerous |

Exact dependency versions are recorded in the npm lockfile and backend
requirements. This table highlights major components and is not a substitute
for each installed package's complete license and transitive notices.
Retain those notices when distributing installed environments or bundles.

## Unmodified vendored Python packages

Three official pure-Python wheels are included for reproducible dependency
installation. Each archive retains its original license files and metadata;
the archive bytes are checked by `deploy/wheels/SHA256SUMS`.

| Package | Version | License | Package and source |
| --- | --- | --- | --- |
| AnyIO | 4.15.1 | MIT | https://pypi.org/project/anyio/4.15.1/ ; https://github.com/agronholm/anyio |
| certifi | 2026.10.23 | MPL-2.0 | https://pypi.org/project/certifi/2026.10.23/ ; https://github.com/certifi/python-certifi |
| python-multipart | 0.0.32 | Apache-2.0 | https://pypi.org/project/python-multipart/0.0.32/ ; https://github.com/Kludex/python-multipart |

These packages are not relicensed under AGPL. Their original notices remain
inside the wheels. Their upstream repositories and PyPI source distributions
provide the corresponding unmodified sources. In particular, certifi and
its certificate material retain their MPL terms.

## Public dataset used in examples

The built-in Graduation examples contain aggregate statistics derived from:
Wang, Dongxuan (2025), “Graduation”, Mendeley Data, V1,
DOI [10.17632/c8ypkyswv3.1](https://data.mendeley.com/datasets/c8ypkyswv3/1),
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The derivative uses 253 records and 76 prepared fields: five career-guidance
columns and seven situation/policy columns were replaced by their respective
equal-weight means, with normalized headers. No rows were removed, imputed,
or standardized. Only aggregate snapshots, not student-level records, are
bundled under `backend/app/example_data/`. Preserve this attribution and
change notice when redistributing these snapshots. See
[case details](docs/explanatory-analysis.md).

Screenshots use **New York City Airbnb Open Data**, published on Kaggle by
`dgomonov`, version 3. The publisher credits Inside Airbnb as the original
source. No original CSV, ZIP, host-name records or private user datasets are
distributed in this repository.

Kaggle's dataset metadata labels the upload CC0. Inside Airbnb's current
data download page states CC BY 4.0. These are different source layers;
the project preserves attribution without asserting that today's upstream
terms independently establish the entire historical license chain.
See [dataset provenance and interpretation](docs/real-data-provenance.md).

- https://www.kaggle.com/datasets/dgomonov/new-york-city-airbnb-open-data
- https://insideairbnb.com/get-the-data/
- https://insideairbnb.com/data-assumptions/

Dataset facts and sample reports are not claims about current prices,
occupancy, transactions or causal effects. Software licensing does not
override rights or obligations associated with data you upload.

## Visual assets

The paper illustration and favicon are original SVG code included with the
application. The interface uses system fonts; no proprietary font files or
official brand image assets are bundled. Icon assets come from Lucide and
retain their ISC terms.
