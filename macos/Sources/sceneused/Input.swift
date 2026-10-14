import ApplicationServices
import CoreGraphics
import AppKit
import Foundation

enum InputError: Error, LocalizedError {
    case notFound(String)
    case permission
    case badRequest(String)

    var errorDescription: String? {
        switch self {
        case .notFound(let s): return s
        case .permission: return "Accessibility is not granted"
        case .badRequest(let s): return s
        }
    }
}

enum Input {
    static func invoke(node: String, action: String?, map: [String: AXUIElement]) throws {
        guard AXIsProcessTrusted() else { throw InputError.permission }
        guard let el = map[node] else { throw InputError.notFound("unknown node \(node)") }
        let raw = denormalizeAction(action ?? "press")
        let err = AXUIElementPerformAction(el, raw as CFString)
        if err != .success {
            throw InputError.badRequest("invoke failed (\(err.rawValue))")
        }
    }

    static func setValue(node: String, value: String, map: [String: AXUIElement]) throws {
        guard AXIsProcessTrusted() else { throw InputError.permission }
        guard let el = map[node] else { throw InputError.notFound("unknown node \(node)") }
        _ = AXUIElementPerformAction(el, kAXPressAction as CFString)
        AXUIElementSetAttributeValue(el, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        let err = AXUIElementSetAttributeValue(el, kAXValueAttribute as CFString, value as CFTypeRef)
        if err != .success {
            throw InputError.badRequest("set failed (\(err.rawValue))")
        }
    }

    /// Bring a window to the front. Required for `key` and some apps; `invoke`/`set` can target a background window.
    static func raise(window: WindowInfo) throws {
        guard AXIsProcessTrusted() else { throw InputError.permission }
        let pid = pid_t(window.pid)
        guard let app = NSRunningApplication(processIdentifier: pid) else {
            throw InputError.notFound("unknown process for \(window.id)")
        }
        let appEl = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(appEl, 1.0)
        // Order THIS window before activate, or activate() keys the app's previous main window.
        guard let el = AXSnap.windowElement(pid: pid, windowId: window.id) else {
            throw InputError.notFound("no AX window for \(window.id)")
        }
        _ = AXUIElementPerformAction(el, kAXRaiseAction as CFString)
        AXUIElementSetAttributeValue(el, kAXMainAttribute as CFString, kCFBooleanTrue)
        AXUIElementSetAttributeValue(appEl, kAXFocusedWindowAttribute as CFString, el)
        AXUIElementSetAttributeValue(el, kAXFocusedAttribute as CFString, kCFBooleanTrue)
        app.activate(options: [.activateIgnoringOtherApps])
        // activate can reshuffle; raise + main again on the same element.
        _ = AXUIElementPerformAction(el, kAXRaiseAction as CFString)
        AXUIElementSetAttributeValue(el, kAXMainAttribute as CFString, kCFBooleanTrue)
        AXUIElementSetAttributeValue(appEl, kAXFocusedWindowAttribute as CFString, el)
        // Title-bar click on THIS window's bounds (not the app's other windows).
        let barX = window.bounds.x + max(24, min(window.bounds.w * 0.5, window.bounds.w - 24))
        let barY = window.bounds.y + 12
        click(at: CGPoint(x: barX, y: barY), button: "left")
    }

    static func hit(window: WindowInfo, local: CGPoint, button: String) {
        let global = CGPoint(x: window.bounds.x + local.x, y: window.bounds.y + local.y)
        click(at: global, button: button)
    }

    static func key(_ tokens: [String]) throws {
        guard !tokens.isEmpty else { throw InputError.badRequest("keys is empty") }
        var flags: CGEventFlags = []
        var keys: [CGKeyCode] = []
        for tok in tokens {
            let t = tok.lowercased()
            switch t {
            case "cmd", "command", "meta": flags.insert(.maskCommand)
            case "shift": flags.insert(.maskShift)
            case "alt", "option": flags.insert(.maskAlternate)
            case "ctrl", "control": flags.insert(.maskControl)
            case "fn": flags.insert(.maskSecondaryFn)
            default:
                guard let code = keyCode(t) else {
                    throw InputError.badRequest("unknown key \(tok)")
                }
                keys.append(code)
            }
        }
        if keys.isEmpty {
            throw InputError.badRequest("no non-modifier key")
        }
        let src = CGEventSource(stateID: .hidSystemState)
        for code in keys {
            if let down = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: true) {
                down.flags = flags
                down.post(tap: .cghidEventTap)
            }
            if let up = CGEvent(keyboardEventSource: src, virtualKey: code, keyDown: false) {
                up.flags = flags
                up.post(tap: .cghidEventTap)
            }
        }
    }

