# sofi-blog

The code behind *Sofia’s little grimoire*: a static personal site (albums, films & series, books, games, links, things I make) with a Tumblr-style homepage, plus a helper that asks questions and builds entries for you.

## Everyday use

```
./sofi-blog.sh
```

Pick what you want to do from the menu and answer the questions. Arrows move, Enter picks, Ctrl+C goes back to the menu without saving. Every change rebuilds the site; "preview the site in your browser" shows it locally, and "publish to GitHub" uploads it.

**Deleting**: "delete things" lists everything on the site (entries, posts, links, right now lines, the made page text) so you can tick what to remove, or clear it all at once. Covers that nothing uses any more are deleted with them, and a copy of the data from before is kept in `data/backups/` (on your computer only) in case you change your mind.

**The made page**: its text is edited with "edit the made page" in the menu.

Reviews, posts and the made page understand a few small things: a blank line starts a new paragraph, `*italic*`, `**bold**`, and `[link text](https://…)`.

## First-time setup

1. **conda**: install [Miniforge](https://github.com/conda-forge/miniforge) if you don't have conda yet. The first `./sofi-blog.sh` creates the `sofi-blog` environment from `environment.yml` on its own.
2. **config.toml**: the first run copies `config.example.toml` to `config.toml`. Everything works with no keys at all: Open Library (books), Wikidata (films and games), TVmaze (series), MusicBrainz (albums) and Steam (game covers) are free and open. One thing is optional:
   - OMDb (optional, film posters): Wikidata rarely has posters. For them, get a free key at omdbapi.com → API Key → FREE (just an email address, no website) and paste it into `[omdb]`. Without it, add a poster yourself with "edit an entry → cover".
   - Put an email in `contact`: MusicBrainz and Wikidata ask scripts to say who they are.
   - `playlist`: the address of a YouTube playlist, e.g. `https://www.youtube.com/playlist?list=PL…` (YouTube Music playlist addresses work too). Set the playlist to public or unlisted; private ones can't be played. A SoundCloud playlist address also works here. Rebuild after changing it; the rebuild's ♪ line says what it found. Songs whose owners block playing on other sites are skipped automatically.
3. **GitHub Pages**: make a new repository on GitHub called `sofi-blog`, then in this folder:
   ```
   git init
   git add -A
   git commit -m "first version"
   git branch -M main
   git remote add origin https://github.com/YOUR-USERNAME/sofi-blog.git
   git push -u origin main
   ```
   On GitHub: repository → Settings → Pages → Source "Deploy from a branch" → branch `main`, folder `/docs` → Save. The site appears at `https://YOUR-USERNAME.github.io/sofi-blog/` a minute later; put that address in `config.toml` as `url` so the RSS feed links work. From then on, "publish to GitHub" in the menu does the commit and push.
   `config.toml` is in `.gitignore`, so your keys never get uploaded.

Moving to your own server later: copy the `docs/` folder to it. Nothing in the site depends on GitHub.

## Where things are

```
sofi-blog.sh           start here
sofi-blog.py           the question-asking helper
config.toml            your keys and settings (stays on your computer)
data/entries.json      every entry, post and link (the helper edits this)
docs/                  the website itself
  index.html           sends visitors to the default style
  feed.xml             RSS feed of homepage posts (generated)
  shared/app.js        page logic shared by every style
  shared/data.js       the data, generated from data/entries.json
  shared/covers/       downloaded covers; replace any file to use your own
  witchy/              the witchy look: index.html, style.css, img/
```


## Changing pictures

Every picture is a file in `docs/witchy/img/`. Replace a file with your own and keep the name, or change the name where it's used: `index.html` for the banner, avatar and buttons, `style.css` for the background and the title icon. PNG, JPG, GIF and SVG all work.

- `banner.svg`, `avatar.svg`, `background.jpg` (the tiled background), `icon-moon.svg` (the moon on every title bar), `btn-play/pause/prev/next.svg` (player buttons).

Covers: replace the file in `docs/shared/covers/` (same name), or use "edit an entry → cover" in the helper to pick an image file.
