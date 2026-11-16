"""Card Timer & Deck Label

It draws a large timer and time bar over the review screen. It does not
keep its own clock, and by default it only displays: everything comes from
Anki's built-in card timer, your deck options and your review history. The
one exception is the off-by-default "pause while editing" setting, which moves
the card's clock on by the time spent in the Edit window, so Anki doesn't
record it either.

  - elapsed time      -> card.timer_started (the same clock Anki records)
  - shown or hidden   -> Timers > "Show on-screen timer"
  - cap / red at max  -> Timers > "Maximum answer seconds"
  - freeze on answer  -> Timers > "Stop on-screen timer on answer"
  - target time       -> Auto Advance > "Seconds to show question for" while
                         Auto Advance is running, else your own pace on the
                         deck (from the review log) when that's turned on,
                         else the add-on config
  - "last" time       -> the card's most recent correct answer (Hard, Good or
                         Easy) in the review log, as text and as a tick on
                         the bar ("60s+" if it hit the cap); clicking it
                         opens Anki's Card Info
  - deck label        -> the card's own (home) deck, in the top corner away
                         from the counter, by default only while you study a
                         parent deck; each side (question, answer) has its
                         own setting for how much of the name shows, and
                         per-deck rules can shorten or hide it, so a topic
                         deck's name doesn't give the answer away
"""

from __future__ import annotations

import html
import json
import math
import time
import zlib
from typing import Any

from aqt import gui_hooks, mw
from aqt.deckoptions import display_options_for_deck_id
from aqt.qt import QAction, QCursor, QEvent, QMenu, QObject, Qt, qconnect
from aqt.reviewer import Reviewer, ReviewerBottomBar
from aqt.utils import tooltip
from aqt.webview import WebContent

from .settings import (
    PACE_MIN_ANSWERS,
    PACE_RECENT_ANSWERS,
    SettingsDialog,
    format_secs,
)

ADDON = __name__

# presets that have already shown the "timer is off" hint, kept in the profile
_HINTED_KEY = "card_timer_deck_label_hinted_presets"
_OPEN_OPTIONS_CMD = "card_timer_deck_label:options"
_CARD_INFO_CMD = "card_timer_deck_label:card_info"
_DECK_MENU_CMD = "card_timer_deck_label:deck_menu"


# config.json, read once: each setting's default, and so the kind of value it
# takes
_DEFAULTS: dict[str, Any] = (
    mw.addonManager.addonConfigDefaults(mw.addonManager.addonFromModule(ADDON)) or {}
)


def _right_kind(value: Any, default: Any) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, type(default))


def _cfg() -> dict[str, Any]:
    """The settings, with the default in place of any that's missing or the
    wrong kind of value (a hand-edited file), so nothing later has to check."""
    cfg = dict(mw.addonManager.getConfig(ADDON) or {})
    for key, default in _DEFAULTS.items():
        if not _right_kind(cfg.get(key), default):
            cfg[key] = dict(default) if isinstance(default, dict) else default
    return cfg


def _deck_conf(card) -> dict[str, Any]:
    return mw.col.decks.config_dict_for_deck_id(card.current_deck_id())


# --------------------------------------------------------------------------
# Inject the display into the review screen (and optionally hide the small
# built-in timer in the bottom bar).
# --------------------------------------------------------------------------

_CSS = """
#ptimer { position: fixed; z-index: 9999; pointer-events: none;
          top: 0; left: 0; right: 0; background-color: inherit; }
#ptimer .pt-bar { position: relative; height: 4px; width: 100%%;
                  background: rgba(128,128,128,.18); }
#ptimer .pt-fill { height: 100%%; width: 0; background: %(normal)s;
                   transition: width .2s linear, background-color .3s; }
#ptimer .pt-tick { position: absolute; top: 0; width: 2px; height: 9px;
                   margin-left: -1px; background: var(--fg, #000); opacity: .6; }
#ptimer .pt-num { position: absolute; top: 10px; %(side)s
                  font: 600 %(size)dpx -apple-system, BlinkMacSystemFont,
                        "Segoe UI", Roboto, sans-serif;
                  font-variant-numeric: tabular-nums; color: %(normal)s;
                  transition: color .3s; pointer-events: auto; cursor: default;
                  /* the card's own background, so anything underneath (like
                     the line between question and answer) is hidden rather
                     than showing through the digits */
                  background-color: inherit; padding: 0 6px 4px;
                  border-radius: 6px;
                  /* "+3s" and "last 60s+" keep their order in right-to-left
                     languages and on right-to-left cards */
                  direction: ltr; unicode-bidi: isolate; }
#ptimer .pt-why { display: none; position: absolute; top: 100%%; margin-top: 6px;
                  %(why_side)s width: max-content; max-width: 280px;
                  padding: 7px 10px; text-align: left;
                  font: 400 13px/1.4 -apple-system, BlinkMacSystemFont,
                        "Segoe UI", Roboto, sans-serif;
                  color: var(--fg, #222); background: var(--canvas-elevated, #fff);
                  border: 1px solid var(--border, #ccc);
                  border-radius: var(--border-radius, 5px);
                  box-shadow: 0 2px 8px rgba(0,0,0,.15); }
#ptimer .pt-num:hover .pt-why:not(:empty) { display: block; }
#ptimer .pt-last { display: block; font-size: .4em; font-weight: 500;
                   opacity: .7; }
/* clicking it opens Anki's Card Info, with the card's full history */
#ptimer .pt-last:not(:empty) { cursor: pointer; }
#ptimer .pt-last:hover { text-decoration: underline; }
/* room for the counter at the top of the card, sized by reserve() in the JS.
   Only while reserve() is making room (it sets the class), so a card
   template's own ::before is left alone the rest of the time */
html.pt-room #qa::before { content: ""; display: block;
                           float: var(--pt-float, none); width: var(--pt-w, 0);
                           height: var(--pt-h, 0); }
/* the same room on the other side, when what would run under the counter is
   centered, so it stays centered; on body, as #qa has only one ::before */
html.pt-room2 body::before { content: ""; display: block;
                             float: var(--pt-float2, none); width: var(--pt-w, 0);
                             height: var(--pt-h2, 0); }
/* Anki scrolls the answer to the top of the window on a tall card; stop short
   of the counter (fixed there) rather than under it. Set by reserve() */
#answer { scroll-margin-top: var(--pt-sm, 0px); }
/* room for the deck label: the card starts below it (or, with the label at
   the bottom, ends above it), sized by deckRoom() in the JS */
#qa { padding-top: var(--pd-pad, 0px); padding-bottom: var(--pd-padb, 0px); }
#ptimer.pt-amber .pt-num  { color: %(amber)s; }
#ptimer.pt-amber .pt-fill { background: %(amber)s; }
#ptimer.pt-over .pt-num   { color: %(over)s; }
#ptimer.pt-over .pt-fill  { background: %(over)s; }
#ptimer.pt-stopped .pt-fill { transition: none; }
#ptimer-hint { position: fixed; z-index: 10000; top: 14px; left: 50%%;
               transform: translateX(-50%%); width: max-content;
               max-width: min(560px, calc(100vw - 32px));
               display: flex; align-items: center; gap: 8px;
               padding: 8px 8px 8px 14px; font-size: 14px;
               color: var(--fg, #222); background: var(--canvas-elevated, #fff);
               border: 1px solid var(--border, #ccc);
               border-radius: var(--border-radius, 5px);
               box-shadow: 0 2px 8px rgba(0,0,0,.15); }
#ptimer-hint button { flex: none; }
"""

