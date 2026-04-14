QUIZ IMAGES — Setup Guide
=========================

Two questions in the quiz pool (Q13 and any you add) support showing a
phishing screenshot to the user before asking them to identify the red flag.

Since Discord doesn't support attaching new files to edited ephemeral
messages, images are referenced by URL. Here's how to set them up:


STEP 1 — Prepare your screenshots
-----------------------------------
Good screenshots to use:
  - A fake "Discord OAuth2 / Authorize" page where the URL bar shows a
    phishing domain (e.g. discord-auth-verify.com)
  - A fake "Free Nitro" redemption page
  - A fake "Discord Staff" DM showing an urgent link
  - A QR code login prompt on a suspicious site

You can create these in Figma or take screenshots of known phishing clones
(from security research sources like PhishTank, with caution).


STEP 2 — Upload the image
---------------------------
Option A (easiest): Upload the image to a Discord channel the bot can see,
right-click the image → "Copy Link". The URL will look like:
  https://cdn.discordapp.com/attachments/.../phishing_example.png

Option B: Upload to Imgur (imgur.com → direct link ending in .png/.jpg)

Option C: Any direct image URL that doesn't require auth.


STEP 3 — Set the image_url in quiz.py
----------------------------------------
Open cogs/quiz.py and find the question with id=13 (or add a new question).
Set the image_url field:

  {
      "id": 13,
      "question": "The image above shows a website asking you to connect...",
      "image_url": "https://YOUR_IMAGE_URL_HERE",
      ...
  }

Once image_url is not None, the embed will display the image above the
answer buttons automatically.


ADDING MORE IMAGE QUESTIONS
-----------------------------
Copy the structure of Q13 and give it a new unique id. Include:
  - "question": str — reference "the image above" in the text
  - "image_url": str — direct image URL
  - "choices": list of 4 strings
  - "correct": int (0-indexed)
  - "explanation": str — shown after the user answers

The quiz randomly picks 10 from the pool each run, so your new question
will appear roughly 10/14 of the time (or whatever the pool size is).
