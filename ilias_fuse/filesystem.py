"""
A FUSE for ILIAS.
"""
import argparse
import os
import pwd
from pathlib import Path
from stat import S_IFDIR, S_IFREG
from typing import Generator, List

import requests

import fusetree
from fusetree.types import Stat
from PFERD.cookie_jar import CookieJar
from PFERD.ilias import (IliasCrawler, IliasCrawlerEntry, IliasDownloadInfo,
                         KitShibbolethAuthenticator)
from PFERD.ilias.crawler import IliasElementType
from PFERD.logging import enable_logging


class IliasHttpDirectory(fusetree.DictDir):
    """
    A directory that is backed by HTTP requests to ILIAS.
    """

    def __init__(
            self,
            crawler: IliasCrawler,
            entry: IliasCrawlerEntry,
            session: requests.Session,
    ):
        super().__init__({})
        self.crawler = crawler
        self.session = session
        self.entry = entry

    async def getattr(self) -> fusetree.Stat:
        return Stat(
            st_mode=S_IFDIR | self.mode,
            st_uid=pwd.getpwuid(os.getuid()).pw_uid,
            st_gid=pwd.getpwuid(os.getuid()).pw_gid
        )

    async def lookup(self, name: str) -> fusetree.Node_Like:
        self.realize_folder()
        return await super().lookup(name)

    async def opendir(self) -> fusetree.DirHandle_Like:
        self.realize_folder()
        return await super().opendir()

    def realize_folder(self) -> None:
        """
        Forces the folder to be eagerly loaded.
        """
        # pylint: disable=protected-access
        if len(self.contents) > 0:
            return

        entries: List[IliasCrawlerEntry]

        if self.entry.entry_type == IliasElementType.VIDEO_FOLDER:
            entries = self.crawler._crawl_video_directory(self.entry.path, self.entry.url())
        elif self.entry.entry_type == IliasElementType.EXERCISE_FOLDER:
            entries = self.crawler._crawl_exercises(self.entry.path, self.entry.url())
        else:
            entries = self.crawler._crawl_folder(self.entry.path, self.entry.url())

        for entry in entries:
            name = entry.path.name

            if entry.entry_type == IliasElementType.FORUM:
                name = "Forum - " + name
            elif entry.entry_type == IliasElementType.EXTERNAL_LINK:
                name = "Link - " + name

            self.contents[name] = _entry_to_node(entry, self.crawler, self.session)


def _entry_to_node(
        entry: IliasCrawlerEntry,
        crawler: IliasCrawler,
        session: requests.Session
) -> fusetree.Node:
    element: fusetree.Node

    if entry.entry_type == IliasElementType.FORUM:
        element = OwnedFile(entry.url())
    elif entry.entry_type == IliasElementType.EXTERNAL_LINK:
        element = OwnedFile(entry.url())
    elif entry.entry_type == IliasElementType.REGULAR_FILE:
        element = IliasHttpFile(entry.to_download_info(), session)
    elif entry.entry_type == IliasElementType.VIDEO_FILE:
        element = IliasHttpFile(entry.to_download_info(), session)
    else:
        element = IliasHttpDirectory(crawler, entry, session)

    return element


class OwnedFile(fusetree.BlobFile):
    """
    A file owned by the running user.
    """

    def __init__(self, data: str = ""):
        super().__init__(data=data.encode("UTF-8"))

    async def getattr(self) -> fusetree.Stat:
        super_stat = await super().getattr()

        return Stat(
            st_mode=super_stat.st_mode,
            st_size=super_stat.st_size,
            st_uid=pwd.getpwuid(os.getuid()).pw_uid,
            st_gid=pwd.getpwuid(os.getuid()).pw_gid,
        )


class IliasHttpFile(fusetree.GeneratorFile):
    """
    An ILIAS file you can download.
    """

    def __init__(self, info: IliasDownloadInfo, session: requests.Session):
        super().__init__(generator=self._process, mode=0o555)
        self.info = info
        self.session = session

    async def getattr(self) -> fusetree.Stat:
        return Stat(
            st_mode=S_IFREG | self.mode,
            st_uid=pwd.getpwuid(os.getuid()).pw_uid,
            st_gid=pwd.getpwuid(os.getuid()).pw_gid,
            st_mtime=self.info.modification_date.timestamp(),
            st_ctime=self.info.modification_date.timestamp(),
            st_atime=self.info.modification_date.timestamp(),
        )

    def _process(self) -> Generator[bytes, None, None]:
        response = self.session.get(self.info.url(), stream=True)
        for chunk in response.iter_content(chunk_size=128):
            yield chunk


def main() -> None:
    """
    The main entrypoint.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cookie-file",
        help="The file to store and load cookies in/from. Default: 'cookies.txt'",
        default="cookies.txt"
    )
    parser.add_argument(
        "--base-url",
        help="The base url to the ilias instance. Default: 'https://ilias.studium.kit.edu/'",
        default="https://ilias.studium.kit.edu/"
    )
    parser.add_argument(
        "--background",
        help="Run the fuse mount in the background",
        action="store_true"
    )

    root_group = parser.add_mutually_exclusive_group()
    root_group.add_argument(
        "--course-id",
        help="The course id to use as the root node",
        type=str
    )
    root_group.add_argument(
        "--personal-desktop",
        help="Uses the personal desktop as the root node. The default.",
        action="store_true",
        default=True
    )

    parser.add_argument(
        "mount_dir",
        help="Where to mount the filesystem"
    )
    args = parser.parse_args()

    cookies = CookieJar(Path(args.cookie_file))
    cookies.load_cookies()

    enable_logging()

    base_url = args.base_url

    root_url: str
    if args.course_id:
        root_url = f"{base_url}goto.php?target=crs_{args.course_id}"
    else:
        root_url = base_url + "?baseClass=ilPersonalDesktopGUI"

    session = cookies.create_session()
    crawler = IliasCrawler(base_url, session, KitShibbolethAuthenticator(), lambda y, x: True)

    root_node = IliasHttpDirectory(
        crawler,
        IliasCrawlerEntry(Path("."), root_url, IliasElementType.REGULAR_FOLDER, None),
        session
    )

    root_node.realize_folder()
    cookies.save_cookies()

    fusetree.FuseTree(root_node, args.mount_dir, foreground=not args.background)


if __name__ == '__main__':
    main()
