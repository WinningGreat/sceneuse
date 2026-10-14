"""Map iOS AX roles to sceneuse tokens."""

from __future__ import annotations

_ROLE = {
    "axbutton": "button",
    "button": "button",
    "axtextfield": "textfield",
    "textfield": "textfield",
    "axtextarea": "textarea",
    "textview": "textarea",
    "axstatictext": "text",
    "statictext": "text",
    "text": "text",
    "axlink": "link",
    "link": "link",
    "aximage": "image",
    "image": "image",
    "axcheckbox": "checkbox",
    "checkbox": "checkbox",
    "axradiobutton": "radio",
    "radio": "radio",
    "axslider": "slider",
    "slider": "slider",
    "axswitch": "checkbox",
    "switch": "checkbox",
    "axcell": "cell",
    "cell": "cell",
    "axmenuitem": "menuitem",
    "menuitem": "menuitem",
    "axtab": "tab",
    "tab": "tab",
    "axpopover": "popup",
    "axpopupbutton": "popup",
    "popup": "popup",
    "axheading": "heading",
    "heading": "heading",
    "axwebarea": "web",
    "web": "web",
    "axlist": "list",
    "list": "list",
    "axtable": "list",
    "axrow": "row",
    "row": "row",
    "axoutline": "outline",
    "outline": "outline",
    "axscrollarea": "scrollarea",
    "scrollarea": "scrollarea",
    "axwindow": "window",
    "window": "window",
    "axapplication": "window",
    "application": "window",
    "axgroup": "group",
    "group": "group",
    "axsheet": "sheet",
    "sheet": "sheet",
    "axdialog": "dialog",
    "dialog": "dialog",
    "axtoolbar": "group",
    "axnavigationbar": "group",
    "axkeyboard": "group",
    "keyboard": "group",
}

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


def normalize_role(raw: str | None) -> str:
    if not raw:
        return "unknown"
    key = raw.strip().lower().replace("-", "").replace(" ", "").replace("_", "")
    return _ROLE.get(key, "unknown" if key.startswith("ax") else key)
