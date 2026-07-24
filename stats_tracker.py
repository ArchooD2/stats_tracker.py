import requests
import json
import os
import tempfile
import defense
import time
from concurrent.futures import ThreadPoolExecutor
from threading import local
import stats_config as config
from contextlib import chdir
from tqdm import tqdm
from difflib import get_close_matches


ALL_GAMES_PATH = "data/all_games.json"
FETCH_WORKERS = min(16, (os.cpu_count() or 1) + 4)
_thread_local = local()


def write_json_atomic(path, payload, indent=2):
    directory = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        delete=False,
    ) as temp_file:
        json.dump(payload, temp_file, indent=indent)
        temp_file.flush()
        os.fsync(temp_file.fileno())

    os.replace(temp_file.name, path)


def get_session():
    """Return one persistent HTTP session per fetch thread."""
    if not hasattr(_thread_local, "session"):
        session = requests.Session()

        adapter = requests.adapters.HTTPAdapter(
            pool_connections=FETCH_WORKERS,
            pool_maxsize=FETCH_WORKERS,
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        _thread_local.session = session

    return _thread_local.session

def get_json_with_retries(url, attempts=5, timeout=30):
    last_error = None
    session = get_session()

    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError,
            ValueError,
        ) as error:
            last_error = error

            if attempt < attempts:
                delay = min(2 ** attempt, 30)

                tqdm.write(
                    f"Request failed ({attempt}/{attempts}): {url}\n"
                    f"{type(error).__name__}: {error}\n"
                    f"Retrying in {delay}s..."
                )

                time.sleep(delay)

    raise RuntimeError(
        f"Failed to fetch {url} after {attempts} attempts"
    ) from last_error

def fetch_player(player_id):
    try:
        player = get_json_with_retries(
            f"https://mmolb.com/api/player/{player_id}"
        )
        return player_id, player, None

    except RuntimeError as error:
        return player_id, None, error

def fetch_team(item):
    league_id, team_id = item

    try:
        team = get_json_with_retries(
            f"https://mmolb.com/api/team/{team_id}"
        )
        return league_id, team_id, team, None

    except RuntimeError as error:
        return league_id, team_id, None, error

def fetch_game(item):
    """Fetch one game without mutating shared player/stat data."""
    game_id, game_info = item

    try:
        game = get_json_with_retries(
            f"https://mmolb.com/api/game/{game_id}"
        )
        return game_id, game_info, game, None

    except RuntimeError as error:
        return game_id, game_info, None, error

