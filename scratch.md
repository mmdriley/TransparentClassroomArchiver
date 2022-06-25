# proof that posts are sorted by date and created_at

```
jq '.[] | .date+.created_at' TransparentClassroomArchive/children/99918/posts.json | sort -rc
```

does *not* succeed for just `created_at` or `id`.

On 2022-05-20 we have three posts that go "ID ID+m ID-n" so we have strong evidence ID *does not* participate in sort order.

It is *not* just `date` + `timepart(created_at)`, as might have been suggested by `toSortableTime` in `webpack://tc/frontend/web/modules/posts/model.js`.

```
jq '.[] | (.date + (.created_at | split("T"))[1])' TransparentClassroomArchive/children/99918/posts.json | sort -rc
sort: -:1283: disorder: "2020-08-2112:26:15.000-07:00"
```

```typescript
export const toSortableTime = (post: PostT) => {
  const timeWithoutDate = post.created_at ? post.created_at.replace(/^[0-9-]+T/, '') : 'zzz'
  const date = moment(post.date, ['L', db]).format(db)
  return `${date}T${timeWithoutDate}`
}
```

here is the full sort key:

```
jq '.[] | (.date + .created_at)' TransparentClassroomArchive/children/99918/posts.json | grep -C3 2020-08-21 
"2020-09-012020-09-01T10:15:27.641-07:00"
"2020-09-012020-09-01T10:09:22.797-07:00"
"2020-09-012020-09-01T09:40:40.328-07:00"
"2020-08-212020-08-19T10:48:04.513-07:00"
"2020-08-212020-08-17T12:26:15.000-07:00"
"2020-08-192020-08-19T13:33:11.027-07:00"
"2020-08-192020-08-19T13:32:59.434-07:00"
"2020-08-172020-08-17T14:06:29.496-07:00"
```