# Anki's flag and mark icons sit in the top corners, hidden until the card is
# flagged or the note marked. Which icon is in which corner: (ltr, rtl).
_CORNER_ICONS = {"left": ("_mark", "_flag"), "right": ("_flag", "_mark")}

_JS = r"""
(function () {
  if (window.ptShow) return;
  var iv = null, o = {};

  function el() {
    var e = document.getElementById('ptimer');
    if (!e) {
      e = document.createElement('div');
      e.id = 'ptimer';
      e.innerHTML = '<div class="pt-bar"><div class="pt-fill"></div>' +
                    '<div class="pt-tick"></div></div>' +
                    '<div class="pt-num"><span class="pt-val"></span>' +
                    '<span class="pt-last"></span><span class="pt-why"></span></div>';
      document.body.appendChild(e);
      // the last time opens Anki's Card Info (_CARD_INFO_CMD in Python)
      e.querySelector('.pt-last').addEventListener('click', function () {
        if (this.textContent) pycmd('card_timer_deck_label:card_info');
      });
      window.addEventListener('resize', reserve);
      // a picture on the card that loads late can move what's under the
      // counter, so check again (load events don't bubble, hence capture)
      document.addEventListener('load', function (ev) {
        var qa = document.getElementById('qa');
        if (qa && ev.target.tagName === 'IMG' && qa.contains(ev.target)) reserve();
      }, true);
    }
    return e;
  }

  // What on the card, laid out as if the counter weren't there, would run
  // under it: null for nothing, else whether any of it is centered.
  // b is the counter's box at its widest, with the page scrolled to the top.
  var MEDIA = /^(IMG|VIDEO|CANVAS|SVG|IFRAME|INPUT|TEXTAREA|BUTTON|SELECT)$/i;
  function overlap(qa, b) {
    var pad = 6, y = window.scrollY, hit = null, range = document.createRange();
    function hits(r) {
      return r.width && r.height && r.right > b.left - pad &&
             r.left < b.right + pad && r.top + y < b.bottom + pad &&
             r.bottom + y > b.top - pad;
    }
    function centered(node) {
      var a = getComputedStyle(node).textAlign;
      return a === 'center' || a === '-webkit-center';
    }
    var walk = document.createTreeWalker(
      qa, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (var n = walk.nextNode(); n; n = walk.nextNode()) {
      var rects = [], from = n.parentElement;
      if (n.nodeType === Node.TEXT_NODE) {
        if (!n.data.trim()) continue;
        range.selectNodeContents(n);
        rects = range.getClientRects();
      } else {
        var r = n.getBoundingClientRect();
        if (r.top + y > b.bottom + pad) continue;  // below the counter
        var s = getComputedStyle(n);
        // pictures and controls, and inline boxes you can see (a badge).
        // Blocks (the line between question and answer, a panel) run the
        // full width whatever room is made, so making room wouldn't help.
        var seen = MEDIA.test(n.tagName) ||
          (s.display.indexOf('inline') === 0 &&
           (s.backgroundColor !== 'rgba(0, 0, 0, 0)' ||
            s.backgroundImage !== 'none' || parseFloat(s.borderTopWidth) > 0 ||
            parseFloat(s.borderLeftWidth) > 0));
        if (seen && s.visibility !== 'hidden') rects = [r];
      }
      for (var i = 0; i < rects.length; i++) {
        if (!hits(rects[i])) continue;
        hit = hit || {centered: false};
        if (from && centered(from)) hit.centered = true;
        break;
      }
      if (hit && hit.centered) break;  // can't get any more decided
    }
    return hit;
  }

  // Room for the counter at the top of the card, only where something would
  // otherwise run under it. In a corner, text flows around it: on its side
  // only (#qa::before), or on both sides (body::before too) when what's there
  // is centered, so it stays centered. A centered counter pushes the card down.
  // Sized for the widest the counter gets on this card, so nothing reflows as
  // it counts. No room while it's held back until the answer: on some cards
  // room means a gap above the text, and there's nothing there yet to avoid.
  function reserve() {
    // the deck label first: its place sets where the card starts
    placeDeck();
    deckRoom();
    placeIcon();
    var e = el(), html = document.documentElement, root = html.style;
    var qa = document.getElementById('qa');
    html.classList.remove('pt-room');
    html.classList.remove('pt-room2');
    var b = qa ? counterBox() : null;
    // measured on the question side too, so it's in place before Anki scrolls
    root.setProperty('--pt-sm', b ? Math.ceil(b.bottom + 6) + 'px' : '0px');
    if (!b || e.querySelector('.pt-num').style.display === 'none') return;
    var side = getComputedStyle(e.querySelector('.pt-num')).textAlign;
    var hit = overlap(qa, b);  // measured with no room made yet
    if (!hit) return;
    var y = window.scrollY, body = document.body, bs = getComputedStyle(body);
    // from where the card's content starts, below any room for the deck label
    var top = qa.getBoundingClientRect().top + y +
              parseFloat(getComputedStyle(qa).paddingTop);
    root.setProperty('--pt-h', Math.max(b.bottom - top + 6, 0) + 'px');
    html.classList.add('pt-room');
    if (side === 'center') {
      root.setProperty('--pt-float', 'none');
      root.setProperty('--pt-w', '0px');
      return;
    }
    var w = side === 'left'
      ? b.right - parseFloat(bs.marginLeft) + 8
      : document.documentElement.clientWidth - b.left -
        parseFloat(bs.marginRight) + 8;
    root.setProperty('--pt-float', side);
    root.setProperty('--pt-w', Math.max(w, 0) + 'px');
    if (hit.centered) {
      // body::before starts at the top of body's content, above the card's
      var btop = body.getBoundingClientRect().top + y +
                 parseFloat(bs.borderTopWidth) + parseFloat(bs.paddingTop);
      root.setProperty('--pt-h2', Math.max(b.bottom - btop + 6, 0) + 'px');
      root.setProperty('--pt-float2', side === 'left' ? 'right' : 'left');
      html.classList.add('pt-room2');
    }
  }
  window.ptReserve = reserve;

  // Anki puts a card's new content in place asynchronously, once its images
  // are preloaded and MathJax is rendered, so measuring right away would
  // see the previous side. Its own update queue runs this after all of that.
  // Errors are caught: a rejected promise would stop Anki's queue.
  function afterShown(fn) {
    var run = function () {
      try { fn(); } catch (err) { console.error('Card Timer & Deck Label', err); }
    };
    if (typeof window._queueAction === 'function') window._queueAction(run);
    else run();
  }

  // seconds elapsed, or seconds left until the target when counting down
  function label(s) {
    if (!o.countDown || !(o.target > 0)) return Math.floor(s) + 's';
    var left = o.target - s;
    if (left > 0) return Math.ceil(left) + 's';
    var over = Math.floor(-left);
    return over ? '+' + over + 's' : '0s';
  }

  function paint(sec) {
    var e = el();
    var s = o.max ? Math.min(sec, o.max) : sec;
    e.querySelector('.pt-val').textContent = label(s);
    var frac = o.target > 0 ? Math.min(s / o.target, 1) : 0;
    var fill = e.querySelector('.pt-fill');
    fill.style.width = (frac * 100) + '%';
    e.querySelector('.pt-bar').style.display = o.bar ? '' : 'none';
    var cls = '';
    if ((o.max && s >= o.max) || (o.target > 0 && s >= o.target)) cls = 'pt-over';
    else if (o.target > 0 && s >= o.target * o.amber) cls = 'pt-amber';
    e.className = cls;
  }

  function stopTick() { if (iv !== null) { clearInterval(iv); iv = null; } }

  // start: when the card's clock started (Anki's card.timer_started, in
  // seconds since the epoch). Counting from it on the wall clock, as Anki
  // does, keeps the counter in step with what Anki records, also when this
  // page got the message late or the computer slept mid-card
  function run(start) {
    stopTick();
    var tick = function () { paint(Math.max(0, Date.now() / 1000 - start)); };
    tick();
    iv = setInterval(tick, 200);
  }

  // "last 7s", or "last 60s+" when that answer hit Maximum answer seconds
  // (Anki records no more, so it took at least that long). widest: the
  // longest it can read, for measuring
  function lastText(s, widest) {
    return 'last ' + Math.floor(s) + 's' + (widest || o.lastCapped ? '+' : '');
  }

  // the card's last correct time, as text and as a tick on the bar
  function showLast(visible) {
    var e = el(), known = visible && o.last != null;
    e.querySelector('.pt-last').textContent = known ? lastText(o.last) : '';
    // past the target it would be off the end of the bar
    var onBar = known && o.target > 0 && o.last < o.target;
    var tick = e.querySelector('.pt-tick');
    tick.style.display = onBar ? '' : 'none';
    if (onBar) tick.style.left = (o.last / o.target * 100) + '%';
  }

  // what the counter area shows on this side: the seconds and the last time,
  // each unless turned off or held back until the answer; with neither, the
  // area (and its backing) goes away
  function showParts(answerSide) {
    var e = el(), num = e.querySelector('.pt-num');
    var counter = o.counter !== 'never' && (o.counter !== 'answer' || answerSide);
    e.querySelector('.pt-val').style.display = counter ? '' : 'none';
    showLast(answerSide || !o.lastOnAnswer);
    var any = counter || e.querySelector('.pt-last').textContent !== '';
    num.style.display = any ? '' : 'none';
  }

  // opts: start (when the card's clock started; see run), elapsed (seconds
  // on it now, shown as-is while paused), max, target, amber,
  // bar, countDown, counter ('always', 'answer' or 'never'),
  // last (seconds the card took last time, or null),
  // lastCapped (that answer hit Maximum answer seconds),
  // lastOnAnswer (hold the last time back until the answer is shown),
  // why ([heading, explanation or ""] shown when hovering the counter),
  // paused (you're editing the card and the clock is paused)
  window.ptShow = function (opts) {
    stopTick();
    o = opts;
    var e = el();
    if (!o.max) {  // timer off in options
      e.style.display = 'none';
      afterShown(reserve);
      return;
    }
    e.style.display = '';
    showParts(false);
    var why = e.querySelector('.pt-why');
    why.textContent = '';
    if (o.why) {
      var head = document.createElement('b');
      head.textContent = o.why[0];
      why.append(head);
      if (o.why[1]) why.append(document.createElement('br'), o.why[1]);
    }
    if (o.paused) paint(o.elapsed);
    else run(o.start);
    afterShown(reserve);
  };

  // You're editing with "pause while editing" on: hold the counter
  window.ptPause = function () { stopTick(); };

  // ...and carry on once you're done, from the clock's start as moved on by
  // the pause
  window.ptResume = function (start) {
    var e = el();
    if (e.style.display === 'none' || e.classList.contains('pt-stopped')) return;
    run(start);
  };

  // Answer side: show the last time if it was held back, and when elapsed is
  // given, freeze on that value (worked out in Python from the card's clock,
  // and capped like Anki's own record)
  window.ptAnswer = function (elapsed) {
    var e = el(), timerOn = e.style.display !== 'none';
    if (timerOn) showParts(true);
    // the answer's content, and the seconds or the last time if they've just
    // appeared, may need different room
    afterShown(reserve);
    if (!timerOn || elapsed === null) return;
    stopTick();
    paint(elapsed);
    e.classList.add('pt-stopped');
  };

  // The card's deck, where the deck_position setting puts it. d: null to hide,
  // or {text, full (shown on hover), hue (0-359, or null for no color),
  // bottom (the label is along the bottom edge), share ('left', 'right' or
  // 'center' when it's in the counter's spot, else null), held (keep its room
  // but show nothing, until the answer)}
  var deck = null;

  // The space the counter takes at its widest on this card (any value it can
  // show, and the last time at its longest), measured even while it's hidden
  // on the question side, so the label beside it never has to move.
  function counterBox() {
    var e = el();
    if (e.style.display === 'none' || !o.max) return null;  // timer off
    var num = e.querySelector('.pt-num'), val = e.querySelector('.pt-val');
    var last = e.querySelector('.pt-last');
    var counterOn = o.counter !== 'never';
    if (!counterOn && o.last == null) return null;  // nothing ever shows
    var saved = [num.style.display, num.style.visibility, val.style.display,
                 val.textContent, last.textContent];
    num.style.display = '';
    num.style.visibility = 'hidden';
    val.style.display = counterOn ? '' : 'none';
    last.textContent = o.last == null ? '' : lastText(o.max, true);
    var box = null, mid = 0;
    [0, o.target || 0, o.max].forEach(function (s) {
      val.textContent = label(s);
      var r = num.getBoundingClientRect();
      if (!box || r.width > box.width) {
        box = r;
        var v = counterOn ? val.getBoundingClientRect() : r;
        mid = (v.top + v.bottom) / 2;  // the digits' row
      }
    });
    num.style.display = saved[0];
    num.style.visibility = saved[1];
    val.style.display = saved[2];
    val.textContent = saved[3];
    last.textContent = saved[4];
    return box && box.width ? {left: box.left, right: box.right, mid: mid,
                               top: box.top, bottom: box.bottom} : null;
  }

  // In the counter's spot: on its row, inward of it, the counter nearest the
  // edge. Anywhere else (or with the timer off) the stylesheet places it.
  function placeDeck() {
    var p = document.getElementById('pdeck');
    if (!p) return;
    p.style.left = p.style.right = p.style.top = p.style.transform = '';
    if (!deck || !deck.share) return;
    var b = counterBox();
    if (!b) return;
    var gap = 6, w = document.documentElement.clientWidth;
    p.style.top = Math.max(4, Math.round(b.mid - p.offsetHeight / 2)) + 'px';
    p.style.transform = 'none';
    if (deck.share === 'left') {
      p.style.left = Math.round(b.right + gap) + 'px';
      p.style.right = 'auto';
    } else {  // right, or the center: the label goes on the counter's left
      p.style.right = Math.round(w - b.left + gap) + 'px';
      p.style.left = 'auto';
    }
  }

  // Anki's flag or mark icon in the counter's corner goes just inward of the
  // counter (and of the deck label beside it), rather than the counter
  // stepping aside for it: the counter never moves, so neither does the room
  // made for it, and flagging or marking a card leaves the card where it is.
  // Placed for the counter at its widest, as the label is, so the icon stays
  // put too. The stylesheet gives the icon in that corner --pt-icon-inset.
  function placeIcon() {
    var root = document.documentElement.style, b = counterBox();
    var side = b ? getComputedStyle(el().querySelector('.pt-num')).textAlign : '';
    if (side !== 'left' && side !== 'right') {
      root.removeProperty('--pt-icon-inset');
      return;
    }
    var left = b.left, right = b.right, gap = 2;
    var p = document.getElementById('pdeck');
    if (deck && deck.share === side && p) {
      var r = p.getBoundingClientRect();
      if (r.width) {
        left = Math.min(left, r.left);
        right = Math.max(right, r.right);
      }
    }
    var inset = side === 'left'
      ? right + gap : document.documentElement.clientWidth - left + gap;
    root.setProperty('--pt-icon-inset', Math.round(inset) + 'px');
  }

  // Room on the card for the deck label: padding above the card for a label
  // at the top, below it for one at the bottom.
  function deckRoom() {
    var root = document.documentElement.style;
    var p = document.getElementById('pdeck'), qa = document.getElementById('qa');
    var pad = 0, padb = 0;
    if (deck && p && qa) {
      if (deck.bottom) {
        // on screen at the bottom: the card's end can scroll clear of it
        padb = Math.ceil(window.innerHeight - p.getBoundingClientRect().top + 6);
      } else {
        // the card starts just below the label; measured with no room set yet.
        // Both scroll with the page, so compare them on screen: Anki may
        // already have scrolled down to the answer
        root.setProperty('--pd-pad', '0px');
        var top = qa.getBoundingClientRect().top;
        pad = Math.ceil(p.getBoundingClientRect().bottom - top + 6);
      }
    }
    root.setProperty('--pd-pad', Math.max(0, pad) + 'px');
    root.setProperty('--pd-padb', Math.max(0, padb) + 'px');
  }
  window.ptDeck = function (d) {
    deck = d;
    var p = document.getElementById('pdeck');
    if (!p) {
      p = document.createElement('div');
      p.id = 'pdeck';
      // right-click for this deck's rules (_DECK_MENU_CMD in Python)
      p.addEventListener('contextmenu', function (ev) {
        ev.preventDefault();
        pycmd('card_timer_deck_label:deck_menu');
      });
      document.body.appendChild(p);
    }
    if (d) {
      p.textContent = d.text;
      p.title = d.full;
      p.className = 'pd-on' + (d.hue === null ? '' : ' pd-hue') +
                    (d.held ? ' pd-held' : '');
      p.style.setProperty('--pd-hue', d.hue === null ? '0' : String(d.hue));
    } else {
      p.className = '';
    }
    // Placing the label and making room for it is left to reserve(), which
    // the ptShow sent right after this queues (as do ptAnswer, ptReserve
    // and resizing)
  };

  // A notice that stays until dismissed; its button sends cmd to Python
  window.ptHint = function (text, button, cmd) {
    var old = document.getElementById('ptimer-hint');
    if (old) old.remove();  // one at a time: the newest
    var h = document.createElement('div');
    h.id = 'ptimer-hint';
    var t = document.createElement('span');
    t.textContent = text;
    var b = document.createElement('button');
    b.textContent = button;
    b.onclick = function () { h.remove(); pycmd(cmd); };
    var x = document.createElement('button');
    x.textContent = '×';
    x.title = 'Dismiss';
    x.onclick = function () { h.remove(); };
    h.append(t, b, x);
    document.body.appendChild(h);
  };
})();
"""


