#!/usr/bin/env python3
from pathlib import Path
from collections import namedtuple
from telegram import ParseMode, Bot
import json
import os


DateChanged = namedtuple("DateChanged", ("new_date",))
HostsChanged = namedtuple("HostsChanged", ("old_hosts", "new_hosts"))  # not tracking individuals
TalkAdded = namedtuple("TalkAdded", ("new_talk",))
TalkRemoved = namedtuple("TalkRemoved", ("old_talk",))
TalkChanged = namedtuple("TalkChanged", ("old_talk", "new_talk"))


def fetch_new_data():
    return json.loads(new_data_file.read_text())


def watch_for_new_data():
    from inotify.adapters import Inotify
    inotify = Inotify()
    inotify.add_watch(str(new_data_file))
    for event in inotify.event_gen(yield_nones=False):
        (_, type_names, path, filename) = event
        if "IN_CLOSE_WRITE" in type_names:
            got_new_data()


def _poll():
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
        if new["talks"] or new["hosts"] != ["fixme"]:
            changes.append(DateChanged(new["date"]))
            changes.append(HostsChanged(list(), new["hosts"]))
            changes += [TalkAdded(talk) for talk in new["talks"]]
        return changes
    if old["hosts"] != new["hosts"]:
        changes.append(HostsChanged(old["hosts"], new["hosts"]))
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


def _format_talk(talk):
    return " \* {} ({})\n".format(
        talk["title"],
        ", ".join(talk["persons"]),
    )


def publish_changes(changes):
    print("**************")
    print(changes)
    if not changes:
        return
    date_changed = tuple(filter(lambda x: isinstance(x, DateChanged), changes))
    hosts_changed = tuple(filter(lambda x: isinstance(x, HostsChanged), changes))
    talks_added = tuple(filter(lambda x: isinstance(x, TalkAdded), changes))
    talks_changed = tuple(filter(lambda x: isinstance(x, TalkChanged), changes))
    talks_removed = tuple(filter(lambda x: isinstance(x, TalkRemoved), changes))
    output = ""
    if date_changed:
        date = date_changed[0].new_date
        output += "*Talks on {}*:\n\n".format(date)
    else:
        date = current_data["date"]
        output += "*Changes to talks on {}*:\n\n".format(date)
    if talks_added:
        output += "Talks added:\n"
        for talk_added in talks_added:
            output += _format_talk(talk_added.new_talk)
        output += "\n"
    if talks_changed:
        output += "Talks changed:\n"
        for talk_changed in talks_changed:
            output += _format_talk(talk_changed.new_talk)  # TODO
        output += "\n"
    if talks_removed:
        output += "Talks removed:\n"
        for talk_removed in talks_removed:
            output += _format_talk(talk_removed.old_talk)
        output += "\n"
    if hosts_changed:
        output += "New hosts: {} (instead of {})\n".format(
            ", ".join(hosts_changed[0].new_hosts),
            ", ".join(hosts_changed[0].old_hosts),
        )  # TODO: []
    print(output)
    for chat_id in chat_ids:
        bot.sendMessage(chat_id=chat_id, text=output, parse_mode=ParseMode.MARKDOWN)


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

bot = Bot(token=os.environ["TELEGRAM_API_KEY"])
chat_ids = [int(x) for x in os.environ["CHAT_IDS"].split(",")]
watch_for_new_data()
