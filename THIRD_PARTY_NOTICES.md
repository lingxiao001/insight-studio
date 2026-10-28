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

## Public datasets used in examples

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

### Hotel booking demand

The city-hotel and resort-hotel cancellation examples derive from
**Hotel booking demand**, published by Jesse Mostipak on Kaggle, version 1:
[Kaggle source](https://www.kaggle.com/datasets/jessemostipak/hotel-booking-demand).
The original data article is Nuno Antonio, Ana de Almeida, and Luis Nunes
(2019), “Hotel booking demand datasets”, *Data in Brief* 22, 41–49,
DOI [10.1016/j.dib.2018.11.126](https://doi.org/10.1016/j.dib.2018.11.126),
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The Kaggle description additionally credits Thomas Mock and Antoine Bichat
for the TidyTuesday CSV compilation.

The derivative selects the complete existing City Hotel population of
79,330 bookings and Resort Hotel population of 40,060 bookings as two
separate cases. It removes agency/company identifiers and outcome-time
fields from explanatory candidates, while preserving each selected
population's records and cancellation target. The public snapshots contain
aggregates, not booking-level rows. The cases describe the two historical
hotels, not all city or resort hotels, and do not estimate intervention effects.

### Default of Credit Card Clients

The credit-card example derives from **Default of Credit Card Clients
Dataset**, published by UCI Machine Learning on Kaggle, version 1:
[Kaggle source](https://www.kaggle.com/datasets/uciml/default-of-credit-card-clients-dataset).
The original repository citation is I-Cheng Yeh (2009), “Default of Credit
Card Clients”, UCI Machine Learning Repository,
DOI [10.24432/C55S3H](https://doi.org/10.24432/C55S3H), with the associated
research by I-Cheng Yeh and Che-hui Lien.

Kaggle labels the uploaded version CC0; the
[original UCI repository](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients)
currently labels the dataset
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The project discloses both source layers and retains original attribution;
it does not assert that the Kaggle label overrides upstream rights.
The derivative preserves all 30,000 records, removes the client ID, and
treats demographic and repayment codes according to their documented
meaning rather than as arbitrary continuous values. Only aggregate
statistics are bundled. No customer-level records or operational credit
decisions are published.

### Heart Failure Clinical Records

The clinical follow-up example derives from **Heart Failure Prediction**,
published on Kaggle by Larxel (`andrewmvd`), version 1:
[Kaggle source](https://www.kaggle.com/datasets/andrewmvd/heart-failure-clinical-data).
Kaggle and the
[original UCI repository](https://archive.ics.uci.edu/dataset/519/heart+failure+clinical+records)
identify [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The repository DOI is [10.24432/C5Z89R](https://doi.org/10.24432/C5Z89R).
Credit Davide Chicco and Giuseppe Jurman (2020), “Machine learning can
predict survival of patients with heart failure from serum creatinine and
ejection fraction alone”, *BMC Medical Informatics and Decision Making* 20,
16, DOI [10.1186/s12911-020-1023-5](https://doi.org/10.1186/s12911-020-1023-5),
and the original clinical data collection by Ahmad and colleagues (2017).

The derivative preserves all 299 patient records locally for computation,
while excluding follow-up duration as an admission-time explanatory
candidate. It publishes only aggregated descriptive statistics and
interpretation limits. Patient-level records, individual points, diagnosis,
treatment recommendations, and individual prognoses are not included.

### Netflix Movies and TV Shows

The catalogue and movie-length examples derive from **Netflix Movies and
TV Shows**, published by Shivam Bansal on Kaggle, version 5, labelled CC0:
[Kaggle source](https://www.kaggle.com/datasets/shivamb/netflix-shows).
The derivative uses all 8,807 catalogue records and the complete 6,131-movie
subset for the two respective questions. It parses only `duration` values
matching a numeric minute count into movie length, leaving three missing
movie durations unfilled (6,128 valid values). Three duration strings
incorrectly stored in `rating` are marked as missing classifications; they
are not used to repair movie duration. Public snapshots omit title-level
text, cast and director names, descriptions, and raw records. The examples
describe a historical catalogue, not current availability, viewer demand,
ratings, or revenue.

All four sources' fixed versions, original-file checksums, transformations,
scope, and reproducible aggregate checks are documented in
[cross-domain examples](docs/cross-domain-examples.md).
Preserve these source attributions and change notices when redistributing
the derived public snapshots. The software license does not relicense
the source datasets.

## Visual assets

The paper illustration and favicon are original SVG code included with the
application. The interface uses system fonts; no proprietary font files or
official brand image assets are bundled. Icon assets come from Lucide and
retain their ISC terms.