def _css(cfg: dict[str, Any]) -> str:
    pos = cfg["counter_position"]
    if pos == "top-center":
        side = "left: 50%; transform: translateX(-50%); text-align: center;"
        why_side = "left: 50%; transform: translateX(-50%);"
        icon = ""
    else:
        edge = "left" if pos == "top-left" else "right"
        ltr, rtl = _CORNER_ICONS[edge]
        # 10px plus the counter's 6px padding puts the digits 16px in
        side = f"{edge}: 10px; text-align: {edge};"
        why_side = f"{edge}: 0;"
        # the icon in that corner goes inward of the counter (placeIcon() in
        # the JS); 10px is where Anki puts it
        icon = (
            f"[dir=ltr] #{ltr}, [dir=rtl] #{rtl} "
            f"{{ {edge}: var(--pt-icon-inset, 10px); }}"
        )
    # with color changes turned off, the counter and bar keep the normal color
    changes = cfg["color_changes"]
    css = _CSS % {
        "side": side,
        "why_side": why_side,
        "size": int(cfg["font_size_px"]),
        "normal": cfg["color_normal"],
        "amber": cfg["color_amber"] if changes else cfg["color_normal"],
        "over": cfg["color_over"] if changes else cfg["color_normal"],
    }
    return css + icon + _deck_css(cfg)


