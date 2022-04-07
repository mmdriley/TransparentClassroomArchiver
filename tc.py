#!/usr/bin/env python3

import json
import os
from typing import List, TypedDict
import requests
import sys

API_BASE = 'https://www.transparentclassroom.com'

# The `posts.json` endpoint seems to accept a `per_page` argument, but passing
# a value causes the endpoint to 500. The default value is 30, which is also
# hardcoded into the mobile app as "fewer than 30 results means done listing".
POSTS_PER_PAGE = 30

class Post(TypedDict):
    id: int
    classroom_id: int
    created_at: str  # e.g. "2022-04-01T11:22:37.000-07:00"
    html: str

# TODO: sentinel ID or `created_at` for "stop looking"`
def get_child_posts(s: requests.Session, school_id: int, child_id: int) -> List[Post]:
    page = 1
    posts: List[Post] = []
    while True:
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

def main(username: str, password: str):
    s = requests.Session()
    s.auth = (username, password)
    r = s.get(f'{API_BASE}/api/v1/authenticate.json')
    assert r.status_code == 200, f'authentication failed, status {r.status_code}'

    user_info = r.json()
    print(
        f'Logged in as "{user_info["first_name"]} {user_info["last_name"]}" ({user_info["email"]})\n'
        f'  User ID:   {user_info["id"]}\n'
        f'  School ID: {user_info["school_id"]}'
    )

    print()

    api_token = r.json()['api_token']
    school_id = int(r.json()['school_id'])

    s = requests.Session()
    s.headers.update({'X-TransparentClassroomToken': api_token})

    r = s.get(f'{API_BASE}/s/{school_id}/users/my_subjects.json')
    assert r.status_code == 200, f'get subjects failed, status {r.status_code}'

    print(f'Found {len(r.json())} children')
    for subj in r.json():
        assert subj['type'] == 'Child', f'unexpected subject type {subj["type"]}'
        print(
            f'- {subj["name"]}\n'
            f'    Child ID:     {subj["id"]}\n'
            f'    Classroom ID: {subj["classroom_id"]}'
        )

    print()

    children_ids = [x['id'] for x in r.json()]

    for child_id in children_ids:
        pass  # TODO
        # ps = get_child_posts(s, school_id, child_id)

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

