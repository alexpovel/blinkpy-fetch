"""Download Blink videos.

This script downloads videos from Blink cameras. It requires the following environment
variables to be set: BLINK_USERNAME, as your Blink username. BLINK_PASSWORD, as your
Blink password. BLINK_UID, as the Blink client UID (optional). See also
https://github.com/MattTW/BlinkMonitorProtocol/blob/2c9d7546b3b9ca1bd64969abc7d6f8d0966628d3/auth/login.md.
On initial run, no UID is available. An interactive prompt will be shown to complete
auth via MFA flow. The used UID will be printed. Subsequent runs can use this UID to
skip MFA, by specifying it as the BLINK_UID environment variable.
"""

import argparse
import asyncio
import datetime
import logging
import os
from pathlib import Path

from aiohttp import ClientSession
from blinkpy.auth import Auth
from blinkpy.blinkpy import Blink, BlinkSyncModule
from sortedcontainers import SortedSet

logging.basicConfig(level=logging.INFO)


async def init(session: ClientSession) -> Blink:
    username = os.getenv("BLINK_USERNAME")
    if not username:
        raise ValueError("Please set the BLINK_USERNAME environment variable")

    password = os.getenv("BLINK_PASSWORD")
    if not password:
        raise ValueError("Please set the BLINK_PASSWORD environment variable")

    # Base login data
    login_data = {
        "username": username,
        "password": password,
    }

    uid = os.getenv("BLINK_UID")
    if uid:
        logging.info("Using UID for authentication")

        login_data |= {
            # https://github.com/MattTW/BlinkMonitorProtocol/blob/2c9d7546b3b9ca1bd64969abc7d6f8d0966628d3/auth/login.md.
            # The UID is a secret value; once MFA-verified, subsequent logins can use the
            # same UID to skip MFA.
            "uid": uid,
            "reauth": False,
        }
    else:
        logging.info("No UID found; will prompt for MFA")

    blink = Blink(session=session)
    auth = Auth(
        login_data=login_data,
        no_prompt="uid" in login_data,
        session=session,
    )
    blink.auth = auth

    await blink.start()

    logging.info(f"UID used: {blink.auth.login_attributes['uid']}")

    return blink


async def main(target_dir: Path, since: datetime.date | None) -> None:
    async with ClientSession() as session:
        blink = await init(session=session)

        my_sync: BlinkSyncModule = blink.sync[
            blink.networks[list(blink.networks)[0]]["name"]
        ]

        for name, camera in blink.cameras.items():
            logging.info(f"Found camera '{name}' with attributes: {camera.attributes}")

        my_sync._local_storage["manifest"] = SortedSet()
        await my_sync.refresh()
        if my_sync.local_storage and my_sync.local_storage_manifest_ready:
            print("Manifest is ready")
            print(f"Manifest {my_sync._local_storage['manifest']}")
        else:
            print("Manifest not ready")
        for name, camera in blink.cameras.items():
            print(f"{camera.name} status: {blink.cameras[name].arm}")
        new_vid = await my_sync.check_new_videos()
        print(f"New videos?: {new_vid}")

        path = "Videos"
        manifest = my_sync._local_storage["manifest"]
        for item in reversed(manifest):
            await item.prepare_download(blink)
            print(f"{item}")
            await item.download_video( 
		blink, 
		f"{path}/{item.name.replace(' ','_')}_{item.created_at.astimezone().isoformat().replace(':','_')}.mp4",
	    )
            await item.delete_video(blink)
            await asyncio.sleep(2)
        await session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=Path("./downloads"),
        help="Target directory to download videos to",
    )
    parser.add_argument(
        "--since",
        type=datetime.datetime.fromisoformat,
        help="Download videos since this date (ISO 8601 format)",
    )
    args = parser.parse_args()

    asyncio.run(main(args.target_dir, args.since))