_DECK_CSS = """
#pdeck { display: none; position: POSITION; z-index: 9998; PLACE
         max-width: calc(50vw - 90px); overflow: hidden; text-overflow: ellipsis;
         white-space: nowrap; padding: 3px 10px; border-radius: 6px;
         font: 600 15px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI",
               Roboto, sans-serif;
         color: var(--fg, #222); background: rgba(128,128,128,.12);
         border: 1px solid rgba(128,128,128,.35); cursor: default; }
#pdeck.pd-on { display: block; }
#pdeck.pd-held { visibility: hidden; }
/* each deck keeps its own color, readable on light and dark cards */
#pdeck.pd-hue { color: hsl(var(--pd-hue) 65% 34%);
                background: hsl(var(--pd-hue) 70% 50% / .13);
                border-color: hsl(var(--pd-hue) 60% 45% / .45); }
.nightMode #pdeck.pd-hue { color: hsl(var(--pd-hue) 80% 76%);
                           background: hsl(var(--pd-hue) 60% 50% / .2);
                           border-color: hsl(var(--pd-hue) 60% 60% / .45); }
"""


_DECK_POSITIONS = (
    "top-left",
    "top-center",
    "top-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
)


def _deck_position(cfg: dict[str, Any]) -> str:
    """Where the deck label goes. "auto" is the top corner away from the
    counter, and the top left when the counter is centered."""
    pos = cfg["deck_position"]
    if pos in _DECK_POSITIONS:
        return pos
    return "top-right" if cfg["counter_position"] == "top-left" else "top-left"


