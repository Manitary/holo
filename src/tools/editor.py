import os
import sys
from collections import OrderedDict

import pygubu
import yaml


def represent_ordereddict(dumper, data) -> yaml.nodes.MappingNode:
    value = []
    for item_key, item_value in data.items():
        node_key = dumper.represent_data(item_key)
        node_value = dumper.represent_data(item_value)
        value.append((node_key, node_value))
    return yaml.nodes.MappingNode("tag:yaml.org,2002:map", value)


yaml.add_representer(OrderedDict, represent_ordereddict)

CURRENT_FILE = "default.yaml"
CURRENT_DOCS = []
CURRENT_DOC = 0

INFO_KEYS = ["mal", "anidb", "anilist", "kitsu"]
STREAM_KEYS = ["crunchyroll", "funimation"]


def load_current_file() -> None:
    print(f"Loading current file: {CURRENT_FILE}")
    global CURRENT_DOCS, CURRENT_DOC
    try:
        with open(CURRENT_FILE, "r", encoding="UTF-8") as f:
            CURRENT_DOCS = list(yaml.load_all(f))
        CURRENT_DOC = len(CURRENT_DOCS)
    except FileNotFoundError:
        pass
    except yaml.YAMLError:
        print("Failed to parse edit file")


def save_current_file() -> bool:
    print(f"Saving current file: {CURRENT_FILE}")

    def order_dict(d):
        return OrderedDict(
            [
                ("title", d["title"]),
                ("type", d["type"]),
                ("has_source", d["has_source"]),
                (
                    "info",
                    OrderedDict(
                        [
                            (key, d["info"][key] if key in d["info"] else "")
                            for key in INFO_KEYS
                        ]
                    ),
                ),
                (
                    "streams",
                    OrderedDict(
                        [
                            (key, d["streams"][key] if key in d["streams"] else "")
                            for key in STREAM_KEYS
                        ]
                    ),
                ),
            ]
        )

    try:
        sorted_docs = [order_dict(doc) for doc in CURRENT_DOCS]
        with open(CURRENT_FILE, "w", encoding="UTF-8") as f:
            yaml.dump_all(
                sorted_docs, f, default_flow_style=False, indent=4, allow_unicode=True
            )
    except Exception:
        from traceback import print_exc

        print_exc()
        return False
    return True


class Application:
    def __init__(self) -> None:
        self.builder = pygubu.Builder()
        self.builder.add_from_file("editor.ui")
        self.mainwindow = self.builder.get_object("mainwindow")

        self.builder.connect_callbacks(self)
        self.mainwindow.protocol("WM_DELETE_WINDOW", self.on_close_window)

    def _get_inputs(self):
        title = self.builder.get_variable("name")
        atype = self.builder.get_variable("type")
        has_source = self.builder.get_variable("has_source")
        return (
            title,
            atype,
            has_source,
            {key: self.builder.get_variable(key + "_url") for key in INFO_KEYS},
            {key: self.builder.get_variable(key + "_url") for key in STREAM_KEYS},
        )

    def set_doc(self) -> None:
        self.clear_doc()

        print(f"Loading doc {CURRENT_DOC}")
        self.update_title()
        doc = CURRENT_DOCS[CURRENT_DOC]

        title, atype, has_source, info_urls, stream_urls = self._get_inputs()
        title.set(doc["title"])
        atype.set(doc["type"])
        has_source.set(doc["has_source"])
        if "info" in doc:
            info = doc["info"]
            for key in INFO_KEYS:
                if key in info:
                    info_urls[key].set(info[key])
        if "streams" in doc:
            streams = doc["streams"]
            for key in STREAM_KEYS:
                if key in streams:
                    stream_urls[key].set(streams[key])

    def clear_doc(self) -> None:
        title, atype, has_source, info_urls, stream_urls = self._get_inputs()
        title.set("")
        atype.set("tv")
        has_source.set(True)
        for _, url in info_urls.items():
            url.set("")
        for _, url in stream_urls.items():
            url.set("")

    def update_title(self) -> None:
        updating = "creating" if CURRENT_DOC >= len(CURRENT_DOCS) else "updating"
        file_name = os.path.basename(CURRENT_FILE)
        file_label = self.builder.get_object("open_label")
        file_label["text"] = "{} ({} shows), {}".format(
            file_name, len(CURRENT_DOCS), updating
        )

    def on_find_button_clicked(self):
        global CURRENT_DOC
        find_text = self.builder.get_variable("find_text").get().lower()
        if len(find_text) > 0:
            for i, doc in enumerate(CURRENT_DOCS):
                name = doc["title"].lower()
                if find_text in name:
                    CURRENT_DOC = i
                    self.set_doc()
        else:
            CURRENT_DOC = 0
            if len(CURRENT_DOCS) > 0:
                self.set_doc()
            else:
                self.clear_doc()

    def on_save_button_clicked(self) -> None:
        global CURRENT_DOC
        self.store_state()
        if save_current_file():
            CURRENT_DOC = len(CURRENT_DOCS)
            self.update_title()
            self.clear_doc()

    def on_next_button_clicked(self) -> None:
        global CURRENT_DOC
        self.store_state()
        if save_current_file():
            CURRENT_DOC += 1
            self.update_title()
            if CURRENT_DOC < len(CURRENT_DOCS):
                self.set_doc()
            else:
                self.clear_doc()

    def on_close_window(self, event=None) -> None:
        self.mainwindow.destroy()

    def store_state(self) -> None:
        global CURRENT_DOCS
        title, atype, has_source, info_urls, stream_urls = self._get_inputs()

        title = title.get()
        print(f"  title={title}")
        atype = atype.get()
        print(f"  type={atype}")
        has_source = has_source.get()
        print(f"  has_source={has_source}")

        info = {}
        for key in INFO_KEYS:
            url = info_urls[key].get() if key in info_urls else ""
            print(f"  {key}={url}")
            info[key] = url

        streams = {}
        for key in STREAM_KEYS:
            url = stream_urls[key].get() if key in stream_urls else ""
            print(f"  {key}={url}")
            streams[key] = url

        show = {
            "title": title,
            "type": atype,
            "has_source": has_source,
            "info": info,
            "streams": streams,
        }
        if CURRENT_DOC >= len(CURRENT_DOCS):
            print("Appending")
            CURRENT_DOCS.append(show)
            print(f"  New length: {len(CURRENT_DOCS)}")
        else:
            print(f"Setting to {CURRENT_DOC}")
            CURRENT_DOCS[CURRENT_DOC] = show

    def run(self) -> None:
        load_current_file()
        self.update_title()
        self.clear_doc()

        self.mainwindow.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        CURRENT_FILE = sys.argv[1]
        print(f"Using file: {CURRENT_FILE}")

    app = Application()
    app.run()
