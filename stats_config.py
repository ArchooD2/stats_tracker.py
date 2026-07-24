# config.py

import json

def set_defaults():
    with open("config.json", "w") as f:
        json.dump({"auto_game_update": "on",
                   "leagues": ["clover", "pineapple"]}, f)

def valid_options():
    options = {"auto_game_update": ["on", "off"],
               "leagues": {  
                            "baseball":     "6805db0cac48194de3cd3fe7", 
                            "precision":    "6805db0cac48194de3cd3fe8", 
                            "isosceles":    "6805db0cac48194de3cd3fe9", 
                            "liberty":      "6805db0cac48194de3cd3fea",
                            "maple":        "6805db0cac48194de3cd3feb", 
                            "cricket":      "6805db0cac48194de3cd3fec", 
                            "tornado":      "6805db0cac48194de3cd3fed",
                            "coleoptera":   "6805db0cac48194de3cd3fee", 
                            "clean":        "6805db0cac48194de3cd3fef",
                            "shiny":        "6805db0cac48194de3cd3ff0", 
                            "psychic":      "6805db0cac48194de3cd3ff1", 
                            "unidentified": "6805db0cac48194de3cd3ff2", 
                            "ghastly":      "6805db0cac48194de3cd3ff3", 
                            "amphibian":    "6805db0cac48194de3cd3ff4", 
                            "deep":         "6805db0cac48194de3cd3ff5", 
                            "harmony":      "6805db0cac48194de3cd3ff6",
                            "clover":       "6805db0cac48194de3cd3fe4", 
                            "pineapple":    "6805db0cac48194de3cd3fe5",
                        }}
    return options

# this is called one time, when the user first opens something up. i hate it a lot. i should do something else eventually
def league_edit():
    settings = ""
    with open("config.json", "r") as f:
        settings = json.load(f)
    cmd = ""
    while cmd.lower() != "exit":
        l = valid_options()["leagues"]
        stupid_ass_counter = 0 # variable name is here to remind me to make a better way to do this
        for i in l.keys():
            stupid_ass_counter += 1
            print(f"{"" if i in settings["leagues"] else "\033[38;5;239m"}{i:<12}\x1b[0m", end="\n" if stupid_ass_counter % 4 == 0 else " ")
            
        cmd = input("\nenter a league's name to toggle it on/off, or 'exit' to leave this submenu: ")
        if cmd.lower() in valid_options()["leagues"]:
            if cmd.lower() in settings["leagues"]:
                settings["leagues"].remove(cmd.lower())
            else:
                settings["leagues"].append(cmd.lower())
        if cmd.lower() != "exit":
            print("\033[F\033[K" * 6, end="")
    with open("config.json", "w") as f:
        json.dump(settings, f)

def edit():
    settings = ""
    with open("config.json", "r") as f:
        settings = json.load(f)
    cmd = ""
    exit_flag = False
    while cmd.lower() not in ["1", "close", "exit", "cls"]:
        print("\ncurrent settings:")
        for i in settings.keys():
            print(f"{i:>20} : {settings[i]}")
        cmd = input("enter a setting to change it, or 'reset' to return to defaults: ")
        if cmd.lower() in settings.keys():
            if cmd.lower() not in "leagues":
                settings[cmd.lower()] = input(f"enter new setting for {cmd.lower()}: ")
            else:
                cmd = ""
                while cmd.lower() != "exit":
                    l = valid_options()["leagues"]
                    stupid_ass_counter = 0 # variable name is here to remind me to make a better way to do this
                    for i in l.keys():
                        stupid_ass_counter += 1
                        print(f"{"" if i in settings["leagues"] else "\033[38;5;239m"}{i:<12}\x1b[0m", end="\n" if stupid_ass_counter % 4 == 0 else " ")
                        
                    cmd = input("\nenter a league's name to toggle it on/off, or 'exit' to leave this submenu: ")
                    if cmd.lower() in valid_options()["leagues"]:
                        if cmd.lower() in settings["leagues"]:
                            settings["leagues"].remove(cmd.lower())
                        else:
                            settings["leagues"].append(cmd.lower())
                    if cmd.lower() != "exit":
                        print("\033[F\033[K" * 6, end="")
                cmd = ""
        elif cmd.lower() == "reset":
            set_defaults()
            with open("config.json", "r") as f:
                settings = json.load(f)
        elif cmd.lower() in ["1", "close", "exit", "cls"]:
            go_ahead = True
            with open("config.json", "r") as f:
                old_settings = json.load(f)
                # print(settings["leagues"], old_settings["leagues"])
                if settings["leagues"] != old_settings["leagues"]:
                    exit_flag = True
            if go_ahead:
                with open("config.json", "w") as f:
                    json.dump(settings, f)
                print("config saved!")
            else: # this is a remnant from when i tried to make an "are you sure" confirmation because getting the new data takes foreeeeever
                print("config menu exited without saving.")
        elif cmd.lower() not in ["1", "close", "exit", "cls"]:
            print("dunno what that is")
    return exit_flag

def get_config():
    try:
        with open("config.json", "r") as f:
            return json.load(f)

    except FileNotFoundError:
        set_defaults()

        with open("config.json", "r") as f:
            return json.load(f)
    
leagues = { "clover":       "6805db0cac48194de3cd3fe4", 
            "pineapple":    "6805db0cac48194de3cd3fe5", 
            "baseball":     "6805db0cac48194de3cd3fe7", 
            "precision":    "6805db0cac48194de3cd3fe8", 
            "isosceles":    "6805db0cac48194de3cd3fe9", 
            "liberty":      "6805db0cac48194de3cd3fea",
            "maple":        "6805db0cac48194de3cd3feb", 
            "cricket":      "6805db0cac48194de3cd3fec", 
            "tornado":      "6805db0cac48194de3cd3fed",
            "coleoptera":   "6805db0cac48194de3cd3fee", 
            "clean":        "6805db0cac48194de3cd3fef",
            "shiny":        "6805db0cac48194de3cd3ff0", 
            "psychic":      "6805db0cac48194de3cd3ff1", 
            "unidentified": "6805db0cac48194de3cd3ff2", 
            "ghastly":      "6805db0cac48194de3cd3ff3", 
            "amphibian":    "6805db0cac48194de3cd3ff4", 
            "deep":         "6805db0cac48194de3cd3ff5", 
            "harmony":      "6805db0cac48194de3cd3ff6"
        }