def _deck_css(cfg: dict[str, Any]) -> str:
    # in the counter's spot, the JS moves it onto the counter's row, inward of
    # it; this is where it goes with the timer off
    vertical, horizontal = _deck_position(cfg).split("-")
    # At the top it scrolls away with the card's first lines: you read it when
    # the card appears, and on screen it would only sit over the text. At the
    # bottom it stays on screen like a footer, or on a long card you'd only
    # see it at the end; the card leaves room for its last line to scroll clear.
    if vertical == "top":
        position, place = "absolute", "top: 10px;"
    else:
        position, place = "fixed", "bottom: 10px;"
    dodge = ""
    if horizontal == "center":
        place += " left: 50%; transform: translateX(-50%);"
    else:
        place += f" {horizontal}: 12px;"
        # Anki's flag and mark icons are in the top corners only
        if vertical == "top":
            ltr, rtl = _CORNER_ICONS[horizontal]
            dodge = (
                f"[dir=ltr] #{ltr}:not([hidden]) ~ #pdeck, "
                f"[dir=rtl] #{rtl}:not([hidden]) ~ #pdeck {{ {horizontal}: 50px; }}"
            )
    css = _DECK_CSS.replace("POSITION", position).replace("PLACE", place)
    return css + dodge


def _bottom_css(cfg: dict[str, Any]) -> str:
    return "#time { display: none !important; }" if cfg["hide_builtin_timer"] else ""


def _on_webview_will_set_content(web_content: WebContent, context: Any) -> None:
    # the style ids let the settings dialog restyle an open review screen
    if isinstance(context, Reviewer):
        web_content.head += (
            f'<style id="ptimer-style">{_css(_cfg())}</style><script>{_JS}</script>'
        )
    elif isinstance(context, ReviewerBottomBar):
        css = _bottom_css(_cfg())
        web_content.head += f'<style id="ptimer-style">{css}</style>'


# --------------------------------------------------------------------------
# Targets and history from the review log.
# --------------------------------------------------------------------------

def _pace_from_log(
    did: int, max_ms: int, percentile: float
) -> tuple[float | None, int]:
    """Seconds you answered within on `percentile`% of your recent answers in
    the deck (None with too few), and how many answers that's based on."""
    # rated answers on cards whose home deck is this one; answers that hit
    # "Maximum answer seconds" are left out, as you'd likely walked away
    times = mw.col.db.list(
        "select time from revlog where cid in "
        "(select id from cards where odid = ? or (odid = 0 and did = ?)) "
        "and ease > 0 and time > 0 and time < ? "
        "order by id desc limit ?",
        did,
        did,
        max_ms,
        PACE_RECENT_ANSWERS,
    )
    if len(times) < PACE_MIN_ANSWERS:
        return None, len(times)
    times.sort()
    rank = min(max(math.ceil(len(times) * percentile / 100), 1), len(times))
    return times[rank - 1] / 1000, len(times)


_pace_cache: dict[tuple[int, int, float], tuple[float | None, int]] = {}


def _pace_target(card, percentile: float) -> tuple[float | None, int]:
    key = (card.current_deck_id(), card.time_limit(), percentile)
    if key not in _pace_cache:
        _pace_cache[key] = _pace_from_log(*key)
    return _pace_cache[key]


def _deck_targets(
    percentile: float,
) -> list[tuple[str, float | None, float | None, int]]:
    """(deck name, its preset's Auto Advance seconds or None, pace target or
    None, answers) for each deck, for the settings dialog's table. Uncached,
    so it includes today's answers."""
    rows = []
    if not mw.col:
        return rows
    decks = mw.col.decks.all_names_and_ids(
        skip_empty_default=True, include_filtered=False
    )
    for deck in decks:
        conf = mw.col.decks.config_dict_for_deck_id(deck.id)
        pace, answers = _pace_from_log(deck.id, conf["maxTaken"] * 1000, percentile)
        auto = float(conf.get("secondsToShowQuestion") or 0) or None
        rows.append((deck.name, auto, pace, answers))
    return rows


def _target(card, conf: dict[str, Any], cfg: dict[str, Any]) -> tuple[float, str]:
    """The target in seconds, and where it comes from (shown on hover)."""
    # Auto Advance's seconds are a real deadline only while it's running (Anki
    # shows the answer, or a reminder, then); otherwise your own pace if on,
    # then the config.
    # Older Anki versions have no Auto Advance, hence the getattr.
    running = getattr(mw.reviewer, "auto_advance_enabled", False)
    if running and conf.get("secondsToShowQuestion"):
        return float(conf["secondsToShowQuestion"]), (
            'Auto Advance is running, so this is the deck\'s "Seconds to show'
            ' question for".'
        )
    # the default needs no explanation, unless pace is on and couldn't be used
    why = ""
    if cfg["pace_target"]:
        percentile = float(cfg["pace_percentile"])
        pace, answers = _pace_target(card, percentile)
        if pace:
            return pace, (
                f"Your pace: you were faster than this on {percentile:g}% of your"
                f" last {answers:,} answers in this deck."
            )
        why = (
            f"Your setting: your pace needs {PACE_MIN_ANSWERS} answers in this"
            f" deck, and it has {answers}."
        )
    return float(cfg["target_seconds"]), why


def _last_time(card) -> tuple[float | None, bool]:
    """Seconds you took the last time you recalled the card (Hard, Good or
    Easy; a fail's time says little), or None, and whether that answer hit
    "Maximum answer seconds". Anki records no more than that, so a capped
    answer shows as "60s+" rather than being skipped for an older one.
    Answers with no time are skipped: Anki records 0 for a card graded from
    the browser, as some imported history has."""
    ms = mw.col.db.scalar(
        "select time from revlog where cid = ? and ease > 1 and time > 0"
        " order by id desc limit 1",
        card.id,
    )
    if not ms:
        return None, False
    return ms / 1000, ms >= card.time_limit()


# How much of a deck's name each choice of the "On the question side" and "On
# the answer side" settings shows; 0 is the whole path. "nothing" isn't here:
# it shows no label.
_LEVELS = {"deck": 1, "parent": 2, "two_parents": 3, "full": 0}
_RULE_VALUES = ("this", "nothing", "usual")


