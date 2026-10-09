# Third-party materials

The FolioLoom [LICENSE](LICENSE) applies only to material that the licensor
owns or is authorized to license. It does not relicense dependencies,
third-party content or another author's contribution. Preserve existing
attribution and comply with the applicable upstream terms.

## Direct Python dependencies

The following is a licensing overview for dependencies declared in
`pyproject.toml`, based on upstream package metadata reviewed on 2026-10-10.
It is not a complete set of redistribution notices. Dependency requirements
are not pinned; the licenses and bundled components of the exact versions
being shipped must be checked before distributing an installation or image.

| Package | Reported license | Upstream package and license metadata |
| --- | --- | --- |
| aiogram | MIT | https://pypi.org/project/aiogram/ |
| fastapi | MIT | https://pypi.org/project/fastapi/ |
| python-multipart | Apache-2.0 | https://pypi.org/project/python-multipart/ |
| httpx | BSD-3-Clause | https://pypi.org/project/httpx/ |
| cryptography | Apache-2.0 OR BSD-3-Clause | https://pypi.org/project/cryptography/ |
| psutil | BSD-3-Clause | https://pypi.org/project/psutil/ |
| uvicorn | BSD-3-Clause | https://pypi.org/project/uvicorn/ |
| pydantic | MIT | https://pypi.org/project/pydantic/ |
| redis (Python client) | MIT | https://pypi.org/project/redis/ |
| psycopg | LGPL-3.0-only | https://pypi.org/project/psycopg/ |
| rq | BSD-2-Clause | https://pypi.org/project/rq/ |
| pytest (development) | MIT | https://pypi.org/project/pytest/ |
| ruff (development) | MIT | https://pypi.org/project/ruff/ |

Extras such as `uvicorn[standard]` and `psycopg[binary]`, their bundled
libraries and other transitive dependencies have their own notices and
obligations. In particular, distributing Psycopg or a combined installation
requires review of the applicable LGPL requirements; the FolioLoom license
does not restrict rights granted under the LGPL.

## Runtime services and images

The Python base image and the PostgreSQL, Redis and ClamAV images referenced
in `Dockerfile` and `docker-compose.yml` are separate third-party components.
They are not covered by the FolioLoom license. The Redis client entry above
does not describe the Redis server license. Retain and review upstream
notices and source-availability obligations for the exact images distributed.

## Fixtures, images and external documents

The synthetic EPUB fixture is documented in `test_samples/rights-manifest.json`.
Project-created fixtures and images fall under LICENSE only to the extent
the licensor holds the relevant rights. External books, manuscripts, document
content, third-party assets visible in images and separately licensed content
retain their own rights and conditions. A code license does not grant rights
to translate or distribute someone else's document.
