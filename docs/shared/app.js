/* Sofia’s little grimoire: shared page logic for every style.
   It reads window.SOFIBLOG (made by sofi-blog.py into shared/data.js) and fills in
   the feed, the shelves, the right now box, the links and the music player.
   Each style folder only decides how things look (its index.html + style.css). */
(function () {
  'use strict';

  var G = window.SOFIBLOG || { entries: [], posts: [], links: [], now: [], music: {}, site: {} };
  var BASE = document.documentElement.getAttribute('data-base') || '';  /* path from the page to docs/ */
  var PAGE_SIZE = 8;

  var TYPE = {
    book:   { label: 'book',   verbs: { finished: 'finished reading', reading: 'started reading', backlog: 'added to the reading pile', dropped: 'put down' } },
    film:   { label: 'film',   verbs: { watched: 'watched', backlog: 'added to the watchlist' } },
    series: { label: 'series', verbs: { finished: 'finished watching', watching: 'started watching', backlog: 'added to the watchlist', dropped: 'stopped watching' } },
    album:  { label: 'album',  verbs: { '': 'added to the album shelf' } },
    game:   { label: 'game',   verbs: { finished: 'finished playing', playing: 'started playing', backlog: 'added to the game backlog', dropped: 'stopped playing' } }
  };
  var SHELF = {
    book:   { title: 'books', groups: [['reading', 'reading now'], ['finished', 'read'], ['dropped', 'put down'], ['backlog', 'reading pile']] },
    film:   { title: 'films', groups: [['watched', 'watched'], ['backlog', 'watchlist']] },
    series: { title: 'series', groups: [['watching', 'watching now'], ['finished', 'finished'], ['dropped', 'stopped watching'], ['backlog', 'watchlist']] },
    game:   { title: 'games', groups: [['playing', 'playing now'], ['finished', 'finished'], ['dropped', 'stopped playing'], ['backlog', 'backlog']] }
  };
  var NOW_LABEL = { reading: 'reading', watching: 'watching', playing: 'playing' };
  var MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

  /* ───── helpers ───── */
  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  /* reviews and posts: blank line = new paragraph, *italic*, **bold**, [text](https://…) */
  function md(s) {
    return esc(s).split(/\n{2,}/).map(function (p) {
      p = p.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
           .replace(/\*(.+?)\*/g, '<i>$1</i>')
           .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
           .replace(/\n/g, '<br>');
      return '<p>' + p + '</p>';
    }).join('');
  }
  function url(u) { return /^([a-z]+:|#|\/)/i.test(u || '') ? u : BASE + u; }
  function host(u) { try { return new URL(u).hostname.replace(/^www\./, ''); } catch (e) { return ''; } }
  function fmtDate(iso) {
    if (!iso) return '';
    var d = new Date(iso.length === 10 ? iso + 'T12:00:00' : iso);
    if (isNaN(d)) return '';
    var s = d.getDate() + ' ' + MONTHS[d.getMonth()];
    return d.getFullYear() === new Date().getFullYear() ? s : s + ' ' + d.getFullYear();
  }
  function stars(r) {
    if (r == null) return '';
    var full = Math.floor(r), half = r - full >= 0.5, s = '';
    for (var i = 0; i < 5; i++) s += i < full ? '★' : (i === full && half ? '½' : '☆');
    return '<span class="stars" role="img" aria-label="' + r + ' out of 5">' + s + '</span>';
  }
  /* newest first; an entry without a date sorts by when you added it */
  function when(e) { return e.date || e.started || e.added || ''; }
  function byDateDesc(a, b) { return when(b).localeCompare(when(a)); }
  var SORTS = {
    recent: { label: 'newest first', fn: byDateDesc },
    rating: { label: 'highest rated', fn: function (a, b) { return (b.rating == null ? -1 : b.rating) - (a.rating == null ? -1 : a.rating) || byDateDesc(a, b); } },
    title:  { label: 'a to z', fn: function (a, b) { return a.title.replace(/^(the|a|an) /i, '').localeCompare(b.title.replace(/^(the|a|an) /i, '')); } }
  };
  var sortBy = 'recent';

  function entries(type, status) {
    return G.entries.filter(function (e) { return e.type === type && (status === undefined || (e.status || '') === status); });
  }

  /* ───── pieces ───── */
  function cover(e, cls) {
    var inner = e.cover
      ? '<img src="' + esc(url(e.cover)) + '" alt="" loading="lazy">'
      : '<span class="nocover" aria-hidden="true">' + esc((e.title || '?').charAt(0)) + '</span>';
    cls = 'cover' + (cls ? ' ' + cls : '') + (e.type === 'album' ? ' square' : '');
    if (!e.link) return '<span class="' + cls + '">' + inner + '</span>';
    return '<a class="' + cls + '" href="' + esc(e.link) + '" target="_blank" rel="noopener" tabindex="-1" aria-hidden="true">' + inner + '</a>';
  }
  function titleLink(e) {
    var t = esc(e.title);
    return e.link ? '<a href="' + esc(e.link) + '" target="_blank" rel="noopener" title="opens on ' + esc(host(e.link)) + '">' + t + '</a>' : t;
  }
  function meta(e) {
    var bits = [];
    if (e.creator) bits.push(esc(e.creator));
    if (e.year) bits.push(esc(e.year));
    return bits.length ? '<p class="entry-meta">' + bits.join(' ✦ ') + '</p>' : '';
  }
  function review(text, limit) {
    if (!text) return '';
    var long = text.length > (limit || 320);
    return '<div class="review' + (long ? ' clamped' : '') + '">' + md(text) + '</div>' +
      (long ? '<button type="button" class="more" aria-expanded="false">read more</button>' : '');
  }
  function entryRow(e) {
    var day = NOW_LABEL[e.status] ? (e.started ? 'since ' + fmtDate(e.started) : '') : fmtDate(e.date);
    var dated = day ? '<span class="entry-date">' + day + '</span>' : '';
    var line2 = [stars(e.rating), dated].filter(Boolean).join(' ');
    return '<article class="entry" id="e-' + esc(e.id) + '">' + cover(e) +
      '<div class="entry-body"><h4 class="entry-title">' + titleLink(e) + '</h4>' + meta(e) +
      (line2 ? '<p class="entry-meta">' + line2 + '</p>' : '') + review(e.review) + '</div></article>';
  }
  function backlogRow(e) {
    return '<li>' + cover(e, 'mini') + '<span>' + titleLink(e) +
      (e.creator ? ' <span class="entry-meta">' + esc(e.creator) + '</span>' : '') + '</span></li>';
  }
  function sortControl() {
    var o = '';
    for (var k in SORTS) o += '<option value="' + k + '"' + (k === sortBy ? ' selected' : '') + '>' + SORTS[k].label + '</option>';
    return '<label class="sort">sort <select data-sort>' + o + '</select></label>';
  }
  function heading(text, level) {
    level = level || 3;
    return '<h' + level + ' class="title"' + (level === 2 ? ' tabindex="-1"' : '') + '>' + text + '</h' + level + '>';
  }

  /* ───── feed (homepage) ───── */
  function feedItems() {
    var items = G.entries.filter(function (e) { return e.home && e.posted; })
      .map(function (e) { return { kind: 'entry', x: e, at: e.posted }; })
      .concat((G.posts || []).map(function (p) { return { kind: 'post', x: p, at: p.posted }; }));
    return items.sort(function (a, b) { return b.at.localeCompare(a.at); });
  }
  function postHtml(it) {
    var x = it.x, id = 'post-' + x.id, body;
    var tag = it.kind === 'entry' ? TYPE[x.type].label : 'note';
    if (it.kind === 'entry') {
      var verb = (TYPE[x.type].verbs[x.status || ''] || '');
      body = '<div class="entry">' + cover(x) + '<div class="entry-body">' +
        (verb ? '<p class="post-verb">' + esc(verb) + '</p>' : '') +
        '<h4 class="entry-title">' + titleLink(x) + '</h4>' + meta(x) +
        (x.rating != null ? '<p class="entry-meta">' + stars(x.rating) + '</p>' : '') +
        '</div></div>' + review(x.review, 480);
    } else {
      body = (x.title ? '<h4 class="post-title">' + esc(x.title) + '</h4>' : '') + review(x.text, 900);
    }
    return '<article class="post post-' + tag + '" id="' + esc(id) + '">' +
      '<header class="post-head"><span class="tag">' + tag + '</span>' +
      '<a class="post-date" href="#' + esc(id) + '" title="link to this post">' + fmtDate(x.posted) + '</a></header>' +
      '<div class="post-body">' + body + '</div></article>';
  }
  var shown = PAGE_SIZE;
  function renderFeed() {
    var box = $('feed');
    if (!box) return;
    var items = feedItems();
    if (!items.length) { box.innerHTML = '<p class="empty">No posts yet.</p>'; return; }
    box.innerHTML = items.slice(0, shown).map(postHtml).join('') +
      (items.length > shown ? '<button type="button" class="older" data-older>older posts</button>' : '');
  }

  /* ───── shelves ───── */
  function renderShelf(type) {
    var spec = SHELF[type], html = '', any = false;
    spec.groups.forEach(function (g) {
      var list = entries(type, g[0]);
      if (!list.length) return;
      any = true;
      var title = g[1] + ' <span class="count">' + list.length + '</span>';
      if (g[0] === 'backlog') {
        html += '<section class="shelf-group">' + heading(title) + '<ul class="backlog">' +
          list.sort(byDateDesc).map(backlogRow).join('') + '</ul></section>';
      } else if (g[0] === 'dropped') {
        html += '<details class="shelf-group dropped"><summary>' + title + '</summary>' +
          list.sort(byDateDesc).map(entryRow).join('') + '</details>';
      } else {
        var sortable = list.length > 2 && !NOW_LABEL[g[0]];
        html += '<section class="shelf-group">' + heading(title) + (sortable ? sortControl() : '') +
          list.sort(SORTS[sortBy].fn).map(entryRow).join('') + '</section>';
      }
    });
    return any ? html : '<p class="empty">Nothing on this shelf yet.</p>';
  }
  function renderScreen(type) {
    var tabs = '<nav class="tabs" aria-label="films or series">' +
      '<a href="#films"' + (type === 'film' ? ' aria-current="page"' : '') + '>films</a>' +
      '<a href="#series"' + (type === 'series' ? ' aria-current="page"' : '') + '>series</a></nav>';
    return heading('films & series', 2) + tabs + renderShelf(type) +
      '<p class="credit">Film details come from <a href="https://www.wikidata.org" target="_blank" rel="noopener">Wikidata</a>; series details and images come from <a href="https://www.tvmaze.com" target="_blank" rel="noopener">TVmaze</a>.</p>';
  }
  function renderAlbums() {
    var list = entries('album').sort(SORTS[sortBy].fn);
    if (!list.length) return heading('albums', 2) + '<p class="empty">Nothing on this shelf yet.</p>';
    return heading('albums', 2) + (list.length > 2 ? sortControl() : '') + '<div class="albums">' +
      list.map(function (e) {
        return '<figure class="album">' + cover(e) + '<figcaption><b>' + titleLink(e) + '</b>' +
          (e.creator ? '<span class="entry-meta">' + esc(e.creator) + '</span>' : '') + stars(e.rating) +
          (e.review ? '<details class="note"><summary>notes</summary>' + md(e.review) + '</details>' : '') +
          '</figcaption></figure>';
      }).join('') + '</div>';
  }
  function renderLinks() {
    var groups = {}, order = [];
    (G.links || []).forEach(function (l) {
      if (!groups[l.group]) { groups[l.group] = []; order.push(l.group); }
      groups[l.group].push(l);
    });
    if (!order.length) return heading('links', 2) + '<p class="empty">No links yet.</p>';
    return heading('links', 2) + order.map(function (g) {
      return heading(esc(g)) + '<ul class="linklist">' + groups[g].map(function (l) {
        return '<li><a href="' + esc(url(l.url)) + '"' + (/^https?:/.test(l.url) ? ' target="_blank" rel="noopener"' : '') + '>' +
          esc(l.label) + '</a>' + (l.note ? ' <span class="entry-meta">' + esc(l.note) + '</span>' : '') + '</li>';
      }).join('') + '</ul>';
    }).join('');
  }
  function renderSinglePost(id) {
    var it = feedItems().filter(function (i) { return i.x.id === id; })[0];
    if (!it) return heading('post not found', 2) + '<p class="empty">This post isn’t here any more. <a href="#home">Back to the homepage</a></p>';
    return '<p class="back"><a href="#home">back to the homepage</a></p>' + postHtml(it);
  }

  /* ───── sidebar boxes (a box with nothing in it hides along with its title) ───── */
  function hideIfEmpty(box, count) {
    box.hidden = !count;
    var t = box.previousElementSibling;
    if (t && t.classList.contains('title')) t.hidden = !count;
  }
  function renderNow() {
    var box = $('now');
    if (!box) return;
    var lines = [];
    ['book', 'series', 'game'].forEach(function (t) {
      entries(t).filter(function (e) { return NOW_LABEL[e.status]; }).sort(byDateDesc).slice(0, 1).forEach(function (e) {
        lines.push(['' + NOW_LABEL[e.status], titleLink(e)]);
      });
    });
    var seen = G.entries.filter(function (e) { return (e.type === 'film' && e.status === 'watched') || (e.type === 'series' && e.status === 'finished'); })
      .sort(byDateDesc)[0];
    if (seen) lines.push(['watched', titleLink(seen)]);
    (G.now || []).forEach(function (n) { lines.push([esc(n.label), esc(n.value)]); });
    box.innerHTML = lines.map(function (l) { return '<b>' + l[0] + '</b> ' + l[1]; }).join('<br>');
    hideIfEmpty(box, lines.length);
  }
  function renderElsewhere() {
    var box = $('elsewhere');
    if (!box) return;
    var mine = (G.links || []).filter(function (l) { return l.group === 'elsewhere'; });
    hideIfEmpty(box, mine.length);
    box.innerHTML = mine.map(function (l) {
      return '<a href="' + esc(url(l.url)) + '"' + (/^https?:/.test(l.url) ? ' target="_blank" rel="noopener"' : '') + '>' + esc(l.label) + '</a>';
    }).join(' ✦ ');
  }

  /* ───── router: #home, #albums, #films, #series, #books, #games, #links, #post-…, plus any <section data-route> in index.html (like #stuff-i-make) ───── */
  var PAGES = {
    albums: renderAlbums,
    films: function () { return renderScreen('film'); },
    series: function () { return renderScreen('series'); },
    books: function () { return heading('books', 2) + renderShelf('book'); },
    games: function () { return heading('games', 2) + renderShelf('game'); },
    links: renderLinks
  };
  var NAV_OF = { series: 'films' };
  /* true when index.html has a <section data-route="…"> with this name (like "stuff-i-make") */
  function hasSection(name) {
    return Array.prototype.some.call(document.querySelectorAll('[data-route]'), function (el) {
      return el.getAttribute('data-route') === name && el.id !== 'view';
    });
  }
  function route() {
    var h = decodeURIComponent(location.hash.replace(/^#/, '')) || 'home';
    var name = h, html = null;
    if (h.indexOf('post-') === 0) { name = 'post'; html = renderSinglePost(h.slice(5)); }
    else if (PAGES[h]) html = PAGES[h]();
    else if (!hasSection(h)) name = 'home';
    var view = $('view');
    document.querySelectorAll('[data-route]').forEach(function (sec) {
      var r = sec.getAttribute('data-route');
      sec.hidden = !(r === name || (r === 'view' && html !== null));
    });
    if (html !== null) view.innerHTML = html;
    var navName = NAV_OF[name] || (name === 'post' ? 'home' : name);
    document.querySelectorAll('[data-nav]').forEach(function (a) {
      if (a.getAttribute('data-nav') === navName) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    var content = $('content');
    var bar = $('player'), barH = bar && getComputedStyle(bar).position === 'fixed' ? bar.offsetHeight : 0;
    if (content && location.hash && content.getBoundingClientRect().top < barH) content.scrollIntoView();
    var h2 = html !== null ? view.querySelector('h2') : null;
    if (h2 && routed) h2.focus({ preventScroll: true });
    routed = true;
  }
  var routed = false;

  document.addEventListener('click', function (ev) {
    var t = ev.target;
    if (t.matches('button.more')) {
      var r = t.previousElementSibling, open = r.classList.toggle('clamped');
      t.textContent = open ? 'read more' : 'read less';
      t.setAttribute('aria-expanded', String(!open));
    } else if (t.matches('[data-older]')) {
      shown += PAGE_SIZE;
      renderFeed();
    }
  });
  document.addEventListener('change', function (ev) {
    if (ev.target.matches('[data-sort]')) {
      sortBy = ev.target.value;
      route();
      var s = $('view').querySelector('[data-sort]');
      if (s) s.focus();
    }
  });

  /* ───── music: a hidden YouTube (or SoundCloud) player driven by the bar's own buttons ───── */
  function initPlayer() {
    var box = $('player');
    if (!box) return;
    var q = function (k) { return box.querySelector('[data-player="' + k + '"]'); };
    var ui = {
      box: box, title: q('title'), bar: q('bar'), fill: q('fill'), cur: q('time'), dur: q('duration'),
      play: q('play'), prev: q('prev'), next: q('next'), link: q('link'),
      setTitle: function (t) {
        ui.title.innerHTML = '<span>' + esc(t) + ' ✦&nbsp;</span><span aria-hidden="true">' + esc(t) + ' ✦&nbsp;</span>';
      },
      off: function (msg, more) {
        ui.title.innerHTML = '<span>' + esc(msg) + '</span>';
        ui.title.title = more || '';
        box.classList.add('off');
        [ui.play, ui.prev, ui.next].forEach(function (b) { b.disabled = true; });
      },
      ready: function () {
        ui.title.title = '';
        box.classList.remove('off');
        [ui.play, ui.prev, ui.next].forEach(function (b) { b.disabled = false; });
      },
      playing: function (on) {
        box.classList.toggle('playing', on);
        ui.play.setAttribute('aria-label', on ? 'Pause' : 'Play');
        ui.play.setAttribute('aria-pressed', String(on));
      },
      progress: function (seconds, total) {
        ui.fill.style.width = (total ? Math.min(100, seconds / total * 100) : 0) + '%';
        ui.cur.textContent = fmtTime(seconds);
        ui.dur.textContent = fmtTime(total);
      },
      showLink: function (href, text) {
        if (!ui.link || !href) return;
        ui.link.href = href;
        ui.link.textContent = text;
        ui.link.hidden = false;
      },
      seekFraction: function (ev) {
        var r = ui.bar.getBoundingClientRect();
        return Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
      }
    };
    var music = G.music || {};
    if (music.provider === 'youtube') startYouTube(ui, music);
    else if (music.playlist) startSoundCloud(ui, music.playlist);
    else ui.off('no playlist yet');
  }

  function fmtTime(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    return Math.floor(sec / 60) + ':' + String(sec % 60).padStart(2, '0');
  }

  /* YouTube titles often carry extras like "(Official Video)"; this trims them and adds the artist */
  function cleanTitle(title, channel) {
    var t = (title || '').replace(/\s*[(\[][^)\]]*\b(official|video|audio|lyrics?|visuali[sz]er|hd|hq|4k|remaster(ed)?)\b[^)\]]*[)\]]/gi, '').trim();
    var a = (channel || '').replace(/\s*-\s*Topic$/i, '').replace(/VEVO$/i, '').trim();
    return / [-–—] /.test(t) || !a ? t : t + ' — ' + a;
  }

  function startYouTube(ui, music) {
    if (location.protocol === 'file:') {
      // YouTube only plays inside pages served from a web address, not a file opened from disk
      ui.off('YouTube won’t play in a file opened from disk', 'Open the site with “preview the site in your browser” in sofi-blog.sh, or visit it online.');
      return;
    }
    ui.off('loading the playlist…');
    var holder = document.createElement('div');
    holder.className = 'yt-frame';
    holder.setAttribute('aria-hidden', 'true');
    holder.innerHTML = '<div id="yt-player"></div>';
    document.body.appendChild(holder);

    var player, ticker = null, skips = 0;
    var timeout = setTimeout(function () {
      ui.off('YouTube didn’t answer (ad blocker?)', 'Check your connection, or allow youtube.com in your ad or tracker blocker, then reload.');
    }, 15000);

    function showVideo() {
      var d = player.getVideoData && player.getVideoData();
      if (d && d.title) {
        ui.setTitle(cleanTitle(d.title, d.author));
        ui.showLink(player.getVideoUrl(), 'on YouTube');
      }
    }
    function tick() { ui.progress(player.getCurrentTime(), player.getDuration()); }
    function onState(ev) {
      var S = window.YT.PlayerState;
      if (ev.data === S.PLAYING) {
        skips = 0;
        ui.playing(true);
        showVideo();
        if (!ticker) ticker = setInterval(tick, 500);
      } else {
        if (ev.data === S.PAUSED || ev.data === S.ENDED) ui.playing(false);
        if (ev.data !== S.BUFFERING) { clearInterval(ticker); ticker = null; }
        if (ev.data === S.CUED || ev.data === S.BUFFERING) showVideo();
      }
    }
    function onError() {
      // the video was removed, is private, or its owner doesn't allow playing it on other sites
      skips += 1;
      if (music.list && skips <= 5) player.nextVideo();
      else ui.off('this song can’t be played here');
    }
    function create() {
      var vars = { controls: 0, disablekb: 1, playsinline: 1, rel: 0, enablejsapi: 1, origin: location.origin };
      if (music.list) { vars.listType = 'playlist'; vars.list = music.list; }
      player = new window.YT.Player('yt-player', {
        width: 200, height: 200,
        videoId: music.list ? undefined : music.video,
        playerVars: vars,
        events: {
          onReady: function () {
            clearTimeout(timeout);
            ui.ready();
            if (music.list) player.setLoop(true);
            ui.setTitle('press play');
            showVideo();
          },
          onStateChange: onState,
          onError: onError
        }
      });
      ui.play.onclick = function () {
        if (player.getPlayerState() === window.YT.PlayerState.PLAYING) player.pauseVideo();
        else player.playVideo();
      };
      ui.prev.onclick = function () { player.previousVideo(); };
      ui.next.onclick = function () { player.nextVideo(); };
      ui.bar.onclick = function (ev) {
        var total = player.getDuration();
        if (total) { player.seekTo(ui.seekFraction(ev) * total, true); tick(); }
      };
    }

    if (window.YT && window.YT.Player) { create(); return; }
    var before = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = function () { if (before) before(); create(); };
    var api = document.createElement('script');
    api.src = 'https://www.youtube.com/iframe_api';
    api.onerror = function () {
      clearTimeout(timeout);
      ui.off('YouTube’s player was blocked (ad blocker?)', 'Allow youtube.com in your ad or tracker blocker, or check your connection, then reload.');
    };
    document.head.appendChild(api);
  }

  function startSoundCloud(ui, playlist) {
    ui.off('loading the playlist…');
    var frame = document.createElement('iframe');
    frame.className = 'sc-frame';
    frame.title = 'SoundCloud player';
    frame.allow = 'autoplay';
    frame.tabIndex = -1;
    frame.setAttribute('aria-hidden', 'true');
    frame.src = 'https://w.soundcloud.com/player/?url=' + encodeURIComponent(playlist) +
      '&auto_play=false&visual=false&show_artwork=false&buying=false&sharing=false&download=false&show_comments=false';
    document.body.appendChild(frame);

    var api = document.createElement('script');
    api.src = 'https://w.soundcloud.com/player/api.js';
    var timeout = setTimeout(function () { ui.off('the player couldn’t load'); }, 12000);
    api.onerror = function () { clearTimeout(timeout); ui.off('the player couldn’t load'); };
    api.onload = function () {
      var w = window.SC.Widget(frame), E = window.SC.Widget.Events, duration = 0;
      function showSound() {
        w.getCurrentSound(function (s) {
          if (!s) return;
          duration = (s.duration || 0) / 1000;
          ui.setTitle(s.title + (s.user && s.user.username ? ' — ' + s.user.username : ''));
          ui.dur.textContent = fmtTime(duration);
          ui.showLink(s.permalink_url, 'on SoundCloud');
        });
      }
      w.bind(E.READY, function () { clearTimeout(timeout); ui.ready(); showSound(); });
      w.bind(E.PLAY, function () { ui.playing(true); showSound(); });
      w.bind(E.PAUSE, function () { ui.playing(false); });
      w.bind(E.FINISH, function () { ui.playing(false); });
      w.bind(E.ERROR, function () { ui.off('this track can’t be played here'); });
      w.bind(E.PLAY_PROGRESS, function (p) { ui.progress(p.currentPosition / 1000, duration); });
      ui.play.onclick = function () { w.toggle(); };
      ui.prev.onclick = function () { w.prev(); };
      ui.next.onclick = function () { w.next(); };
      ui.bar.onclick = function (ev) { if (duration) w.seekTo(ui.seekFraction(ev) * duration * 1000); };
    };
    document.head.appendChild(api);
  }

  function renderMade() {
    var box = $('made');
    if (box) box.innerHTML = G.made ? md(G.made) : '<p class="empty">Nothing here yet.</p>';
  }

  /* ───── start ───── */
  renderFeed();
  renderMade();
  renderNow();
  renderElsewhere();
  route();
  window.addEventListener('hashchange', route);
  initPlayer();
})();
