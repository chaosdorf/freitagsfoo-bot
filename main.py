#!/usr/bin/env python3
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
from telegram import ParseMode, Bot
from mypy_extensions import TypedDict
from typing import List, NamedTuple, Optional, Tuple, Union
import json
import os
import logging

# has to be in sync with freitagsfoo-wiki-json
Talk = TypedDict("Talk", {
    "title": str,
    "description": str,
    "persons": List[str],
})
TalksData = TypedDict("TalksData", {
    "hosts": List[str],
    "date": str,
    "talks": List[Talk],
})
DateChanged = NamedTuple("DateChanged", (("new_date", str),))
HostsChanged = NamedTuple("HostsChanged", (("old_hosts", List[str]), ("new_hosts", List[str])))  # not tracking individuals
TalkAdded = NamedTuple("TalkAdded", (("new_talk", Talk),))
TalkRemoved = NamedTuple("TalkRemoved", (("old_talk", Talk),))
TalkChanged = NamedTuple("TalkChanged", (("old_talk", Talk), ("new_talk", Talk)))
Change = Union[DateChanged, HostsChanged, TalkAdded, TalkRemoved, TalkChanged]


def fetch_new_data():
    return json.loads(new_data_file.read_text())


def watch_for_new_data() -> None:
    from inotify.adapters import Inotify
    inotify = Inotify()
    inotify.add_watch(str(new_data_file))
    for event in inotify.event_gen(yield_nones=False):
        (_, type_names, path, filename) = event
        if "IN_CLOSE_WRITE" in type_names:
            got_new_data()


def _poll() -> None:
    from time import sleep
    while True:  # TODO
        sleep(60)
        got_new_data()


def save_current_data() -> None:
    current_data_file.write_text(json.dumps(current_data))


def got_new_data() -> None:
    global current_data
    new_data = fetch_new_data()
    logging.debug("Got new data: %s", new_data)
    changes = compare_data(current_data, new_data)
    logging.debug("Computed changes: %s", changes)
    publish_changes(changes)
    logging.debug("Published.")
    current_data = new_data
    save_current_data()


def compare_data(old: TalksData, new: TalksData) -> List[Change]:
    changes = list()  # type: List[Change]
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
        matching_talk = find_matching_talk(talk, old["talks"])
        if not matching_talk:
            changes.append(TalkAdded(talk))
        # no need to track modified talks here, see above
    return changes


def find_matching_talk(original_talk: Talk, list_of_talks: List[Talk]) -> Optional[Talk]:
    """Find a talk in list_of_talks that matches original_talk."""
    # TODO: improve
    for possibility in list_of_talks:
        if original_talk["title"] == possibility["title"]:
            return possibility
    return None


def publish_changes(changes: List[Change]) -> None:
    if not changes:
        return
    date_changed = tuple(filter(lambda x: isinstance(x, DateChanged), changes))  # type: Tuple[DateChanged, ...]
    hosts_changed = tuple(filter(lambda x: isinstance(x, HostsChanged), changes))  # type: Tuple[HostsChanged, ...]
    talks_added = tuple(filter(lambda x: isinstance(x, TalkAdded), changes))  # type: Tuple[TalkAdded, ...]
    talks_changed = tuple(filter(lambda x: isinstance(x, TalkChanged), changes))  # type: Tuple[TalkChanged, ...]
    talks_removed = tuple(filter(lambda x: isinstance(x, TalkRemoved), changes))  # type: Tuple[TalkRemoved, ...]
    date = date_changed[0].new_date if date_changed else current_data["date"]
    output = jinja_templ.render(
        date=date,
        date_changed=date_changed,
        talks_added=talks_added,
        talks_changed=talks_changed,
        talks_removed=talks_removed,
        hosts_changed=hosts_changed,
    )
    print(output)
    for chat_id in chat_ids:
        bot.sendMessage(chat_id=chat_id, text=output, parse_mode=ParseMode.MARKDOWN)


if __name__ == '__main__':
    if os.environ.get("LOGLEVEL"):
        logging.basicConfig(level=getattr(logging, os.environ["LOGLEVEL"].upper()))
    
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
    
    jinja_env = Environment(
        loader=FileSystemLoader("."),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    jinja_templ = jinja_env.get_template("template.j2")
    bot = Bot(token=os.environ["TELEGRAM_API_KEY"])
    chat_ids = [int(x) for x in os.environ["CHAT_IDS"].split(",")]
    logging.debug("Waiting for data...")
    watch_for_new_data()
