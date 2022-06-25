import requests
from typing import List, TypedDict


API_BASE = 'https://www.transparentclassroom.com'


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
    user_info: UserInfo
    session: requests.Session
    subjects: List[Subject]


class TransparentClassroom:
    user_info: UserInfo
    session: requests.Session
    subjects: List[Subject]

    def __init__(self, username: str, password: str):
        self.user_info = self._authenticate(username, password)
        self._print_user_info()

        # Create a session with the right authentication header for all requests.
        # As an added bonus, using a session gets us connection keep-alive.
        self.session = requests.Session()
        self.session.headers.update({'X-TransparentClassroomToken': self.user_info['api_token']})

        self.subjects = self._get_subjects(self.session, self.user_info['school_id'])
        self._print_children()


    @staticmethod
    def _authenticate(username: str, password: str) -> UserInfo:
        r = requests.get(f'{API_BASE}/api/v1/authenticate.json', auth=(username, password))
        r.raise_for_status()
        return r.json()


    @staticmethod
    def _get_subjects(s: requests.Session, school_id: int) -> List[Subject]:
        r = s.get(f'{API_BASE}/s/{school_id}/users/my_subjects.json')
        r.raise_for_status()
        return r.json()


    def child_ids(self) -> set[int]:
        return set(s['id'] for s in self.subjects)


    def classroom_ids(self) -> set[int]:
        return set(s['classroom_id'] for s in self.subjects)


    def school_id(self) -> int:
        return self.user_info['school_id']


    def _print_user_info(self):
        ui = self.user_info
        print(
            f'Logged in as "{ui["first_name"]} {ui["last_name"]}" ({ui["email"]})\n'
            f'  User ID:   {ui["id"]}\n'
            f'  School ID: {ui["school_id"]}'
        )
        print()


    def _print_children(self):
        print(f'Found {len(self.subjects)} children')
        for subj in self.subjects:
            assert subj['type'] == 'Child', f'unexpected subject type: {subj["type"]}'
            print(
                f'- {subj["name"]}\n'
                f'    Child ID:     {subj["id"]}\n'
                f'    Classroom ID: {subj["classroom_id"]}'
            )
        print()
