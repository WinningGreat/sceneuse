import Darwin
import Foundation

final class Connection {
    let fd: Int32
    let token = ConnToken()
    var id: ObjectIdentifier { ObjectIdentifier(token) }
    private let lock = NSLock()
    var subscribed = false
    var tiles = true

    init(fd: Int32) {
        self.fd = fd
    }

    func send<T: Encodable>(_ value: T) {
        lock.lock()
        defer { lock.unlock() }
        do {
            var data = try jsonEncoder().encode(value)
            data.append(0x0a)
            data.withUnsafeBytes { raw in
                guard let base = raw.bindMemory(to: UInt8.self).baseAddress else { return }
                var off = 0
                while off < data.count {
                    let n = Darwin.write(fd, base + off, data.count - off)
                    if n <= 0 { break }
                    off += n
                }
            }
        } catch {
            fputs("sceneused encode: \(error)\n", stderr)
        }
    }

    func sendJSON(_ obj: [String: Any]) {
        lock.lock()
        defer { lock.unlock() }
        guard JSONSerialization.isValidJSONObject(obj),
              var data = try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys]) else { return }
        data.append(0x0a)
        data.withUnsafeBytes { raw in
            guard let base = raw.bindMemory(to: UInt8.self).baseAddress else { return }
            var off = 0
            while off < data.count {
                let n = Darwin.write(fd, base + off, data.count - off)
                if n <= 0 { break }
                off += n
            }
        }
    }

    func close() {
        Darwin.close(fd)
    }
}

/// Stable identity for a connection (file descriptor is not unique over process life).
final class ConnToken: NSObject {}

final class UnixServer {
    let path: String
    private var listenFD: Int32 = -1
    private var connections: [ObjectIdentifier: Connection] = [:]
    private let lock = NSLock()

    init(path: String) {
        self.path = path
    }