def _rules_by_name(cfg: dict[str, Any]) -> dict[str, dict[str, str]]:
    """The per-deck rules, by deck name. A rule has an entry for each side
    ("question", "answer") it changes: "this" (just that deck's own name),
    "nothing", or "usual" (what the settings say, whatever a parent deck's
    rule says). Rules for decks that aren't in this collection are left out."""
    rules = cfg["deck_rules"]
    if not rules:
        return {}
    return {
        deck.name: rules[str(deck.id)]
        for deck in mw.col.decks.all_names_and_ids(include_filtered=False)
        if isinstance(rules.get(str(deck.id)), dict)
    }


def _deck_rule(
    deck_name: str, side: str, rules: dict[str, dict[str, str]]
) -> tuple[str | None, str]:
    """The rule for one side of this deck's label, and the deck it's set on.
    The closest one wins, from the deck itself up through its parents.
    (None, the deck) when there's none, so the setting for that side applies."""
    parts = deck_name.split("::")
    for depth in range(len(parts), 0, -1):
        name = "::".join(parts[:depth])
        value = rules.get(name, {}).get(side)
        if value in _RULE_VALUES:
            return value, name
    return None, deck_name


def _contains_studied_deck(deck_name: str) -> bool:
    """Whether this deck is, or contains, the deck you picked to study, so a
    label with this deck's name would only repeat what you picked."""
    studying = mw.col.decks.name(mw.col.decks.get_current_id())
    return studying == deck_name or studying.startswith(deck_name + "::")


def _side_shows(
    deck_name: str, side: str, cfg: dict[str, Any], rules: dict[str, dict[str, str]]
) -> tuple[str, int] | None:
    """What the label shows on one side for a card of this deck: the deck
    whose name it is and how many levels of it (0 for all), or None for
    nothing."""
    value, rule_deck = _deck_rule(deck_name, side, rules)
    if value == "nothing":
        return None
    if value == "this":
        # its own name would only repeat the deck you picked to study
        return None if _contains_studied_deck(rule_deck) else (rule_deck, 1)
    setting = cfg[f"deck_{side}_shows"]
    if setting == "nothing":
        return None
    return deck_name, _LEVELS.get(setting, 2)


def _deck_label(
    card, cfg: dict[str, Any], answer: bool = False
) -> dict[str, Any] | None:
    """What the deck label shows for this card on this side, or None for no
    label."""
    mode = cfg["show_deck"]
    if mode == "never":
        return None
    # the card's home deck, also when it's being studied in a filtered deck
    did = card.current_deck_id()
    # studying the deck itself, the label would only repeat what you picked
    if mode == "parent" and did == mw.col.decks.get_current_id():
        return None
    name = mw.col.decks.name(did)
    rules = _rules_by_name(cfg)
    this_side, other_side = "question", "answer"
    if answer:
        this_side, other_side = other_side, this_side
    pos = _deck_position(cfg)
    place = {
        "bottom": pos.startswith("bottom"),
        # in the counter's spot: which side it sits beside the counter
        "share": pos.split("-")[1] if pos == cfg["counter_position"] else None,
    }
    here = _side_shows(name, this_side, cfg, rules)
    if here is None:
        # Nothing on this side. If the other side shows it, its room is kept
        # here (unless that's turned off), so the card doesn't move when you
        # flip it.
        if not cfg["deck_keep_space"]:
            return None
        if _side_shows(name, other_side, cfg, rules) is None:
            return None
        return {"text": " ", "full": "", "hue": None, "held": True, **place}
    shown, levels = here
    parts = shown.split("::")
    if levels > 0:
        parts = parts[-levels:]
    return {
        "text": " › ".join(parts),
        # hover and color go by what's shown, so neither gives away a subdeck
        "full": shown.replace("::", " › ")
        + "\nRight-click for options",
        # from the deck's name, so a deck keeps its color across sessions
        "hue": zlib.crc32(shown.encode()) % 360 if cfg["deck_colors"] else None,
        "held": False,
        **place,
    }


def _save_deck_rules(rules: dict[str, dict[str, str]], confirmation: str) -> None:
    cfg = _cfg()
    cfg["deck_rules"] = rules
    mw.addonManager.writeConfig(ADDON, cfg)
    # the card on screen now: Auto Advance may have moved on from the one the
    # menu was opened on
    card = mw.reviewer.card
    if card and mw.state == "review":
        answer = mw.reviewer.state == "answer"
        mw.reviewer.web.eval(
            "window.ptDeck && ptDeck(%s); window.ptReserve && ptReserve();"
            % json.dumps(_deck_label(card, cfg, answer=answer))
        )
    tooltip(html.escape(confirmation))


