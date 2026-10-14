import Foundation
import CoreVideo
import ApplicationServices
import AppKit

final class SceneEngine: CaptureDelegate {
    static let shared = SceneEngine()

    private let queue = DispatchQueue(label: "dev.sceneuse.scene", qos: .userInitiated)
    private let capture = CaptureSession()

    private var seq = 0
    private var subscribers: [ObjectIdentifier: (SceneMessage) -> Void] = [:]
    private var tilesEnabledDefault = true
    private var tilesByClient: [ObjectIdentifier: Bool] = [:]

    private var lastWindows: [WindowInfo] = []
    private var lastNodes: [NodeInfo] = []
    private var lastDisplays: [DisplayInfo] = []
    private var lastFocus = FocusInfo()
    private var lastObserve = FocusInfo()
    private var lastWindowSig = ""
    private var lastNodeSig = ""
    private var lastAXTime: TimeInterval = 0
    private var lastEmit: TimeInterval = 0
    private var pendingDirty: [CGRect] = []
    private var lastBuffer: CVPixelBuffer?
    private var lastScale: CGFloat = 2
    private var nodeElements: [String: AXUIElement] = [:]
    private var windowById: [String: WindowInfo] = [:]
    private var axRawCount = 0
    private var forceFull = true
    /// Compositor window id whose AX tree is walked. Nil = OS frontmost.
    private var observeWindowId: String?

    private let minEmitInterval: TimeInterval = 0.12
    private let axInterval: TimeInterval = 0.25

    var elementMap: [String: AXUIElement] {
        queue.sync { nodeElements }
    }

    var windows: [WindowInfo] {
        queue.sync { lastWindows }
    }

    private init() {
        capture.delegate = self
    }

    func startCaptureIfNeeded() {
        queue.async { [weak self] in
            guard let self else { return }
            if !self.capture.isRunning {
                self.forceFull = true
                self.capture.start()
            }
            // Always emit a scene even before frames (windows + AX).
            self.emit(dirtyPixels: [], buffer: nil, scale: self.lastScale, force: true)
        }
    }

    func stopCaptureIfIdle() {
        queue.async { [weak self] in
            guard let self, self.subscribers.isEmpty else { return }
            self.capture.stop()
        }
    }

    func subscribe(id: ObjectIdentifier, tiles: Bool, window: String? = nil, app: String? = nil, handler: @escaping (SceneMessage) -> Void) {
        queue.async { [weak self] in
            guard let self else { return }
            self.subscribers[id] = handler
            self.tilesByClient[id] = tiles
            if window != nil || (app != nil && !(app ?? "").isEmpty) {
                self.applyObserveLocked(window: window, app: app)
            }
            self.forceFull = true
            if !self.capture.isRunning {
                self.capture.start()
            }
            self.emit(dirtyPixels: [], buffer: nil, scale: self.lastScale, force: true)
        }
    }

    /// Set observation handle. Empty window+app clears to frontmost. Returns the resolved window.
    @discardableResult
    func setObserve(window: String?, app: String?) throws -> WindowInfo? {
        try queue.sync { [weak self] () -> WindowInfo? in
            guard let self else { return nil }
            let clear = (window == nil || window?.isEmpty == true)
                && (app == nil || app?.isEmpty == true)
            let resolved: WindowInfo?
            if clear {
                self.observeWindowId = nil
                resolved = nil
            } else {
                let wins = self.lastWindows.isEmpty ? WindowSnap.list() : self.lastWindows
                guard let hit = WindowSnap.resolve(windows: wins, window: window, app: app) else {
                    throw InputError.notFound("no window matching window=\(window ?? "") app=\(app ?? "")")
                }
                self.observeWindowId = hit.id
                resolved = hit
            }
            self.forceFull = true
            self.lastAXTime = 0
            // Emit async so target/raise RPCs never block on AX main.sync.
            let buf = self.lastBuffer
            let scale = self.lastScale
            self.queue.async { [weak self] in
                self?.emit(dirtyPixels: [], buffer: buf, scale: scale, force: true)
            }
            return resolved
        }
    }

    /// Caller must be on `queue`.
    @discardableResult
    private func applyObserveLocked(window: String?, app: String?) -> WindowInfo? {
        let wins = lastWindows.isEmpty ? WindowSnap.list() : lastWindows
        if (window == nil || window?.isEmpty == true) && (app == nil || app?.isEmpty == true) {
            observeWindowId = nil
            return nil
        }
        guard let hit = WindowSnap.resolve(windows: wins, window: window, app: app) else {
            return nil
        }
        observeWindowId = hit.id
        return hit
    }

    func unsubscribe(id: ObjectIdentifier) {
        queue.async { [weak self] in
            guard let self else { return }
            self.subscribers.removeValue(forKey: id)
            self.tilesByClient.removeValue(forKey: id)
            if self.subscribers.isEmpty {
                self.capture.stop()
            }
        }
    }

    func window(id: String) -> WindowInfo? {
        queue.sync { windowById[id] }
    }

    /// Re-walk AX and emit a full scene so the next client read sees the act.
    func refreshAfterAct() {
        queue.sync { [weak self] in
            guard let self else { return }
            self.forceFull = true
            self.lastAXTime = 0
            self.emit(dirtyPixels: [], buffer: self.lastBuffer, scale: self.lastScale, force: true)
        }
    }

