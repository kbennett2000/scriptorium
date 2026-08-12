# Making a book

*Load a book, kick it off, go to bed — wake up to a finished, illustrated book.* That's the whole idea.

This guide walks through making a book in the **Admin** app (the bakery's control room). It assumes the
bakery and its graphics card are already set up — if not, start with the
**[self-hosting guide](self-hosting.md)** first.

Open the Admin app in a browser:

```
http://your-home-server:8720/admin
```

---

## The short version

1. **New Book** → choose a book, pick an art style, say how illustrated you want it.
2. Press **Make this book**.
3. The bakery does the rest — reading the text, drawing the characters, painting the scenes.
4. (Optionally) glance at the review screen and approve.
5. **Publish.** It shows up on everyone's shelf.

That's it. The long version below just explains each screen.

---

## Step 1 — Start a new book

From the **Books** list (your library so far), click **New Book**.

![The Books list](../assets/screenshots/_placeholder.svg)

The wizard is one friendly form with a few numbered steps:

![The New Book wizard](../assets/screenshots/_placeholder.svg)

1. **Choose a book.** Search a big catalog of free classics (Project Gutenberg), paste text, or upload
   a file. Searching is the easiest — type a title or author and pick from the list.
2. **About the book.** Confirm the title, author, and roughly *when and where* it's set. This helps the
   pictures feel right (a Victorian parlor vs. a spaceship).
3. **Pick an art style.** Click a style tile — comic book, woodcut, watercolor, and so on.
4. **How many pictures?** More, balanced, or fewer. "Balanced" is a lovely default.
5. **How rich?** How many images each illustrated scene can get.
6. **Character portraits.** Leave these on for the cast page. You can also tick *"let me review the
   portraits"* if you'd like to approve the characters' looks before the whole book is drawn.

Press **Make this book** and you're off. 🎉

---

## Step 2 — Let it bake

The book appears on the Books list with a live status. Open it to watch the **progress** move through
its stages — finding the characters, working out each scene's time and place, choosing what to
illustrate, writing a description for each picture, then drawing.

![Book progress](../assets/screenshots/_placeholder.svg)

You don't have to babysit it. The heavy AI work is handed to the graphics card, and if the card is
asleep or busy, the job simply **waits and resumes** on its own. Big books take a while — this is a
"start it and come back later" affair.

From this screen you can also **pause**, **resume**, or **delete** a book, and edit chapter details if
you like.

> **Want it fully hands-off?** If your bakery is set to unattended mode, it will start and approve books
> for you automatically — the true "kick it off, go to bed" experience. See
> [unattended mode](self-hosting.md#unattended-wake-to-a-finished-book-mode) in the self-hosting guide.

---

## Step 3 — Review (optional but nice)

Before any pictures are drawn, you can look over the plan on the **Review** screen: the list of scenes
to illustrate, and the cast of characters with their descriptions. Tweak a description, adjust which
scenes get a picture, then press **Approve** to send it to the easel.

![The review gate](../assets/screenshots/_placeholder.svg)

If you asked to review portraits, you'll get a screen showing each character's portrait beside its
description. Don't love how someone looks? Edit the description and **regenerate** just that portrait
until you're happy, then approve.

![Portrait review](../assets/screenshots/_placeholder.svg)

After the pictures are painted, an optional **post-render** screen lets you spot-check the finished
plates as thumbnails and redraw any single one you'd like to improve.

![Post-render review](../assets/screenshots/_placeholder.svg)

---

## Step 4 — Publish

When you're happy, **publish** the book. Published books are final and tidy — they show up on every
reader's shelf, ready to download and read offline.

Want the same book in a different look later? You (or any reader) can spin up a new **picture set** in
another art style without redoing the whole book — the original stays exactly as it was.

---

## Tips

- **Start big books before bed.** A short story is quick; a 600-page novel takes real time on the
  graphics card. Kick it off and let it run overnight.
- **"Balanced" pictures + portraits on** is a great default recipe.
- **The GPU box does the drawing.** If books sit at "waiting for the graphics card," the card is off or
  busy — see the [self-hosting guide](self-hosting.md).

Now go read what you made → **[Reading books](reading-books.md)**.
