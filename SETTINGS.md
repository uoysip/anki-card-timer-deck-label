# Settings

Open the add-on's settings from **Tools > Card Timer & Deck Label**. Changes apply when you click Save. In the window, hover over a setting's name to see what it does.

## What the timer takes from Anki

The add-on displays Anki's own card timer, so three of Anki's deck options, under [**Timers**](https://docs.ankiweb.net/deck-options.html#timers), decide how it behaves:

- [**Show on-screen timer**](https://docs.ankiweb.net/deck-options.html#on-screen-timer) must be on for the timer to appear in a deck. The deck label appears regardless.
- [**Maximum answer seconds**](https://docs.ankiweb.net/deck-options.html#internal-timer) is where the timer stops and turns red.
- [**Stop on-screen timer on answer**](https://docs.ankiweb.net/deck-options.html#on-screen-timer), if on, freezes the timer when you reveal the answer.

## Target time

The time bar fills toward the target time, and the counter turns amber, then red, as you near and pass it. A card uses the first of these that applies:

1. While Anki's [Auto Advance](https://docs.ankiweb.net/deck-options.html#auto-advance) is running: Anki's [**Seconds to show question for**](https://docs.ankiweb.net/deck-options.html#auto-advance) deck option, when that's above 0.
2. With the add-on's **Use my pace in each deck instead** on: your pace in the deck, once it has 20 answers. Your pace is the time you beat on 90% of your last 1,000 answers there; **Red when slower than** changes the 90%.
3. Otherwise: the add-on's **Target time**.

## Hiding spoilers in the deck label

Some deck names give the answer away. If a card in `Art › Post-Impressionism` asks which movement a painting belongs to, a label reading "Art › Post-Impressionism" answers it for you.

To fix it while reviewing:

1. Right-click the deck label and open **Question side**.
2. Under "for every deck under Art", choose **Art**. If Art is the deck you're studying, the only choice there is **Nothing until the answer**, so choose that.

Every deck under Art now shows just "Art" on the question side, or nothing if you chose that, and the usual label on the answer side. Clicking the checked choice removes the rule.

The rules you set this way are listed in the settings under **Per-deck rules**. They're stored by deck ID, so a rule only applies in the Anki profile it was set in.

## The add-on's settings

In the order of the settings window. Where a setting has choices, the first is the default. Config names are the ones in the add-on's `meta.json`.

| Setting | Config name | Default or choices |
|---|---|---|
| Target time | `target_seconds` | 15 seconds |
| Use my pace in each deck instead | `pace_target` | Off |
| Red when slower than | `pace_percentile` | 90% |
| Show counter | `show_counter` | Always (`always`), On the answer side (`answer`), Never (`never`) |
| Counter position | `counter_position` | Top right (`top-right`), Top left (`top-left`), Top center (`top-center`) |
| Counter size | `font_size_px` | 34 px |
| Show last answer time | `show_last_time` | On the answer side (`answer`), Always (`always`), Never (`never`) |
| Show a time bar along the top | `show_progress_bar` | On |
| Count down to the target time | `count_down` | Off |
| Hide Anki's own timer in the bottom bar | `hide_builtin_timer` | On |
| Change color near the target time | `color_changes` | On |
| Turn amber at | `amber_fraction` | 67% (`0.67`) |
| Normal | `color_normal` | Gray (`#8a8a8a`) |
| Near the target time | `color_amber` | Amber (`#e6a23c`) |
| Past the target time | `color_over` | Red (`#e5534b`) |
| Show deck label | `show_deck` | When studying a parent deck (`parent`), Always (`always`), Never (`never`) |
| Label position | `deck_position` | Opposite the counter (`auto`), Top left (`top-left`), Top center (`top-center`), Top right (`top-right`), Bottom left (`bottom-left`), Bottom center (`bottom-center`), Bottom right (`bottom-right`) |
| On the question side | `deck_question_shows` | The deck and its parent (`parent`), Nothing (`nothing`), Just the deck (`deck`), The deck and two parents (`two_parents`), The full path (`full`) |
| On the answer side | `deck_answer_shows` | Same choices as the question side |
| Give each deck its own color | `deck_colors` | On |
| Keep the label's space when one side hides it | `deck_keep_space` | On |
| Per-deck rules | `deck_rules` | None. For each side (`question`, `answer`): the deck's own name (`this`), Nothing (`nothing`) or Same as other decks (`usual`) |
| Pause the clock while I'm editing the card | `pause_while_editing` | Off |
