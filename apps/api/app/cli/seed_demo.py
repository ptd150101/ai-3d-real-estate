from __future__ import annotations

import argparse
import json

from ..database import Base, SessionLocal, engine
from ..seed import seed_database
from ..services.demo_seed import reset_demo_data, seed_demo_data
from ..services.scale_seed import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_TOTAL_PROPERTIES,
    reset_scale_properties,
    seed_scale_properties,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed deterministic Nestora demo and scale datasets")
    parser.add_argument("--preset", default="mvp", choices=["mvp", "million"])
    parser.add_argument("--count", type=int, default=DEFAULT_TOTAL_PROPERTIES, help="Target total properties for the million preset")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Scale insert batch size; commits each batch so interrupted runs can resume")
    parser.add_argument("--upsert", action="store_true", help="Compatibility flag; upsert is the default")
    parser.add_argument("--reset-demo", action="store_true", help="Remove demo and scale mock records before seeding")
    parser.add_argument("--force-assets", action="store_true", help="Rebuild rich assets for the 72 showcase properties")
    return parser


def _progress(done: int, total: int) -> None:
    percent = (done / total * 100) if total else 100.0
    print(f"[scale-seed] {done:,}/{total:,} properties ({percent:.1f}%)", flush=True)


def main() -> None:
    args = build_parser().parse_args()
    if args.count <= 0:
        raise SystemExit("--count must be positive")
    if args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        scale_reset = 0
        if args.reset_demo:
            # Scale rows use their own prefix and are removed with one SQL DELETE,
            # so reset never materializes a million ORM objects in Python memory.
            scale_reset = reset_scale_properties(db)
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
                preset="mvp",
                force_assets=True,
            )

        if args.preset == "million":
            scale_result = seed_scale_properties(
                db,
                target_total=args.count,
                batch_size=args.batch_size,
                progress=_progress,
            )
            result = {**result, **scale_result}
        else:
            result = {"preset": "mvp", **result}

        if scale_reset:
            result["scale_reset"] = scale_reset
        db.commit()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
