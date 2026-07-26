import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from threading import local
from contextlib import chdir

import requests
from tqdm import tqdm

import defense
import stats_config as config

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
    teams_to_fetch = []

    for league_id in league_ids:
        try:
            league = get_json_with_retries(
                f"https://mmolb.com/api/league/{league_id}"
            )
        except RuntimeError as error:
            tqdm.write(f"Skipping league {league_id}: {error}")
            continue

        league_dict[league_id] = league["Teams"]

        for team_id in league["Teams"]:
            teams_to_fetch.append((league_id, team_id))

    teams_to_fetch = list(dict.fromkeys(teams_to_fetch))

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        fetched_teams = executor.map(fetch_team, teams_to_fetch)

        for league_id, team_id, team, error in fetched_teams:
            if error is not None:
                tqdm.write(f"Skipping team {team_id}: {error}")
                continue

            record = team.get("Record", {}).get("Regular Season", {})
            wins = record.get("Wins", 0)
            losses = record.get("Losses", 0)

            if wins + losses <= 0:
                continue

            tqdm.write(
                f"Fetched team: {team['Location']} {team['Name']}"
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
                    "name": f"{player['FirstName']} {player['LastName']}",
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
                        "name": f"{player['FirstName']} {player['LastName']}",
                        "position": player["Slot"],
                        "team": team_id,
                        "bench": True,
                    }

                    members.append(player_id)

            team_dict[team_id] = {
                "league": league_id,
                "emoji": team["Emoji"],
                "name": f"{team['Location']} {team['Name']}",
                "members": members,
                "wins": wins,
                "losses": losses,
                "rd": record.get("RunDifferential", 0),
            }

    roster_info = {
        "players": player_dict,
        "teams": team_dict,
        "leagues": league_dict,
    }

    write_json_atomic("data/roster_info.json", roster_info)


def update_rosters_deep():
    roster_path = "data/roster_info.json"

    if not os.path.isfile(roster_path):
        print("Cannot fetch player details: roster_info.json is missing")
        return

    with open(roster_path, "r", encoding="utf-8") as f:
        roster_info = json.load(f)

    player_ids = list(roster_info["players"])
    print("Fetching individual player info...")

    progress = tqdm(
        total=len(player_ids),
        desc="Fetching player details",
        unit="player",
        dynamic_ncols=True,
    )

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        fetched_players = executor.map(fetch_player, player_ids)

        for processed_count, (player_id, player, error) in enumerate(
            fetched_players,
            start=1,
        ):
            progress.update(1)

            if error is not None:
                tqdm.write(f"Skipping player {player_id}: {error}")
                continue

            player_info = roster_info["players"][player_id]
            effective_level = 1 + len(player.get("AugmentHistory", []))
            effective_level += len(player.get("AppliedLevelUps", []))

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

            if processed_count % 1000 == 0:
                write_json_atomic(roster_path, roster_info)

    progress.close()
    write_json_atomic(roster_path, roster_info)


def update_games(season_id, hard_reset=False):
    games = {} if hard_reset else load_games()

    start_search_from = 0
    if games:
        start_search_from = max(game["day"] for game in games.values()) - 1

    season = get_json_with_retries(f"https://mmolb.com/api/season/{season_id}")

    for day_counter, day_id in enumerate(season["Days"], start=1):
        if day_counter < start_search_from:
            continue

        try:
            day = get_json_with_retries(f"https://mmolb.com/api/day/{day_id}")
        except RuntimeError as error:
            tqdm.write(
                f"Skipping day {day_id} after repeated failures:\n{error}"
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
            was_checked = games.get(game_id, {}).get("checked", False)

            games[game_id] = {
                "away_team_id": game["AwayTeamID"],
                "home_team_id": game["HomeTeamID"],
                "day": day["Day"],
                "state": game["State"],
                "checked": was_checked and not hard_reset,
            }

        if stop_early_flag:
            break

    save_games(games)


def record_games(toi=None, hard_reset=False):
    games = load_games()
    players = {} if hard_reset else load_players_for_recording()

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

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as executor:
        fetched_games = executor.map(fetch_game, games_to_record)

        for processed_count, (game_id, game_info, game, error) in enumerate(
            fetched_games,
            start=1,
        ):
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

            for team in game["Stats"]:
                for player_id in game["Stats"][team]:
                    if player_id not in players:
                        players[player_id] = {}

                    for stat, value in game["Stats"][team][player_id].items():
                        players[player_id][stat] = (
                            players[player_id].get(stat, 0) + value
                        )

            defense_stats = defense.parse_fielding(game)

            for player_id, player_stats in defense_stats.items():
                if player_id not in players:
                    players[player_id] = {}

                for stat, value in player_stats.items():
                    players[player_id][stat] = (
                        players[player_id].get(stat, 0) + value
                    )

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

                pitch_data = players[pitcher_id].setdefault("pitch_data", {})

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

            if processed_count % 1000 == 0:
                save_games(games)
                write_json_atomic("data/player_data.json", players, indent=None)

    progress.close()
    save_games(games)
    write_json_atomic("data/player_data.json", players)


def run_updates(current_season, configuration):
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

        if (
            configuration["auto_game_update"] == "on"
            or not os.path.isfile(ALL_GAMES_PATH)
            or input(
                "Update games? (takes a while) (enter 'yes' to activate) "
                "(do this on your first run)\n"
            ).lower() in ["y", "yes"]
        ):
            first_run = not os.path.isfile(ALL_GAMES_PATH)
        
            print("Looking for new games...")
            update_games(current_season, hard_reset=first_run)
        
            with open("data/roster_info.json", "r", encoding="utf-8") as f:
                roster_info = json.load(f)
        
            get_league_set = list(roster_info["teams"])
            record_games(toi=get_league_set, hard_reset=first_run)


def main():
    with chdir(os.path.dirname(os.path.realpath(__file__))):
        current = requests.get("https://mmolb.com/api/seasons").json()["seasons"][0]["season_id"]

        if not os.path.exists(os.path.join("data")):
            config.set_defaults()
            config.league_edit()
            print("Making data folder...")
            os.makedirs(os.path.join("data"))

        configuration = config.get_config()
        run_updates(current, configuration)


if __name__ == "__main__":
    main()
