# Posting clips

The **Post** button on a finished clip (`frontend/src/components/post-clip.tsx`) opens a window with an editable
caption and a button each for YouTube, TikTok and Instagram. A button copies the caption, shows the clip's file
selected in File Explorer (`POST /tasks/{id}/clips/{clip_id}/reveal`, `backend/src/api/routes/post.py`) and opens
that site's upload page in the browser. The user drags the file in and pastes the caption. LocalClip uploads nothing.

## Several clips at once

Each clip on the results page has a tick box, and "Select all" sits next to the download format. With clips ticked, a bar
at the bottom offers **Export all** (`frontend/src/components/batch-export.tsx`). It calls
`POST /tasks/{id}/clips/{clip_id}/export-to-folder?preset=` once per clip, which copies the clip (in the chosen download
format) to `Videos\LocalClip\<stream title>\01 <hook title>.mp4`, then `POST /tasks/{id}/export-folder/open` shows that
folder in File Explorer. The window that follows lists each caption with a Copy button and links to the three upload pages.

Why not post through the sites' APIs:

- **YouTube**: possible (Google's device login allows the `youtube` scope), but it needs a Google Cloud project
  and a verification by Google before more than 100 people can log in. Built once in PR #37 and removed at
  Marky's request.
- **TikTok**: forbids putting its app secret in open-source code, and posts from an unreviewed app are private only.
- **Instagram**: Meta's login needs a secret kept on a web server.
