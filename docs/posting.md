# Posting clips

The **Post** button on a finished clip (`frontend/src/components/post-clip.tsx`) opens a window with an editable
title and caption. Nothing is posted until a button in that window is pressed.

| Site | How | Why |
| --- | --- | --- |
| YouTube Shorts | Direct upload with the user's own login (`backend/src/youtube_upload.py`) | Google's device login works for desktop apps |
| TikTok | Copies the caption, shows the file in File Explorer, opens TikTok's upload page | TikTok forbids putting its app secret in open-source code, and posts from an unreviewed app are private only |
| Instagram | Same as TikTok | Meta's login needs a secret kept on a web server, and uploading a file from a PC needs Facebook Login for Business |

YouTube falls back to the same "open the upload page" button when no Google client is configured.

Routes (`backend/src/api/routes/post.py`): `GET /tasks/post/youtube`, `POST /tasks/post/youtube/login`,
`.../login/poll`, `.../logout`, `POST /tasks/{id}/clips/{clip_id}/post/youtube` with `{title, description, privacy}`,
`POST /tasks/{id}/clips/{clip_id}/reveal`. The login is kept in `TEMP_DIR/youtube_login.json`.

## Setting up YouTube posting (once, by whoever ships the app)

1. Open <https://console.cloud.google.com/projectcreate> and create a project called `LocalClip`.
2. Open <https://console.cloud.google.com/apis/library/youtube.googleapis.com> and press **Enable**.
3. Open <https://console.cloud.google.com/auth/overview> and press **Get started**: app name `LocalClip`, your
   email, audience **External**.
4. **Audience** > **Test users** > add your own Google account.
5. **Data access** > **Add or remove scopes** > tick `https://www.googleapis.com/auth/youtube` > **Save**.
6. **Clients** > **Create client** > application type **TVs and Limited Input devices** > **Create**. Copy the
   Client ID and Client secret.
7. Add both to the `.env` file in the LocalClip folder, then restart LocalClip:

   ```
   YOUTUBE_CLIENT_ID=...apps.googleusercontent.com
   YOUTUBE_CLIENT_SECRET=...
   ```

While the Google app is in **Testing**, only the test users can log in and the login expires after 7 days.
To open it to everyone, press **Publish app** on the Audience page. Google then asks for verification because the
YouTube scope is sensitive: a home page, a privacy policy and a short video of the login. Until that passes, users
see an "unverified app" warning and only 100 people can log in.

Limits: Google allows 100 uploads a day for the whole project. Vertical clips up to 3 minutes become Shorts; longer
ones are posted as normal videos.
