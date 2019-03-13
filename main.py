#!/usr/bin/env python3
from pathlib import Path
from collections import namedtuple
import json
import os


DateChanged = namedtuple("DateChanged", ("new_date",))
HostsChanged = namedtuple("HostsChanged", ("hosts",))  # not tracking individuals
TalkAdded = namedtuple("TalkAdded", ("new_talk",))
TalkRemoved = namedtuple("TalkRemoved", ("old_talk",))
TalkChanged = namedtuple("TalkChanged", ("old_talk", "new_talk"))


def fetch_new_data():
    return json.loads(new_data_file.read_text())


def watch_for_new_data():
    from time import sleep
    while True:  # TODO
        sleep(60)
        got_new_data()


def save_current_data():
    current_data_file.write_text(json.dumps(current_data))


def got_new_data():
    global current_data
    new_data = fetch_new_data()
    changes = compare_data(current_data, new_data)
    publish_changes(changes)
    current_data = new_data
    save_current_data()


def compare_data(old, new):
    changes = list()
    if old["date"] != new["date"]:  # next week, no need to compare stuff
        if new["talks"] or new["hosts"] != ["FIXME"]:
            changes.append(DateChanged(new["date"]))
            changes.append(HostsChanged(new["hosts"]))
            changes += [TalkAdded(talk) for talk in new["talks"]]
        return changes
    if old["hosts"] != new["hosts"]:
        changes.append(HostsChanged(new["hosts"]))
    for talk in old["talks"]:
        matching_talk = find_matching_talk(talk, new["talks"])
        if not matching_talk:
            changes.append(TalkRemoved(talk))
        else:
            if talk != matching_talk:
                changes.append(TalkChanged(talk, matching_talk))
    for talk in new["talks"]:
        matching_talk = find_matching_talk(talk, new["talks"])
        if not matching_talk:
            changes.append(TalkAdded(talk))
        # no need to track modified talks here, see above
    return changes


def find_matching_talk(original_talk, list_of_talks):
    """Find a talk in list_of_talks that matches original_talk."""
    # TODO: improve
    for possibility in list_of_talks:
        if original_talk["title"] == possibility["title"]:
            return possibility


def publish_changes(changes):
    print("**************")
    for change in changes:
        print(change)


data_path = Path("data")
current_data_file = data_path / Path("current.json")
new_data_file = Path(os.environ.get("NEW_DATA_FILE", "new.json"))
current_data = None

try:
    current_data = json.loads(current_data_file.read_text())
except FileNotFoundError:
    current_data = fetch_new_data()
    save_current_data()

assert current_data

watch_for_new_data()
