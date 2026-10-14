"""Map Android widget class names to sceneuse role tokens."""

from __future__ import annotations

_CLASS = {
    "android.widget.button": "button",
    "android.widget.imagebutton": "button",
    "android.widget.compoundbutton": "button",
    "android.widget.togglebutton": "button",
    "android.widget.edittext": "textfield",
    "android.widget.autocompletetextview": "textfield",
    "android.widget.multiautocompletetextview": "textarea",
    "android.widget.checkbox": "checkbox",
    "android.widget.radiobutton": "radio",
    "android.widget.switch": "checkbox",
    "android.widget.switchcompat": "checkbox",
    "androidx.appcompat.widget.switchcompat": "checkbox",
    "android.widget.seekbar": "slider",
    "android.widget.ratingbar": "slider",
    "android.widget.textview": "text",
    "android.widget.imageview": "image",
    "android.webkit.webview": "web",
    "android.widget.listview": "list",
    "android.widget.gridview": "list",
    "androidx.recyclerview.widget.recyclerview": "list",
    "android.widget.scrollview": "scrollarea",
    "android.widget.horizontalscrollview": "scrollarea",
    "android.widget.nestedscrollview": "scrollarea",
    "androidx.core.widget.nestedscrollview": "scrollarea",
    "android.widget.spinner": "popup",
    "android.widget.tabwidget": "tab",
    "com.google.android.material.tabs.tablayout": "tab",
    "android.widget.tabhost": "tab",
    "android.view.viewgroup": "group",
    "android.widget.framelayout": "group",
    "android.widget.linearlayout": "group",
    "android.widget.relativelayout": "group",
    "android.widget.absolutelayout": "group",
    "androidx.constraintlayout.widget.constraintlayout": "group",
    "android.view.view": "unknown",
}

_ACTION = {
    "click": "press",
    "press": "press",
    "tap": "press",
    "long click": "show_menu",
    "longclick": "show_menu",
    "long-click": "show_menu",
}


def normalize_role(class_name: str | None) -> str:
    if not class_name:
        return "unknown"
    key = class_name.strip().lower()
    if key in _CLASS:
        return _CLASS[key]
    short = key.rsplit(".", 1)[-1]
    for full, role in _CLASS.items():
        if full.endswith("." + short) or full.rsplit(".", 1)[-1] == short:
            return role
    if "edit" in short or "textfield" in short:
        return "textfield"
    if "button" in short:
        return "button"
    if "check" in short:
        return "checkbox"
    if "radio" in short:
        return "radio"
    if "switch" in short:
        return "checkbox"
    if "seek" in short or "slider" in short:
        return "slider"
    if "web" in short:
        return "web"
    if "list" in short or "recycler" in short:
        return "list"
    if "scroll" in short:
        return "scrollarea"
    if "tab" in short:
        return "tab"
    if "image" in short:
        return "image"
    if "text" in short:
        return "text"
    if "layout" in short or "group" in short:
        return "group"
    return "unknown"


def normalize_action(raw: str | None) -> str:
    if not raw:
        return "press"
    return _ACTION.get(raw.strip().lower(), raw.strip().lower().replace(" ", "_"))


INTERACTIVE = frozenset(
    {
        "button",
        "textfield",
        "textarea",
        "checkbox",
        "radio",
        "slider",
        "link",
        "menuitem",
        "tab",
        "popup",
        "cell",
    }
)
