# Posting clips

The **Post** button on a finished clip (`frontend/src/components/post-clip.tsx`) opens a window with an editable
caption and a button each for YouTube, TikTok and Instagram. A button copies the caption, shows the clip's file
selected in File Explorer (`POST /tasks/{id}/clips/{clip_id}/reveal`, `backend/src/api/routes/post.py`) and opens
that site's upload page in the browser. The user drags the file in and pastes the caption. LocalClip uploads nothing.

Each site has its own caption (the tabs above the text box); a site's button copies that site's caption.
**Write with AI** (`POST /tasks/{id}/clips/{clip_id}/captions`, `backend/src/post_captions.py`) asks the model from
Settings > AI model for a YouTube Shorts title, a TikTok caption and an Instagram caption, hashtags included, from the
clip's transcript, on-screen title and suggested hashtags. The text stays editable, and is kept in the browser's
localStorage (`localclip-post-captions:<clip id>`) so reopening the window does not ask the model again.

Why not post through the sites' APIs:

- **YouTube**: possible (Google's device login allows the `youtube` scope), but it needs a Google Cloud project
  and a verification by Google before more than 100 people can log in. Built once in PR #37 and removed at
  Marky's request.
- **TikTok**: forbids putting its app secret in open-source code, and posts from an unreviewed app are private only.
- **Instagram**: Meta's login needs a secret kept on a web server.
