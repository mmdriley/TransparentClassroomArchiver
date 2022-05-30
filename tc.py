#!/usr/bin/env python3

import aiohttp
import argparse
import asyncio
import json
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


def url_extension(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    _, dot, ext = parsed.path.rpartition('.')
    assert dot == '.', f'get extension from url failed: {url}'
    assert ext in ['jpg', 'jpeg', 'png'], f'unexpected image extension: {ext}'

    return ext


# TODO:
#  - set filetime with `Last-Modified` header
#    (or at least store it somewhere? I probably don't actually want to care about preserving filesystem metadata)
#  - any reason to care about mime type?
#  - move Post parsing out of this, just take a Dict of url -> filename
#    (still some debate on where the add-extension code should go)
# - may want a mode that double-checks photos already downloaded
#   (with what? etag?)
async def download_photos(posts: List[TC.Post], target_path: pathlib.Path):
    target_path.mkdir(exist_ok=True)
    limiter = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    tasks = []

    async with aiohttp.ClientSession() as session:
        async def download_one(url: str, stem_path: pathlib.Path):
            # Invariant: file exists at final path only if it was downloaded
            # successfully and completely.
            final_path = stem_path.with_suffix('.' + url_extension(url))
            if final_path.exists():
                return

            temp_path = stem_path.with_suffix('.unfinished')
            async with limiter, session.get(url) as response:
                response.raise_for_status()
                with temp_path.open('wb') as f:
                    f.write(await response.read())

                temp_path.rename(final_path)
                print(final_path)

        for p in posts:
            # skip text-only posts
            if 'photo_url' not in p:
                continue

            id = p['id']
            tasks += map(asyncio.create_task, [
                download_one(p['photo_url'], target_path.joinpath(f'{id}')),
                download_one(p['original_photo_url'], target_path.joinpath(f'{id}_original')),
            ])
    
        await asyncio.gather(*tasks)


async def main(args):
    base_path = pathlib.Path('./TransparentClassroomArchive')

    def create_tc():
        username = os.getenv('TC_USERNAME')
        password = os.getenv('TC_PASSWORD')
        assert username and password, 'set TC_USERNAME and TC_PASSWORD'

        return TC.TransparentClassroom(username, password)
    tc = None

    if args.no_update_posts:
        print('Not retrieving posts')
    else:
        tc = tc or create_tc()
        download_posts(tc.session, tc.school_id(), tc.child_ids(), base_path)


    for posts_json in base_path.glob('children/*/posts.json'):
        with posts_json.open('r') as f:
            posts = json.load(f)
            await download_photos(posts, base_path.joinpath('photos'))


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
