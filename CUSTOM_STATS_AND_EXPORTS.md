# Custom Stats and Data Exports

The stat tracker supports user-defined statistics through `config.json` and can export leaderboard or team data as CSV or JSON.

Custom stats are **not enabled by default**. A new configuration starts with an empty object:

```json
"custom_stats": {}
```

Users may add whichever statistics they want.

---

## Custom Stats

Custom stats are defined inside the `custom_stats` object in `config.json`.

```json
{
  "custom_stats": {
    "ISO": {
      "formula": "SLG - AVG",
      "lower_is_better": false,
      "qualification": "batting",
      "precision": 3
    }
  }
}
```

Each custom stat supports four settings.

### `formula`

The expression used to calculate the statistic.

Formulas may reference raw MMOLB statistics stored in `player_data.json`, calculated statistics such as `AVG`, `OBP`, `SLG`, `OPS`, `ERA`, and `WHIP`, and other custom stats.

```json
"formula": "SLG - AVG"
```

```json
"formula": "(strikeouts - walks) / batters_faced"
```

Stat names must exactly match the names recognized by the program.

To inspect the raw statistics stored for a player, use:

```text
debug PLAYER_ID
```

### `lower_is_better`

Controls leaderboard ordering and percentile coloring.

Use `true` when lower values are better:

```json
"lower_is_better": true
```

Use `false` when higher values are better:

```json
"lower_is_better": false
```

### `qualification`

Determines which playing-time threshold is applied.

| Value | Threshold |
|---|---|
| `"batting"` | Minimum at-bat threshold |
| `"pitching"` | Minimum pitching-outs threshold |
| `"defense"` | Defensive qualification rules |

Example:

```json
"qualification": "pitching"
```

### `precision`

Controls the intended number of decimal places for the statistic.

```json
"precision": 3
```

---

## Supported Formula Syntax

Custom formulas support ordinary arithmetic:

```text
+   addition
-   subtraction
*   multiplication
/   division
//  floor division
%   remainder
**  exponentiation
```

Parentheses may be used normally:

```json
"formula": "(strikeouts - walks) / batters_faced"
```

The formula evaluator also supports these functions:

```text
abs()
min()
max()
round()
sqrt()
```

Custom formulas are evaluated with a restricted expression parser. They cannot execute arbitrary Python code.

---

## Example Custom Stats

These examples are optional and are not part of the default configuration.

### FIP

```json
"FIP": {
  "formula": "(13 * home_runs_allowed + 3 * (walks + hit_batters) - 2 * strikeouts) / (outs / 3) + 3.1",
  "lower_is_better": true,
  "qualification": "pitching",
  "precision": 3
}
```

This version uses a fixed FIP constant of `3.1`.

### K-BB%

```json
"K-BB%": {
  "formula": "(strikeouts - walks) / batters_faced",
  "lower_is_better": false,
  "qualification": "pitching",
  "precision": 3
}
```

### ISO

```json
"ISO": {
  "formula": "SLG - AVG",
  "lower_is_better": false,
  "qualification": "batting",
  "precision": 3
}
```

### BABIP

```json
"BABIP": {
  "formula": "(singles + doubles + triples) / (at_bats - struck_out - home_runs + sac_flies)",
  "lower_is_better": false,
  "qualification": "batting",
  "precision": 3
}
```

A complete example configuration would look like this:

```json
{
  "auto_game_update": "on",
  "leagues": [
    "clover",
    "pineapple"
  ],
  "custom_stats": {
    "FIP": {
      "formula": "(13 * home_runs_allowed + 3 * (walks + hit_batters) - 2 * strikeouts) / (outs / 3) + 3.1",
      "lower_is_better": true,
      "qualification": "pitching",
      "precision": 3
    },
    "K-BB%": {
      "formula": "(strikeouts - walks) / batters_faced",
      "lower_is_better": false,
      "qualification": "pitching",
      "precision": 3
    },
    "ISO": {
      "formula": "SLG - AVG",
      "lower_is_better": false,
      "qualification": "batting",
      "precision": 3
    },
    "BABIP": {
      "formula": "(singles + doubles + triples) / (at_bats - struck_out - home_runs + sac_flies)",
      "lower_is_better": false,
      "qualification": "batting",
      "precision": 3
    }
  }
}
```

---

## Referencing Other Custom Stats

A custom stat may reference another custom stat:

```json
"ERA-FIP": {
  "formula": "ERA - FIP",
  "lower_is_better": false,
  "qualification": "pitching",
  "precision": 3
}
```

Avoid circular dependencies:

```json
"A": {
  "formula": "B + 1"
},
"B": {
  "formula": "A + 1"
}
```

Neither value can be resolved because each depends on the other.

---

## Missing or Invalid Data

A custom stat is omitted for a player when:

- A referenced value is unavailable
- The formula divides by zero
- The formula contains invalid syntax
- The result is not finite
- The player lacks the required type of data

One invalid custom stat does not stop the rest of the program.

---

# Exporting Data

Leaderboards and team data can be exported as CSV or JSON.

## Exporting a Leaderboard

```text
export leaderboard STAT csv
```

Examples:

```text
export leaderboard OPS csv
export leaderboard FIP json
```

Without a custom path, files are written to `exports/`:

```text
exports/leaderboard_OPS.csv
exports/leaderboard_FIP.json
```

Leaderboard exports use the same sorting, qualification, and player-filtering rules as console leaderboards.

Exported fields may include:

```text
rank
player_id
name
position
team_id
team
stat
value
```

## Exporting a Team

Teams may be supplied by ID or name:

```text
export team TEAM csv
```

Examples:

```text
export team "Bordon Beagles" csv
export team TEAM_ID json
```

Names containing spaces should be placed in quotation marks.

The default filename is generated from the team name:

```text
exports/bordon_beagles.csv
```

Team exports include identifying information and each calculated statistic available for a player.

## Custom Export Paths

An optional path may be supplied at the end of the command:

```text
export leaderboard ISO csv reports/iso.csv
export team "Bordon Beagles" json reports/beagles.json
```

Missing output directories are created automatically.

## Choosing a Format

Use CSV for spreadsheets, sorting, filtering, or graphing.

Use JSON for websites, bots, Python programs, or additional data processing.
