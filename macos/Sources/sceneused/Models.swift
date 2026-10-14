import Foundation

let sceneuseVersion = "0.1.0"
let protocolVersion = 1

struct Rect: Codable, Equatable {
    var x: Double
    var y: Double
    var w: Double
    var h: Double

    var area: Double { max(0, w) * max(0, h) }
    var cg: CGRect { CGRect(x: x, y: y, width: w, height: h) }

    func intersection(_ other: Rect) -> Rect {
        let r = cg.intersection(other.cg)
        if r.isNull || r.isEmpty { return Rect(x: 0, y: 0, w: 0, h: 0) }
        return Rect(x: r.origin.x, y: r.origin.y, w: r.width, h: r.height)
    }

    func coverage(of other: Rect) -> Double {
        let inter = intersection(other).area
        if area <= 0 { return 0 }
        return inter / area
    }

    var center: CGPoint { CGPoint(x: x + w / 2, y: y + h / 2) }
}

struct Permissions: Codable, Equatable {
    var screenRecording: Bool
    var accessibility: Bool

    enum CodingKeys: String, CodingKey {
        case screenRecording = "screen_recording"
        case accessibility
    }
}

struct DisplayInfo: Codable, Equatable {
    var id: String
    var bounds: Rect
    var scale: Double
    var colorSpace: String?

    enum CodingKeys: String, CodingKey {
        case id, bounds, scale
        case colorSpace = "color_space"
    }
}

struct WindowInfo: Codable, Equatable {
    var id: String
    var pid: Int
    var app: String
    var bundle: String?
    var title: String?
    var bounds: Rect
    var z: Int
    var focused: Bool
    var onScreen: Bool
    var occluded: Bool

    enum CodingKeys: String, CodingKey {
        case id, pid, app, bundle, title, bounds, z, focused
        case onScreen = "on_screen"
        case occluded
    }
}

struct CursorInfo: Codable, Equatable {
    var x: Double
    var y: Double
    var visible: Bool
    var shape: String?
}

struct FocusInfo: Codable, Equatable {
    var window: String?
    var app: String?
    var pid: Int?
}

struct SceneMessage: Encodable {
    var v: Int = protocolVersion
    var type: String = "scene"
    var seq: Int
    var t: Double
    var kind: String
    var permissions: Permissions
    var displays: [DisplayInfo]?
    var windows: [WindowInfo]?
    var cursor: CursorInfo
    var focus: FocusInfo
    /// Window whose AX tree is in `nodes`. Distinct from OS `focus` when the agent pinned a handle.
    var observe: FocusInfo
    var damage: [Rect]
    var nodes: [NodeInfo]?
    var tiles: [TileInfo]
    var nodeCount: Int?

    enum CodingKeys: String, CodingKey {
        case v, type, seq, t, kind, permissions, displays, windows, cursor, focus, observe, damage, nodes, tiles
        case nodeCount = "node_count"
    }
}

struct NodeInfo: Codable, Equatable {
    var id: String
    var window: String
    var role: String
    var name: String?
    var value: String?
    var states: [String]
    var actions: [String]
    var bounds: Rect?
    var parent: String?
    /// Hint for agents. Does not drop nodes. See Salience.
    var tags: [String] = []
}

struct TileInfo: Codable {
    var rect: Rect
    var mime: String
    var data: String
}

struct OkMessage: Encodable {
    var v: Int = protocolVersion
    var id: String
    var type: String = "ok"
    var result: [String: AnyCodable]
}

struct ErrorMessage: Encodable {
    var v: Int = protocolVersion
    var id: String?
    var type: String = "error"
    var error: ErrorBody
}

struct ErrorBody: Encodable {
    var code: String
    var message: String
}

/// Minimal JSON-friendly Any encoder for small result objects.
struct AnyCodable: Encodable {
    let value: Any

    init(_ value: Any) { self.value = value }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch value {
        case let v as String: try c.encode(v)
        case let v as Int: try c.encode(v)
        case let v as Double: try c.encode(v)
        case let v as Bool: try c.encode(v)
        case let v as [String: Any]:
            try c.encode(v.mapValues { AnyCodable($0) })
        case let v as [Any]:
            try c.encode(v.map { AnyCodable($0) })
        default:
            try c.encode(String(describing: value))
        }
    }
}

func jsonEncoder() -> JSONEncoder {
    let e = JSONEncoder()
    e.outputFormatting = [.sortedKeys]
    return e
}
