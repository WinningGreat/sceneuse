import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

enum Coord {
    static var mainDisplayBounds: CGRect {
        CGDisplayBounds(CGMainDisplayID())
    }

    static var mainHeight: CGFloat {
        mainDisplayBounds.height
    }

    /// Cocoa (bottom-left) → logical top-left of the main display.
    static func cocoaPointToLogical(_ p: CGPoint) -> CGPoint {
        CGPoint(x: p.x, y: mainHeight - p.y)
    }

    static func cocoaRectToLogical(_ r: CGRect) -> Rect {
        Rect(
            x: r.origin.x,
            y: Double(mainHeight - r.origin.y - r.height),
            w: r.width,
            h: r.height
        )
    }

    /// Logical top-left point is what CGEvent / Quartz HID uses (origin upper-left of main display).
    static func logicalPoint(_ x: Double, _ y: Double) -> CGPoint {
        CGPoint(x: x, y: y)
    }

    static func pixelRectToLogical(_ r: CGRect, scale: CGFloat, displayLogical: Rect) -> Rect {
        Rect(
            x: displayLogical.x + Double(r.origin.x / scale),
            y: displayLogical.y + Double(r.origin.y / scale),
            w: Double(r.width / scale),
            h: Double(r.height / scale)
        )
    }
}

enum PermissionProbe {
    static func current() -> Permissions {
        Permissions(
            screenRecording: CGPreflightScreenCaptureAccess(),
            accessibility: AXIsProcessTrusted()
        )
    }

    /// Extra fields for `status` — helps debug TCC after ad-hoc rebuilds.
    static func statusExtras() -> [String: String] {
        var out: [String: String] = [
            "pid": String(ProcessInfo.processInfo.processIdentifier),
        ]
        out["bundle_path"] = Bundle.main.bundlePath
        if let exe = Bundle.main.executablePath {
            out["executable"] = exe
        }
        if !CGPreflightScreenCaptureAccess() || !AXIsProcessTrusted() {
            out["tcc_hint"] =
                "Grant Screen Recording + Accessibility to sceneused in System Settings. "
                + "After make bundle, toggle off/on — ad-hoc rebuilds change the signature."
        }
        return out
    }

    static func promptIfNeeded() {
        if !CGPreflightScreenCaptureAccess() {
            _ = CGRequestScreenCaptureAccess()
        }
        if !AXIsProcessTrusted() {
            let opts = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
            _ = AXIsProcessTrustedWithOptions(opts)
        }
    }
}

enum Displays {
    static func list() -> [DisplayInfo] {
        NSScreen.screens.enumerated().map { idx, screen in
            let scale = screen.backingScaleFactor
            let cs = screen.colorSpace?.localizedName ?? screen.colorSpace?.description
            return DisplayInfo(
                id: "d\(idx)",
                bounds: Coord.cocoaRectToLogical(screen.frame),
                scale: Double(scale),
                colorSpace: cs?.lowercased().replacingOccurrences(of: " ", with: "_")
            )
        }
    }
}

enum CursorSnap {
    static func current() -> CursorInfo {
        let p = Coord.cocoaPointToLogical(NSEvent.mouseLocation)
        return CursorInfo(x: p.x, y: p.y, visible: true, shape: "arrow")
    }
}

func windowSignature(_ windows: [WindowInfo]) -> String {
    windows.map { "\($0.id)|\($0.pid)|\($0.title ?? "")|\($0.bounds.x)|\($0.bounds.y)|\($0.bounds.w)|\($0.bounds.h)|\($0.focused)" }
        .joined(separator: ";")
}

func nodeSignature(_ nodes: [NodeInfo]) -> String {
    nodes.map { "\($0.id)|\($0.role)|\($0.name ?? "")|\($0.value ?? "")|\($0.tags.joined(separator: ","))" }
        .joined(separator: ";")
}

enum Salience {
    /// AX marks whole outlines as focused (Notes). These are not the work surface.
    private static let weakFocus: Set<String> = [
        "cell", "row", "outline", "list", "table", "group", "splitgroup",
        "unknown", "window", "sheet", "dialog", "scrollarea", "web",
    ]

    static func apply(
        _ nodes: inout [NodeInfo],
        cursor: CursorInfo,
        damage: [Rect],
        displayArea: Double
    ) {
        let cursorPt = CGPoint(x: cursor.x, y: cursor.y)
        let smallDamage = damage.filter { displayArea <= 0 || $0.area < displayArea * 0.40 }
        var tagged: [String: [String]] = [:]

        func add(_ id: String, _ tag: String) {
            var cur = tagged[id] ?? []
            if !cur.contains(tag) { cur.append(tag) }
            tagged[id] = cur
        }

        var rankedFocus: [(Int, String)] = []
        for n in nodes {
            if n.states.contains("focused"), !weakFocus.contains(n.role) {
                let rank: Int
                switch n.role {
                case "textarea", "textfield": rank = 0
                case "button", "link", "checkbox", "radio", "popup", "menuitem": rank = 1
                default: rank = 2
                }
                rankedFocus.append((rank, n.id))
            }
            guard let b = n.bounds else { continue }
            if b.cg.contains(cursorPt) { add(n.id, "cursor") }
            if smallDamage.contains(where: { $0.intersection(b).area > 1 }) {
                if AXSnap.isInteractive(n.role) {
                    add(n.id, "changed")
                }
            }
        }
        rankedFocus.sort { $0.0 < $1.0 }
        for (_, id) in rankedFocus.prefix(3) {
            add(id, "focus")
        }

        let target =
            rankedFocus.first(where: { $0.0 == 0 })?.1
            ?? nodes.first(where: { (tagged[$0.id] ?? []).contains("cursor") && AXSnap.isInteractive($0.role) })?.id
            ?? sheetButton(nodes)
            ?? rankedFocus.first?.1
        if let target {
            add(target, "target")
        }

        for i in nodes.indices {
            nodes[i].tags = tagged[nodes[i].id] ?? []
        }
    }

    private static func sheetButton(_ nodes: [NodeInfo]) -> String? {
        let sheetish = nodes.contains { $0.role == "sheet" || $0.role == "dialog" }
        guard sheetish else { return nil }
        return nodes.first(where: {
            $0.role == "button" && ($0.actions.contains("press")) && !($0.name ?? "").isEmpty
        })?.id
    }
}
