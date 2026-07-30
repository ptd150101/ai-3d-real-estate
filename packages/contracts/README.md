# API contracts

`openapi.json` is generated from the FastAPI application:

```bash
python scripts/generate_openapi.py
```

Frontend domain types are maintained in `apps/web/lib/types.ts`. A production pipeline can generate a typed client from this OpenAPI file and fail CI when the generated diff is not committed.
