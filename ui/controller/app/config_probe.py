from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def validate(manifest_path: Path) -> dict[str, object]:
    from src.pipeline.config import ConfigRepository

    first = ConfigRepository(manifest_path)
    environments = first.environment_names()
    profiles = first.profile_names()
    documents = []
    for environment in environments:
        repository = ConfigRepository(manifest_path, environment=environment)
        for profile in profiles:
            document = repository.profile(profile)
            documents.append({
                "environment": environment,
                "profile": profile,
                "sha256": document.sha256,
                "source_count": len(document.source_paths),
            })
    return {
        "status": "ok",
        "environments": list(environments),
        "profiles": list(profiles),
        "documents": documents,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    try:
        result = validate(Path(args.manifest).expanduser().resolve())
    except Exception as exc:
        result = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