    static func scroll(window: WindowInfo?, local: CGPoint?, delta: CGPoint) {
        let point = CursorSnap.current()
        var at = CGPoint(x: point.x, y: point.y)
        if let window, let local {
            at = CGPoint(x: window.bounds.x + local.x, y: window.bounds.y + local.y)
            move(to: at)
        }
        let src = CGEventSource(stateID: .hidSystemState)
        let ev = CGEvent(
            scrollWheelEvent2Source: src,
            units: .pixel,
            wheelCount: 2,
            wheel1: Int32(delta.y),
            wheel2: Int32(delta.x),
            wheel3: 0
        )
        ev?.post(tap: .cghidEventTap)
        _ = at
    }

    static func drag(window: WindowInfo, from: CGPoint, to: CGPoint) {
        let a = CGPoint(x: window.bounds.x + from.x, y: window.bounds.y + from.y)
        let b = CGPoint(x: window.bounds.x + to.x, y: window.bounds.y + to.y)
        let src = CGEventSource(stateID: .hidSystemState)
        CGEvent(mouseEventSource: src, mouseType: .leftMouseDown, mouseCursorPosition: a, mouseButton: .left)?
            .post(tap: .cghidEventTap)
        CGEvent(mouseEventSource: src, mouseType: .leftMouseDragged, mouseCursorPosition: b, mouseButton: .left)?
            .post(tap: .cghidEventTap)
        CGEvent(mouseEventSource: src, mouseType: .leftMouseUp, mouseCursorPosition: b, mouseButton: .left)?
            .post(tap: .cghidEventTap)
    }

    private static func click(at point: CGPoint, button: String) {
        let src = CGEventSource(stateID: .hidSystemState)
        switch button {
        case "right":
            CGEvent(mouseEventSource: src, mouseType: .rightMouseDown, mouseCursorPosition: point, mouseButton: .right)?
                .post(tap: .cghidEventTap)
            CGEvent(mouseEventSource: src, mouseType: .rightMouseUp, mouseCursorPosition: point, mouseButton: .right)?
                .post(tap: .cghidEventTap)
        case "double":
            guard let down = CGEvent(mouseEventSource: src, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left) else { return }
            down.setIntegerValueField(.mouseEventClickState, value: 1)
            down.post(tap: .cghidEventTap)
            let up = CGEvent(mouseEventSource: src, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)
            up?.setIntegerValueField(.mouseEventClickState, value: 1)
            up?.post(tap: .cghidEventTap)
            let down2 = CGEvent(mouseEventSource: src, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)
            down2?.setIntegerValueField(.mouseEventClickState, value: 2)
            down2?.post(tap: .cghidEventTap)
            let up2 = CGEvent(mouseEventSource: src, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)
            up2?.setIntegerValueField(.mouseEventClickState, value: 2)
            up2?.post(tap: .cghidEventTap)
        default:
            CGEvent(mouseEventSource: src, mouseType: .leftMouseDown, mouseCursorPosition: point, mouseButton: .left)?
                .post(tap: .cghidEventTap)
            CGEvent(mouseEventSource: src, mouseType: .leftMouseUp, mouseCursorPosition: point, mouseButton: .left)?
                .post(tap: .cghidEventTap)
        }
    }

    private static func move(to point: CGPoint) {
        let src = CGEventSource(stateID: .hidSystemState)
        CGEvent(mouseEventSource: src, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left)?
            .post(tap: .cghidEventTap)
    }

    private static func denormalizeAction(_ name: String) -> String {
        switch name {
        case "press": return kAXPressAction as String
        case "confirm": return kAXConfirmAction as String
        case "cancel": return kAXCancelAction as String
        case "show_menu": return kAXShowMenuAction as String
        case "increment": return kAXIncrementAction as String
        case "decrement": return kAXDecrementAction as String
        case "pick": return "AXPick"
        default: return name
        }
    }

    private static func keyCode(_ t: String) -> CGKeyCode? {
        if t.count == 1, let c = t.unicodeScalars.first {
            return letterCode[Character(c)]
        }
        switch t {
        case "return", "enter": return 36
        case "tab": return 48
        case "space": return 49
        case "escape", "esc": return 53
        case "delete", "forwarddelete": return 117
        case "backspace": return 51
        case "left": return 123
        case "right": return 124
        case "down": return 125
        case "up": return 126
        case "f1": return 122
        case "f2": return 120
        case "f3": return 99
        case "f4": return 118
        case "f5": return 96
        case "f6": return 97
        case "f7": return 98
        case "f8": return 100
        case "f9": return 101
        case "f10": return 109
        case "f11": return 103
        case "f12": return 111
        default: return nil
        }
    }
}

private let letterCode: [Character: CGKeyCode] = [
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
    "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19,
    "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28,
    "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "l": 37, "j": 38,
    "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47,
    "`": 50,
]
