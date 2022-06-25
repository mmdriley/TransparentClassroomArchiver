#!/usr/bin/env python3

import aiohttp
import argparse
import asyncio
from dataclasses import dataclass
import json
import mimetypes
import os
import pathlib
from typing import Dict, List, TypedDict
import urllib.parse
import requests
import sys


import TransparentClassroom as TC


# TODO: announcements have photos too


# Max number of posts per page to expect from `posts.json`
#
# This value is also hardcoded in the mobile app: when it seems fewer than 30
# posts on a page, it stops listing.
#
# The endpoint seems to accept a `per_page` argument, but setting it to *any*
# value -- even the evident "default" of 30 -- causes it to return a 500.
POSTS_PER_PAGE = 30


MAX_CONCURRENT_DOWNLOADS = 10


def url_suffix(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    _, dot, ext = parsed.path.rpartition('.')
    assert dot == '.', f'get extension from url failed: {url}'

    suffix = dot + ext
    assert suffix in ['.jpg', '.jpeg', '.png'], f'unexpected image extension: {suffix}'

    return suffix


@dataclass
class DownloadItem:
    filename: pathlib.Path
    url: str

    def __init__(self, filename: str, url: str, add_suffix = True):
        self.url = url

        self.filename = pathlib.Path(filename)
        if add_suffix and not self.filename.suffix:
            # add suffix from URL
            self.filename = self.filename.with_suffix(url_suffix(url))


# TODO: sentinel ID or `created_at` for "stop looking"`
def get_child_posts_once(s: requests.Session, school_id: int, child_id: int) -> List[TC.Post]:
    page = 1
    posts: List[TC.Post] = []
    while True:
        print(f'requesting child {child_id} page {page}')
        r = s.get(f'{TC.API_BASE}/s/{school_id}/children/{child_id}/posts.json?page={page}')
        r.raise_for_status()

        j = r.json()
        assert len(j) <= POSTS_PER_PAGE, f'response has {len(j)} posts, expected <= {POSTS_PER_PAGE}'

        posts += r.json()

        # if page is not full, we've got everything
        if len(j) < POSTS_PER_PAGE:
            break

        page = page + 1

    return posts


def get_child_posts(s: requests.Session, school_id: int, child_id: int) -> List[TC.Post]:
    # Retrieve posts twice and check the lists match.
    #
    # todo: rewrite this long comment. Turns out, empirically, posts are sorted
    # by `date` (which can be backdated!), and then seemingly by `created_at` to
    # break ties. We still observe inversions in `id` even within equal values
    # for `date`, so it doesn't seem to be involved in sorting.

    list1 = get_child_posts_once(s, school_id, child_id)
    list2 = get_child_posts_once(s, school_id, child_id)
    assert list1 == list2, 'posts changed while listing'

    return list1


# TODO:
#   - this could be a much better "archiver", right now it will *throw away* details on posts
#     that have been deleted by the school. Need to union?
#   - ideally might write updates to new files, in case old files are backed up
def download_posts(s: requests.Session, school_id: int, children_ids: List[int], target_path: pathlib.Path):
    for child_id in children_ids:
        child_path = target_path.joinpath(f'children/{child_id}')
        child_path.mkdir(parents=True, exist_ok=True)

        # TODO: incremental update
        ps = get_child_posts(s, school_id, child_id)
        print(f'child {child_id}: {len(ps)} posts')
        print()

        with child_path.joinpath(f'posts.json').open('w') as f:
            json.dump(ps, f, indent=2)


async def download_post_photos(posts: List[TC.Post], target_path: pathlib.Path):
    download_items = []

    for p in posts:
        # skip text-only posts
        if 'photo_url' not in p:
            continue

        id = p['id']

        # TODO: is `id` unique enough here or should I include namespacing, e.g. photo{id}
        # actually, will probably solve this by downloading into different *directories*

        download_items += [
            DownloadItem(f'{id}', p['photo_url']),
            DownloadItem(f'{id}_original', p['original_photo_url']),
        ]
    
    await download_urls(download_items, target_path)


# TODO:
# - may want a mode that double-checks photos already downloaded
#   (with what? etag?)

# Downloads some URLs to `target_path`. Skips items already downloaded.
# TODO: remove `target_path`, make it part of `items`.
async def download_urls(items: List[DownloadItem], target_path: pathlib.Path):
    target_path.mkdir(exist_ok=True)
    limiter = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    tasks = []

    async with aiohttp.ClientSession() as session:
        async def download_one(url: str, final_path: pathlib.Path):
            # Invariant: file exists at final path only if it was downloaded
            # successfully and completely.
            assert final_path.suffix != '.unfinished'
            temp_path = final_path.with_suffix('.unfinished')
            async with limiter, session.get(url) as response:
                response.raise_for_status()

                mimetype = response.headers.getone('content-type')
                assert final_path.suffix in mimetypes.guess_all_extensions(mimetype), f"{url} shouldn't be {mimetype}"

                with temp_path.open('wb') as f:
                    f.write(await response.read())
                temp_path.rename(final_path)

        for i in items:
            final_path = target_path.joinpath(i.filename)
            if final_path.exists():
                continue

            tasks += [asyncio.create_task(download_one(i.url, final_path))]
    
        await asyncio.gather(*tasks)


def download_announcements(s: requests.Session, school_id: int, base_path: pathlib.Path):
    announcements = []
    params = {}

    while True:
        r = s.get(f'{TC.API_BASE}/s/{school_id}/frontend/announcements.json', params=params)
        r.raise_for_status()

        announcements += r.json()['data']

        # When we run out of pages, the last response is:
        # {"data":[],"pagination":{"next":null}}
        next = r.json()['pagination']['next']
        if next is None:
            break
        print(next)
        params['page'] = next

    with base_path.joinpath('announcements.json').open('w') as f:
        json.dump(announcements, f, indent=2)


def parse_announcements(announcements):
    for a in announcements:
        assert a['type'] == 'Announcement'

        assert 'data' in a
        d = a['data']

        assert 'id' in d
        assert 'createdAt' in d
        assert 'title' in d
        assert 'body' in d
        assert 'attachments' in d

        assert 'author' in d
        assert 'id' in d['author']
        assert 'name' in d['author']

        assert 'subject' in d
        assert 'id' in d['subject']
        assert 'type' in d['subject']
        assert 'name' in d['subject']
        assert d['subject']['type'] in ['Classroom', 'School']

        for att in d['attachments']:
            assert att['type'] == 'Attachment'
            assert 'data' in att
            att_d = att['data']
            assert 'name' in att_d
            assert 'id' in att_d
            assert 'url' in att_d
            assert 'size' in att_d

    print(f'{len(announcements)} announcements')


async def main(args):
    base_path = pathlib.Path('./TransparentClassroomArchive')

    def create_tc():
        username = os.getenv('TC_USERNAME')
        password = os.getenv('TC_PASSWORD')
        assert username and password, 'set TC_USERNAME and TC_PASSWORD'

        return TC.TransparentClassroom(username, password)
    tc = None

    # Announcements!
    # tc = tc or create_tc()
    # download_announcements(tc.session, tc.school_id(), base_path)

    # with base_path.joinpath('announcements.json').open('r') as f:
    #     announcements = json.load(f)
    #     parse_announcements(announcements)
    # sys.exit(1)

    if args.no_update_posts:
        print('Not retrieving posts')
    else:
        tc = tc or create_tc()
        download_posts(tc.session, tc.school_id(), tc.child_ids(), base_path)


    for posts_json in base_path.glob('children/*/posts.json'):
        with posts_json.open('r') as f:
            posts = json.load(f)
            await download_post_photos(posts, base_path.joinpath('photos'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-update-posts', action='store_true')
    asyncio.run(main(parser.parse_args()))


# the appendices

# r = s.get(f'{API_ROOT}/v1/activity.json?child_id={child}')
# r.raise_for_status()
# print(json.dumps(r.json(), indent=2))

# works, gets my info
# r = s.get(f'https://www.transparentclassroom.com/s/87/users/my_self.json')

# works, appears to list all children in the school.
# r = s.get(f'https://www.transparentclassroom.com/s/87/children.json')

# works, gets posts per classroom
# r = s.get(f'https://www.transparentclassroom.com/s/87/classrooms/1141/posts.json')

# r = s.get(f'{API_BASE}/s/87/children/290952/posts.json?page=3')

# /s/87/classrooms/1141/children?reverse=true&sort_by=last_name
# /s/87/frontend/announcements.json?page=2022-03-31T08:23:34.075-07:00

# r = s.get(f'{API_BASE}/s/87/children/99918/posts.json')
# r.raise_for_status()

# r = s.get(f'{API_BASE}/s/87/children/99918/posts.json?ids[]=50562295&ids[]=25491909')
# r.raise_for_status()
# print(json.dumps(r.json(), indent=2))

# https://www.transparentclassroom.com/s/87/posts.json
# all posts for all accessible children
# seems like it should take `child_id=NNN` but it has no effect
