import ApplicationServices
import AppKit
import CoreGraphics
import Foundation

enum WindowSnap {
    /// Processes that steal "frontmost" without owning a layer-0 window.
    private static let ignoreFrontmostBundles: Set<String> = [
        "com.apple.universalcontrol",
        "com.apple.controlcenter",
        "com.apple.notificationcenterui",
        "com.apple.UserNotificationCenter",
        "com.apple.loginwindow",
        "com.apple.WindowManager",
        "com.apple.dock",
        "com.apple.Spotlight",
    ]

    static func chooseFocusPID(windows: [WindowInfo], front: NSRunningApplication?) -> pid_t? {
        if let front, !shouldIgnoreFrontmost(front),
           windows.contains(where: { $0.pid == Int(front.processIdentifier) }) {
            return front.processIdentifier
        }
        return windows.first.map { pid_t($0.pid) }
    }

    static func shouldIgnoreFrontmost(_ app: NSRunningApplication) -> Bool {
        if let bundle = app.bundleIdentifier, ignoreFrontmostBundles.contains(bundle) {
            return true
        }
        let name = (app.localizedName ?? "").lowercased()
        return name == "universal control" || name == "control center"
    }

    static func cgID(from windowId: String) -> UInt32? {
        guard windowId.hasPrefix("w:") else { return nil }
        return UInt32(windowId.dropFirst(2))
    }

    /// Pick a window to observe without changing OS frontmost.
    static func resolve(windows: [WindowInfo], window: String?, app: String?) -> WindowInfo? {
        if let window, let hit = windows.first(where: { $0.id == window }) {
            return hit
        }
        if let app, !app.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let needle = app.lowercased()
            let hits = windows.filter { $0.onScreen && $0.app.lowercased().contains(needle) }
            return hits.sorted { a, b in
                let ao = a.occluded ? 1 : 0
                let bo = b.occluded ? 1 : 0
                if ao != bo { return ao < bo }
                return a.z < b.z
            }.first
        }
        return nil
    }

    static func applyFocus(_ windows: inout [WindowInfo], pid: pid_t?, windowNumber: UInt32?) {
        for i in windows.indices { windows[i].focused = false }
        if let windowNumber, let idx = windows.firstIndex(where: { $0.id == "w:\(windowNumber)" }) {
            windows[idx].focused = true
            return
        }
        if let pid, let idx = windows.firstIndex(where: { $0.pid == Int(pid) }) {
            windows[idx].focused = true
        }
    }

    static func list(focusPID: pid_t? = nil, focusWindowNumber: UInt32? = nil) -> [WindowInfo] {
        let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
        guard let raw = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
            return []
        }

        var collected: [(layer: Int, info: WindowInfo)] = []
        for entry in raw {
            let layer = entry[kCGWindowLayer as String] as? Int ?? 0
            if layer != 0 { continue }
            let alpha = entry[kCGWindowAlpha as String] as? Double ?? 1
            if alpha < 0.02 { continue }
            guard let number = entry[kCGWindowNumber as String] as? UInt32 else { continue }
            let pid = entry[kCGWindowOwnerPID as String] as? pid_t ?? 0
            let app = entry[kCGWindowOwnerName as String] as? String ?? ""
            let title = entry[kCGWindowName as String] as? String
            guard let boundsDict = entry[kCGWindowBounds as String] as? [String: Any],
                  let x = boundsDict["X"] as? NSNumber,
                  let y = boundsDict["Y"] as? NSNumber,
                  let w = boundsDict["Width"] as? NSNumber,
                  let h = boundsDict["Height"] as? NSNumber else { continue }
            if w.doubleValue < 2 || h.doubleValue < 2 { continue }

            let bounds = Rect(x: x.doubleValue, y: y.doubleValue, w: w.doubleValue, h: h.doubleValue)
            let running = NSRunningApplication(processIdentifier: pid)
            let focused: Bool
            if let focusWindowNumber {
                focused = number == focusWindowNumber
            } else if let focusPID {
                focused = pid == focusPID && collected.filter({ $0.info.pid == pid }).isEmpty
            } else {
                focused = false
            }

            collected.append((
                layer: layer,
                info: WindowInfo(
                    id: "w:\(number)",
                    pid: Int(pid),
                    app: app,
                    bundle: running?.bundleIdentifier,
                    title: title,
                    bounds: bounds,
                    z: 0,
                    focused: focused,
                    onScreen: entry[kCGWindowIsOnscreen as String] as? Bool ?? true,
                    occluded: false
                )
            ))
        }

        var windows = collected.map(\.info)
        for i in windows.indices {
            windows[i].z = i
        }
        for i in windows.indices.reversed() {
            let b = windows[i].bounds.cg
            let covered = windows[..<i].contains { front in
                front.bounds.cg.contains(b) || front.bounds.cg.insetBy(dx: -1, dy: -1).contains(b)
            }
            windows[i].occluded = covered
        }
        if !windows.contains(where: \.focused), let focusPID {
            if let idx = windows.firstIndex(where: { $0.pid == focusPID }) {
                windows[idx].focused = true
            }
        }
        return windows
    }
}