    func captureDidProduce(dirtyPixels: [CGRect], scale: CGFloat, buffer: CVPixelBuffer?, contentRect: CGRect) {
        queue.async { [weak self] in
            guard let self else { return }
            self.lastScale = scale
            self.lastBuffer = buffer
            self.pendingDirty.append(contentsOf: dirtyPixels)
            let now = Date().timeIntervalSince1970
            if now - self.lastEmit < self.minEmitInterval, !self.forceFull {
                return
            }
            let dirty = self.pendingDirty
            self.pendingDirty.removeAll()
            self.emit(dirtyPixels: dirty, buffer: buffer, scale: scale, force: false)
        }
    }

    func captureDidFail(_ error: Error) {
        fputs("sceneused capture: \(error.localizedDescription)\n", stderr)
        queue.async { [weak self] in
            self?.emit(dirtyPixels: [], buffer: nil, scale: self?.lastScale ?? 2, force: true)
        }
    }

    private func emit(dirtyPixels: [CGRect], buffer: CVPixelBuffer?, scale: CGFloat, force: Bool) {
        let perms = PermissionProbe.current()
        let displays = Displays.list()
        let front = NSWorkspace.shared.frontmostApplication
        var windows = WindowSnap.list()
        let preferredPID = WindowSnap.chooseFocusPID(windows: windows, front: front)
        WindowSnap.applyFocus(&windows, pid: preferredPID, windowNumber: nil)
        let observeWin = observeWindowId.flatMap { id in windows.first(where: { $0.id == id }) }

        let ax: AXSnap.Result
        let now = Date().timeIntervalSince1970
        if now - lastAXTime >= axInterval || force || forceFull {
            ax = AXSnap.snapshot(windows: windows, previous: lastNodes, observe: observeWin)
            lastAXTime = now
        } else {
            ax = AXSnap.Result(
                nodes: lastNodes,
                rawCount: axRawCount,
                elements: nodeElements,
                focusPID: lastObserve.pid.map { pid_t($0) },
                focusWindowNumber: nil,
                focusAppName: lastObserve.app
            )
        }

        // OS frontmost stays on `focused`; observation handle is separate.
        WindowSnap.applyFocus(&windows, pid: preferredPID, windowNumber: nil)
        let focus = FocusInfo(
            window: windows.first(where: \.focused)?.id,
            app: windows.first(where: \.focused)?.app ?? front?.localizedName,
            pid: windows.first(where: \.focused)?.pid ?? front.map { Int($0.processIdentifier) }
        )
        let observe = FocusInfo(
            window: observeWin?.id ?? ax.focusWindowNumber.map { "w:\($0)" } ?? focus.window,
            app: observeWin?.app ?? ax.focusAppName ?? focus.app,
            pid: observeWin?.pid ?? ax.focusPID.map { Int($0) } ?? focus.pid
        )

        let displayLogical = displays.first?.bounds ?? Rect(x: 0, y: 0, w: 1470, h: 956)
        let tilesWanted = tilesByClient.values.contains(true) || (tilesByClient.isEmpty && tilesEnabledDefault)

        let packed: (logicalDamage: [Rect], tiles: [TileInfo])
        if let buffer, perms.screenRecording {
            packed = Tiles.encode(
                buffer: buffer,
                dirtyPixels: dirtyPixels,
                scale: scale,
                displayLogical: displayLogical,
                nodes: ax.nodes,
                enabled: tilesWanted
            )
        } else {
            packed = (dirtyPixels.map { Coord.pixelRectToLogical($0, scale: scale, displayLogical: displayLogical) }.filter { $0.w >= 1 && $0.h >= 1 }, [])
        }

        let cursor = CursorSnap.current()
        var nodes = ax.nodes
        Salience.apply(
            &nodes,
            cursor: cursor,
            damage: packed.logicalDamage,
            displayArea: displayLogical.area
        )

        let winSig = windowSignature(windows)
        let nodeSig = nodeSignature(nodes)
        let windowsChanged = winSig != lastWindowSig
        let nodesChanged = nodeSig != lastNodeSig
        let displaysChanged = displays != lastDisplays
        let focusChanged = focus != lastFocus
        let observeChanged = observe != lastObserve
        let damageArea = packed.logicalDamage.reduce(0.0) { $0 + $1.area }
        let hugeDamage = displayLogical.area > 0 && damageArea >= displayLogical.area * 0.40
        let kind: String
        if forceFull || force || focusChanged || observeChanged || hugeDamage || lastWindows.isEmpty {
            kind = "full"
        } else {
            kind = "delta"
        }

        seq += 1
        lastEmit = now
        lastWindows = windows
        lastNodes = nodes
        lastDisplays = displays
        lastFocus = focus
        lastObserve = observe
        lastWindowSig = winSig
        lastNodeSig = nodeSig
        nodeElements = ax.elements
        axRawCount = ax.rawCount
        windowById = Dictionary(uniqueKeysWithValues: windows.map { ($0.id, $0) })
        forceFull = false

        var scene = SceneMessage(
            seq: seq,
            t: now,
            kind: kind,
            permissions: perms,
            displays: nil,
            windows: nil,
            cursor: cursor,
            focus: focus,
            observe: observe,
            damage: packed.logicalDamage,
            nodes: nil,
            tiles: packed.tiles,
            nodeCount: nil
        )
        if kind == "full" || displaysChanged {
            scene.displays = displays
        }
        if kind == "full" || windowsChanged {
            scene.windows = windows
        }
        if kind == "full" || nodesChanged {
            scene.nodes = nodes
            scene.nodeCount = ax.rawCount
        }

        let message = scene
        let handlers = subscribers.values
        DispatchQueue.global(qos: .userInitiated).async {
            for send in handlers { send(message) }
        }
    }
}
