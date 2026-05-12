"""
Publishing-memory workflow CLI.

Commands:
  python publishing_memory.py auth
  python publishing_memory.py status
  python publishing_memory.py sync-channel
  python publishing_memory.py mark-published --run-id <run_id> --youtube-video-id <video_id>
"""

from __future__ import annotations

import argparse
import json

from config.paths import MEMORY_DIR
from pipelines.layer_10_memory_learning.publish_state_updater import mark_run_as_published
from pipelines.layer_10_memory_learning.publishing_channel_sync import sync_channel_state
from pipelines.layer_10_memory_learning.youtube_publishing_auth import (
    authorization_status,
    ensure_credentials,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publishing-memory workflow")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show local OAuth credential/token status")
    auth_parser = sub.add_parser("auth", help="Run interactive OAuth authorization for the publishing channel")
    auth_parser.add_argument("--no-browser", action="store_true")

    sync_parser = sub.add_parser("sync-channel", help="Sync authenticated publishing-channel state and inventory")
    sync_parser.add_argument("--max-videos", type=int, default=None)
    sync_parser.add_argument("--no-analytics", action="store_true")

    publish_parser = sub.add_parser("mark-published", help="Mark a prepared run as published and rebuild memory")
    publish_parser.add_argument("--run-id", required=True)
    publish_parser.add_argument("--youtube-video-id", required=True)
    publish_parser.add_argument("--published-at", default=None)
    publish_parser.add_argument("--video-url", default=None)
    publish_parser.add_argument("--no-analytics", action="store_true")

    args = parser.parse_args()

    if args.command == "status":
        print(json.dumps(authorization_status(), indent=2))
        return

    if args.command == "auth":
        creds = ensure_credentials(interactive=True, open_browser=not args.no_browser)
        print(json.dumps({
            "status": "authorized",
            "scopes": list(creds.scopes or []),
        }, indent=2))
        return

    if args.command == "sync-channel":
        result = sync_channel_state(
            memory_dir=MEMORY_DIR,
            interactive=True,
            max_videos=args.max_videos,
            sync_analytics_for_mapped_videos=not args.no_analytics,
        )
        print(json.dumps(result, indent=2))
        return

    if args.command == "mark-published":
        result = mark_run_as_published(
            run_id=args.run_id,
            youtube_video_id=args.youtube_video_id,
            published_at=args.published_at,
            video_url=args.video_url,
            interactive=True,
            memory_dir=MEMORY_DIR,
            sync_analytics=not args.no_analytics,
        )
        print(json.dumps(result, indent=2))
        return


if __name__ == "__main__":
    main()