    func start() throws {
        unlink(path)
        let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno), userInfo: [NSLocalizedDescriptionKey: "socket() failed"]) }

        var yes: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, socklen_t(MemoryLayout<Int32>.size))
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &yes, socklen_t(MemoryLayout<Int32>.size))

        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let maxLen = MemoryLayout.size(ofValue: addr.sun_path)
        _ = path.withCString { src in
            withUnsafeMutablePointer(to: &addr.sun_path) { dst in
                dst.withMemoryRebound(to: CChar.self, capacity: maxLen) { dstp in
                    strncpy(dstp, src, maxLen - 1)
                }
            }
        }

        let bindOk = withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.stride))
            }
        }
        guard bindOk == 0 else {
            Darwin.close(fd)
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno), userInfo: [NSLocalizedDescriptionKey: "bind(\(path)) failed"])
        }
        guard listen(fd, 16) == 0 else {
            Darwin.close(fd)
            throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno), userInfo: [NSLocalizedDescriptionKey: "listen() failed"])
        }
        chmod(path, 0o600)
        listenFD = fd

        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            self?.acceptLoop()
        }
    }

    private func acceptLoop() {
        while true {
            var addr = sockaddr()
            var len: socklen_t = socklen_t(MemoryLayout<sockaddr>.size)
            let client = accept(listenFD, &addr, &len)
            if client < 0 {
                if errno == EINTR { continue }
                continue
            }
            var yes: Int32 = 1
            setsockopt(client, SOL_SOCKET, SO_NOSIGPIPE, &yes, socklen_t(MemoryLayout<Int32>.size))
            let conn = Connection(fd: client)
            lock.lock()
            connections[conn.id] = conn
            lock.unlock()
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                self?.readLoop(conn)
            }
        }
    }

    private func readLoop(_ conn: Connection) {
        var buffer = Data()
        var tmp = [UInt8](repeating: 0, count: 16 * 1024)
        defer {
            SceneEngine.shared.unsubscribe(id: conn.id)
            lock.lock()
            connections.removeValue(forKey: conn.id)
            lock.unlock()
            conn.close()
            SceneEngine.shared.stopCaptureIfIdle()
        }
        while true {
            let n = tmp.withUnsafeMutableBytes { Darwin.read(conn.fd, $0.baseAddress, $0.count) }
            if n <= 0 { return }
            buffer.append(contentsOf: tmp.prefix(n))
            while let nl = buffer.firstIndex(of: 0x0a) {
                let line = buffer.subdata(in: 0..<nl)
                buffer.removeSubrange(0...nl)
                if line.isEmpty { continue }
                handleLine(conn, line)
            }
        }
    }

    private func handleLine(_ conn: Connection, _ line: Data) {
        guard let obj = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
              let type = obj["type"] as? String else {
            conn.send(ErrorMessage(id: nil, error: ErrorBody(code: "bad_request", message: "invalid JSON")))
            return
        }
        let id = obj["id"] as? String
        let params = obj["params"] as? [String: Any] ?? [:]

        switch type {
        case "hello":
            guard let id else { return fail(conn, nil, "bad_request", "id required") }
            conn.send(OkMessage(id: id, result: [
                "protocol": AnyCodable(protocolVersion),
                "adapter": AnyCodable("macos"),
                "version": AnyCodable(sceneuseVersion),
            ]))
        case "status":
            guard let id else { return fail(conn, nil, "bad_request", "id required") }
            let p = PermissionProbe.current()
            var result: [String: AnyCodable] = [
                "permissions": AnyCodable([
                    "screen_recording": p.screenRecording,
                    "accessibility": p.accessibility,
                ]),
                "socket": AnyCodable(path),
                "adapter": AnyCodable("macos"),
                "version": AnyCodable(sceneuseVersion),
            ]
            for (k, v) in PermissionProbe.statusExtras() {
                result[k] = AnyCodable(v)
            }
            conn.send(OkMessage(id: id, result: result))
        case "subscribe":
            guard let id else { return fail(conn, nil, "bad_request", "id required") }
            let tiles = (params["tiles"] as? Bool) ?? true
            conn.tiles = tiles
            conn.subscribed = true
            let window = params["window"] as? String
            let app = params["app"] as? String
            SceneEngine.shared.subscribe(id: conn.id, tiles: tiles, window: window, app: app) { [weak conn] scene in
                conn?.send(scene)
            }
            conn.send(OkMessage(id: id, result: ["subscribed": AnyCodable(true)]))
        case "unsubscribe":
            guard let id else { return fail(conn, nil, "bad_request", "id required") }
            conn.subscribed = false
            SceneEngine.shared.unsubscribe(id: conn.id)
            conn.send(OkMessage(id: id, result: ["subscribed": AnyCodable(false)]))
        case "target":
            guard let id else { return fail(conn, nil, "bad_request", "id required") }
            do {
                let resolved = try SceneEngine.shared.setObserve(
                    window: params["window"] as? String,
                    app: params["app"] as? String
                )
                var result: [String: AnyCodable] = [:]
                if let resolved {
                    result["window"] = AnyCodable(resolved.id)
                    result["app"] = AnyCodable(resolved.app)
                    result["pid"] = AnyCodable(resolved.pid)
                } else {
                    result["cleared"] = AnyCodable(true)
                }
                conn.send(OkMessage(id: id, result: result))
            } catch let e as InputError {
                let code: String
                switch e {
                case .permission: code = "permission_denied"
                case .notFound: code = "not_found"
                case .badRequest: code = "bad_request"
                }
                fail(conn, id, code, e.localizedDescription)
            } catch {
                fail(conn, id, "internal", error.localizedDescription)
            }
        case "act":
            guard let id else { return fail(conn, nil, "bad_request", "id required") }
            do {
                try performAct(params)
                let settle = Double(ProcessInfo.processInfo.environment["SCENEUSE_SETTLE"] ?? "1") ?? 1
                if settle > 0 { Thread.sleep(forTimeInterval: settle) }
                SceneEngine.shared.refreshAfterAct()
                conn.send(OkMessage(id: id, result: ["ok": AnyCodable(true)]))
            } catch let e as InputError {
                let code: String
                switch e {
                case .permission: code = "permission_denied"
                case .notFound: code = "not_found"
                case .badRequest: code = "bad_request"
                }
                fail(conn, id, code, e.localizedDescription)
            } catch {
                fail(conn, id, "internal", error.localizedDescription)
            }
        default:
            fail(conn, id, "unknown_type", "unknown type \(type)")
        }
    }

    private func fail(_ conn: Connection, _ id: String?, _ code: String, _ message: String) {
        conn.send(ErrorMessage(id: id, error: ErrorBody(code: code, message: message)))
    }

    private func performAct(_ params: [String: Any]) throws {
        let op = (params["op"] as? String) ?? ""
        let map = SceneEngine.shared.elementMap
        switch op {
        case "invoke":
            guard let node = params["node"] as? String else { throw InputError.badRequest("node required") }
            try Input.invoke(node: node, action: params["action"] as? String, map: map)
        case "set":
            guard let node = params["node"] as? String else { throw InputError.badRequest("node required") }
            let value: String
            if let s = params["value"] as? String { value = s }
            else if let n = params["value"] as? NSNumber { value = n.stringValue }
            else { throw InputError.badRequest("value required") }
            try Input.setValue(node: node, value: value, map: map)
        case "hit":
            guard let wid = params["window"] as? String,
                  let window = SceneEngine.shared.window(id: wid) else {
                throw InputError.notFound("unknown window")
            }
            guard let point = params["point"] as? [String: Any],
                  let x = num(point["x"]), let y = num(point["y"]) else {
                throw InputError.badRequest("point required")
            }
            let button = (params["button"] as? String) ?? "left"
            Input.hit(window: window, local: CGPoint(x: x, y: y), button: button)
        case "key":
            guard let keys = params["keys"] as? [String] else { throw InputError.badRequest("keys required") }
            try Input.key(keys)
        case "scroll":
            var window: WindowInfo?
            if let wid = params["window"] as? String {
                window = SceneEngine.shared.window(id: wid)
            }
            var local: CGPoint?
            if let point = params["point"] as? [String: Any], let x = num(point["x"]), let y = num(point["y"]) {
                local = CGPoint(x: x, y: y)
            }
            guard let delta = params["delta"] as? [String: Any], let dx = num(delta["x"]), let dy = num(delta["y"]) else {
                throw InputError.badRequest("delta required")
            }
            Input.scroll(window: window, local: local, delta: CGPoint(x: dx, y: dy))
        case "drag":
            guard let wid = params["window"] as? String,
                  let window = SceneEngine.shared.window(id: wid) else {
                throw InputError.notFound("unknown window")
            }
            guard let from = params["from"] as? [String: Any], let fx = num(from["x"]), let fy = num(from["y"]),
                  let to = params["to"] as? [String: Any], let tx = num(to["x"]), let ty = num(to["y"]) else {
                throw InputError.badRequest("from/to required")
            }
            Input.drag(window: window, from: CGPoint(x: fx, y: fy), to: CGPoint(x: tx, y: ty))
        case "raise":
            guard let wid = params["window"] as? String,
                  let window = SceneEngine.shared.window(id: wid) else {
                throw InputError.notFound("unknown window")
            }
            try Input.raise(window: window)
        default:
            throw InputError.badRequest("unknown op \(op)")
        }
    }

    private func num(_ v: Any?) -> Double? {
        if let d = v as? Double { return d }
        if let i = v as? Int { return Double(i) }
        if let n = v as? NSNumber { return n.doubleValue }
        return nil
    }
}