def load_games():
    if not os.path.isfile(ALL_GAMES_PATH):
        return {}

    with open(ALL_GAMES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_players_for_recording():
    player_path = "data/player_data.json"

    if not os.path.isfile(player_path):
        return {}

    try:
        with open(player_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as error:
        tqdm.write(
            f"player_data.json is malformed ({error}); rebuilding from scratch."
        )
        return {}

def save_games(games):
    write_json_atomic(ALL_GAMES_PATH, games)

def update_rosters():
    league_ids = [
        config.valid_options()["leagues"][index]
        for index in config.get_config()["leagues"]
    ]

    player_dict = {}
    team_dict = {}
    league_dict = {}

    # First fetch the league records and gather all their team IDs.
    teams_to_fetch = []

    for league_id in league_ids:
        try:
            league = get_json_with_retries(
                f"https://mmolb.com/api/league/{league_id}"
            )
        except RuntimeError as error:
            tqdm.write(
                f"Skipping league {league_id}: {error}"
            )
            continue

        league_dict[league_id] = league["Teams"]

        for team_id in league["Teams"]:
            teams_to_fetch.append((league_id, team_id))

    # Remove duplicate league/team pairs while preserving order.
    teams_to_fetch = list(dict.fromkeys(teams_to_fetch))

    with ThreadPoolExecutor(
        max_workers=FETCH_WORKERS
    ) as executor:
        fetched_teams = executor.map(
            fetch_team,
            teams_to_fetch,
        )

        for league_id, team_id, team, error in fetched_teams:
            if error is not None:
                tqdm.write(
                    f"Skipping team {team_id}: {error}"
                )
                continue

            record = team.get("Record", {}).get(
                "Regular Season",
                {},
            )

            wins = record.get("Wins", 0)
            losses = record.get("Losses", 0)

            # Ignore inactive teams.
            if wins + losses <= 0:
                continue

            tqdm.write(
                f"Fetched team: "
                f"{team['Location']} {team['Name']}"
            )

            members = []

            for player in team["Players"]:
                player_id = player["PlayerID"]

                if player_id == "#":
                    continue

                position = player["Position"]

                duplicate_position = any(
                    player_dict[member_id]["position"] == position
                    for member_id in members
                    if (
                        member_id in player_dict
                        and position not in ["SP", "RP"]
                    )
                )

                if duplicate_position:
                    position = "DH"

                player_dict[player_id] = {
                    "name": (
                        f"{player['FirstName']} "
                        f"{player['LastName']}"
                    ),
                    "position": position,
                    "team": team_id,
                    "bench": False,
                }

                members.append(player_id)

            for bench_group in team["Bench"].values():
                for player in bench_group:
                    player_id = player["PlayerID"]

                    if player_id == "#":
                        continue

                    player_dict[player_id] = {
                        "name": (
                            f"{player['FirstName']} "
                            f"{player['LastName']}"
                        ),
                        "position": player["Slot"],
                        "team": team_id,
                        "bench": True,
                    }

                    members.append(player_id)

            team_dict[team_id] = {
                "league": league_id,
                "emoji": team["Emoji"],
                "name": (
                    f"{team['Location']} {team['Name']}"
                ),
                "members": members,
                "wins": wins,
                "losses": losses,
                "rd": record.get("RunDifferential", 0)
            }

    roster_info = {
        "players": player_dict,
        "teams": team_dict,
        "leagues": league_dict,
    }

    write_json_atomic("data/roster_info.json", roster_info)

# gather data you need to go to individual player IDs to obtain
def update_rosters_deep():
    roster_path = "data/roster_info.json"

    if not os.path.isfile(roster_path):
        print("Cannot fetch player details: roster_info.json is missing")
        return

    with open(roster_path, "r", encoding="utf-8") as f:
        roster_info = json.load(f)

    player_ids = list(roster_info["players"])

    print(f"Fetching individual player info...")

    progress = tqdm(
        total=len(player_ids),
        desc="Fetching player details",
        unit="player",
        dynamic_ncols=True,
    )

    with ThreadPoolExecutor(
        max_workers=FETCH_WORKERS
    ) as executor:
        fetched_players = executor.map(
            fetch_player,
            player_ids,
        )

        for processed_count, (
            player_id,
            player,
            error,
        ) in enumerate(fetched_players, start=1):
            progress.update(1)

            if error is not None:
                tqdm.write(
                    f"Skipping player {player_id}: {error}"
                )
                continue

            player_info = roster_info["players"][player_id]

            effective_level = 1 + len(
                player.get("AugmentHistory", [])
            )

            effective_level += len(
                player.get("AppliedLevelUps", [])
            )

            player_info["effective_level"] = effective_level
            player_info["throws"] = player.get("Throws")
            player_info["equipment"] = player.get("Equipment")

            drip_score = 0

            for equipment in player.get("Equipment", {}).values():
                if equipment is None:
                    continue

                for effect in equipment.get("Effects", []):
                    drip_score += effect.get("Tier", 0)

            player_info["drip_score"] = drip_score

            # Checkpoint occasionally so a later failure does not lose
            # every successfully fetched player.
            if processed_count % 1000 == 0:
                write_json_atomic(roster_path, roster_info)

    progress.close()

    write_json_atomic(roster_path, roster_info)

# update the game list
def update_games(s, hard_reset=False):
    games = load_games()

    start_search_from = 0
    if games:
        start_search_from = (
            max(game["day"] for game in games.values()) - 1
        )

    season = get_json_with_retries(
        f"https://mmolb.com/api/season/{s}"
    )

    for day_counter, day_id in enumerate(
        season["Days"],
        start=1,
    ):
        if day_counter < start_search_from:
            continue

        try:
            day = get_json_with_retries(
                f"https://mmolb.com/api/day/{day_id}"
            )
        except RuntimeError as error:
            tqdm.write(
                f"Skipping day {day_id} after repeated failures:\n"
                f"{error}"
            )
            continue

        if day["Season"] == 11 and day["Day"] == 2:
            continue

        stop_early_flag = True

        for game in day["Games"]:
            stop_early_flag = False

            if game["GameID"] == "#":
                continue

            game_id = game["GameID"]
            was_checked = games.get(
                game_id,
                {},
            ).get("checked", False)

            games[game_id] = {
                "away_team_id": game["AwayTeamID"],
                "home_team_id": game["HomeTeamID"],
                "day": day["Day"],
                "state": game["State"],
                "checked": was_checked and not hard_reset,
            }

        if stop_early_flag or day["Day"] == 240:
            break

    save_games(games)

# add data from unrecorded games to the player_data.json file
def record_games(toi=None, hard_reset=False):
    games = load_games()
    players = {}

    if not hard_reset:
        players = load_players_for_recording()

    games_to_record = [
        (game_id, game_info)
        for game_id, game_info in games.items()
        if game_info["state"] == "Complete"
        and not game_info["checked"]
        and (
            toi is None
            or game_info["away_team_id"] in toi
            or game_info["home_team_id"] in toi
        )
    ]

    progress = tqdm(
    total=len(games_to_record),
    desc="Processing games",
    unit="game",
    dynamic_ncols=True,
    )

    # Only game downloads are concurrent. All mutations to `players`,
    # `games`, and the JSON files still happen here on the main thread.
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        fetched_games = executor.map(fetch_game, games_to_record)

        for processed_count, (
            game_id,
            game_info,
            game,
            error,
        ) in enumerate(fetched_games, start=1):
            progress.update(1)

            if error is not None:
                tqdm.write(
                    f"\nSkipping game {game_id} after repeated request failures:"
                    f"\n{error}\n"
                )
                continue
            
            away_victory = (
                game["EventLog"][-1]["away_score"]
                > game["EventLog"][-1]["home_score"]
            )
            
            tqdm.write(
                f"Processing game: {game_id} "
                f"| S{game['Season']} D{game['Day']:<3} "
                f"| \033[38;5;{157 if away_victory else 217}m"
                f"{game['AwayTeamName']}\x1b[0m vs. "
                f"\033[38;5;{217 if away_victory else 157}m"
                f"{game['HomeTeamName']}\x1b[0m"
            )

            # Tick up standard game stats.
            for team in game["Stats"]:
                for player_id in game["Stats"][team]:
                    if player_id not in players:
                        players[player_id] = {}

                    for stat, value in game["Stats"][team][player_id].items():
                        players[player_id][stat] = (
                            players[player_id].get(stat, 0) + value
                        )

            # Tick up parsed fielding stats.
            defense_stats = defense.parse_fielding(game)

            for player_id, player_stats in defense_stats.items():
                if player_id not in players:
                    players[player_id] = {}

                for stat, value in player_stats.items():
                    players[player_id][stat] = (
                        players[player_id].get(stat, 0) + value
                    )

            # Tick up pitch-location data.
            for event in game["EventLog"]:
                if event["event"] != "Pitch":
                    continue

                pitcher = event.get("pitcher")
                pitch_info = event.get("pitch_info")
                zone = event.get("zone")

                if (
                    not pitcher
                    or not pitcher.get("id")
                    or not pitch_info
                    or zone is None
                ):
                    continue

                pitcher_id = pitcher["id"]
                pitch = "".join(pitch_info.strip().split()[1:])
                zone = str(zone)

                if pitcher_id not in players:
                    players[pitcher_id] = {}

                pitch_data = players[pitcher_id].setdefault(
                    "pitch_data",
                    {},
                )

                if pitch not in pitch_data:
                    pitch_data[pitch] = {
                        "1": 0,
                        "2": 0,
                        "3": 0,
                        "4": 0,
                        "5": 0,
                        "6": 0,
                        "7": 0,
                        "8": 0,
                        "9": 0,
                        "11": 0,
                        "12": 0,
                        "13": 0,
                        "14": 0,
                    }

                if zone not in pitch_data[pitch]:
                    tqdm.write(
                        f"Unknown pitch zone {zone} in game {game_id}; "
                        "skipping pitch"
                    )
                    continue

                pitch_data[pitch][zone] += 1

            game_info["checked"] = True

            # Less frequent checkpoints avoid repeatedly rewriting large
            # JSON files while still limiting lost work after a crash.
            if processed_count % 1000 == 0:
                save_games(games)

                write_json_atomic("data/player_data.json", players, indent=None)

    progress.close()

    # Save the final partial batch.
    save_games(games)

    write_json_atomic("data/player_data.json", players)

# create a json that stores common human metrics for players
def calculate_human_stats():
    players = {}
    if os.path.isfile("data/player_data.json"):
        with open("data/player_data.json", "r") as f:
            players = json.load(f)
            f.close()
    full_result = {}
    for p in players:
        good_shit = {"at_bats": 0,
                     "plate_appearances": 0,
                     "singles": 0,
                     "doubles": 0,
                     "triples": 0,
                     "home_runs": 0,
                     "walked": 0,
                     "hit_by_pitch": 0,
                     "sac_flies": 0,
                     "ground_ball_fielded": 0,
                     "ground_ball_allowed": 0,
                     "fly_ball_fielded": 0,
                     "fly_ball_allowed": 0,
                     "line_drive_fielded": 0,
                     "line_drive_allowed": 0,
                     "outs": 0, # pitcher
                     "earned_runs": 0, # pitcher
                     "strikeouts": 0, # pitcher
                     "struck_out": 0, 
                     "hits_allowed": 0, # pitcher
                     "walks": 0, # pitcher
                     "home_runs_allowed": 0} # pitcher
        result = {}
        for stat in good_shit:
            if stat in players[p]:
                good_shit[stat] = players[p][stat]
        if good_shit["at_bats"] > 0:
            hits = good_shit["singles"] + good_shit["doubles"] + good_shit["triples"] + good_shit["home_runs"]
            result["AVG"] = hits / good_shit["at_bats"]
            result["OBP"] = (hits + good_shit["walked"] + good_shit["hit_by_pitch"]) / (good_shit["at_bats"] + good_shit["walked"] + good_shit["hit_by_pitch"] + good_shit["sac_flies"])
            result["SLG"] = (good_shit["singles"] + 2 * good_shit["doubles"] + 3 * good_shit["triples"] + 4 * good_shit["home_runs"]) / good_shit["at_bats"]
            result["OPS"] = result["OBP"] + result["SLG"]
            result["K%"] = good_shit["struck_out"] / good_shit["plate_appearances"]
        if good_shit["outs"] > 0:
            result["ERA"] = good_shit["earned_runs"] / (good_shit["outs"] / 27)
            result["WHIP"] = (good_shit["walks"] + good_shit["hits_allowed"]) / (good_shit["outs"] / 3)
            result["K/9"] = good_shit["strikeouts"] / (good_shit["outs"] / 27)
            result["BB/9"] = good_shit["walks"] / (good_shit["outs"] / 27)
            result["H/9"] = good_shit["hits_allowed"] / (good_shit["outs"] / 27)
            result["HR/9"] = good_shit["home_runs_allowed"] / (good_shit["outs"] / 27)
        if good_shit["ground_ball_fielded"] + good_shit["ground_ball_allowed"] > 0:
            result["GBO%"] = good_shit["ground_ball_fielded"] / (good_shit["ground_ball_fielded"] + good_shit["ground_ball_allowed"])
        if good_shit["fly_ball_fielded"] + good_shit["fly_ball_allowed"] > 0:
            result["FBO%"] = good_shit["fly_ball_fielded"] / (good_shit["fly_ball_fielded"] + good_shit["fly_ball_allowed"])
        if good_shit["line_drive_fielded"] + good_shit["line_drive_allowed"] > 0:
            result["LDO%"] = good_shit["line_drive_fielded"] / (good_shit["line_drive_fielded"] + good_shit["line_drive_allowed"])
        full_result[p] = result
    write_json_atomic("data/processed_player_data.json", full_result)

# calculate 100 thresholds for each calculated human stat and stores them in stat_barriers
def calculate_percentiles():
    barriers = {}
    players = {}
    rosters = {} # we want to have this so that we potentially exclude people who are not recognized by the program
    if os.path.isfile("data/player_data.json"):
        with open("data/player_data.json", "r") as f:
            players = json.load(f)
    if os.path.isfile("data/roster_info.json"):
        with open("data/roster_info.json", "r") as f:
            rosters = json.load(f)
            rosters = [_ for _ in rosters["players"].keys()]

    at_bats, outs = thresholds()

    for stat in ["AVG", "OBP", "SLG", "OPS", "ERA", "WHIP", "K%", "K/9", "BB/9", "H/9", "HR/9", "GBO%", "FBO%", "LDO%"]:
        lower_better = False
        pitching_stat = False
        if stat in ["ERA", "WHIP", "K%", "BB/9", "H/9", "HR/9"]:
            lower_better = True
        if stat in ["ERA", "WHIP", "K/9", "BB/9", "H/9", "HR/9"]:
            pitching_stat = True
        numbers = {}
        if os.path.isfile("data/processed_player_data.json"):
            with open("data/processed_player_data.json", "r") as f:
                numbers = json.load(f)
        everyone = []
        for i in numbers:
            if stat in numbers[i] and ((pitching_stat and players[i]["outs"] > outs) or ("at_bats" in players[i] and players[i]["at_bats"] > at_bats)) and i in rosters:
                everyone.append(numbers[i][stat])
        everyone.sort(key=lambda x: x, reverse=lower_better)
        results = []
        for i in range(100):
            results.append(everyone[int((len(everyone) * i / 100))])
        # print(results)
        barriers[stat] = results
    write_json_atomic("data/stat_barriers.json", barriers)

# return the ansi string that will color a piece of text in the console
def color(stat, value):
    lower_better = False
    pitching_stat = False
    if stat in ["ERA", "WHIP", "K%", "BB/9", "H/9", "HR/9"]:
        lower_better = True
    if stat in ["ERA", "WHIP", "K/9", "BB/9", "H/9", "HR/9"]:
        pitching_stat = True
    
    barriers = []
    with open("data/stat_barriers.json", "r") as f:
        barriers = json.load(f)
    percentile = 0
    for i in range(100):
        if not lower_better:
            if value < barriers[stat][i]:
                break
        else:
            if value > barriers[stat][i]:
                break
        percentile += 1
    ans = 0
    if percentile < 10:
        ans = 161
    elif percentile < 30:
        ans = 208
    elif percentile < 70:
        ans = 220
    elif percentile < 90:
        ans = 77
    elif percentile < 99:
        ans = 33
    else:
        ans = "92m\033[1"
    return f"\033[38;5;{ans}m"
    # 208, 216, 231, 105, 33, 92

# return the minimum numbers of ABs or outs to qualify a player for the stat leaderboards
def thresholds():
    players = {}
    if os.path.isfile("data/player_data.json"):
        with open("data/player_data.json", "r") as f:
            players = json.load(f)
    at_bats = []
    outs = []
    for i in players:
        if "at_bats" in players[i]:
            at_bats.append(players[i]["at_bats"])
        if "outs" in players[i]:
            outs.append(players[i]["outs"])
    at_bats.sort()
    outs.sort()
    # SEASON 13 MODIFICATION: Due to Flood weather, benchies now technically play and make the at-bat percentages
    # plummit. We're going to be shifting this from eliminating the bottom 15% to eliminating the bottom 30%
    # at_bats = at_bats[int((len(at_bats) * 0.30) // 1)]
    # outs = outs[int((len(outs) * 0.35) // 1)]
    at_bats = at_bats[-1] // 2.5 # 07/10/2026: i changed the thresholds to be a fraction of the leader instead of a percentile
    outs = outs[-1] // 2.5 #                   the idea is that the leader's always a regular, so we only want someone who's pitched a % of the regular
    return at_bats, outs

# print the leaderboards for a specific stat (though it prints all relevant stats, it sorts by the specified one)
# "reverse" argument makes it so the worst players show up
# "no_qualify" removes the AB/out limit
def leaderboard(stat, reverse=False, no_qualify=False, include_unknown_players=False):
    stat = stat.upper()
    numbers = {}
    if os.path.isfile("data/processed_player_data.json"):
        with open("data/processed_player_data.json", "r") as f:
            numbers = json.load(f)
    qual_check = {}
    if os.path.isfile("data/player_data.json"):
        with open("data/player_data.json", "r") as f:
            qual_check = json.load(f)
    at_bats, outs = thresholds()
    # if "all" is enabled, we no longer cared about the barriers
    at_bats = 1 if no_qualify else at_bats
    outs = 1 if no_qualify else outs
    roster_info = {}
    if os.path.isfile("data/roster_info.json"):
        with open("data/roster_info.json", "r") as f:
            roster_info = json.load(f)
    registered_players = [_ for _ in roster_info["players"].keys()]

    leaderboard = []
    lower_better = False
    pitching_stat = False
    defense_stat = False
    if stat in ["ERA", "WHIP", "K%", "BB/9", "H/9", "HR/9"]:
        lower_better = True
    if stat in ["ERA", "WHIP", "K/9", "BB/9", "H/9", "HR/9"]:
        pitching_stat = True
    if stat in ["GBO%", "LDO%", "FBO%"]:
        defense_stat = True
        print("NOTE: defense thresholds are currently a work in progress (current criteria is 20)")
    if pitching_stat:
        print("Required outs:", outs)
    else:
        print("Required ABs:", at_bats)
    if stat not in ["ERA", "WHIP", "K/9", "AVG", "OBP", "SLG", "OPS", "K%", "BB/9", "H/9", "HR/9", "GBO%", "LDO%", "FBO%"]:
        print(f"Stat {stat} not recognized")
        return -1

    for i in numbers:
        if i in registered_players or include_unknown_players:
            if pitching_stat:
                if "outs" in qual_check[i] and qual_check[i]["outs"] > outs:
                    leaderboard.append([i, numbers[i][stat]])
            elif defense_stat:
                
                if "outs" not in qual_check[i] or qual_check[i]["outs"] < 3: # the "WE HATE PITCHERS" line that excludes pitchers from defense leaderboards
                    defense = ["ground_ball_allowed", "ground_ball_fielded", "fly_ball_allowed", "fly_ball_fielded", "line_drive_allowed", "line_drive_fielded"]
                    for d in range(len(defense)):
                        defense[d] = qual_check[i][defense[d]] if defense[d] in qual_check[i] else 0
                    if stat == "GBO%" and defense[0] + defense[1] > 20:
                        leaderboard.append([i, numbers[i][stat]])
                    if stat == "FBO%" and defense[2] + defense[3] > 20:
                        leaderboard.append([i, numbers[i][stat]])
                    if stat == "LDO%" and defense[4] + defense[5] > 20:
                        leaderboard.append([i, numbers[i][stat]])
            else:
                if "at_bats" in qual_check[i] and qual_check[i]["at_bats"] > at_bats:
                    leaderboard.append([i, numbers[i][stat]])

    leaderboard.sort(key=lambda x: x[1], reverse=reverse ^ (not lower_better))

    for i in leaderboard[:20]:
        print_overview(i[0], roster_info, numbers, header="emoji")

# print the thresholds for the program to color stats in overviews
def legend():
    strings = []
    with open("data/stat_barriers.json", "r") as f:
        barriers = json.load(f)
        string = " " * 19 + "| "
        for i in barriers.keys():
            string += f"{i:<6} | "
        print(string)
        for i in [[98, "92m\033[1", "Elite   | Top 2%  "], 
                  [90, 33, "Great   | Top 10% "], 
                  [70, 77, "Good    | Top 30% "], 
                  [50, 241, "Median  | Top 50% "],
                  [30, 220, "Average | Top 70% "], 
                  [10, 208, "Bad     | Top 90% "], 
                  [0, 161, "Awful   | Top 100%"]]:
            string = ""
            for j in barriers.keys():
                string += f"{f"\033[38;5;{i[1]}m{f"{barriers[j][i[0]]:.3f}":>6}\x1b[0m | ":<12}"
            print(f"\033[38;5;{i[1]}m{i[2]}\x1b[0m |", string)

# console
def search_program():
    numbers = {}
    if os.path.isfile("data/processed_player_data.json"):
        with open("data/processed_player_data.json", "r") as f:
            numbers = json.load(f)
    roster_info = {}
    if os.path.isfile("data/roster_info.json"):
        with open("data/roster_info.json", "r") as f:
            roster_info = json.load(f)
    prompt = " "
    while prompt.lower() not in ["1", "close", "exit", "cls"]:
        prompt = input("Look up team by ID or name: ")
        flag = False
        teams = roster_info["teams"]
        matches = ""

        # Direct team ID lookup
        if prompt in teams:
            flag = True

        else:
            normalized_prompt = prompt.strip().lower()

            name_to_id = {
                team_info["name"].lower(): team_id
                for team_id, team_info in teams.items()
            }

            # Exact team-name lookup
            if normalized_prompt in name_to_id:
                prompt = name_to_id[normalized_prompt]
                flag = True

            else:
                matches = get_close_matches(
                    normalized_prompt,
                    name_to_id,
                    n=1,
                    cutoff=0.6,
                )

                

        if flag:
            print(f"{roster_info["teams"][prompt]["emoji"]} {roster_info["teams"][prompt]["name"]}")
            for m in roster_info["teams"][prompt]["members"]:
                print_overview(m, roster_info, numbers)

        if not flag:
            if prompt.lower() == "legend":
                legend()
            elif prompt[:11].lower() == "leaderboard":
                prompt = prompt.split(" ")
                reverse = False
                no_qualify = False
                if len(prompt) > 2:
                    arguments = prompt[2:]
                    reverse = "reverse" in arguments
                    no_qualify = "all" in arguments
                if len(prompt) > 1:
                    leaderboard(prompt[1].upper(), reverse=reverse, no_qualify=no_qualify)
                prompt = "".join(prompt)
            elif prompt[:5].lower() == "debug":
                prompt = prompt.split(" ")
                if len(prompt) > 1:
                    with open("data/player_data.json", "r") as f:
                        nitty_gritty = json.load(f)
                        if prompt[1] in nitty_gritty:
                            print(numbers[prompt[1]])
                            print(dict(sorted(nitty_gritty[prompt[1]].items())))
                        else:
                            print("player not found :(")
                prompt = "" # this is to return it to a string that won't crash the program
            elif prompt[:5].lower() == "pitch":
                prompt = prompt.split(" ")
                if len(prompt) > 1:
                    pitch_breakdown(prompt[1])
                prompt = ""
            elif prompt.lower() == "config":
                if config.edit():
                    print("as the league list has changed the program will now exit; please run again to begin adding new data")
                    print("yes this is kind of stupid. maybe azurite will change it later?")
                    os.remove(ALL_GAMES_PATH)
                    os.remove("data/player_data.json")
                    os.remove("data/processed_player_data.json")
                    os.remove("data/roster_info.json")
                    os.remove("data/stat_barriers.json")
                    return
            elif matches: # fuzzy search, now prioritized after leaderboards
                matched_name = matches[0]
                prompt = name_to_id[matched_name]

                print(
                    f'No exact match. Using '
                    f'"{teams[prompt]["name"]}".'
                )
                
                print(f"{roster_info["teams"][prompt]["emoji"]} {roster_info["teams"][prompt]["name"]}")
                for m in roster_info["teams"][prompt]["members"]:
                    print_overview(m, roster_info, numbers)
                
                
            elif prompt.lower() not in ["1", "close", "exit", "cls"]:
                print("team not found :(")
        print("")

def pitch_breakdown(playerID):
    with open("data/player_data.json", "r") as f, open("data/roster_info.json", "r") as f2:
        nitty_gritty = json.load(f)
        roster_info = json.load(f2)
        global_dist = get_pitch_zone_statistics()
        if "pitch_data" in nitty_gritty[playerID]:
            print(roster_info["players"][playerID]["name"], "-", f"{roster_info["teams"][roster_info["players"][playerID]["team"]]["emoji"]} {f"{roster_info["teams"][roster_info["players"][playerID]["team"]]["name"]}"}")
            for i in nitty_gritty[playerID]["pitch_data"]:
                grid = [[11, 0, 0, 0, 12, 0, -11, 0, 0, 0, -12],
                        [0, 1, 2, 3, 0, 0, 0, -1, -2, -3, 0],
                        [0, 4, 5, 6, 0, 0, 0, -4, -5, -6, 0],
                        [0, 7, 8, 9, 0, 0, 0, -7, -8, -9, 0],
                        [13, 0, 0, 0, 14, 0, -13, 0, 0, 0, -14]]
                print(i, "distribution")
                data = nitty_gritty[playerID]["pitch_data"][i] # this is here to make the code not hyroglyphic
                personal = {}
                everyone = {}
                for j in data.keys():
                    pitch_type = " ".join([roster_info["players"][playerID]["throws"], i])
                    personal[j] = 100 * data[str(j)] / sum([data[l] for l in data.keys()]) # load % of distribution for this player only
                    everyone[j] = 100 * global_dist[pitch_type][str(j)] / sum([global_dist[pitch_type][l] for l in global_dist[pitch_type].keys()]) # load % of distribution for everyone
                for j in grid:
                    to_print = ""
                    for k in j:
                        if k == 0:
                            to_print += f"{"":>5}"
                        if k > 0:
                            to_print += f"\033[38;5;77m" if personal[str(k)] > everyone[str(k)] else f"\033[38;5;161m"
                            if str(k) not in data.keys():
                                to_print += f"{"0.0":>5}"
                            else:
                                to_print += f"{f"{personal[str(k)]:.1f}":>5}"
                            to_print += "\x1b[0m"
                        if k < 0:
                            # print(pitch_type)
                            if str(k * -1) not in global_dist[" ".join([roster_info["players"][playerID]["throws"], i])].keys():
                                to_print += f"{"0.0":>5}"
                            else:
                                # print("hi2")
                                to_print += f"{f"{everyone[str(k * -1)]:.1f}":>5}"
                    print(to_print)

def get_pitch_zone_statistics():
    with open("data/player_data.json", "r") as f, open("data/roster_info.json", "r") as f2:
        nitty_gritty = json.load(f)
        roster_info = json.load(f2)
        counters = {}
        count = 0
        for i in nitty_gritty.keys():
            if "pitch_data" in nitty_gritty[i].keys() and i in roster_info["players"].keys():
                for j in nitty_gritty[i]["pitch_data"]:
                    # print(roster_info["players"][i]["name"], roster_info["players"][i]["throws"], j, nitty_gritty[i]["pitch_data"][j])
                    if "throws" not in roster_info["players"][i].keys():
                        print("pitch zone statistics will be available when you do a deep dive on player info. enter 'd' or 'deep' on the roster update screen to do this")
                        return counters
                    if " ".join([roster_info["players"][i]["throws"], j]) not in counters.keys():
                        counters[" ".join([roster_info["players"][i]["throws"], j])] = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0, "7": 0, "8": 0, "9": 0, "11": 0, "12": 0, "13": 0, "14": 0}
                    for k in nitty_gritty[i]["pitch_data"][j].keys():
                        counters[" ".join([roster_info["players"][i]["throws"], j])][k] += nitty_gritty[i]["pitch_data"][j][k]
            count += 1
        return counters

# TODO: hey there's a todo in this function
def print_overview(playerID, roster_info, numbers, header="position"):
    hidden_stats = {"C": ["GBO%", "LDO%", "FBO%"],
                    "1B": ["LDO%", "FBO%"],
                    "2B": ["LDO%", "FBO%"],
                    "3B": ["LDO%", "FBO%"],
                    "SS": ["LDO%", "FBO%"],
                    "LF": ["GBO%"],
                    "CF": ["GBO%"],
                    "RF": ["GBO%"],
                    "DH": ["GBO%", "LDO%", "FBO%"],
                    "SP": ["GBO%", "LDO%", "FBO%"],
                    "RP": ["GBO%", "LDO%", "FBO%"],
                    "CL": ["GBO%", "LDO%", "FBO%"],
                    "B1": [], "B2": [], "B3": [], "B4": [],
                    "P1": [], "P2": [], "P3": [], "P4": []} # this dictionary tells us stats we don't are about (e.g. GBO% for outfielders)
    to_print = ""
    if playerID in roster_info["players"]:
        player_info = roster_info["players"][playerID]
        to_print = f"{"\033[38;5;239m" if player_info["bench"] else ""}{player_info["position"][:2]:>2} {f"{player_info["name"]} \033[38;5;239m{f"{f"({player_info["effective_level"]})" if "effective_level" in player_info.keys() else ""}"}\x1b[0m":<40}"
        if header == "emoji":
            to_print = f"{"\033[38;5;239m" if player_info["bench"] else ""}{roster_info["teams"][roster_info["players"][playerID]["team"]]["emoji"]} {f"{player_info["name"]} \033[38;5;239m{f"{f"({player_info["effective_level"]})" if "effective_level" in player_info.keys() else ""}"}\x1b[0m":<40}"
    else:
        to_print = f"{playerID:<28}" # this is 28 and the other one is offset by 40 because that's the amount of space the coloring takes up
    # print the name
    if playerID in numbers.keys() and playerID in roster_info["players"]:
        for k in numbers[playerID]: # TODO: there's an issue in which players who have not done anything at all (benchies mostly) crash this due to not being in the database
            if k not in hidden_stats[roster_info["players"][playerID]["position"][:2]]: # 07/10/2026: the reason there's a [:2] is because of the SP specification bug
                to_print += f"{k} {color(k, numbers[playerID][k])}{f"{numbers[playerID][k]:.3f}":>6}\x1b[0m | "
    print(to_print)

with chdir(os.path.dirname(os.path.realpath(__file__))):
    current = requests.get("https://mmolb.com/api/seasons").json()["seasons"][0]["season_id"]
    yesno = ""

    # data folder initialization
    if not os.path.exists(os.path.join('data')):
        config.set_defaults()
        config.league_edit()
        print("Making data folder...")
        os.makedirs(os.path.join('data'))
    
    configuration = config.get_config()

    # roster info initialization
    if not os.path.isfile("data/roster_info.json"):
        print("No roster information detected, automatically fetching info...")
        update_rosters()
        update_rosters_deep()
    else:
        yesno = input("Update players? (takes a while) (enter 'yes' to activate)\n")
        if yesno.lower() in ["y", "yes"]:
            update_rosters()
        if yesno.lower() in ["d", "deep", "depth"]:
            update_rosters()
            update_rosters_deep()
            
    # games initialization
    if configuration["auto_game_update"] == "on" or not os.path.isfile(ALL_GAMES_PATH) or input("Update games? (takes a while) (enter 'yes' to activate) (do this on your first run)\n").lower() in ["y", "yes"]:
        print("Looking for new games...")
        update_games(current)
        with open("data/roster_info.json", "r") as f:
            roster_info = json.load(f)
            get_league_set = [i for i in roster_info["teams"].keys()]
            record_games(toi=get_league_set)

    get_pitch_zone_statistics()
    calculate_human_stats()
    calculate_percentiles()
    # quality_starts("quality_starts")
    # quality_starts("wins")
    search_program()

# TODO: make a "quick" roster update option


# roster_info
#   players
#     id
#       name
#       position
#       team
#   teams
#     id
#       league
#       emoji
#       name
#       members
#   league
#     doesn't matter lol 