def _show_deck_menu(card) -> None:
    """Right-clicking the label: pick what it says, for this card's deck or
    for every deck under one of its parents. Each side has its own submenu,
    in the same order whichever side of the card you're on, with the same
    sections whichever deck you're studying. In each, one line
    is always checked: what's in force, in the section of the deck it's set
    on. Clicking it removes that deck's rule for that side."""
    cfg = _cfg()
    full = mw.col.decks.name(card.current_deck_id())
    ids = {
        deck.name: str(deck.id)
        for deck in mw.col.decks.all_names_and_ids(include_filtered=False)
    }
    own = ids.get(full)
    if not own:
        return
    saved = {d: dict(r) for d, r in cfg["deck_rules"].items() if isinstance(r, dict)}
    by_name = _rules_by_name(cfg)
    parts = full.split("::")
    chain = ["::".join(parts[:depth]) for depth in range(1, len(parts) + 1)]
    studying = _contains_studied_deck(full)

    def for_menu(text: str) -> str:
        # in menus, & marks a shortcut key unless doubled
        short = text if len(text) <= 60 else text[:59] + "…"
        return short.replace("&", "&&")

    def add_side(menu: QMenu, side: str) -> None:
        """The sections for one side ("question" or "answer")."""
        value, rule_deck = _deck_rule(full, side, by_name)
        # what this side's setting gives the card: None for Nothing
        setting = cfg[f"deck_{side}_shows"]
        levels = _LEVELS.get(setting, 2)
        usual = None
        if setting != "nothing":
            usual = " › ".join(parts[-levels:] if levels > 0 else parts)
        nothing = "Nothing"
        if side == "question" and _side_shows(full, "answer", cfg, by_name):
            nothing = "Nothing until the answer"

        def with_rule(
            deck_id: str, new: str | None, clear: tuple[str, ...] = ()
        ) -> dict[str, dict[str, str]]:
            """The rules with one deck's rule for this side set (None: no
            rule), and this side's rules of the decks in `clear` removed.
            The other side's rules are left alone."""
            rules = {d: dict(r) for d, r in saved.items()}
            for d in (deck_id, *clear):
                rules.get(d, {}).pop(side, None)
            if new:
                rules.setdefault(deck_id, {})[side] = new
            return {d: r for d, r in rules.items() if r}

        def heading(text: str) -> None:
            menu.addAction(text).setEnabled(False)

        def choice(
            text: str,
            checked: bool,
            deck_id: str,
            new_rules: dict[str, dict[str, str]],
            decks: str,
            shows: str,
        ) -> None:
            action = menu.addAction(for_menu(text))
            action.setCheckable(True)
            action.setChecked(checked)
            if checked and side not in saved.get(deck_id, {}):
                # nothing set on this deck to remove: it's the setting in force
                done = lambda: tooltip("This is what it already shows.")
            elif checked:
                off = with_rule(deck_id, None)
                done = lambda: _save_deck_rules(
                    off, f"Removed the {side}-side rule for {decks}."
                )
            else:
                done = lambda: _save_deck_rules(
                    new_rules, f"On the {side} side, {decks} now shows {shows}."
                )
            qconnect(action.triggered, done)

        # A rule on this deck for just its own name: what that comes to
        # depends on whether the name differs from the usual label, and on
        # whether you're studying this deck (then it would only repeat your
        # pick, so shows nothing, and Nothing is the line that's checked)
        own_name = value == "this" and rule_deck == full
        differs = usual != parts[-1]
        follows_setting = value in (None, "usual")
        # a parent's rule that this deck would otherwise follow
        above = None
        if len(parts) > 1:
            above = _deck_rule(chain[-2], side, by_name)[0]

        title = f"{side.capitalize()} side"
        here = f'the "{parts[-1]}" deck'
        heading(f"{title}, for the {for_menu(parts[-1])} deck, show:")
        if usual is not None:
            choice(
                usual,
                follows_setting or (own_name and not differs and not studying),
                own,
                # back to the setting; said outright where a parent's rule
                # would otherwise apply
                with_rule(own, "usual" if above in ("this", "nothing") else None),
                here,
                f'"{usual}"',
            )
        # offered where it would change something
        if differs and not studying:
            choice(
                parts[-1], own_name, own, with_rule(own, "this"), here, f'"{parts[-1]}"'
            )
        choice(
            nothing,
            (value == "nothing" and rule_deck == full)
            or (usual is None and follows_setting)
            or (own_name and studying),
            own,
            # with the setting on Nothing, no rule is needed unless a parent
            # has one
            with_rule(
                own,
                "nothing" if usual is not None or above in ("this", "nothing") else None,
            ),
            here,
            "no deck label",
        )

        # nearest parent first
        for depth in range(len(chain) - 1, 0, -1):
            deck_path, name = chain[depth - 1], parts[depth - 1]
            if deck_path not in ids:
                continue
            # Every parent has a section, so the menu is laid out the same
            # whichever deck you're studying. A parent you're studying (or one
            # above it) has no line for its own name: that would only repeat
            # your pick, so the label shows nothing then, and a rule for the
            # name set there is checked as Nothing
            in_force = rule_deck == deck_path and value in ("this", "nothing")
            repeats = _contains_studied_deck(deck_path)
            parent = ids[deck_path]
            # a rule set further down would otherwise still win on this card
            below = tuple(ids[deeper] for deeper in chain[depth:] if deeper in ids)
            under = f'every deck under "{name}"'
            menu.addSeparator()
            heading(f"{title}, for every deck under {for_menu(name)}, show:")
            if not repeats:
                choice(
                    name,
                    value == "this" and rule_deck == deck_path,
                    parent,
                    with_rule(parent, "this", below),
                    under,
                    f'"{name}"',
                )
            choice(
                nothing,
                in_force and (value == "nothing" or repeats),
                parent,
                with_rule(parent, "nothing", below),
                under,
                "no deck label",
            )

    menu = QMenu(mw)
    menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    for side in ("question", "answer"):
        add_side(menu.addMenu(f"{side.capitalize()} side"), side)
    menu.addSeparator()
    qconnect(menu.addAction("Label settings…").triggered, _on_config_action)
    menu.popup(QCursor.pos())


def _hint_once(conf: dict[str, Any]) -> None:
    hinted = mw.pm.profile.setdefault(_HINTED_KEY, [])
    if conf["id"] in hinted:
        return
    hinted.append(conf["id"])
    text = (
        "Card Timer & Deck Label isn't showing its timer: "
        '"Show on-screen timer" is off in '
        f'this deck\'s "{conf["name"]}" preset (Timers section).'
    )
    mw.reviewer.web.eval(
        "window.ptHint && ptHint(%s, %s, %s);"
        % (
            json.dumps(text),
            json.dumps("Open deck options"),
            json.dumps(_OPEN_OPTIONS_CMD),
        )
    )


# --------------------------------------------------------------------------
# Drive the display from Anki's own timer.
# --------------------------------------------------------------------------

# (card id, timer start, seconds) of the answer frozen on screen. Anki redraws
# the answer after the note is edited; this keeps the time you took to reveal
# it, like Anki's own timer, instead of recounting with the editing included.
_frozen: tuple[int, float, float] | None = None


def _on_show_question(card) -> None:
    global _frozen
    if not mw.reviewer or card.timer_started is None:
        return
    # back on the question side (a new card, or one flipped back by another
    # add-on): the next reveal is timed afresh. Not when the settings dialog
    # redraws a card that's on its answer side.
    if mw.reviewer.state == "question":
        _frozen = None
    cfg = _cfg()
    conf = _deck_conf(card)
    # before the counter, whose room is measured from below the label; shown
    # whether or not the deck's preset has the timer on
    mw.reviewer.web.eval(
        "window.ptDeck && ptDeck(%s);" % json.dumps(_deck_label(card, cfg))
    )
    opts: dict[str, Any] = {"max": 0}
    if card.should_show_timer():
        target, why = _target(card, conf, cfg)
        amber = float(cfg["amber_fraction"])
        last, last_capped = (
            _last_time(card) if cfg["show_last_time"] != "never" else (None, False)
        )
        opts = {
            "start": card.timer_started,
            "elapsed": _elapsed(card),
            "paused": _paused_for(card),
            "max": card.time_limit() / 1000,
            "target": target,
            "why": [
                f"Target time {format_secs(target)}"
                + (
                    f", amber from {format_secs(target * amber)}"
                    if cfg["color_changes"]
                    else ""
                ),
                why,
            ],
            "amber": amber,
            "bar": bool(cfg["show_progress_bar"]),
            "countDown": bool(cfg["count_down"]),
            "counter": cfg["show_counter"],
            "last": last,
            "lastCapped": last_capped,
            "lastOnAnswer": cfg["show_last_time"] == "answer",
        }
    else:
        _hint_once(conf)
    mw.reviewer.web.eval("window.ptShow && ptShow(%s);" % json.dumps(opts))


def _on_show_answer(card) -> None:
    global _frozen
    if not mw.reviewer or card.timer_started is None:
        return
    # what the answer side's setting and rules give, which can differ from
    # what the question side showed
    mw.reviewer.web.eval(
        "window.ptDeck && ptDeck(%s);"
        % json.dumps(_deck_label(card, _cfg(), answer=True))
    )
    elapsed = None
    if _deck_conf(card).get("stopTimerOnAnswer"):
        key = (card.id, card.timer_started)
        if _frozen and _frozen[:2] == key:
            elapsed = _frozen[2]
        else:
            # capped at "Maximum answer seconds", same as Anki's log
            elapsed = min(_elapsed(card), card.time_limit() / 1000)
            _frozen = (*key, elapsed)
    mw.reviewer.web.eval("window.ptAnswer && ptAnswer(%s);" % json.dumps(elapsed))


