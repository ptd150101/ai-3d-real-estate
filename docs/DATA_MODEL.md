# Data model

The SQLAlchemy model contains:

- Identity: `users`, `agencies`, `agents`.
- Inventory: `projects`, `properties`, `property_features`, `property_media`.
- 3D: `property_models_3d`, `property_floors`, `property_hotspots`.
- Trust: `property_documents`, verification and validity timestamps.
- Geography: property coordinates and `nearby_places`; a PostGIS GiST expression index supports radius search.
- Conversion: `appointments`, `leads`, `favorites`, `saved_searches`, `property_comparisons`.
- AI: `chat_sessions`, `chat_messages`, `knowledge_documents`, `knowledge_chunks`.
- Operations: `audit_logs`, `background_jobs`.

The API never stores images or GLBs in PostgreSQL. Object URLs and processing metadata are stored instead.