enum AXSnap {
    static let maxNodes = 200
    static let maxDepth = 12
    static let maxChildren = 40

    struct Result {
        var nodes: [NodeInfo]
        var rawCount: Int
        var elements: [String: AXUIElement]
        var focusPID: pid_t?
        var focusWindowNumber: UInt32?
        var focusAppName: String?
    }

    static func snapshot(windows: [WindowInfo], previous: [NodeInfo] = [], observe: WindowInfo? = nil) -> Result {
        if Thread.isMainThread {
            return snapshotOnMain(windows: windows, previous: previous, observe: observe)
        }
        var result: Result?
        DispatchQueue.main.sync {
            result = snapshotOnMain(windows: windows, previous: previous, observe: observe)
        }
        return result!
    }

    /// AX window for a compositor window id (`w:1234`), or nil.
    static func windowElement(pid: pid_t, windowId: String) -> AXUIElement? {
        let appEl = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(appEl, 1.0)
        return matchingWindow(in: appEl, windowId: windowId) ?? firstWindow(in: appEl)
    }

    private static func snapshotOnMain(windows: [WindowInfo], previous: [NodeInfo], observe: WindowInfo?) -> Result {
        guard AXIsProcessTrusted() else {
            return Result(nodes: [], rawCount: 0, elements: [:], focusPID: nil, focusWindowNumber: nil, focusAppName: nil)
        }

        let front = NSWorkspace.shared.frontmostApplication
        let pid: pid_t = {
            if let observe { return pid_t(observe.pid) }
            if let w = windows.first(where: \.focused) { return pid_t(w.pid) }
            if let chosen = WindowSnap.chooseFocusPID(windows: windows, front: front) {
                return chosen
            }
            return front.flatMap { WindowSnap.shouldIgnoreFrontmost($0) ? nil : $0.processIdentifier } ?? 0
        }()
        guard pid != 0 else {
            return Result(nodes: [], rawCount: 0, elements: [:], focusPID: nil, focusWindowNumber: nil, focusAppName: nil)
        }

        let appEl = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(appEl, 1.0)

        let appName = observe?.app
            ?? windows.first(where: { $0.pid == Int(pid) })?.app
            ?? NSRunningApplication(processIdentifier: pid)?.localizedName
            ?? front?.localizedName

        var focusedWin: AXUIElement?
        if let observe {
            focusedWin = matchingWindow(in: appEl, windowId: observe.id) ?? firstWindow(in: appEl)
        } else {
            var focusedWinRef: AnyObject?
            _ = AXUIElementCopyAttributeValue(appEl, kAXFocusedWindowAttribute as CFString, &focusedWinRef)
            focusedWin = focusedWinRef.map { $0 as! AXUIElement }
            if focusedWin == nil {
                focusedWin = firstWindow(in: appEl)
            }
        }

        var windowNumber: UInt32?
        if let focusedWin {
            windowNumber = cgWindowNumber(focusedWin)
        }

        let windowId: String = {
            if let observe { return observe.id }
            if let n = windowNumber { return "w:\(n)" }
            return windows.first(where: { $0.pid == Int(pid) && $0.focused })?.id
                ?? windows.first(where: { $0.pid == Int(pid) })?.id
                ?? "w:unknown"
        }()

        var nodes: [NodeInfo] = []
        var elements: [String: AXUIElement] = [:]
        var raw = 0
        var nextId = 1

        func emit(_ el: AXUIElement, parent: String?, depth: Int) {
            raw += 1
            if nodes.count >= maxNodes || depth > maxDepth { return }

            let roleRaw = stringAttr(el, kAXRoleAttribute) ?? "AXUnknown"
            let role = normalizeRole(roleRaw)
            let name = bestName(el)
            let value = stringify(valueAttr(el))
            let actions = actionNames(el)
            let states = stateList(el)
            let bounds = frameOf(el)

            let interactive = isInteractive(role)
            let named = !(name ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            let focusedNode = states.contains("focused")
            let keepField = role == "textfield" || role == "textarea"
            let keepChrome = role == "window" || role == "web" || role == "sheet" || role == "dialog" || depth == 0
            let keep = named || keepField || keepChrome || (interactive && focusedNode)

            var id: String?
            if keep {
                id = "n\(nextId)"
                nextId += 1
                nodes.append(NodeInfo(
                    id: id!,
                    window: windowId,
                    role: role,
                    name: name,
                    value: value,
                    states: states,
                    actions: actions,
                    bounds: bounds,
                    parent: parent
                ))
                elements[id!] = el
            }

            guard depth < maxDepth, nodes.count < maxNodes else { return }
            let kids = childrenOf(el)
            for child in kids.prefix(maxChildren) {
                emit(child, parent: id ?? parent, depth: depth + 1)
            }
        }

        if let focusedWin {
            emit(windowRoot(from: focusedWin), parent: nil, depth: 0)
        } else {
            emit(appEl, parent: nil, depth: 0)
        }

        stabilize(nodes: &nodes, elements: &elements, previous: previous)

        return Result(
            nodes: nodes,
            rawCount: raw,
            elements: elements,
            focusPID: pid,
            focusWindowNumber: windowNumber,
            focusAppName: appName
        )
    }

    static func isInteractive(_ role: String) -> Bool {
        ["button", "textfield", "textarea", "checkbox", "radio", "slider", "link", "menuitem", "tab", "popup", "cell"].contains(role)
    }

    static func usable(_ node: NodeInfo) -> Bool {
        if isInteractive(node.role) { return true }
        if let n = node.name, !n.isEmpty { return true }
        return false
    }

    private static func bestName(_ el: AXUIElement) -> String? {
        let attrs = [
            kAXTitleAttribute as String,
            kAXDescriptionAttribute as String,
            kAXPlaceholderValueAttribute as String,
            kAXHelpAttribute as String,
        ]
        for attr in attrs {
            if let s = nonempty(stringAttr(el, attr)) { return s }
        }
        if let s = nonempty(stringify(valueAttr(el))) {
            let role = stringAttr(el, kAXRoleAttribute) ?? ""
            if role == "AXStaticText" || role == "AXHeading" { return s }
        }
        for child in childrenOf(el).prefix(8) {
            let role = stringAttr(child, kAXRoleAttribute) ?? ""
            if role == "AXStaticText" || role == "AXHeading" || role == "AXLink" {
                if let s = nonempty(stringAttr(child, kAXTitleAttribute as String))
                    ?? nonempty(stringify(valueAttr(child))) {
                    return s
                }
            }
        }
        return nil
    }

    private static func nonempty(_ s: String?) -> String? {
        guard let s else { return nil }
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? nil : t
    }

    private static func stabilize(
        nodes: inout [NodeInfo],
        elements: inout [String: AXUIElement],
        previous: [NodeInfo]
    ) {
        func fingerprint(_ n: NodeInfo) -> String {
            let x = n.bounds.map { Int(($0.x / 8.0).rounded() * 8) } ?? 0
            let y = n.bounds.map { Int(($0.y / 8.0).rounded() * 8) } ?? 0
            return "\(n.role)|\(n.name ?? "")|\(n.window)|\(x)|\(y)"
        }

        var buckets: [String: [String]] = [:]
        for n in previous {
            buckets[fingerprint(n), default: []].append(n.id)
        }

        var used = Set<String>()
        var mapping: [String: String] = [:]
        for n in nodes {
            let key = fingerprint(n)
            if var ids = buckets[key], let reuse = ids.first, !used.contains(reuse) {
                ids.removeFirst()
                buckets[key] = ids
                mapping[n.id] = reuse
                used.insert(reuse)
            }
        }

        var next = 1
        func fresh() -> String {
            while used.contains("n\(next)") { next += 1 }
            let id = "n\(next)"
            used.insert(id)
            next += 1
            return id
        }

        for i in nodes.indices {
            let old = nodes[i].id
            let newId = mapping[old] ?? fresh()
            mapping[old] = newId
            nodes[i].id = newId
        }
        for i in nodes.indices {
            if let p = nodes[i].parent {
                nodes[i].parent = mapping[p]
            }
        }
        var nextEls: [String: AXUIElement] = [:]
        for (old, el) in elements {
            if let nid = mapping[old] {
                nextEls[nid] = el
            }
        }
        elements = nextEls
    }

    private static func parentOf(_ el: AXUIElement) -> AXUIElement? {
        var ref: AnyObject?
        guard AXUIElementCopyAttributeValue(el, kAXParentAttribute as CFString, &ref) == .success else {
            return nil
        }
        return ref.map { $0 as! AXUIElement }
    }

    private static func firstWindow(in appEl: AXUIElement) -> AXUIElement? {
        var winsRef: AnyObject?
        guard AXUIElementCopyAttributeValue(appEl, kAXWindowsAttribute as CFString, &winsRef) == .success,
              let wins = winsRef as? [AXUIElement] else { return nil }
        return wins.first
    }

    private static func matchingWindow(in appEl: AXUIElement, windowId: String) -> AXUIElement? {
        guard let want = WindowSnap.cgID(from: windowId) else { return nil }
        var winsRef: AnyObject?
        guard AXUIElementCopyAttributeValue(appEl, kAXWindowsAttribute as CFString, &winsRef) == .success,
              let wins = winsRef as? [AXUIElement] else { return nil }
        for win in wins {
            if cgWindowNumber(win) == want { return win }
        }
        return nil
    }

    private static func windowRoot(from focused: AXUIElement) -> AXUIElement {
        var el = focused
        for _ in 0..<10 {
            let role = normalizeRole(stringAttr(el, kAXRoleAttribute) ?? "")
            if role == "window" { return el }
            guard let parent = parentOf(el) else { return el }
            el = parent
        }
        return focused
    }

    private static func childrenOf(_ el: AXUIElement) -> [AXUIElement] {
        var ref: AnyObject?
        guard AXUIElementCopyAttributeValue(el, kAXChildrenAttribute as CFString, &ref) == .success,
              let arr = ref as? [AXUIElement] else { return [] }
        return arr
    }

    private static func stringAttr(_ el: AXUIElement, _ attr: String) -> String? {
        var ref: AnyObject?
        guard AXUIElementCopyAttributeValue(el, attr as CFString, &ref) == .success else { return nil }
        return ref as? String
    }

    private static func valueAttr(_ el: AXUIElement) -> AnyObject? {
        var ref: AnyObject?
        guard AXUIElementCopyAttributeValue(el, kAXValueAttribute as CFString, &ref) == .success else { return nil }
        return ref
    }

    private static func stringify(_ value: AnyObject?) -> String? {
        guard let value else { return nil }
        if let s = value as? String { return s }
        if let n = value as? NSNumber { return n.stringValue }
        if let b = value as? Bool { return b ? "true" : "false" }
        return nil
    }

    private static func actionNames(_ el: AXUIElement) -> [String] {
        var names: CFArray?
        guard AXUIElementCopyActionNames(el, &names) == .success, let names else { return [] }
        let arr = names as NSArray as? [String] ?? []
        return arr.map(normalizeAction).filter { !$0.isEmpty }
    }

    private static func stateList(_ el: AXUIElement) -> [String] {
        var states: [String] = []
        if boolAttr(el, kAXEnabledAttribute, default: true) { states.append("enabled") } else { states.append("disabled") }
        if boolAttr(el, kAXFocusedAttribute, default: false) { states.append("focused") }
        if let v = valueAttr(el) as? NSNumber, v.boolValue, (stringAttr(el, kAXRoleAttribute) ?? "").contains("Check") {
            states.append("checked")
        }
        return states
    }

    private static func boolAttr(_ el: AXUIElement, _ attr: String, default def: Bool) -> Bool {
        var ref: AnyObject?
        guard AXUIElementCopyAttributeValue(el, attr as CFString, &ref) == .success else { return def }
        if let b = ref as? Bool { return b }
        if let n = ref as? NSNumber { return n.boolValue }
        return def
    }

    private static func frameOf(_ el: AXUIElement) -> Rect? {
        var posRef: AnyObject?
        var sizeRef: AnyObject?
        guard AXUIElementCopyAttributeValue(el, kAXPositionAttribute as CFString, &posRef) == .success,
              AXUIElementCopyAttributeValue(el, kAXSizeAttribute as CFString, &sizeRef) == .success else { return nil }
        var point = CGPoint.zero
        var size = CGSize.zero
        guard let posVal = posRef, CFGetTypeID(posVal) == AXValueGetTypeID(),
              let sizeVal = sizeRef, CFGetTypeID(sizeVal) == AXValueGetTypeID() else { return nil }
        AXValueGetValue(posVal as! AXValue, .cgPoint, &point)
        AXValueGetValue(sizeVal as! AXValue, .cgSize, &size)
        if size.width <= 0 || size.height <= 0 { return nil }
        return Rect(x: point.x, y: point.y, w: size.width, h: size.height)
    }

    private static func cgWindowNumber(_ el: AXUIElement) -> UInt32? {
        // Private-ish but widely used: _AXUIElementGetWindow
        typealias Fn = @convention(c) (AXUIElement, UnsafeMutablePointer<CGWindowID>) -> AXError
        guard let handle = dlopen("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices", RTLD_LAZY) else {
            return nil
        }
        defer { dlclose(handle) }
        guard let sym = dlsym(handle, "_AXUIElementGetWindow") else { return nil }
        let fn = unsafeBitCast(sym, to: Fn.self)
        var id: CGWindowID = 0
        return fn(el, &id) == .success ? id : nil
    }

    private static func normalizeRole(_ raw: String) -> String {
        switch raw {
        case "AXButton", "AXPopUpButton": return raw == "AXPopUpButton" ? "popup" : "button"
        case "AXTextField": return "textfield"
        case "AXTextArea": return "textarea"
        case "AXCheckBox": return "checkbox"
        case "AXRadioButton": return "radio"
        case "AXMenuItem": return "menuitem"
        case "AXLink": return "link"
        case "AXSlider": return "slider"
        case "AXTabGroup": return "tab"
        case "AXStaticText": return "text"
        case "AXImage": return "image"
        case "AXHeading": return "heading"
        case "AXCell": return "cell"
        case "AXRow": return "row"
        case "AXList": return "list"
        case "AXOutline": return "outline"
        case "AXWebArea": return "web"
        case "AXWindow": return "window"
        case "AXSheet": return "sheet"
        case "AXDialog": return "dialog"
        case "AXScrollArea": return "scrollarea"
        case "AXGroup": return "group"
        case "AXComboBox": return "popup"
        default:
            let trimmed = raw.hasPrefix("AX") ? String(raw.dropFirst(2)) : raw
            return trimmed.lowercased()
        }
    }

    private static func normalizeAction(_ raw: String) -> String {
        switch raw {
        case "AXPress": return "press"
        case "AXConfirm": return "confirm"
        case "AXCancel": return "cancel"
        case "AXShowMenu": return "show_menu"
        case "AXPick": return "pick"
        case "AXIncrement": return "increment"
        case "AXDecrement": return "decrement"
        default:
            let t = raw.hasPrefix("AX") ? String(raw.dropFirst(2)) : raw
            return t.lowercased().replacingOccurrences(of: " ", with: "_")
        }
    }
}
