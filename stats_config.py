import json
from copy import deepcopy

DEFAULT_CONFIG = {
    "auto_game_update": "on",
    "leagues": ["clover", "pineapple"],
    "custom_stats": {},
}


def set_defaults():
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)


def valid_options():
    options = {
        "auto_game_update": ["on", "off"],
        "leagues": {
            "baseball": "6805db0cac48194de3cd3fe7",
            "precision": "6805db0cac48194de3cd3fe8",
            "isosceles": "6805db0cac48194de3cd3fe9",
            "liberty": "6805db0cac48194de3cd3fea",
            "maple": "6805db0cac48194de3cd3feb",
            "cricket": "6805db0cac48194de3cd3fec",
            "tornado": "6805db0cac48194de3cd3fed",
            "coleoptera": "6805db0cac48194de3cd3fee",
            "clean": "6805db0cac48194de3cd3fef",
            "shiny": "6805db0cac48194de3cd3ff0",
            "psychic": "6805db0cac48194de3cd3ff1",
            "unidentified": "6805db0cac48194de3cd3ff2",
            "ghastly": "6805db0cac48194de3cd3ff3",
            "amphibian": "6805db0cac48194de3cd3ff4",
            "deep": "6805db0cac48194de3cd3ff5",
            "harmony": "6805db0cac48194de3cd3ff6",
            "clover": "6805db0cac48194de3cd3fe4",
            "pineapple": "6805db0cac48194de3cd3fe5",
        },
    }
    return options

def normalize_config(settings):
    """Add newly introduced settings without destroying an old config."""
    changed = False

    for key, value in DEFAULT_CONFIG.items():
        if key not in settings:
            settings[key] = deepcopy(value)
            changed = True

    return settings, changed


# This is called one time, when the user first opens something up.
def league_edit():
    with open("config.json", "r", encoding="utf-8") as f:
        settings = json.load(f)

    settings, _ = normalize_config(settings)
    cmd = ""

    while cmd.lower() != "exit":
        leagues = valid_options()["leagues"]
        counter = 0

        for league_name in leagues:
            counter += 1
            dim = "" if league_name in settings["leagues"] else "\033[38;5;239m"
            print(
                f"{dim}{league_name:<12}\x1b[0m",
                end="\n" if counter % 4 == 0 else " ",
            )

        cmd = input(
            "\nenter a league's name to toggle it on/off, "
            "or 'exit' to leave this submenu: "
        )

        if cmd.lower() in leagues:
            if cmd.lower() in settings["leagues"]:
                settings["leagues"].remove(cmd.lower())
            else:
                settings["leagues"].append(cmd.lower())

        if cmd.lower() != "exit":
            print("\033[F\033[K" * 6, end="")

    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def edit():
    with open("config.json", "r", encoding="utf-8") as f:
        settings = json.load(f)

    settings, _ = normalize_config(settings)
    original_leagues = settings["leagues"].copy()

    cmd = ""
    exit_flag = False

    while cmd.lower() not in ["1", "close", "exit", "cls"]:
        print("\ncurrent settings:")
        for key, value in settings.items():
            print(f"{key:>20} : {value}")

        cmd = input(
            "enter a setting to change it, or 'reset' to return to defaults: "
        )

        if cmd.lower() in settings:
            if cmd.lower() == "leagues":
                league_edit()
                settings = get_config()
                cmd = ""
            elif cmd.lower() == "custom_stats":
                print(
                    "custom_stats is edited directly in config.json; "
                    "see the documentation for formula examples."
                )
            else:
                settings[cmd.lower()] = input(
                    f"enter new setting for {cmd.lower()}: "
                )
        elif cmd.lower() == "reset":
            set_defaults()
            settings = get_config()
        elif cmd.lower() in ["1", "close", "exit", "cls"]:
            if settings["leagues"] != original_leagues:
                exit_flag = True

            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)

            print("config saved!")
        else:
            print("dunno what that is")

    return exit_flag


def get_config():
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            settings = json.load(f)
    except FileNotFoundError:
        set_defaults()
        with open("config.json", "r", encoding="utf-8") as f:
            settings = json.load(f)

    settings, changed = normalize_config(settings)

    if changed:
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)

    return settings


leagues = valid_options()["leagues"]