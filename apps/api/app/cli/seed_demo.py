from __future__ import annotations

import argparse
import json

from ..database import Base, SessionLocal, engine
from ..seed import seed_database
from ..services.demo_seed import reset_demo_data, seed_demo_data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed the deterministic Nestora demo dataset")
    parser.add_argument("--preset", default="mvp", choices=["mvp"])
    parser.add_argument("--upsert", action="store_true", help="Compatibility flag; upsert is the default")
    parser.add_argument("--reset-demo", action="store_true", help="Remove only demo records before seeding")
    parser.add_argument("--force-assets", action="store_true", help="Rebuild media, nearby places and 3D metadata")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if args.reset_demo:
            reset_demo_data(db)
        result = seed_database(db)
        if args.force_assets:
            from sqlalchemy import select

            from ..models import User

            admin = db.scalar(select(User).where(User.email == "admin@nestora.vn"))
            if not admin:
                raise RuntimeError("Admin seed user was not created")
            result = seed_demo_data(
                db,
                admin=admin,
                preset=args.preset,
                force_assets=True,
            )
        db.commit()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
