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


# TODO: announcements have photos too


API_BASE = 'https://www.transparentclassroom.com'


# Max number of posts per page to expect from `posts.json`
#
# This value is also hardcoded in the mobile app: when it seems fewer than 30
# posts on a page, it stops listing.
#
# The endpoint seems to accept a `per_page` argument, but setting it to *any*
# value -- even the evident "default" of 30 -- causes it to return a 500.
POSTS_PER_PAGE = 30


MAX_CONCURRENT_DOWNLOADS = 10


# Response from `authenticate.json`
class UserInfo(TypedDict):
    id: int

    school_id: int

    first_name: str
    last_name: str
    email: str

    api_token: str


# One subject from `my_subjects.json`
class Subject(TypedDict):
    id: int

    school_id: int
    classroom_id: int

    name: str
    school_name: str

    type: str  # e.g. "Child"


# One post from `posts.json`
class Post(TypedDict):
    id: int
    created_at: str  # e.g. "2022-04-01T11:22:37.000-07:00"

    classroom_id: int

    author: str
    date: str  # e.g. "2022-04-01"

    html: str
    normalized_text: str

    # these are missing for text-only posts
    photo_url: str
    medium_photo_url: str
    large_photo_url: str
    original_photo_url: str


# TODO: sentinel ID or `created_at` for "stop looking"`
def get_child_posts_once(s: requests.Session, school_id: int, child_id: int) -> List[Post]:
    page = 1
    posts: List[Post] = []
    while True:
        print(f'requesting child {child_id} page {page}')
        r = s.get(f'{API_BASE}/s/{school_id}/children/{child_id}/posts.json?page={page}')
        assert r.status_code == 200, f'get posts failed, status {r.status_code}'

        j = r.json()
        assert len(j) <= POSTS_PER_PAGE, f'response has {len(j)} posts, expected <= {POSTS_PER_PAGE}'

        posts += r.json()

        # if page is not full, we've got everything
        if len(j) < POSTS_PER_PAGE:
            break

        page = page + 1

    return posts


def get_child_posts(s: requests.Session, school_id: int, child_id: int) -> List[Post]:
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


def authenticate(username: str, password: str) -> UserInfo:
    s = requests.Session()
    s.auth = (username, password)

    r = s.get(f'{API_BASE}/api/v1/authenticate.json')
    assert r.status_code == 200, f'authentication failed, status {r.status_code}'

    return r.json()


def get_subjects(s: requests.Session, school_id: int) -> List[Subject]:
    r = s.get(f'{API_BASE}/s/{school_id}/users/my_subjects.json')
    assert r.status_code == 200, f'get subjects failed, status {r.status_code}'

    return r.json()


# TODO:
#   - this could be a much better "archiver", right now it will *throw away* details on posts
#     that have been deleted by the school. Need to union?
#   - ideally might write updates to new files, in case old files are backed up
def download_posts(username: str, password: str, target_path: pathlib.Path):
    user_info = authenticate(username, password)

    print(
        f'Logged in as "{user_info["first_name"]} {user_info["last_name"]}" ({user_info["email"]})\n'
        f'  User ID:   {user_info["id"]}\n'
        f'  School ID: {user_info["school_id"]}'
    )
    print()

    api_token = user_info['api_token']
    school_id = int(user_info['school_id'])

    # Create a session with the right authentication header for all future requests.
    # As an added bonus, using a session gets us connection keep-alive.
    s = requests.Session()
    s.headers.update({'X-TransparentClassroomToken': api_token})

    subjects = get_subjects(s, school_id)

    print(f'Found {len(subjects)} children')
    for subj in subjects:
        assert subj['type'] == 'Child', f'unexpected subject type: {subj["type"]}'
        print(
            f'- {subj["name"]}\n'
            f'    Child ID:     {subj["id"]}\n'
            f'    Classroom ID: {subj["classroom_id"]}'
        )
    print()

    children_ids = [s['id'] for s in subjects]

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
async def download_photos(posts: List[Post], target_path: pathlib.Path):
    target_path.mkdir(exist_ok=True)
    limiter = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    tasks = []

    async with aiohttp.ClientSession() as session:
        async def download_one(url: str, stem_path: pathlib.Path):
            final_path = stem_path.with_suffix('.' + url_extension(url))
            if final_path.exists():
                return

            temp_path = stem_path.with_suffix('.unfinished')
            async with limiter, session.get(url) as response:
                with temp_path.open('wb') as f:
                    f.write(await response.read())

                # invariant: file only exists with final name if successfully
                # and completely downloaded
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

    if args.no_update_posts:
        print('Not retrieving posts')
    else:
        username = 'mdriley@gmail.com'
        password = os.getenv('TC_PASSWORD')

        assert password, 'password not found in TC_PASSWORD'

        download_posts(username, password, base_path)

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
# assert r.status_code == 200, f'getting activity failed, status {r.status_code}'
# print(json.dumps(r.json(), indent=2))

# works, gets my info
# r = s.get(f'https://www.transparentclassroom.com/s/87/users/my_self.json')

# works, lists... all children?
# r = s.get(f'https://www.transparentclassroom.com/s/87/children.json')

# works, gets posts per classroom
# r = s.get(f'https://www.transparentclassroom.com/s/87/classrooms/1141/posts.json')

# r = s.get(f'{API_BASE}/s/87/children/290952/posts.json?page=3')

# /s/87/classrooms/1141/children?reverse=true&sort_by=last_name
# /s/87/frontend/announcements.json?page=2022-03-31T08:23:34.075-07:00

# r = s.get(f'{API_BASE}/s/87/children/99918/posts.json')
# assert r.status_code == 200, f'failed getting posts, status {r.status_code}\n{r.text}'

# r = s.get(f'{API_BASE}/s/87/children/99918/posts.json?ids[]=50562295&ids[]=25491909')
# assert r.status_code == 200, f'failed getting posts, status {r.status_code}\n{r.text}'
# print(json.dumps(r.json(), indent=2))
