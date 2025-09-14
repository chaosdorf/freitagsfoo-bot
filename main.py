#!/usr/bin/env python3
import asyncio
from asyncinotify import Inotify, Mask
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, Template
from markdown import markdown
from nio import AsyncClient
from typing import List, NamedTuple, Optional, Tuple, Union, TypedDict
import json
import os
import logging
import traceback

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


async def fetch_new_data(new_data_file: Path, backoff: int = 5) -> TalksData:
    try:
        data = json.loads(new_data_file.read_text())
        return data
    except Exception as exc:
        print("Failed to get data, retrying:")
        traceback.print_exception(exc)
        await asyncio.sleep(backoff)
        return await fetch_new_data(new_data_file, backoff * 2)


async def watch_for_new_data(client: AsyncClient, room_ids: List[str], jinja_templ: Template, current_data_file: Path, new_data_file: Path) -> None:
    inotify = Inotify()
    inotify.add_watch(str(new_data_file), Mask.CLOSE)
    async for event in inotify:
        await got_new_data(client, room_ids, jinja_templ, current_data_file, new_data_file)


async def _poll(client: AsyncClient, room_ids: List[str], jinja_templ: Template, current_data_file: Path, new_data_file: Path) -> None:
    from time import sleep
    while True:  # TODO
        sleep(60)
        await got_new_data(client, room_ids, jinja_templ, current_data_file, new_data_file)


def save_current_data(current_data: TalksData, current_data_file: Path) -> None:
    current_data_file.write_text(json.dumps(current_data))


async def got_new_data(client: AsyncClient, room_ids: List[str], jinja_templ: Template, current_data_file: Path, new_data_file: Path) -> None:
    global current_data
    new_data = await fetch_new_data(new_data_file)
    logging.debug("Got new data: %s", new_data)
    changes = compare_data(current_data, new_data)
    logging.debug("Computed changes: %s", changes)
    await publish_changes(client, room_ids, jinja_templ, changes)
    logging.debug("Published.")
    current_data = new_data
    save_current_data(current_data, current_data_file)


def compare_data(old: TalksData, new: TalksData) -> List[Change]:
    changes: List[Change] = list()
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


async def publish_changes(client: AsyncClient, room_ids: List[str], jinja_templ: Template, changes: List[Change]) -> None:
    if not changes:
        return
    date_changed: Tuple[DateChanged, ...] = tuple(filter(lambda x: isinstance(x, DateChanged), changes))
    hosts_changed: Tuple[HostsChanged, ...] = tuple(filter(lambda x: isinstance(x, HostsChanged), changes))
    talks_added: Tuple[TalkAdded, ...] = tuple(filter(lambda x: isinstance(x, TalkAdded), changes))
    talks_changed: Tuple[TalkChanged, ...] = tuple(filter(lambda x: isinstance(x, TalkChanged), changes))
    talks_removed: Tuple[TalkRemoved, ...] = tuple(filter(lambda x: isinstance(x, TalkRemoved), changes))
    date = date_changed[0].new_date if date_changed else current_data["date"]
    output_md = jinja_templ.render(
        date=date,
        date_changed=date_changed,
        talks_added=talks_added,
        talks_changed=talks_changed,
        talks_removed=talks_removed,
        hosts_changed=hosts_changed,
    )
    print(output_md)
    for room_id in room_ids:
        await client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "format": "org.matrix.custom.html",
                "body": output_md,
                "formatted_body": markdown(output_md),
            },
        )


async def main():
    global current_data
    if os.environ.get("LOGLEVEL"):
        logging.basicConfig(level=getattr(logging, os.environ["LOGLEVEL"].upper()))
    
    data_path = Path("data")
    current_data_file = data_path / Path("current.json")
    new_data_file = Path(os.environ.get("NEW_DATA_FILE", "new.json"))
    current_data = None
    
    try:
        current_data = json.loads(current_data_file.read_text())
    except:
        logging.warn("Failed to load old data")
        current_data = await fetch_new_data(new_data_file)
        save_current_data(current_data, current_data_file)
    
    assert current_data
    
    jinja_env = Environment(
        loader=FileSystemLoader("."),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    jinja_templ = jinja_env.get_template("template.j2")
    client = AsyncClient(os.environ["MATRIX_HOMESERVER"], os.environ["MATRIX_USERNAME"])
    room_ids = os.environ["MATRIX_ROOM_IDS"].split(",")
    logging.info(await client.login(os.environ["MATRIX_PASSWORD"]))
    logging.debug("Waiting for data...")
    syncer = asyncio.create_task(client.sync_forever(timeout=30000))
    await watch_for_new_data(client, room_ids, jinja_templ, current_data_file, new_data_file)


if __name__ == "__main__":
    asyncio.run(main())
