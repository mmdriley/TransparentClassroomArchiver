#!/usr/bin/env python3

import json
import os
from typing import List, TypedDict
import requests
import sys


API_BASE = 'https://www.transparentclassroom.com'


# Max number of posts per page to expect from `posts.json`
#
# This value is also hardcoded in the mobile app: when it seems fewer than 30
# posts on a page, it stops listing.
#
# The endpoint seems to accept a `per_page` argument, but setting it to *any*
# value -- even the evident "default" of 30 -- causes it to return a 500.
POSTS_PER_PAGE = 30


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
    # The only API we have for getting posts is to list by page. While we're
    # retrieving pages there's a vanishingly small, but nonzero, chance that a
    # post will be added or deleted.
    # 
    # We want to make sure in all circumstances we return *at least* all posts
    # that existed when we started enumerating and still existed when we're
    # done. That way, later updates can assume they have all posts older than
    # the newest post we return.
    #
    # An added post wouldn't be too hard to work around. The new post would move
    # a post that had been on page N to page N+1, so at worst we would see a
    # post twice on two different pages and we'd need to deduplicate. We might
    # not get the new post in our listing but that's no worse than if we'd done
    # the listing right before the post was added.
    #
    # Deleted posts are more worrying. If a post on page N is deleted, a post
    # from page N+1 will shift to page N, and likewise for all later pairs of
    # adjacent pages. If we're in the midst of retrieving any page after N we
    # will silently *miss* a post.
    #
    # We can imagine some complex schemes to fix this. For example, if we
    # happened to know the index of the last page of results, we could detect
    # that a delete happened: retrieve the last page first, then get pages in
    # order, then finally check if the number of posts on the last page has gone
    # down. If so, a delete happened, though we don't know where. If the page is
    # the same size, it's *still possible* that a delete happened if there was
    # also an add, but we can check if an add occurred by *also* re-retrieving
    # the first page and seeing if the ID of the first post has changed. (This
    # assumes new posts will sort first, which seems correct.)
    #
    # Instead, we choose an approach that is inefficient but straightforwardly
    # correct: do the full listing twice and fail if it changes.

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


def main(username: str, password: str):
    user_info = authenticate(username, password)

    print(
        f'Logged in as "{user_info["first_name"]} {user_info["last_name"]}" ({user_info["email"]})\n'
        f'  User ID:   {user_info["id"]}\n'
        f'  School ID: {user_info["school_id"]}'
    )
    print()

    api_token = user_info['api_token']
    school_id = int(user_info['school_id'])

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

    return

    children_ids = [x['id'] for x in r.json()]

    for child_id in children_ids:
        ps = get_child_posts(s, school_id, child_id)
        print(f'child {child_id}: {len(ps)} posts')

    # r = s.get(f'{API_BASE}/s/87/children/99918/posts.json?per_page=50')
    # assert r.status_code == 200, f'failed getting posts, status {r.status_code}\n{r.text}'


if __name__ == '__main__':
    username = 'mdriley@gmail.com'
    password = os.getenv('TC_PASSWORD')

    assert password, 'password not found in TC_PASSWORD'

    main(username, password)


# r = s.get(f'{API_BASE}/s/87/children/99918/posts.json?ids=50562295')
# assert r.status_code == 200, f'failed getting posts, status {r.status_code}\n{r.text}'

# j = r.json()
# print(len(j))
# print(json.dumps(j[0], indent=2))


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

# get specific id. seems like it's supposed to support multiple IDs
#  but I can't figure out how to provide a list
# r = s.get(f'{API_BASE}/s/87/children/99918/posts.json?ids=50562295')