def _on_js_message(handled: tuple[bool, Any], message: str, context: Any):
    if not isinstance(context, Reviewer):
        return handled
    if message == _OPEN_OPTIONS_CMD:
        if context.card:
            display_options_for_deck_id(context.card.current_deck_id())
        return True, None
    if message == _CARD_INFO_CMD:
        # Anki's own Card Info for the current card, as pressing I does
        context.on_card_info()
        return True, None
    if message == _DECK_MENU_CMD:
        if context.card:
            _show_deck_menu(context.card)
        return True, None
    return handled


def _on_state_will_change(new_state: str, old_state: str) -> None:
    # recompute pace targets each review session, so today's answers count;
    # before the first card is shown, which state_did_change comes after
    if new_state == "review":
        _pace_cache.clear()


# --------------------------------------------------------------------------
# "Pause while editing": Anki's card clock never stops, so time spent editing
# counts as answer time. With the setting on, the clock pauses from when the
# Edit window becomes active until you're back in the main window (or close
# Edit), and its start moves later by that long. Switching to another app
# mid-edit stays paused. This is the one place the add-on changes what Anki
# records.
# --------------------------------------------------------------------------

# (card id, timer start, when the pause began) while you're editing
_paused: tuple[int, float, float] | None = None


def _paused_for(card) -> bool:
    return bool(_paused) and _paused[:2] == (card.id, card.timer_started)


def _elapsed(card) -> float:
    """Seconds on the card's clock, leaving out a pause still in progress."""
    end = _paused[2] if _paused_for(card) else time.time()
    return max(0.0, end - card.timer_started)


def _on_dialog_opened(dialog_manager: Any, name: str, window: Any) -> None:
    # Anki 26.9's new editor opens as "NewEditCurrent"
    if name not in ("EditCurrent", "NewEditCurrent"):
        return
    window.installEventFilter(_edit_window_watcher)  # Qt ignores repeats
    # usually it becomes active just after this, which the watcher sees
    if window.isActiveWindow():
        _pause_start()


def _pause_start() -> None:
    global _paused
    card = mw.reviewer.card
    if not _cfg()["pause_while_editing"] or mw.state != "review" or not card:
        return
    if card.timer_started is None or _paused_for(card):
        return
    _paused = (card.id, card.timer_started, time.time())
    # to see you come back to the review; removed again when the pause ends
    mw.installEventFilter(_edit_window_watcher)
    mw.reviewer.web.eval("window.ptPause && ptPause();")


def _pause_end() -> None:
    global _paused, _frozen
    mw.removeEventFilter(_edit_window_watcher)
    card = mw.reviewer.card
    if mw.state != "review" or not card or not _paused_for(card):
        _paused = None
        return
    old_start = card.timer_started
    card.timer_started += time.time() - _paused[2]
    _paused = None
    if _frozen and _frozen[:2] == (card.id, old_start):
        _frozen = (card.id, card.timer_started, _frozen[2])
    mw.reviewer.web.eval(
        "window.ptResume && ptResume(%s);" % json.dumps(card.timer_started)
    )


class _EditWindowWatcher(QObject):
    """On the Edit window: pause when it becomes active, end the pause when
    it closes. On the main window (only while paused): end the pause when you
    come back to it."""

    def eventFilter(self, obj: Any, event: Any) -> bool:
        kind = event.type()
        if obj is mw:
            if kind == QEvent.Type.WindowActivate:
                _pause_end()
        elif kind == QEvent.Type.WindowActivate:
            _pause_start()
        elif kind == QEvent.Type.Close:
            _pause_end()
        return False


_edit_window_watcher = _EditWindowWatcher()


def _on_will_answer(
    ease_tuple: tuple[bool, int], reviewer: Any, card
) -> tuple[bool, int]:
    # answering while still paused: end the pause first, since Anki reads the
    # clock right after this
    if _paused_for(card):
        _pause_end()
    return ease_tuple


# --------------------------------------------------------------------------
# Settings dialog, in place of the JSON editor behind Add-ons > Config, and
# under Tools.
# --------------------------------------------------------------------------


_RESTYLE_JS = (
    "(function (css) { var s = document.getElementById('ptimer-style');"
    " if (s) s.textContent = css; })(%s);"
)


def _apply_to_open_reviewer() -> None:
    if mw.state != "review":
        return
    cfg = _cfg()
    mw.reviewer.web.eval(_RESTYLE_JS % json.dumps(_css(cfg)))
    mw.reviewer.web.eval("window.ptReserve && ptReserve();")
    mw.reviewer.bottom.web.eval(_RESTYLE_JS % json.dumps(_bottom_css(cfg)))
    # redraw the current card with the new options, on whichever side it's
    # on (a frozen answer time is kept)
    card = mw.reviewer.card
    if card and mw.reviewer.state in ("question", "answer"):
        _on_show_question(card)
        if mw.reviewer.state == "answer":
            _on_show_answer(card)


def _deck_list() -> list[tuple[str, str]]:
    """(deck id as text, name) for each deck, for the per-deck rules."""
    if not mw.col:
        return []
    # the Default deck too, even when empty: the label's menu can set a rule
    # on it for the decks under it
    decks = mw.col.decks.all_names_and_ids(include_filtered=False)
    return [(str(deck.id), deck.name) for deck in decks]


def _on_config_action() -> bool:
    # over the window it was opened from (Add-ons, say), but not the label's
    # menu, which is about to go
    parent = mw.app.activeWindow()
    if not parent or isinstance(parent, QMenu):
        parent = mw
    dialog = SettingsDialog(parent, _cfg(), _DEFAULTS, _deck_targets, _deck_list)
    if dialog.exec():
        mw.addonManager.writeConfig(ADDON, dialog.config())
        _apply_to_open_reviewer()
    dialog.deleteLater()
    return True


mw.addonManager.setConfigAction(ADDON, _on_config_action)
_tools_action = QAction("Card Timer && Deck Label…", mw.form.menuTools)
qconnect(_tools_action.triggered, _on_config_action)
mw.form.menuTools.addAction(_tools_action)

gui_hooks.webview_will_set_content.append(_on_webview_will_set_content)
gui_hooks.dialog_manager_did_open_dialog.append(_on_dialog_opened)
gui_hooks.reviewer_will_answer_card.append(_on_will_answer)
gui_hooks.webview_did_receive_js_message.append(_on_js_message)
gui_hooks.state_will_change.append(_on_state_will_change)
gui_hooks.reviewer_did_show_question.append(_on_show_question)
gui_hooks.reviewer_did_show_answer.append(_on_show_answer)
