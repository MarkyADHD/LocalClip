# Posting clips

The **Post** button on a finished clip (`frontend/src/components/post-clip.tsx`) opens a window with an editable
caption and a button each for YouTube, TikTok and Instagram. A button copies the caption, shows the clip's file
selected in File Explorer (`POST /tasks/{id}/clips/{clip_id}/reveal`, `backend/src/api/routes/post.py`) and opens
that site's upload page in the browser. The user drags the file in and pastes the caption. LocalClip uploads nothing.

Why not post through the sites' APIs:

- **YouTube**: possible (Google's device login allows the `youtube` scope), but it needs a Google Cloud project
  and a verification by Google before more than 100 people can log in. Built once in PR #37 and removed at
  Marky's request.
- **TikTok**: forbids putting its app secret in open-source code, and posts from an unreviewed app are private only.
- **Instagram**: Meta's login needs a secret kept on a web server.
